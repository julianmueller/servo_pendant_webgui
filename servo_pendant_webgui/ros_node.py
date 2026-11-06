"""
All ROS communication of the servo pendant: jog inputs of every browser in, MoveIt Servo commands out, plus the
robot state for the page. The callbacks run in the ROS thread and only store data under the lock.
"""

import concurrent.futures
import re
import threading
import time

import numpy as np

from rclpy.node import Node
from rclpy.parameter import Parameter, parameter_value_to_python
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.validate_topic_name import validate_topic_name

from control_msgs.msg import JointJog
from geometry_msgs.msg import TwistStamped
from moveit_msgs.msg import ServoStatus
from moveit_msgs.srv import ServoCommandType
from rcl_interfaces.msg import Log, ParameterDescriptor, SetParametersResult
from rcl_interfaces.srv import GetParameters, ListParameters
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from std_srvs.srv import SetBool

from servo_pendant_webgui.mesh_cache import glb_url
from servo_pendant_webgui.urdf_kinematics import UrdfModel

JOINT = "joint"
TWIST = "twist"
MODE_NAMES = {JOINT: "Joint", TWIST: "Cartesian"}

# Which base/tool axes the 2D pad (horizontal, vertical) and the 1D rocker drive, per plane
PLANES = {
    "XY": ((0, 1), 2),
    "XZ": ((0, 2), 1),
    "YZ": ((1, 2), 0),
}
AXIS_NAMES = "XYZ"

# Topics and services of the node: parameter -> ROS type (the settings offer the topics / services of this type)
CONNECTIONS = {
    "joint_states_topic": "sensor_msgs/msg/JointState",
    "robot_description_topic": "std_msgs/msg/String",
    "twist_topic": "geometry_msgs/msg/TwistStamped",
    "joint_jog_topic": "control_msgs/msg/JointJog",
    "switch_command_type_service": "moveit_msgs/srv/ServoCommandType",
    "pause_servo_service": "std_srvs/srv/SetBool",
    "servo_status_topic": "moveit_msgs/msg/ServoStatus",
}

# moveit_msgs/ServoStatus code -> (level ok / warn / bad, what it means). Slowing down is a warning, Servo refusing to
# move (a halt, a joint at its bound) is an error. NO_WARNING (0) is not shown at all.
SERVO_CODES = {
    ServoStatus.INVALID: ("bad", "Servo: invalid state"),
    ServoStatus.NO_WARNING: ("ok", "Servo: no warning"),
    ServoStatus.DECELERATE_FOR_APPROACHING_SINGULARITY: ("warn", "Slowing: approaching a singularity"),
    ServoStatus.HALT_FOR_SINGULARITY: ("bad", "Halted: singularity"),
    ServoStatus.DECELERATE_FOR_LEAVING_SINGULARITY: ("warn", "Slowing: leaving a singularity"),
    ServoStatus.DECELERATE_FOR_COLLISION: ("warn", "Slowing: collision ahead"),
    ServoStatus.HALT_FOR_COLLISION: ("bad", "Halted: collision"),
    ServoStatus.JOINT_BOUND: ("bad", "Halted: joint at its limit"),
}

# MoveIt Servo's warning for a command of another type than the one it was switched to
SERVO_TYPE_WARNING = "Command type has not been set"

# Parameters that can be changed while the node runs (settings panel or `ros2 param set`). All others are read-only:
# they are set at launch.
LIVE_PARAMETERS = (
    *CONNECTIONS,
    "base_frame",
    "tool_frame",
    "max_linear_speed",
    "max_angular_speed",
    "max_joint_speed",
    "input_timeout",
    "publish_rate",
    "exclude_joints",
)
_POSITIVE = (
    "max_linear_speed",
    "max_angular_speed",
    "max_joint_speed",
    "input_timeout",
    "publish_rate",
)


def _shape(v):
    """Quadratic response: fine control near the centre, full speed at the edge."""
    return v * abs(v)


