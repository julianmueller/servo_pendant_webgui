"""Settings overlay: the interface of this browser, the node's parameters and MoveIt Servo's (read-only)."""

import asyncio

from nicegui import ui

from servo_pendant_webgui.servo_commander import LIVE_PARAMETERS

SCALE_MIN, SCALE_MAX = 60, 160  # [%] UI scale

# (title, note, node parameters)
NODE_GROUPS = (
    (
        "ROBOT CONTROL",
        "Applies at once, to every connected panel. Held inputs are released.",
        (
            "base_frame",
            "tool_frame",
            "max_linear_speed",
            "max_angular_speed",
            "max_joint_speed",
            "input_timeout",
            "publish_rate",
            "exclude_joints",
        ),
    ),
    (
        "TOPICS & SERVICES",
        "Set at launch: --ros-args -p <name>:=<value>",
        (
            "twist_topic",
            "joint_jog_topic",
            "joint_states_topic",
            "robot_description_topic",
            "switch_command_type_service",
        ),
    ),
    ("WEB SERVER", "Set at launch", ("host", "port")),
)
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
NUMBER_STEPS = {"publish_rate": 5.0, "input_timeout": 0.05}


def _title(name):
    return name.replace("_", " ").capitalize()


def _fmt(value):
    if isinstance(value, str):
        return value or '""'
    if hasattr(value, "__iter__"):
        return ", ".join(map(str, value)) or "[]"
    return str(value)


