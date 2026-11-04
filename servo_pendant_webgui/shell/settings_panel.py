"""
Settings: an overlay with its tabs in the header.

- ROS: domain ID, discovery range, static peers, node name and namespace. *Apply and restart* restarts the
  webgui's ROS node with them (whole webgui, saved on the server).
- Web GUI: the node's parameters (refresh rates, sampling, limits, ...) and the app's own sections. They apply at
  once (whole webgui).
- Appearance: theme, text size and spacing (this browser).
- About: what the webgui is, its version and address, ROS and software facts.

Shared webgui shell (from the nicegui-ros2-webgui skill): keep it identical across the webgui packages. App specific
settings are node parameters (shown in *Web GUI* automatically) or a section added with `extra_sections`.
"""

import platform
import re
from dataclasses import replace
from functools import cache
from importlib import metadata
from pathlib import Path

import nicegui
from nicegui import app, run, ui
from rclpy.parameter import Parameter

from servo_pendant_webgui.shell import theme
from servo_pendant_webgui.shell.config import DISCOVERY_RANGES, MAX_DOMAIN_ID

HIDDEN_PARAMETERS = {"use_sim_time", "start_type_description_service"}

# tab name -> (label, icon)
TABS = {
    "ros": ("ROS", "sym_o_hub"),
    "webgui": ("Web GUI", "sym_o_tune"),
    "appearance": ("Appearance", "sym_o_palette"),
    "about": ("About", "sym_o_info"),
}

CSS = """
.q-dialog__inner:has(> .wg-settings) { padding: 16px; }
.q-dialog__inner--minimized > .wg-settings { max-width: calc(100vw - 32px); max-height: calc(100dvh - 32px); }
.wg-settings { width: 760px; height: 720px; display: flex; flex-direction: column; overflow: hidden;
               background: var(--wg-surface); color: var(--wg-text); border: 1px solid var(--wg-border);
               border-radius: var(--wg-radius); box-shadow: 0 16px 48px var(--wg-veil); }
.wg-settings-head { display: flex; align-items: stretch; gap: 8px; min-height: var(--wg-header-h); flex: none;
                    padding: 0 8px 0 20px; border-bottom: 1px solid var(--wg-border); }
.wg-settings-title { display: flex; align-items: center; gap: 10px; padding-right: 12px; color: var(--wg-muted); }
.wg-settings-title .wg-h2 { color: var(--wg-text); }
.wg-settings-tabs { flex: 1; min-width: 0; }
.wg-settings-tabs .q-tab { min-height: var(--wg-header-h); padding: 0 14px; }
.wg-settings-tabs .q-tab:not(.q-tab--active) { color: var(--wg-muted); }
.wg-settings-tabs .q-tab__icon { font-size: 20px; }
.wg-settings-close { align-self: center; }
.wg-settings > .q-tab-panels { flex: 1; min-height: 0; background: transparent; color: inherit; }
.wg-settings .q-panel, .wg-settings .q-panel > div { height: 100%; width: 100%; }
.wg-settings .q-tab-panel { padding: 0; width: 100%; height: 100%; overflow-y: auto; display: flex;
                            flex-direction: column; align-items: stretch; gap: 0; }
.wg-set-body { flex: 1 0 auto; padding: 0 var(--wg-space-lg) var(--wg-space-lg); }
.wg-set-intro { padding: var(--wg-space) 0 0; }
.wg-set-section { padding: var(--wg-space-lg) 0 var(--wg-space-sm); display: flex; flex-direction: column; gap: 2px; }
.wg-set-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 320px); gap: var(--wg-space-in);
              align-items: center; padding: calc(10px * var(--wg-space-scale)) 0;
              border-top: 1px solid var(--wg-divider); }
.wg-set-label { display: flex; flex-direction: column; min-width: 0; }
.wg-set-name { font-weight: 500; }
.wg-set-key { color: var(--wg-subtle); font-size: var(--wg-fs-xs); overflow-wrap: anywhere; }
.wg-set-ctl { display: flex; justify-content: flex-end; min-width: 0; }
.wg-set-ctl > .q-field { width: 100%; }
.wg-set-value { text-align: right; overflow-wrap: anywhere; user-select: text; }
.wg-set-footer { position: sticky; bottom: 0; z-index: 1; display: flex; align-items: center; flex-wrap: wrap;
                 gap: var(--wg-space-in); padding: var(--wg-space-in) var(--wg-space-lg); flex: none;
                 background: var(--wg-surface); border-top: 1px solid var(--wg-border); }
.wg-set-footer .wg-hint { flex: 1; min-width: 200px; overflow-wrap: anywhere; }
.wg-set-footer .wg-hint.wg-pending { color: var(--wg-warning); font-weight: 500; }
.wg-about-head { display: flex; align-items: center; gap: var(--wg-space); padding: var(--wg-space-lg) 0 0; }
.wg-about-head > .q-icon { color: var(--wg-primary); flex: none; }
@media (max-width: 720px) {
  .q-dialog__inner:has(> .wg-settings) { padding: 0 !important; }
  .q-dialog__inner--minimized > .wg-settings { max-width: 100vw; max-height: 100dvh; }
  .wg-settings { width: 100vw; height: 100dvh; border: none; border-radius: 0; }
  .wg-settings-head { flex-wrap: wrap; padding: 0 8px 0 16px; gap: 0; }
  .wg-settings-title { flex: 1; min-height: var(--wg-header-h); }
  .wg-settings-close { order: 2; }
  .wg-settings-tabs { order: 3; flex: 1 0 100%; margin: 0 -8px 0 -16px; }
  .wg-settings-tabs .q-tab { min-height: var(--wg-touch); padding: 0 12px; }
  .wg-settings-tabs .q-tab__icon { display: none; }
  .wg-set-body { padding: 0 16px 16px; }
  .wg-set-footer { padding: 12px 16px; }
}
@media (max-width: 520px) {
  .wg-set-row { grid-template-columns: minmax(0, 1fr); }
  .wg-set-ctl { justify-content: flex-start; }
  .wg-set-value { text-align: left; }
}
"""


