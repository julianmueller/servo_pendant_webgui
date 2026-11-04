"""
The frame of every webgui page: header (name, ROS status, help, theme, settings, full screen), footer (facts: the
app's left, the node and version right), the settings overlay and the standard keyboard shortcuts. The app builds
its content inside `with frame.content:` and puts its own facts into `with frame.footer:`.

Shared webgui shell (from the nicegui-ros2-webgui skill): keep it identical across the webgui packages.
"""

from nicegui import ui

from servo_pendant_webgui.shell import theme
from servo_pendant_webgui.shell.settings_panel import SettingsPanel, package_version
from servo_pendant_webgui.shell.shortcuts import Shortcuts

THEME_ICONS = {"light": "sym_o_light_mode", "dark": "sym_o_dark_mode", "auto": "sym_o_brightness_auto"}

FRAME_CSS = """
.wg-shortcuts { width: min(480px, 100vw); padding: 16px 20px 20px; }
"""


class AppFrame:
    def __init__(self, bridge, store, request, title, icon, extra_settings=(), description=""):
        """
        bridge: RosBridge, store: SettingsStore, request: the page's request (appearance cookies), title: app name,
        icon: Material Symbols name (e.g. "sym_o_precision_manufacturing"), extra_settings: sections of the
        Settings > Web GUI tab (see SettingsPanel), description: one sentence for Settings > About.
        """
        self.bridge, self.store = bridge, store
        self.title, self.icon, self.description = title, icon, description
        self.appearance = theme.preferences(request)
        self.theme = self.appearance["theme"]
        self.dark = ui.dark_mode(theme.dark_value(self.theme))
        ui.add_css(FRAME_CSS)
        ui.add_css(theme.appearance_css(self.appearance))
        ui.page_title(title)
        self.fullscreen = ui.fullscreen()
        self.shortcuts = Shortcuts()
        self.settings = SettingsPanel(self, extra_settings)

        with ui.header(elevated=False).classes("wg-header"):
            with ui.element("div").classes("wg-brand"):
                ui.icon(icon, size="28px")
                ui.label(title).classes("wg-brand-name")
            self.status_bar = ui.element("div").classes("wg-header-status")
            with self.status_bar:
                self._ros_status = ui.element("button").classes("wg-status")
                self._ros_status.on("click", lambda: self.settings.open("ros"))
            with ui.element("div").classes("wg-header-actions"):
                self.actions = ui.element("div").classes("flex items-center gap-1")  # app buttons go here
                self._icon_button("sym_o_keyboard", "Keyboard shortcuts (?)", self.shortcuts.show_help)
                self._theme_button = self._icon_button(THEME_ICONS[self.theme], "Theme (D)", self.toggle_theme)
                self._icon_button("sym_o_settings", "Settings (Ctrl+,)", self.settings.open)
                self._icon_button("sym_o_fullscreen", "Full screen (F)", self.fullscreen.toggle)

        with ui.footer(elevated=False).classes("wg-footer"):
            self.footer = ui.element("div").classes("wg-footer-app")  # app facts go here: short labels, no buttons
            with ui.element("div").classes("wg-footer-shell"):
                with ui.element("div").tooltip("This web GUI's ROS node (Settings > ROS)"):
                    ui.icon("sym_o_hub")
                    self._footer_node = ui.label().classes("wg-mono")
                version = package_version(store.package)
                if version != "unknown":
                    ui.label(f"Version {version}").classes("wg-footer-version")

        ui.context.client.content.classes("wg-root")
        self.content = ui.element("div").classes("wg-page")

        self.shortcuts.add("?", "Show keyboard shortcuts", self.shortcuts.show_help)
        self.shortcuts.add(",", "Open settings", self.settings.open, ctrl=True)
        self.shortcuts.add("d", "Switch between light and dark theme", self.toggle_theme)
        self.shortcuts.add("f", "Full screen on / off", self.fullscreen.toggle)

        self._last_status = None
        self._update_status()
        ui.timer(1.0, self._update_status)

    @staticmethod
    def _icon_button(icon, tooltip, on_click):
        return ui.button(icon=icon, on_click=on_click).props("flat round").classes("wg-icon-btn").tooltip(tooltip)

    # ------------------------------------------------------------------ appearance (this browser)

    def set_theme(self, preference):
        self.theme = self.appearance["theme"] = preference
        self.dark.set_value(theme.dark_value(preference))
        self._theme_button.props(f"icon={THEME_ICONS[preference]}")
        theme.save_preference("theme", preference)
        toggle = self.settings.theme_toggle  # D pressed while the settings are open
        if toggle is not None and not toggle.is_deleted and toggle.value != preference:
            toggle.set_value(preference)

    def set_appearance(self, name, value):
        """name: "text" (text size) or "spacing", value: a key of theme.TEXT_SIZES / theme.SPACINGS."""
        self.appearance[name] = value
        theme.apply_appearance(name, value)
        theme.save_preference(name, value)

    async def toggle_theme(self):
        dark = self.dark.value if self.dark.value is not None else await theme.system_is_dark()
        self.set_theme("light" if dark else "dark")

    # ------------------------------------------------------------------ ROS status in the header

    def _update_status(self):
        node = self.bridge.node
        name = node.get_fully_qualified_name() if node else "restarting"
        if self._footer_node.text != name:
            self._footer_node.set_text(name)
        domain = self.bridge.connection.domain_id
        others = self.bridge.other_nodes()
        if others is None:
            state = ("wg-warn", "sym_o_sync", f"Connecting to domain {domain}")
        elif not others:
            state = ("wg-warn", "sym_o_portable_wifi_off", f"No other nodes in domain {domain}")
        else:
            state = ("wg-ok", "sym_o_hub", f"Domain {domain}: {len(others)} node{'s' if len(others) != 1 else ''}")
        if state == self._last_status:
            return
        self._last_status = state
        css, icon, text = state
        self._ros_status.classes(replace=f"wg-status {css}")
        self._ros_status.clear()
        with self._ros_status:
            ui.icon(icon, size="18px")
            ui.label(text)
