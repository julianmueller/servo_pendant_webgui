"""
App sections of Settings > Web GUI (the shell adds the node parameters and the ROS, Appearance and About tabs): the
topics and the Servo service as dropdowns of the ones found, the command frames and hidden joints, with editors the
generic parameter list has no control for, and MoveIt Servo's parameters. The controls follow the parameters while
the settings are open, so a `ros2 param set` shows up at once.
"""

import asyncio

from nicegui import ui

from servo_pendant_webgui.shell import settings_panel

# MoveIt Servo parameters shown first; the others are folded away
SERVO_MAIN = (
    "move_group_name",
    "active_subgroup",
    "command_in_type",
    "command_out_type",
    "command_out_topic",
    "publish_period",
    "incoming_command_timeout",
    "check_collisions",
)


def _text(value):
    if isinstance(value, str):
        return value or "(empty)"
    if hasattr(value, "__iter__"):
        return ", ".join(map(str, value)) or "(empty)"
    return str(value)


def _apply(node, name, value):
    if node is None or value is None or value == node.get_parameter(name).value:
        return
    try:
        ok, reason = node.set_parameter_value(name, value)
    except Exception as e:  # e.g. a value of the wrong type
        ok, reason = False, str(e)
    if ok:
        ui.notify(f"{name} set to {_text(value)}", type="positive")
    else:
        ui.notify(f"{name} not changed: {reason}", type="negative")


class _LiveRows:
    """
    Keeps the controls of a section in step with the node's parameters while the settings are open, so a change made
    elsewhere (`ros2 param set`, another browser) shows up at once. A control is only updated when its parameter
    changed, so a value being typed is not overwritten.
    """

    def __init__(self, panel):
        self.panel = panel
        self.rows = []  # [name, control, options (callable or None), last parameter value]
        self._ticks = 0
        ui.timer(0.5, self._sync)

    def add(self, name, control, options=None):
        node = self.panel.bridge.node
        self.rows.append([name, control, options, node.get_parameter(name).value])
        return control

    def _sync(self):
        node = self.panel.bridge.node
        if node is None or not self.panel.dialog.value:
            return
        self._ticks += 1
        for row in self.rows:
            name, control, options, last = row
            value = node.get_parameter(name).value
            if isinstance(value, (list, tuple)):
                value = list(value)
            if options is not None and (value != last or self._ticks % 4 == 0):  # topics come and go: every 2 s
                control.set_options(_with(options(node), value), value=value)
            elif value != last:
                control.value = value
            row[3] = value


def _with(options, value):
    return options if value in options else [*options, value]


def _select(panel, live, name, options):
    """A dropdown of the found names, which also takes any other name (typed, then Enter)."""
    node = panel.bridge.node
    value = node.get_parameter(name).value
    return live.add(
        name,
        ui.select(
            _with(options(node), value),
            value=value,
            with_input=True,
            new_value_mode="add-unique",
            on_change=lambda e: _apply(panel.bridge.node, name, e.value),
        ).props("outlined"),
        options,
    )


def _description_topics(node):
    # every std_msgs/String topic, those named like a robot description first
    return sorted(node.connection_names("robot_description_topic"), key=lambda n: ("description" not in n, n))


# parameter -> (title, description, options)
TOPICS = {
    "joint_states_topic": (
        "Joint states",
        "sensor_msgs/JointState of the robot (e.g. /isaac_joint_states)",
        lambda node: node.connection_names("joint_states_topic"),
    ),
    "robot_description_topic": (
        "Robot description",
        "std_msgs/String with the URDF, for the 3D view and the joint limits",
        _description_topics,
    ),
    "twist_topic": (
        "Cartesian commands",
        "geometry_msgs/TwistStamped to Servo",
        lambda node: node.connection_names("twist_topic"),
    ),
    "joint_jog_topic": (
        "Joint commands",
        "control_msgs/JointJog to Servo",
        lambda node: node.connection_names("joint_jog_topic"),
    ),
    "switch_command_type_service": (
        "Servo command type service",
        "moveit_msgs/ServoCommandType. Servo's node (for its parameters) is found from it.",
        lambda node: node.connection_names("switch_command_type_service"),
    ),
    "pause_servo_service": (
        "Servo pause service",
        "std_srvs/SetBool: called with true by Pause, with false when a mode is chosen again",
        lambda node: node.connection_names("pause_servo_service"),
    ),
    "servo_status_topic": (
        "Servo status",
        "moveit_msgs/ServoStatus: slowing down or halted, and why. Shown on the robot while not NO_WARNING.",
        lambda node: node.connection_names("servo_status_topic"),
    ),
}


def topics_section(panel):
    node = panel.bridge.node
    if node is None:
        return
    panel.section("Topics and services", "The topics and services found of each type; type another name and press "
                  "Enter. Applies at once to every open page. Held inputs are released.")  # fmt: skip
    live = _LiveRows(panel)
    for name, (title, description, options) in TOPICS.items():
        with panel.row(title, description, name):
            _select(panel, live, name, options)


def robot_control_section(panel):
    node = panel.bridge.node
    if node is None:
        return
    panel.section("Frames and joints", "Applies at once to every open page. Held inputs are released.")
    live = _LiveRows(panel)

    def links(node):
        return list(node.model.links) if node.model is not None else []

    for name, title, description in (
        ("base_frame", "Base frame", "Frame of the commands in base mode"),
        ("tool_frame", "Tool frame", "Frame of the commands in tool mode"),
    ):
        with panel.row(title, description, name):
            _select(panel, live, name, links)
    with panel.row("Hidden joints", "Regular expressions of joints not shown in the panel", "exclude_joints"):
        live.add(
            "exclude_joints",
            ui.input_chips(
                value=list(node.get_parameter("exclude_joints").value),
                new_value_mode="add-unique",
                on_change=lambda e: _apply(panel.bridge.node, "exclude_joints", list(e.value)),
            ).props("outlined"),
        )


def servo_section(panel):
    node = panel.bridge.node
    if node is None:
        return
    panel.section("MoveIt Servo", f"Read-only, from {node.servo_node} (set in Servo's configuration)")
    box = ui.element("div").classes("w-full")
    with box:
        status = ui.label("Reading the parameters").classes("wg-hint py-2")

    async def load():
        try:
            values = await asyncio.wait_for(asyncio.wrap_future(node.fetch_servo_parameters()), 3.0)
        except Exception as e:
            if not box.is_deleted:
                status.set_text(f"Not available: {str(e) or 'no answer'}. Start Servo with launch_servo:=true.")
            return
        if box.is_deleted:  # the settings were closed or rebuilt meanwhile
            return
        box.clear()
        with box:
            main = [n for n in SERVO_MAIN if n in values]
            for name in main:
                _servo_row(panel, name, values[name])
            rest = [n for n in values if n not in main]
            if rest:
                with ui.expansion(f"All {len(values)} Servo parameters").classes("w-full"):
                    for name in rest:
                        _servo_row(panel, name, values[name])

    ui.timer(0, load, once=True)


def _servo_row(panel, name, value):
    with panel.row(name.replace("_", " ").replace(".", ": ").capitalize(), key="moveit_servo." + name):
        ui.label(_text(value)).classes("wg-mono wg-set-value")


SETTINGS_SECTIONS = (topics_section, robot_control_section, servo_section)

# Shown by the sections above with their own controls: not again in the generic parameter list of the shell
settings_panel.HIDDEN_PARAMETERS.update((*TOPICS, "base_frame", "tool_frame", "exclude_joints"))