class ServoCommander(Node):
    """
    Holds the jog inputs of all connected web clients and publishes them to MoveIt Servo at a fixed rate.

    Every input expires after `input_timeout` unless it is refreshed (the web controls send a heartbeat while
    they are touched), so a lost connection or a stuck browser can never leave the robot moving.
    """

    def __init__(self, **kwargs):  # kwargs from RosBridge: context, namespace, parameter_overrides
        super().__init__("servo_pendant_webgui", **kwargs)

        def p(name, default, description):
            descriptor = ParameterDescriptor(
                description=description, read_only=name not in LIVE_PARAMETERS
            )
            self.declare_parameter(name, default, descriptor)

        p("twist_topic", "/servo_node/delta_twist_cmds", "Cartesian commands to Servo")
        p("joint_jog_topic", "/servo_node/delta_joint_cmds", "Joint commands to Servo")
        p("joint_states_topic", "/joint_states", "Joint positions of the robot")
        p("robot_description_topic", "/robot_description", "URDF for the 3D view and limits")
        p(
            "switch_command_type_service",
            "/servo_node/switch_command_type",
            "Switches Servo between joint and Cartesian commands",
        )
        p("pause_servo_service", "/servo_node/pause_servo", "Pauses (true) and resumes (false) Servo")
        p("servo_status_topic", "/servo_node/status", "Servo's status: slowing down or halted, and why")
        p("base_frame", "panda_link0", "Frame of Cartesian commands in base mode")
        p("tool_frame", "panda_link8", "Frame of Cartesian commands in tool mode")
        p("max_linear_speed", 0.1, "[m/s] at full deflection and 100 % speed")
        p("max_angular_speed", 0.5, "[rad/s] at full deflection and 100 % speed")
        p("max_joint_speed", 0.5, "[rad/s] at full deflection and 100 % speed")
        p("publish_rate", 50.0, "[Hz] of the commands sent to Servo")
        p(
            "input_timeout",
            0.3,
            "[s] an input that is not refreshed for this long counts as released",
        )
        p("exclude_joints", [".*finger.*"], "Regexes of joints not shown in the panel")

        def val(name):
            return self.get_parameter(name).value

        self.base_frame = val("base_frame")
        self.tool_frame = val("tool_frame")
        self.max_linear = val("max_linear_speed")
        self.max_angular = val("max_angular_speed")
        self.max_joint = val("max_joint_speed")
        self.input_timeout = val("input_timeout")
        self._exclude = [re.compile(r) for r in val("exclude_joints")]

        self._lock = threading.Lock()
        self._inputs = {}  # key -> (value, monotonic time)
        # JOINT, TWIST, or None: paused, the start state. Nothing is published while paused, and the command type is
        # only sent once a mode is chosen, so merely opening the pendant takes Servo from no other client.
        self.mode = None
        self._resume_mode = TWIST  # the mode Pause returns to
        self.speed = 0.3  # global speed scale 0..1
        self.frame = "base"  # 'base' | 'tool'
        self.plane = "XY"
        self._idle_count = 0
        self.last_command = "idle"

        self.joint_names = []  # arm joints shown in the panel, in joint_states order
        self._seen_joints = []  # all joint_states names in order, to filter again when exclude_joints changes
        self.positions = {}
        self._joint_states_time = 0.0
        self.model = None
        self.model_status = "Waiting for the robot description"
        self._joint_states_topic = val("joint_states_topic")
        self.robot_description_topic = val("robot_description_topic")
        self.joint_states_warning = ""
        self._joint_stamps = {}  # joint -> newest joint_states stamp [s], to drop stale / out-of-order messages

        self.servo_status = ("warn", "Waiting for Servo")  # (level ok / warn / bad, text) for the page
        self._servo_report = None  # (code, message) of the latest ServoStatus, None before the first one
        self._servo_was_ready = False
        # Servo accepts only commands of the type it was switched to (it has no service to ask for the current type),
        # and other clients (nbv_planner's small steps) switch it for themselves. So the type is sent: when Servo
        # (re)appears, on every mode button / key, whenever a jog starts, every second while jogging, and at once
        # when Servo logs that it rejected a command for its type. The first commands wait for Servo's answer (at
        # most type_pending_max seconds). It is not sent while idle: that would take Servo from the other clients.
        self._type_confirmed_mode = None  # mode Servo last confirmed
        self._type_sent = 0.0  # monotonic time of the last switch request
        self._type_pending = False
        self.type_pending_max = 0.5  # [s]
        self.type_rejections = 0  # commands Servo rejected for their type (from its log), for the page

        self._pub_lock = threading.Lock()  # the publishers are replaced when their topic parameter changes
        self._twist_pub = self.create_publisher(TwistStamped, val("twist_topic"), 10)
        self._jog_pub = self.create_publisher(JointJog, val("joint_jog_topic"), 10)
        self._joint_states_sub = self.create_subscription(
            JointState, self._joint_states_topic, self._on_joint_states, 10
        )
        self._description_generation = 0  # counts robot description topics, so a stale conversion is dropped
        self._description_sub = self._subscribe_description(self.robot_description_topic)
        self._switch_client = None
        self._connect_servo(val("switch_command_type_service"))
        self._pause_client = self.create_client(SetBool, val("pause_servo_service"))
        self._status_sub = self.create_subscription(
            ServoStatus, val("servo_status_topic"), self._on_servo_status, 10
        )
        # Servo's log, to notice at once when it rejects the commands because another client switched its type
        self.create_subscription(Log, "/rosout", self._on_rosout, 100)
        self._publish_timer = self.create_timer(
            1.0 / val("publish_rate"), self._publish
        )
        self.create_timer(1.0, self._watch_servo)
        self.create_timer(2.0, self._check_joint_states_publishers)
        self.add_on_set_parameters_callback(self._validate_parameters)
        self.add_post_set_parameters_callback(self._apply_parameters)

    # ------------------------------------------------------------------ #
    #  Inputs from the web panel (called from the web server thread)
    # ------------------------------------------------------------------ #

    def set_input(self, key, value):
        with self._lock:
            self._inputs[key] = (value, time.monotonic())

    def release_all(self):
        with self._lock:
            self._inputs.clear()

    def set_mode(self, mode):
        """Switches the mode, and Servo's command type with it. The same mode again sends the type again.

        None pauses: the jog is stopped, Servo is paused, and nothing is published until a mode is chosen again,
        which resumes Servo first.
        """
        if mode != self.mode:
            jogging = self._idle_count < 3
            self.release_all()
            if jogging and self.mode is not None:
                self._publish_stop()  # stop in the old mode's type before Servo is switched
            if self.mode is not None:
                self._resume_mode = self.mode
            was_paused = self.mode is None
            self.mode = mode
            self._idle_count = 3  # no idle zero commands in the new type before Servo knows it
            if mode is None:
                self._call_pause(True)
                return
            if was_paused:
                self._call_pause(False)
        elif mode is None:
            return
        self.send_command_type()

    @property
    def paused(self):
        return self.mode is None

    def toggle_pause(self):
        """Pause, or resume the mode that was active before."""
        self.set_mode(self._resume_mode if self.mode is None else None)

    def _call_pause(self, pause):
        """Asks Servo to pause or resume (asynchronously; servo_status shows a failure, or the pause)."""
        verb = "pause" if pause else "resume"
        if not self._pause_client.service_is_ready():
            # the pendant itself sends nothing while paused, so this is safe; but say that Servo did not hear it
            self.servo_status = ("warn", f"Could not {verb} Servo: no pause service")
            return
        future = self._pause_client.call_async(SetBool.Request(data=pause))

        def done(f):
            result = None if f.exception() is not None else f.result()
            if result is None or not result.success:
                reason = (result.message if result is not None else "") or "no answer"
                self.servo_status = ("bad", f"Servo did not {verb}: {reason}")
            elif pause and self.mode is None:
                self.servo_status = ("ok", "Servo paused")

        future.add_done_callback(done)

    def _on_servo_status(self, msg):
        self._servo_report = (int(msg.code), msg.message)

    def servo_report(self):
        """(level, title, message) of Servo's latest status, or None when there is nothing to warn about."""
        report = self._servo_report
        if report is None or report[0] == ServoStatus.NO_WARNING:
            return None
        code, message = report
        level, title = SERVO_CODES.get(code, ("bad", f"Servo status {code}"))
        return level, title, message

    def _publish_stop(self):
        """One zero command in the current mode's type: Servo stops at once instead of at its timeout."""
        stamp = self.get_clock().now().to_msg()
        with self._pub_lock:
            if self.mode == JOINT:
                msg = JointJog()
                msg.header.stamp = stamp
                msg.joint_names = list(self.joint_names)
                msg.velocities = [0.0] * len(self.joint_names)
                self._jog_pub.publish(msg)
            else:
                msg = TwistStamped()
                msg.header.stamp = stamp
                msg.header.frame_id = self.command_frame()
                self._twist_pub.publish(msg)

    def set_speed(self, speed):
        self.speed = float(np.clip(speed, 0.0, 1.0))

    def set_frame(self, frame):
        self.release_all()
        self.frame = frame

    def set_plane(self, plane):
        self.release_all()
        self.plane = plane

    def stop(self):
        """Release every input and ask the driver to stop the current motion."""
        self.release_all()

    def set_parameter_value(self, name, value):
        """Sets one of the node's parameters. Returns (successful, reason)."""
        kind = self.get_parameter(name).type_
        if kind == Parameter.Type.DOUBLE:
            value = float(value)
        result = self.set_parameters([Parameter(name, kind, value)])[0]
        return result.successful, result.reason

    def active_inputs(self):
        """Inputs that are currently held, without expired ones."""

        now = time.monotonic()
        with self._lock:
            return {
                k: v
                for k, (v, t) in self._inputs.items()
                if now - t < self.input_timeout and np.any(v)
            }

    # ------------------------------------------------------------------ #
    #  Commands
    # ------------------------------------------------------------------ #

    def joint_velocities(self, inputs=None):
        """Joint name -> velocity. Slider ('j:<joint>') and keyboard ('k:<joint>') inputs: the larger one wins."""
        inputs = self.active_inputs() if inputs is None else inputs
        out = {}
        for key, v in inputs.items():
            if key[:2] in ("j:", "k:"):
                vel = _shape(v) * self.max_joint * self.speed
                if abs(vel) > abs(out.get(key[2:], 0.0)):
                    out[key[2:]] = vel
        return out

    def cartesian_command(self, inputs=None):
        """Returns (linear [m/s], angular [rad/s]) in the selected frame."""
        inputs = self.active_inputs() if inputs is None else inputs
        linear = np.zeros(3)
        (h_axis, v_axis), rocker_axis = PLANES[self.plane]
        pad = inputs.get("pad", (0.0, 0.0))
        linear[h_axis] = _shape(pad[0])
        linear[v_axis] = _shape(pad[1])
        linear[rocker_axis] = _shape(inputs.get("rocker", 0.0))
        # the X / Y / Z sliders (the page's other translation input: only one of them is shown at a time)
        for axis, key in enumerate("xyz"):
            linear[axis] = np.clip(linear[axis] + _shape(inputs.get(key, 0.0)), -1.0, 1.0)
        angular = np.array([_shape(inputs.get(k, 0.0)) for k in ("rx", "ry", "rz")])
        return (
            linear * self.max_linear * self.speed,
            angular * self.max_angular * self.speed,
        )

    def command_frame(self):
        return self.tool_frame if self.frame == "tool" else self.base_frame

    def _publish(self):
        if self.mode is None:
            return  # paused
        inputs = self.active_inputs()
        stamp = self.get_clock().now().to_msg()
        if self.mode == JOINT:
            velocities = self.joint_velocities(inputs)
            moving = any(abs(v) > 1e-9 for v in velocities.values())
        else:
            linear, angular = self.cartesian_command(inputs)
            moving = bool(
                np.any(np.abs(linear) > 1e-9) or np.any(np.abs(angular) > 1e-9)
            )

        if not moving:
            # A few explicit zero commands after a release, then silence (Servo halts on its own timeout,
            # and the driver's receiver needs the stream to pause to re-arm after an error)
            if self._idle_count >= 3:
                return
            self._idle_count += 1
            self.last_command = "idle"
        else:
            now = time.monotonic()
            if self._idle_count >= 3 or now - self._type_sent > 1.0:
                # a jog starts, or has been going on for a second: make sure Servo is in this mode's type (another
                # client may have switched it meanwhile)
                self.send_command_type()
            self._idle_count = 0
            if self._type_pending and self._type_confirmed_mode != self.mode:
                if now - self._type_sent < self.type_pending_max:
                    return  # Servo has not confirmed the type yet: the command would only be rejected
                self._type_pending = False  # no answer: send anyway, Servo may be switched already

        if self.mode == JOINT:
            msg = JointJog()
            msg.header.stamp = stamp
            # always the full joint vector: a joint released a moment ago is commanded 0 explicitly
            names = list(self.joint_names) + [
                n for n in velocities if n not in self.joint_names
            ]
            msg.joint_names = names
            msg.velocities = [float(velocities.get(n, 0.0)) for n in names]
            with self._pub_lock:
                self._jog_pub.publish(msg)
            if moving:
                self.last_command = "joint jog: " + ", ".join(
                    f"{n} {v:+.2f} rad/s" for n, v in velocities.items()
                )
        else:
            msg = TwistStamped()
            msg.header.stamp = stamp
            msg.header.frame_id = self.command_frame()
            msg.twist.linear.x, msg.twist.linear.y, msg.twist.linear.z = (
                float(v) for v in linear
            )
            msg.twist.angular.x, msg.twist.angular.y, msg.twist.angular.z = (
                float(v) for v in angular
            )
            with self._pub_lock:
                self._twist_pub.publish(msg)
            if moving:
                self.last_command = (
                    f"twist [{msg.header.frame_id}]: v=({linear[0]:+.3f}, {linear[1]:+.3f}, {linear[2]:+.3f}) m/s  "
                    f"w=({angular[0]:+.2f}, {angular[1]:+.2f}, {angular[2]:+.2f}) rad/s"
                )

    # ------------------------------------------------------------------ #
    #  Servo command type
    # ------------------------------------------------------------------ #

    def _connect_servo(self, service):
        """Clients of MoveIt Servo's node, found from its switch_command_type service."""
        for client in (self._switch_client, getattr(self, "_servo_list_parameters", None),
                       getattr(self, "_servo_get_parameters", None)):  # fmt: skip
            if client is not None:
                self.destroy_client(client)
        # Servo's node (its parameters, like the move group, are shown in the settings)
        self.servo_node = service.rsplit("/", 1)[0] or "/"
        servo = self.servo_node.rstrip("/")
        self._switch_client = self.create_client(ServoCommandType, service)
        self._servo_list_parameters = self.create_client(ListParameters, f"{servo}/list_parameters")
        self._servo_get_parameters = self.create_client(GetParameters, f"{servo}/get_parameters")
        self._servo_was_ready = False  # _watch_servo sends the type as soon as the service is there
        self._type_confirmed_mode = None
        self.servo_status = ("warn", "Waiting for Servo")

    def _watch_servo(self):
        ready = self._switch_client.service_is_ready()
        if ready and not self._servo_was_ready:
            if self.mode is None:
                self.servo_status = ("ok", "Paused: choose a mode")
            else:
                self.send_command_type()  # (re)appeared: make Servo match the panel's mode
        elif not ready:
            self.servo_status = ("warn", "Servo not available")
            self._servo_report = None  # its last status is no longer news
        self._servo_was_ready = ready

    def _on_rosout(self, msg):
        """Servo rejected a command for its type: send the type again at once, if this node is jogging."""
        # by the text only: Servo's logger name depends on its version (node name or moveit.ros.servo...), and a
        # needless switch request is harmless
        if SERVO_TYPE_WARNING not in msg.msg:
            return
        if self._idle_count >= 3:
            return  # not jogging: the rejected command came from another client
        self.type_rejections += 1
        if time.monotonic() - self._type_sent > 0.2:
            self.get_logger().warn("Servo rejected a command for its command type: switching it again")
            self.send_command_type()

    def send_command_type(self):
        """Asks Servo to switch to the current mode's command type (asynchronously; servo_status shows the answer)."""
        if self.mode is None:
            return  # paused: no type to send
        if not self._switch_client.service_is_ready():
            self.servo_status = ("warn", "Servo not available")
            return
        request = ServoCommandType.Request()
        request.command_type = (
            ServoCommandType.Request.JOINT_JOG
            if self.mode == JOINT
            else ServoCommandType.Request.TWIST
        )
        mode = self.mode
        self._type_sent = time.monotonic()
        self._type_pending = True
        future = self._switch_client.call_async(request)

        def done(f):
            ok = f.exception() is None and f.result() is not None and f.result().success
            name = MODE_NAMES[mode]
            self._type_pending = False
            self._type_confirmed_mode = mode if ok else None
            self.servo_status = ("ok", f"Servo: {name} mode") if ok else ("bad", f"Servo rejected {name} mode")

        future.add_done_callback(done)

    # ------------------------------------------------------------------ #
    #  Parameters
    # ------------------------------------------------------------------ #

    def _validate_parameters(self, params):
        def reject(reason):
            return SetParametersResult(successful=False, reason=reason)

        for prm in params:
            if prm.name in ("base_frame", "tool_frame", *CONNECTIONS) and not prm.value.strip():
                return reject(f"{prm.name} must not be empty")
            if prm.name in CONNECTIONS:
                try:
                    validate_topic_name(prm.value.strip())  # service names follow the same rules
                except Exception as e:  # InvalidTopicNameException
                    return reject(f"invalid name {prm.value!r}: {e}")
            if prm.name in _POSITIVE and not prm.value > 0.0:
                return reject(f"{prm.name} must be > 0")
            if prm.name == "publish_rate" and prm.value > 1000.0:
                return reject("publish_rate must be <= 1000 Hz")
            if prm.name == "exclude_joints":
                for r in prm.value:
                    try:
                        re.compile(r)
                    except re.error as e:
                        return reject(f"invalid regex {r!r}: {e}")
        return SetParametersResult(successful=True)

    def _apply_parameters(self, params):
        # a changed frame, speed or joint list must never carry on an ongoing jog
        self.release_all()
        for prm in params:
            name, value = prm.name, prm.value
            if name == "joint_states_topic":
                self._resubscribe_joint_states(value.strip())
            elif name == "robot_description_topic":
                self._resubscribe_description(value.strip())
            elif name == "twist_topic":
                with self._pub_lock:
                    old, self._twist_pub = self._twist_pub, self.create_publisher(TwistStamped, value.strip(), 10)
                self.destroy_publisher(old)
            elif name == "joint_jog_topic":
                with self._pub_lock:
                    old, self._jog_pub = self._jog_pub, self.create_publisher(JointJog, value.strip(), 10)
                self.destroy_publisher(old)
            elif name == "switch_command_type_service":
                self._connect_servo(value.strip())
            elif name == "pause_servo_service":
                old, self._pause_client = self._pause_client, self.create_client(SetBool, value.strip())
                self.destroy_client(old)
            elif name == "servo_status_topic":
                self.destroy_subscription(self._status_sub)
                self._servo_report = None
                self._status_sub = self.create_subscription(
                    ServoStatus, value.strip(), self._on_servo_status, 10
                )
            elif name == "base_frame":
                self.base_frame = value.strip()
            elif name == "tool_frame":
                self.tool_frame = value.strip()
            elif name == "max_linear_speed":
                self.max_linear = value
            elif name == "max_angular_speed":
                self.max_angular = value
            elif name == "max_joint_speed":
                self.max_joint = value
            elif name == "input_timeout":
                self.input_timeout = value
            elif name == "publish_rate":
                self._publish_timer.timer_period_ns = 1e9 / value
            elif name == "exclude_joints":
                with self._lock:
                    self._exclude = [re.compile(r) for r in value]
                    self.joint_names = [
                        n for n in self._seen_joints if not self._excluded(n)
                    ]

    def _resubscribe_joint_states(self, topic):
        """Switch to another joint states topic. The joints start over: the new topic may be another robot."""
        if topic == self._joint_states_topic:
            return
        self.destroy_subscription(self._joint_states_sub)
        with self._lock:
            self._joint_states_topic = topic
            self.positions, self._joint_stamps = {}, {}
            self._seen_joints, self.joint_names = [], []
            self._joint_states_time = 0.0
        self.joint_states_warning = ""
        self._joint_states_sub = self.create_subscription(
            JointState, topic, self._on_joint_states, 10
        )
        self.get_logger().info(f"Joint states from {topic}")

    def _subscribe_description(self, topic):
        latched = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        generation = self._description_generation
        return self.create_subscription(
            String, topic, lambda msg: self._on_robot_description(msg, generation), latched
        )

    def _resubscribe_description(self, topic):
        """Another robot description topic. The robot shown stays until the new description has arrived."""
        if topic == self.robot_description_topic:
            return
        self.destroy_subscription(self._description_sub)
        self._description_generation += 1
        self.robot_description_topic = topic
        self.model_status = f"Waiting for the robot description on {topic}"
        self._description_sub = self._subscribe_description(topic)
        self.get_logger().info(f"Robot description from {topic}")

    def connection_names(self, parameter):
        """Topics (or services) of the type of a CONNECTIONS parameter, for the settings."""
        kind = CONNECTIONS[parameter]
        found = self.get_service_names_and_types() if "/srv/" in kind else self.get_topic_names_and_types()
        return sorted(name for name, types in found if kind in types)

    def _excluded(self, joint):
        return any(r.fullmatch(joint) for r in self._exclude)

    def fetch_servo_parameters(self):
        """MoveIt Servo's parameters (`moveit_servo.*`, without the prefix), read from its node.

        Returns a concurrent.futures.Future of {name: value}, so the web page can await it.
        """
        result = concurrent.futures.Future()
        if not (
            self._servo_list_parameters.service_is_ready()
            and self._servo_get_parameters.service_is_ready()
        ):
            result.set_exception(RuntimeError(f"{self.servo_node} not available"))
            return result

        def failed(f):
            if f.exception() is None and f.result() is not None:
                return False
            result.set_exception(RuntimeError(f"{self.servo_node} did not answer"))
            return True

        def got(names, f):
            if not failed(f):
                values = f.result().values
                result.set_result(
                    {
                        n.removeprefix("moveit_servo."): parameter_value_to_python(v)
                        for n, v in zip(names, values)
                    }
                )

        def listed(f):
            if failed(f):
                return
            names = sorted(f.result().result.names)
            self._servo_get_parameters.call_async(
                GetParameters.Request(names=names)
            ).add_done_callback(lambda g: got(names, g))

        request = ListParameters.Request(
            prefixes=["moveit_servo"], depth=ListParameters.Request.DEPTH_RECURSIVE
        )
        self._servo_list_parameters.call_async(request).add_done_callback(listed)
        return result

    # ------------------------------------------------------------------ #
    #  Robot state
    # ------------------------------------------------------------------ #

    def _on_joint_states(self, msg):
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        with self._lock:
            for name, position in zip(msg.name, msg.position):
                if stamp > 0.0:
                    if stamp < self._joint_stamps.get(name, 0.0):
                        continue  # older than what we already have (stale publisher / out of order)
                    self._joint_stamps[name] = stamp
                self.positions[name] = position
                if name not in self._seen_joints:
                    self._seen_joints.append(name)
                    if not self._excluded(name):
                        self.joint_names.append(name)
            self._joint_states_time = time.monotonic()

    def _on_robot_description(self, msg, generation):
        if generation != self._description_generation:
            return  # from the previous topic
        try:
            model = UrdfModel(msg.data)
        except Exception as e:
            self.get_logger().error(f"Could not parse the robot description: {e}")
            return

        def prepare():
            self.model_status = "Converting the robot meshes"
            # convert the meshes for the 3D view up front (cached), so the web page never waits for it
            meshes = model.mesh_filenames()
            for filename in meshes:
                glb_url(filename, self.get_logger())
            if generation != self._description_generation:
                return  # the topic was changed meanwhile
            self.model = model
            self.get_logger().info(
                f"Robot model loaded: {len(model.joints)} joints, {len(meshes)} meshes, "
                f"root {model.root}"
            )

        threading.Thread(target=prepare, name="mesh_conversion", daemon=True).start()

    def _check_joint_states_publishers(self):
        """More than one publisher on the joint states topic usually means cross-talk (e.g. another robot)."""
        nodes = sorted(
            {
                info.node_name
                for info in self.get_publishers_info_by_topic(self._joint_states_topic)
            }
        )
        self.joint_states_warning = (
            f"{len(nodes)} publishers on {self._joint_states_topic}: {', '.join(nodes)}"
            if len(nodes) > 1
            else ""
        )

    def joint_states_age(self):
        return (
            time.monotonic() - self._joint_states_time
            if self._joint_states_time
            else None
        )

    def snapshot_positions(self):
        with self._lock:
            return dict(self.positions)
