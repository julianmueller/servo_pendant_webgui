import concurrent.futures
import os
import re
import threading
import time

import numpy as np

from rclpy.node import Node
from rclpy.parameter import Parameter, parameter_value_to_python
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.utilities import get_rmw_implementation_identifier

from control_msgs.msg import JointJog
from geometry_msgs.msg import TwistStamped
from moveit_msgs.srv import ServoCommandType
from rcl_interfaces.msg import ParameterDescriptor, SetParametersResult
from rcl_interfaces.srv import GetParameters, ListParameters
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from std_srvs.srv import Trigger

from servo_pendant_webgui.mesh_cache import glb_url
from servo_pendant_webgui.urdf_kinematics import UrdfModel

JOINT = "joint"
TWIST = "twist"

# Which base/tool axes the 2D pad (horizontal, vertical) and the 1D rocker drive, per plane
PLANES = {
    "XY": ((0, 1), 2),
    "XZ": ((0, 2), 1),
    "YZ": ((1, 2), 0),
}
AXIS_NAMES = "XYZ"

# Parameters that can be changed while the node runs (settings panel or `ros2 param set`). All others are read-only:
# they are set at launch.
LIVE_PARAMETERS = (
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

    def __init__(self):
        super().__init__("servo_pendant_webgui")
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
        p("base_frame", "panda_link0", "Frame of Cartesian commands in BASE mode")
        p("tool_frame", "panda_link8", "Frame of Cartesian commands in TOOL mode")
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
        p("host", "0.0.0.0", "Network interface of the web server")
        p("port", 8080, "Port of the web server")

        def val(name):
            return self.get_parameter(name).value

        self.base_frame = val("base_frame")
        self.tool_frame = val("tool_frame")
        self.max_linear = val("max_linear_speed")
        self.max_angular = val("max_angular_speed")
        self.max_joint = val("max_joint_speed")
        self.input_timeout = val("input_timeout")
        self.host = val("host")
        self.port = val("port")
        self._exclude = [re.compile(r) for r in val("exclude_joints")]
        # MoveIt Servo's node, from its service name (its parameters, like the move group, are shown in the settings)
        self.servo_node = val("switch_command_type_service").rsplit("/", 1)[0] or "/"

        self._lock = threading.Lock()
        self._inputs = {}  # key -> (value, monotonic time)
        self.mode = TWIST
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
        self.model_status = "Waiting for /robot_description ..."
        self._joint_states_topic = val("joint_states_topic")
        self.joint_states_warning = ""
        self._joint_stamps = {}  # joint -> newest joint_states stamp [s], to drop stale / out-of-order messages

        self.servo_status = "waiting for servo_node"
        self._servo_was_ready = False

        self._twist_pub = self.create_publisher(TwistStamped, val("twist_topic"), 10)
        self._jog_pub = self.create_publisher(JointJog, val("joint_jog_topic"), 10)
        self.create_subscription(
            JointState, self._joint_states_topic, self._on_joint_states, 10
        )
        latched = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self.create_subscription(
            String, val("robot_description_topic"), self._on_robot_description, latched
        )
        self._switch_client = self.create_client(
            ServoCommandType, val("switch_command_type_service")
        )
        servo = self.servo_node.rstrip("/")
        self._servo_list_parameters = self.create_client(
            ListParameters, f"{servo}/list_parameters"
        )
        self._servo_get_parameters = self.create_client(
            GetParameters, f"{servo}/get_parameters"
        )
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
        self.release_all()
        self.mode = mode
        self._send_command_type()

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
        angular = np.array([_shape(inputs.get(k, 0.0)) for k in ("rx", "ry", "rz")])
        return (
            linear * self.max_linear * self.speed,
            angular * self.max_angular * self.speed,
        )

    def command_frame(self):
        return self.tool_frame if self.frame == "tool" else self.base_frame

    def _publish(self):
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
            self._idle_count = 0

        if self.mode == JOINT:
            msg = JointJog()
            msg.header.stamp = stamp
            # always the full joint vector: a joint released a moment ago is commanded 0 explicitly
            names = list(self.joint_names) + [
                n for n in velocities if n not in self.joint_names
            ]
            msg.joint_names = names
            msg.velocities = [float(velocities.get(n, 0.0)) for n in names]
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
            self._twist_pub.publish(msg)
            if moving:
                self.last_command = (
                    f"twist [{msg.header.frame_id}]: v=({linear[0]:+.3f}, {linear[1]:+.3f}, {linear[2]:+.3f}) m/s  "
                    f"w=({angular[0]:+.2f}, {angular[1]:+.2f}, {angular[2]:+.2f}) rad/s"
                )

    # ------------------------------------------------------------------ #
    #  Servo command type
    # ------------------------------------------------------------------ #

    def _watch_servo(self):
        ready = self._switch_client.service_is_ready()
        if ready and not self._servo_was_ready:
            self._send_command_type()  # (re)appeared: make Servo match the panel's mode
        elif not ready:
            self.servo_status = "servo_node not available"
        self._servo_was_ready = ready

    def _send_command_type(self):
        if not self._switch_client.service_is_ready():
            self.servo_status = "servo_node not available"
            return
        request = ServoCommandType.Request()
        request.command_type = (
            ServoCommandType.Request.JOINT_JOG
            if self.mode == JOINT
            else ServoCommandType.Request.TWIST
        )
        mode = self.mode
        future = self._switch_client.call_async(request)

        def done(f):
            ok = f.result() is not None and f.result().success
            self.servo_status = (
                f"servo: {mode} mode" if ok else f"servo rejected {mode} mode"
            )

        future.add_done_callback(done)

    # ------------------------------------------------------------------ #
    #  Parameters
    # ------------------------------------------------------------------ #

    def _validate_parameters(self, params):
        def reject(reason):
            return SetParametersResult(successful=False, reason=reason)

        for prm in params:
            if prm.name in ("base_frame", "tool_frame") and not prm.value.strip():
                return reject(f"{prm.name} must not be empty")
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
            if name == "base_frame":
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

    def _excluded(self, joint):
        return any(r.fullmatch(joint) for r in self._exclude)

    def ros_info(self):
        """How this node is connected to ROS. All of it is fixed when the node starts."""
        return {
            "Node": self.get_fully_qualified_name(),
            "ROS_DOMAIN_ID": str(self.context.get_domain_id()),
            "RMW implementation": get_rmw_implementation_identifier(),
            "Discovery range": os.environ.get(
                "ROS_AUTOMATIC_DISCOVERY_RANGE", "SUBNET (default)"
            ),
        }

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

    def _on_robot_description(self, msg):
        try:
            model = UrdfModel(msg.data)
        except Exception as e:
            self.get_logger().error(f"Could not parse the robot description: {e}")
            return

        def prepare():
            self.model_status = "Converting robot meshes ..."
            # convert the meshes for the 3D view up front (cached), so the web page never waits for it
            meshes = model.mesh_filenames()
            for filename in meshes:
                glb_url(filename, self.get_logger())
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
