"""
App sections of Settings > Web GUI (the shell adds the node parameters and the ROS, Appearance and About tabs): the
joint states topic, the command frames and hidden joints with editors the generic parameter list has no control for,
and MoveIt Servo's parameters.
"""

import asyncio

from nicegui import ui

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


def robot_control_section(panel):
    node = panel.bridge.node
    if node is None:
        return
    panel.section("Frames and joints", "Applies at once to every open page. Held inputs are released.")
    topic = node.get_parameter("joint_states_topic").value
    topics = node.joint_state_topics()
    with panel.row("Joint states topic", "sensor_msgs/JointState of the robot (e.g. /isaac_joint_states)",
                   "joint_states_topic"):
        ui.select(
            topics if topic in topics else topics + [topic],
            value=topic,
            with_input=True,
            new_value_mode="add-unique",
            on_change=lambda e: _apply(panel.bridge.node, "joint_states_topic", e.value),
        ).props("outlined")
    links = list(node.model.links) if node.model is not None else []
    for name, title, description in (
        ("base_frame", "Base frame", "Frame of the commands in base mode"),
        ("tool_frame", "Tool frame", "Frame of the commands in tool mode"),
    ):
        value = node.get_parameter(name).value
        with panel.row(title, description, name):
            ui.select(
                links if value in links else links + [value],
                value=value,
                with_input=True,
                new_value_mode="add-unique",
                on_change=lambda e, n=name: _apply(panel.bridge.node, n, e.value),
            ).props("outlined")
    with panel.row("Hidden joints", "Regular expressions of joints not shown in the panel", "exclude_joints"):
        ui.input_chips(
            value=list(node.get_parameter("exclude_joints").value),
            new_value_mode="add-unique",
            on_change=lambda e: _apply(panel.bridge.node, "exclude_joints", list(e.value)),
        ).props("outlined")


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


SETTINGS_SECTIONS = (robot_control_section, servo_section)