def _title(name):
    return name.replace("_", " ").replace(".", ": ").capitalize()


def _text(value):
    if isinstance(value, str):
        return value or "(empty)"
    if isinstance(value, (list, tuple)) or hasattr(value, "tolist"):
        return ", ".join(map(str, value)) or "(empty)"
    return str(value)


def _home(path):
    return str(path).replace(str(Path.home()), "~", 1)


@cache
def package_version(package):
    """Version of the installed package (from setup.py / package.xml), or 'unknown'."""
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        pass
    try:
        from ament_index_python.packages import get_package_share_directory

        xml = (Path(get_package_share_directory(package)) / "package.xml").read_text()
        return re.search(r"<version>\s*([^<\s]+)\s*</version>", xml).group(1)
    except Exception:  # not installed with colcon (e.g. run from the source tree)
        return "unknown"


class SettingsPanel:
    def __init__(self, frame, extra_sections=()):
        """extra_sections: callables that build a section of the app in the Web GUI tab (use `panel.section`)."""
        self.frame = frame
        self.bridge = frame.bridge
        self._extra = extra_sections
        self.theme_toggle = None
        ui.add_css(CSS)
        with ui.dialog() as self.dialog, ui.element("div").classes("wg-settings"):
            with ui.element("div").classes("wg-settings-head"):
                with ui.element("div").classes("wg-settings-title"):
                    ui.icon("sym_o_settings", size="24px")
                    ui.label("Settings").classes("wg-h2")
                with ui.tabs(value="ros").props(
                    "no-caps inline-label align=left active-color=primary indicator-color=primary"
                ).classes("wg-settings-tabs") as self.tabs:
                    for name, (label, icon) in TABS.items():
                        ui.tab(name, label, icon)
                ui.button(icon="sym_o_close", on_click=self.dialog.close).props("flat round").classes(
                    "wg-icon-btn wg-settings-close"
                ).tooltip("Close (Esc)")
            self._panels = {}
            with ui.tab_panels(self.tabs, value="ros", animated=False):
                for name in TABS:
                    with ui.tab_panel(name):
                        self._panels[name] = ui.element("div").classes("contents")
        self.dialog.on_value_change(lambda e: e.value and self._build())

    def open(self, tab=None):
        """Opens the settings, on `tab` ("ros", "webgui", "appearance", "about") or the one shown last."""
        if tab:
            self.tabs.set_value(tab)
        self.dialog.open()

    # ------------------------------------------------------------------ building blocks for every tab

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

    def value_row(self, name, value, mono=True):
        with self.row(name):
            ui.label(value).classes("wg-set-value" + (" wg-mono" if mono else ""))

    # ------------------------------------------------------------------ content (rebuilt on every opening)

    def _build(self):
        for name, build in (
            ("ros", self._ros),
            ("webgui", self._webgui),
            ("appearance", self._appearance),
            ("about", self._about),
        ):
            container = self._panels[name]
            container.clear()
            with container:
                build()

    # ------------------------------------------------------------------ ROS

    def _ros(self):
        c = self.bridge.connection
        package = self.frame.store.package
        with ui.element("div").classes("wg-set-body"):
            self.section("Connection", "Which ROS nodes the web GUI finds and talks to.")
            with self.row("Domain ID", f"0 to {MAX_DOMAIN_ID}. Only nodes with the same ID can talk to each other.",
                          "ROS_DOMAIN_ID"):  # fmt: skip
                domain = ui.number(value=c.domain_id, min=0, max=MAX_DOMAIN_ID, step=1, precision=0).props("outlined")
            with self.row("Discovery range", "Where other nodes are looked for", "ROS_AUTOMATIC_DISCOVERY_RANGE"):
                discovery = ui.select(DISCOVERY_RANGES, value=c.discovery_range).props("outlined")
            with self.row("Static peers", "Hosts outside the range, separated by ;", "ROS_STATIC_PEERS"):
                peers = ui.input(value=c.static_peers, placeholder="e.g. 192.168.0.20").props("outlined")

            self.section("Node", "The web GUI's own node: its topics, services and parameters are under this name.")
            with self.row("Node name", f"Empty: {package}", "__node"):
                node_name = ui.input(value=c.node_name, placeholder=package).props("outlined")
            with self.row("Namespace", "Prefix of the node and its relative topics, e.g. /robot1", "__ns"):
                namespace = ui.input(value=c.namespace, placeholder="none").props("outlined")
            node = self.bridge.node
            self.value_row("Running as", node.get_fully_qualified_name() if node else "restarting")

        def entered():
            value = domain.value
            ns = (namespace.value or "").strip().rstrip("/")
            return replace(
                c,
                domain_id=int(value) if value is not None else -1,
                discovery_range=discovery.value,
                static_peers=(peers.value or "").strip(),
                node_name=(node_name.value or "").strip(),
                namespace=("/" + ns.lstrip("/")) if ns else "",
            )

        saved = f"Applies to the whole web GUI. Saved in {_home(self.frame.store.path)}"

        def show_pending():
            pending = entered() != c
            button.set_enabled(pending)
            note.set_text("Not applied yet. Apply restarts the node; every open page uses the new one."
                          if pending else saved)  # fmt: skip
            if pending:
                note.classes(add="wg-pending")
            else:
                note.classes(remove="wg-pending")

        async def apply():
            new = entered()
            error = new.validate()
            if error:
                ui.notify(error, type="negative")
                return
            button.props("loading")
            try:
                await run.io_bound(self.bridge.reconnect, new)
            except Exception as e:
                ui.notify(f"Not restarted: {e}. The node runs with the previous settings.", type="negative")
                return
            finally:
                button.props(remove="loading")
            self.frame.store.save_connection(new)
            node = self.bridge.node
            ui.notify(f"Node restarted: {node.get_fully_qualified_name() if node else '?'} in domain {new.domain_id}",
                      type="positive")  # fmt: skip
            self._build()

        with ui.element("div").classes("wg-set-footer"):
            note = ui.label(saved).classes("wg-hint")
            button = ui.button("Apply and restart", icon="sym_o_restart_alt", on_click=apply).props("unelevated")
            button.disable()
        for field in (domain, discovery, peers, node_name, namespace):
            field.on_value_change(show_pending)

    # ------------------------------------------------------------------ Web GUI

    def _webgui(self):
        node = self.bridge.node
        names = []
        if node is not None:
            names = sorted(n for n in node.get_parameters_by_prefix("") if n not in HIDDEN_PARAMETERS)
        with ui.element("div").classes("wg-set-body"):
            if node is None:
                self._empty("sym_o_sync", "The node is restarting", "Its parameters show up here in a moment.")
                return
            if not names and not self._extra:
                self._empty("sym_o_tune", "No settings for this web GUI",
                            "Node parameters with a description show up here.")  # fmt: skip
                return
            ui.label("Apply at once, for every open page. Parameters can also be set with ros2 param set.").classes(
                "wg-hint wg-set-intro"
            )
            for build in self._extra:
                build(self)
            groups = {}  # "refresh.topics" -> section "Refresh", row "Topics"
            for name in names:
                group, _, rest = name.partition(".") if "." in name else ("", "", name)
                groups.setdefault(group, []).append((name, rest))
            for group in sorted(groups, key=lambda g: (g != "", g)):
                self.section(_title(group) if group else "Parameters")
                for name, short in groups[group]:
                    self._parameter(node, name, short)

    @staticmethod
    def _empty(icon, title, hint):
        with ui.element("div").classes("wg-empty"):
            ui.icon(icon, size="36px")
            ui.label(title)
            ui.label(hint).classes("wg-hint")

    def _parameter(self, node, name, short):
        value = node.get_parameter(name).value
        descriptor = node.describe_parameter(name)
        limits = descriptor.floating_point_range or descriptor.integer_range
        notes = [descriptor.description.rstrip(".")] if descriptor.description else []
        if limits:
            notes.append(f"From {limits[0].from_value:g} to {limits[0].to_value:g}")
        if descriptor.read_only:
            notes.append("Set at start")
        with self.row(_title(short), ". ".join(notes) or None, name):
            if descriptor.read_only or isinstance(value, (list, tuple, bytes)) or value is None:
                ui.label(_text(value)).classes("wg-mono wg-set-value")
            elif isinstance(value, bool):
                ui.switch(value=value, on_change=lambda e, n=name: self._set(n, e.value))
            elif isinstance(value, (int, float)):
                field = ui.number(value=value, precision=0 if isinstance(value, int) else None).props("outlined")
                if limits:
                    field.props(f"min={limits[0].from_value} max={limits[0].to_value}")
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
        except Exception as e:  # e.g. a value of the wrong type or out of range
            ok, reason = False, str(e)
        if ok:
            ui.notify(f"{_title(name)} set to {_text(value)}", type="positive")
        else:
            ui.notify(f"{_title(name)} not changed: {reason}", type="negative")

    # ------------------------------------------------------------------ Appearance

    def _appearance(self):
        frame = self.frame
        toggle = "no-caps unelevated toggle-color=primary"
        with ui.element("div").classes("wg-set-body"):
            self.section("This browser", "Saved here. Other web GUIs at the same address use these settings too.")
            with self.row("Theme", "Light, dark, or as set in the operating system"):
                self.theme_toggle = ui.toggle(
                    theme.THEMES, value=frame.theme, on_change=lambda e: frame.set_theme(e.value)
                ).props(toggle)
            with self.row("Text size", "Size of all text and of the controls around it"):
                ui.toggle(theme.TEXT_SIZES, value=frame.appearance["text"],
                          on_change=lambda e: frame.set_appearance("text", e.value)).props(toggle)  # fmt: skip
            with self.row("Spacing", "Space around and between panels. Touch targets stay at least 44 px."):
                ui.toggle(theme.SPACINGS, value=frame.appearance["spacing"],
                          on_change=lambda e: frame.set_appearance("spacing", e.value)).props(toggle)  # fmt: skip

        def reset():
            frame.set_theme(theme.APPEARANCE["theme"][2])
            for name in ("text", "spacing"):
                frame.set_appearance(name, theme.APPEARANCE[name][2])
            self._build()

        with ui.element("div").classes("wg-set-footer"):
            ui.label("Keyboard: D switches between light and dark.").classes("wg-hint")
            ui.button("Reset appearance", icon="sym_o_undo", on_click=reset).props("outline")

    # ------------------------------------------------------------------ About

    def _about(self):
        frame, store = self.frame, self.frame.store
        version = package_version(store.package)
        with ui.element("div").classes("wg-set-body"):
            with ui.element("div").classes("wg-about-head"):
                ui.icon(frame.icon, size="44px")
                with ui.element("div").classes("flex flex-col min-w-0"):
                    ui.label(frame.title).classes("wg-h1")
                    if frame.description:
                        ui.label(frame.description).classes("wg-hint")

            self.section("Web GUI")
            self.value_row("Package", store.package)
            self.value_row("Version", version)
            self.value_row("Web address", ", ".join(sorted(app.urls)) or "starting")
            self.value_row("Start options", "--host, --port, --domain-id, --namespace, --node-name")
            self.value_row("Settings file", _home(store.path))
            with self.row("Keyboard shortcuts", "Every key of this page"):
                ui.button("Show", icon="sym_o_keyboard", on_click=self._show_shortcuts).props("outline")

            self.section("ROS")
            for name, value in self.bridge.info().items():
                self.value_row(name, value)

            self.section("Software")
            self.value_row("NiceGUI", nicegui.__version__)
            self.value_row("Python", platform.python_version())
            self.value_row("Fonts", "IBM Plex Sans and Mono (SIL Open Font License)", mono=False)

    def _show_shortcuts(self):
        self.dialog.close()
        self.frame.shortcuts.show_help()
