"""
The frame of every webgui page: header (name, ROS status, help, theme, settings, full screen), settings drawer and
the standard keyboard shortcuts. The app builds its content inside `with frame.content:`.

Shared webgui shell (from the nicegui-ros2-webgui skill): keep it identical across the webgui packages.
"""

from nicegui import ui

from servo_pendant_webgui.shell import theme
from servo_pendant_webgui.shell.settings_panel import SettingsPanel
from servo_pendant_webgui.shell.shortcuts import Shortcuts

THEME_ICONS = {"light": "sym_o_light_mode", "dark": "sym_o_dark_mode", "auto": "sym_o_brightness_auto"}

FRAME_CSS = """
.wg-settings { width: min(460px, 100vw); height: 100%; display: flex; flex-direction: column;
               background: var(--wg-surface); color: var(--wg-text); border-left: 1px solid var(--wg-border); }
.q-dialog__inner--right:has(> .wg-settings) { padding: 0 !important; }
.wg-settings-head { display: flex; align-items: center; gap: 10px; height: var(--wg-header-h); flex: none;
                    padding: 0 8px 0 16px; border-bottom: 1px solid var(--wg-border); color: var(--wg-muted); }
.wg-settings-head .wg-h2 { color: var(--wg-text); }
.wg-settings-body { flex: 1; min-height: 0; overflow-y: auto; padding: 0 16px 32px; }
.wg-set-section { padding: 24px 0 8px; display: flex; flex-direction: column; gap: 2px; }
.wg-set-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 210px); gap: 12px; align-items: center;
              padding: 10px 0; border-top: 1px solid var(--wg-divider); }
.wg-set-label { display: flex; flex-direction: column; min-width: 0; }
.wg-set-name { font-weight: 500; }
.wg-set-key { color: var(--wg-subtle); font-size: 12px; overflow-wrap: anywhere; }
.wg-set-ctl { display: flex; justify-content: flex-end; min-width: 0; }
.wg-set-ctl > .q-field { width: 100%; }
.wg-set-value { text-align: right; overflow-wrap: anywhere; user-select: text; }
.wg-set-actions { display: flex; align-items: center; gap: 12px; padding: 12px 0 0;
                  border-top: 1px solid var(--wg-divider); }
.wg-set-actions .wg-hint { overflow-wrap: anywhere; }
.wg-shortcuts { width: min(480px, 100vw); padding: 16px 20px 20px; }
@media (max-width: 520px) { .wg-set-row { grid-template-columns: minmax(0, 1fr); } .wg-set-ctl { justify-content: flex-start; } }
"""


class AppFrame:
    def __init__(self, bridge, store, request, title, icon, extra_settings=()):
        """
        bridge: RosBridge, store: SettingsStore, request: the page's request (theme cookie), title: app name,
        icon: Material Symbols name (e.g. "sym_o_precision_manufacturing"), extra_settings: see SettingsPanel.
        """
        self.bridge, self.store = bridge, store
        self.theme = theme.preference(request)
        self.dark = ui.dark_mode(theme.dark_value(self.theme))
        ui.add_css(FRAME_CSS)
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
                self._ros_status = ui.element("button").classes("wg-status").on("click", self.settings.open)
            with ui.element("div").classes("wg-header-actions"):
                self.actions = ui.element("div").classes("flex items-center gap-1")  # app buttons go here
                self._icon_button("sym_o_keyboard", "Keyboard shortcuts (?)", self.shortcuts.show_help)
                self._theme_button = self._icon_button(THEME_ICONS[self.theme], "Theme (D)", self.toggle_theme)
                self._icon_button("sym_o_settings", "Settings (Ctrl+,)", self.settings.open)
                self._icon_button("sym_o_fullscreen", "Full screen (F)", self.fullscreen.toggle)

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

    # ------------------------------------------------------------------ theme

    def set_theme(self, preference):
        self.theme = preference
        self.dark.set_value(theme.dark_value(preference))
        self._theme_button.props(f"icon={THEME_ICONS[preference]}")
        theme.save_preference(preference)

    async def toggle_theme(self):
        dark = self.dark.value if self.dark.value is not None else await theme.system_is_dark()
        self.set_theme("light" if dark else "dark")

    # ------------------------------------------------------------------ ROS status in the header

    def _update_status(self):
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