class SettingsPanel:
    """
    Overlay on the right. Interface settings are handed to on_theme(dark) / on_scale(scale) and kept per browser by
    the page; parameters are set on the node, so they apply to all panels (and `ros2 param get` shows them).
    """

    def __init__(self, commander, dark, scale, on_theme, on_scale):
        self.c = commander
        self._fields = {}  # parameter -> element showing it
        with ui.dialog().props("position=right full-height") as self.dialog:
            with ui.element("div").classes("sd-settings"):
                with ui.element("div").classes("sd-settings-head"):
                    ui.icon("settings", size="22px")
                    ui.label("SETTINGS").classes("sd-title")
                    ui.space()
                    ui.button(icon="close", color=None, on_click=self.dialog.close).props(
                        "flat round dense"
                    ).classes("sd-icon-btn")
                with ui.element("div").classes("sd-settings-body"):
                    self._group("INTERFACE", "This browser only")
                    with self._row("Theme", "Light or dark colours"):
                        self.theme = (
                            ui.toggle(
                                {False: "LIGHT", True: "DARK"},
                                value=dark,
                                on_change=lambda e: on_theme(e.value),
                            )
                            .props("unelevated dense toggle-color=primary")
                            .classes("sd-toggle")
                        )
                    with self._row("UI scale", "Size of the whole panel"):
                        with ui.element("div").classes("sd-scale"):
                            ui.button(
                                icon="restart_alt",
                                color=None,
                                on_click=lambda: self.scale.set_value(100),
                            ).props("flat round dense").classes("sd-icon-btn").tooltip(
                                "100 %"
                            )
                            self.scale = ui.slider(
                                min=SCALE_MIN,
                                max=SCALE_MAX,
                                step=5,
                                value=round(scale * 100),
                                on_change=lambda e: (
                                    on_scale(e.value / 100),
                                    scale_label.set_text(f"{e.value} %"),
                                ),
                            ).props("dense")
                            scale_label = ui.label(f"{round(scale * 100)} %").classes(
                                "sd-set-value"
                            )

                    for title, note, names in NODE_GROUPS:
                        self._group(title, note)
                        for name in names:
                            self._parameter(name)

                    self._group(
                        "MOVEIT SERVO",
                        f"Read-only, from {commander.servo_node} (set in Servo's config)",
                    )
                    self.servo_box = ui.element("div").classes("w-full")

                    self._group("ROS", "Fixed when the node starts")
                    for key, value in commander.ros_info().items():
                        with self._row(key):
                            ui.label(value).classes("sd-set-value")
        self.dialog.on_value_change(self._on_open)

    @property
    def is_open(self):
        return self.dialog.value

    def open(self):
        self.dialog.open()

    # ------------------------------------------------------------------ #

    @staticmethod
    def _group(title, note):
        with ui.element("div").classes("sd-set-group"):
            ui.label(title).classes("sd-title")
            ui.label(note).classes("sd-set-desc")

    @staticmethod
    def _row(title, description=None, key=None):
        """A settings row; returns the container of its control (use it with `with`)."""
        with ui.element("div").classes("sd-set-row"):
            with ui.element("div").classes("sd-set-label"):
                ui.label(title).classes("sd-set-name")
                if description:
                    ui.label(description).classes("sd-set-desc")
                if key:
                    ui.label(key).classes("sd-set-key")
            return ui.element("div").classes("sd-set-ctl")

    def _parameter(self, name):
        value = self.c.get_parameter(name).value
        description = self.c.describe_parameter(name).description
        with self._row(_title(name), description, name):
            if name not in LIVE_PARAMETERS:
                field = ui.label(_fmt(value)).classes("sd-set-value")
            elif name in ("base_frame", "tool_frame"):
                field = ui.select(
                    [value],
                    value=value,
                    with_input=True,
                    new_value_mode="add-unique",
                    on_change=lambda e, n=name: self._apply(n, e.value),
                ).props("dense outlined options-dense")
            elif name == "exclude_joints":
                field = ui.input_chips(
                    value=list(value),
                    new_value_mode="add-unique",
                    on_change=lambda e, n=name: self._apply(n, list(e.value)),
                ).props("dense outlined")
            else:
                field = ui.number(value=value, step=NUMBER_STEPS.get(name, 0.05)).props(
                    "dense outlined"
                )
                # on blur / enter, not per keystroke: "0.25" must not be applied as 0, then 0.2
                for event in ("blur", "keydown.enter"):
                    field.on(event, lambda _, n=name, f=field: self._apply(n, f.value))
        self._fields[name] = field

    def _apply(self, name, value):
        if value is None or value == self.c.get_parameter(name).value:
            return
        try:
            ok, reason = self.c.set_parameter_value(name, value)
        except Exception as e:  # e.g. a value of the wrong type
            ok, reason = False, str(e)
        if ok:
            ui.notify(f"{name} = {_fmt(value)}", type="positive", position="top")
        else:
            ui.notify(f"{name} not changed: {reason}", type="negative", position="top")
            self._show(name)

    def _show(self, name):
        """Show the parameter's current value (it may have been changed elsewhere, e.g. `ros2 param set`)."""
        field, value = self._fields[name], self.c.get_parameter(name).value
        if isinstance(field, ui.select):
            model = self.c.model
            frames = list(model.links) if model is not None else []
            field.set_options(frames if value in frames else frames + [value], value=value)
        elif isinstance(field, ui.input_chips):
            field.value = list(value)
        elif isinstance(field, ui.number):
            field.value = value
        else:
            field.set_text(_fmt(value))

    async def _on_open(self, e):
        if not e.value:
            return
        for name in self._fields:
            self._show(name)
        await self._load_servo()

    async def _load_servo(self):
        self.servo_box.clear()
        with self.servo_box:
            status = ui.label("Reading ...").classes("sd-set-desc sd-set-pad")
        try:
            values = await asyncio.wait_for(
                asyncio.wrap_future(self.c.fetch_servo_parameters()), 3.0
            )
        except Exception as e:
            status.set_text(f"Not available: {str(e) or 'no answer'}")
            return
        self.servo_box.clear()
        with self.servo_box:
            main = [n for n in SERVO_MAIN if n in values]
            for name in main:
                self._servo_row(name, values[name])
            rest = [n for n in values if n not in main]
            if rest:
                with ui.expansion(f"All {len(values)} Servo parameters").classes(
                    "sd-set-more w-full"
                ).props("dense"):
                    for name in rest:
                        self._servo_row(name, values[name])

    def _servo_row(self, name, value):
        with self._row(_title(name.replace(".", " ")), key="moveit_servo." + name):
            ui.label(_fmt(value)).classes("sd-set-value")
