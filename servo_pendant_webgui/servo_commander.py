import re
import threading
import time

import numpy as np

from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from control_msgs.msg import JointJog
from geometry_msgs.msg import TwistStamped
from moveit_msgs.srv import ServoCommandType
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
        p = self.declare_parameter
        p("twist_topic", "/servo_node/delta_twist_cmds")
        p("joint_jog_topic", "/servo_node/delta_joint_cmds")
        p("joint_states_topic", "/joint_states")
        p("robot_description_topic", "/robot_description")
        p("switch_command_type_service", "/servo_node/switch_command_type")
        p("stop_service", "/panda_driver/stop")
        p("base_frame", "panda_link0")
        p("tool_frame", "panda_link8")
        p("max_linear_speed", 0.1)  # [m/s] at full deflection and 100 % speed
        p("max_angular_speed", 0.5)  # [rad/s]
        p("max_joint_speed", 0.5)  # [rad/s]
        p("publish_rate", 50.0)  # [Hz]
        p(
            "input_timeout", 0.3
        )  # [s] an input that is not refreshed for this long counts as released
        p(
            "exclude_joints", [".*finger.*"]
        )  # regexes of joint_states names not shown in the panel
        p("host", "0.0.0.0")
        p("port", 8080)

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

        self._lock = threading.Lock()
        self._inputs = {}  # key -> (value, monotonic time)
        self.mode = TWIST
        self.speed = 0.3  # global speed scale 0..1
        self.frame = "base"  # 'base' | 'tool'
        self.plane = "XY"
        self._idle_count = 0
        self.last_command = "idle"

        self.joint_names = []  # arm joints shown in the panel, in joint_states order
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
        self._stop_client = self.create_client(Trigger, val("stop_service"))

        self.create_timer(1.0 / val("publish_rate"), self._publish)
        self.create_timer(1.0, self._watch_servo)
        self.create_timer(2.0, self._check_joint_states_publishers)

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
        if self._stop_client.service_is_ready():
            self._stop_client.call_async(Trigger.Request())
            self.last_command = "STOP sent"
        else:
            self.last_command = "inputs released (stop service not available)"

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
            names = list(self.joint_names) + [n for n in velocities if n not in self.joint_names]
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
                if name not in self.joint_names and not any(
                    r.fullmatch(name) for r in self._exclude
                ):
                    self.joint_names.append(name)
            self._joint_states_time = time.monotonic()

    def _on_robot_description(self, msg):
        try:
            model = UrdfModel.from_xml(msg.data)
        except Exception as e:
            self.get_logger().error(f"Could not parse the robot description: {e}")
            return

        def prepare():
            self.model_status = "Converting robot meshes ..."
            # convert the meshes for the 3D view up front (cached), so the web page never waits for it
            meshes = {
                v.filename
                for visuals in model.visuals.values()
                for v in visuals
                if v.kind == "mesh"
            }
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
        nodes = sorted({info.node_name for info in self.get_publishers_info_by_topic(self._joint_states_topic)})
        self.joint_states_warning = (
            f"{len(nodes)} publishers on {self._joint_states_topic}: {', '.join(nodes)}" if len(nodes) > 1 else ""
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
