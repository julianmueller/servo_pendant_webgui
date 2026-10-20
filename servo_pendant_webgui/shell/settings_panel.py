"""
Settings drawer on the right: appearance (this browser), ROS connection and node parameters (the whole webgui).

Shared webgui shell (from the nicegui-ros2-webgui skill): keep it identical across the webgui packages. App specific
settings are node parameters (shown here automatically) or a section added with `extra_sections`.
"""

from dataclasses import replace
from pathlib import Path

from nicegui import app, run, ui
from rclpy.parameter import Parameter

from servo_pendant_webgui.shell import theme
from servo_pendant_webgui.shell.config import DISCOVERY_RANGES, MAX_DOMAIN_ID

HIDDEN_PARAMETERS = {"use_sim_time", "start_type_description_service"}


def _title(name):
    return name.replace("_", " ").replace(".", ": ").capitalize()


def _text(value):
    if isinstance(value, str):
        return value or "(empty)"
    if isinstance(value, (list, tuple)) or hasattr(value, "tolist"):
        return ", ".join(map(str, value)) or "(empty)"
    return str(value)


class SettingsPanel:
    def __init__(self, frame, extra_sections=()):
        """extra_sections: callables that build a section of the app inside the panel (use `panel.section`)."""
        self.frame = frame
        self.bridge = frame.bridge
        self._extra = extra_sections
        with ui.dialog().props("position=right full-height") as self.dialog:
            with ui.element("div").classes("wg-settings"):
                with ui.element("div").classes("wg-settings-head"):
                    ui.icon("sym_o_settings", size="24px")
                    ui.label("Settings").classes("wg-h2 flex-1")
                    ui.button(icon="sym_o_close", on_click=self.dialog.close).props("flat round").classes("wg-icon-btn")
                self.body = ui.element("div").classes("wg-settings-body")
        self.dialog.on_value_change(lambda e: e.value and self._build())

    def open(self):
        self.dialog.open()

    # ------------------------------------------------------------------ building blocks for every section

    @staticmethod
    def section(title, note=None):
        with ui.element("div").classes("wg-set-section"):
            ui.label(title).classes("wg-h2")
            if note:
                ui.label(note).classes("wg-hint")

    @staticmethod
    def row(name, description=None, key=None):
        """A setting: name (and description) left, the control right. Use the result with `with`."""
        with ui.element("div").classes("wg-set-row"):
            with ui.element("div").classes("wg-set-label"):
                ui.label(name).classes("wg-set-name")
                if description:
                    ui.label(description).classes("wg-hint")
                if key:
                    ui.label(key).classes("wg-mono wg-set-key")
            return ui.element("div").classes("wg-set-ctl")

    # ------------------------------------------------------------------ content (rebuilt on every opening)

    def _build(self):
        self.body.clear()
        with self.body:
            self._appearance()
            self._connection()
            for build in self._extra:
                build(self)
            self._parameters()
            self._about()

    def _appearance(self):
        self.section("Appearance", "Saved in this browser.")
        with self.row("Theme", "Light, dark, or as set in the operating system"):
            ui.toggle(theme.THEMES, value=self.frame.theme, on_change=lambda e: self.frame.set_theme(e.value)).props(
                "no-caps unelevated toggle-color=primary"
            )

    def _connection(self):
        c = self.bridge.connection
        form = {"domain_id": c.domain_id, "namespace": c.namespace, "discovery_range": c.discovery_range,
                "static_peers": c.static_peers}
        self.section("ROS connection", "Applies to the whole web GUI: every open page uses the new connection.")
        with self.row("Domain ID", f"0 to {MAX_DOMAIN_ID}. Only nodes with the same ID can talk to each other.",
                      "ROS_DOMAIN_ID"):
            ui.number(min=0, max=MAX_DOMAIN_ID, step=1, precision=0).props("outlined").bind_value(form, "domain_id")
        with self.row("Namespace", "Prefix of the node's relative topics, e.g. /robot1"):
            ui.input(placeholder="none").props("outlined").bind_value(form, "namespace")
        with self.row("Discovery range", "Where other nodes are looked for", "ROS_AUTOMATIC_DISCOVERY_RANGE"):
            ui.select(DISCOVERY_RANGES).props("outlined").bind_value(form, "discovery_range")
        with self.row("Static peers", "Hosts outside the range, separated by ;", "ROS_STATIC_PEERS"):
            ui.input(placeholder="e.g. 192.168.0.20").props("outlined").bind_value(form, "static_peers")

        async def apply():
            new = replace(
                c,
                domain_id=int(form["domain_id"] or 0),
                namespace=(form["namespace"] or "").strip(),
                discovery_range=form["discovery_range"],
                static_peers=(form["static_peers"] or "").strip(),
            )
            error = new.validate()
            if error:
                ui.notify(error, type="negative")
                return
            button.props("loading")
            try:
                await run.io_bound(self.bridge.reconnect, new)
                self.frame.store.save_connection(new)
            except Exception as e:
                ui.notify(f"Not connected: {e}. Check the settings and apply them again.", type="negative")
                return
            finally:
                button.props(remove="loading")
            ui.notify(f"Connected to ROS domain {new.domain_id}", type="positive")
            self._build()

        with ui.element("div").classes("wg-set-actions"):
            ui.label(f"Saved in {str(self.frame.store.path).replace(str(Path.home()), '~', 1)}").classes(
                "wg-hint flex-1"
            )
            button = ui.button("Apply and reconnect", icon="sym_o_sync", on_click=apply).props("unelevated no-caps")

    def _parameters(self):
        node = self.bridge.node
        if node is None:
            return
        names = sorted(n for n in node.get_parameters_by_prefix("") if n not in HIDDEN_PARAMETERS)
        if not names:
            return
        self.section("Parameters", "Node parameters, also available with ros2 param. Applies to every open page.")
        for name in names:
            value = node.get_parameter(name).value
            descriptor = node.describe_parameter(name)
            with self.row(_title(name), descriptor.description or None, name):
                if descriptor.read_only or isinstance(value, (list, tuple, bytes)) or value is None:
                    ui.label(_text(value)).classes("wg-mono wg-set-value")
                elif isinstance(value, bool):
                    ui.switch(value=value, on_change=lambda e, n=name: self._set(n, e.value))
                elif isinstance(value, (int, float)):
                    field = ui.number(value=value, precision=0 if isinstance(value, int) else None).props("outlined")
                    # on blur / Enter, not per keystroke: typing "0.25" must not apply 0, then 0.2
                    for event in ("blur", "keydown.enter"):
                        field.on(event, lambda _, n=name, f=field, t=type(value): self._set(n, t(f.value or 0)))
                else:
                    field = ui.input(value=value).props("outlined")
                    for event in ("blur", "keydown.enter"):
                        field.on(event, lambda _, n=name, f=field: self._set(n, f.value))

    def _set(self, name, value):
        node = self.bridge.node
        if node is None or node.get_parameter(name).value == value:
            return
        try:
            result = node.set_parameters([Parameter(name, value=value)])[0]
            ok, reason = result.successful, result.reason
        except Exception as e:  # e.g. a value of the wrong type
            ok, reason = False, str(e)
        if ok:
            ui.notify(f"{_title(name)} set to {_text(value)}", type="positive")
        else:
            ui.notify(f"{_title(name)} not changed: {reason}", type="negative")

    def _about(self):
        self.section("About")
        rows = dict(self.bridge.info())
        rows["Web address"] = ", ".join(app.urls) or "starting"
        rows["Server options"] = "--host, --port, --domain-id, --namespace"
        for name, value in rows.items():
            with self.row(name):
                ui.label(value).classes("wg-mono wg-set-value")
