"""
The pendant (workbench layout, like a robot teach pendant): Cartesian jogging left, the robot in the middle, the
joints right, and mode, speed and STOP in the action bar at the bottom. The three panels fill the browser width, a
third each at the start, and their borders can be dragged (two nested splitters). One screen without scrolling from
1280×800; on narrow screens one column with scrolling: the control of the active mode, the robot below it.

The page is rebuilt whenever the bridge has a new node (domain change in the settings), since every control talks to
the node it was built for.
"""

import math

from nicegui import ui

from servo_pendant_webgui.components import JogPad, JogSlider, KeyJog
from servo_pendant_webgui.robot_view import RobotView
from servo_pendant_webgui.ros_node import AXIS_NAMES, JOINT, PLANES, TWIST
from servo_pendant_webgui.shell import theme

SPEED_MIN, SPEED_STEP = 5, 5  # [%]
TOGGLE = "no-caps unelevated toggle-color=primary"
STATUS_ICONS = {"ok": "sym_o_check_circle", "warn": "sym_o_warning", "bad": "sym_o_error"}

CSS = """
:root { --sp-bar-h: 77px; --sp-bar-space: var(--sp-bar-h); }  /* space: the footer's measured height (BAR_JS) */
.sp-main { display: flex; user-select: none; min-height: 560px;
           height: calc(100dvh - var(--wg-header-h) - var(--sp-bar-space) - 2 * var(--wg-space)); }
.sp-main > .sp-wide { flex: 1; justify-content: center; }
.wg-panel.sp-panel { position: relative; gap: 8px; min-height: 0; overflow: hidden; flex: 1; }

/* resizable panels: two nested splitters (outer: Cartesian | rest, inner: robot | joints). The handles take no
   width; the gaps are paddings of the splitter parts, shared so that 1/3 and 1/2 give three equal panels. The handle
   is 44 px wide to grab (also by touch) and lies in the gap. */
.sp-split { width: 100%; height: 100%; --sp-gap: var(--wg-space); }
.sp-split > .q-splitter__panel { display: flex; flex-direction: row; align-items: stretch; min-width: 0;
                                 overflow: hidden; }
.sp-outer > .q-splitter__before { padding-right: calc(var(--sp-gap) * 2 / 3); }
.sp-inner > .q-splitter__before { padding: 0 calc(var(--sp-gap) / 3); }
.sp-inner > .q-splitter__after { padding-left: calc(var(--sp-gap) * 2 / 3); }
.sp-split > .q-splitter__separator { width: 0; background: transparent; overflow: visible; z-index: 6; }
.sp-split > .q-splitter__separator > .q-splitter__separator-area { left: -22px; right: -22px; display: flex;
  align-items: center; justify-content: center; color: var(--wg-subtle); }
.sp-outer > .q-splitter__separator .q-icon { transform: translateX(calc(var(--sp-gap) / -6)); }
.sp-inner > .q-splitter__separator .q-icon { transform: translateX(calc(var(--sp-gap) / 6)); }
.sp-split > .q-splitter__separator:hover .q-icon, .sp-split.q-splitter--active > .q-splitter__separator .q-icon {
  color: var(--wg-primary); }
.sp-row { display: flex; align-items: center; gap: 12px; }
/* narrow panels: the title keeps its width, the hint next to it is cut off with an ellipsis */
.sp-panel > .wg-panel-head > .wg-h2 { flex: none; }
.sp-panel > .wg-panel-head > .wg-hint { flex: 1; text-align: right; }
.sp-panel > .wg-panel-head > .q-btn-toggle { margin-left: auto; }
/* The action bar (mode, speed, STOP) is the footer: it is built in the shell footer's app slot, which takes the
   footer's whole width and height, and the shell's node / version line is hidden (node and version are in
   Settings > About). Quasar keeps the page clear of the footer, whatever its height. */
.q-footer.wg-footer { height: auto; padding: 0; color: var(--wg-text); }
.wg-footer > .wg-footer-shell { display: none; }
.wg-footer > .wg-footer-app { overflow: visible; }
.wg-footer-app > .wg-actionbar.sp-bar { position: static; display: flex; border-top: none; }
.wg-footer .sp-bar .q-icon { font-size: 1.715em; color: inherit; }  /* undo the footer's small grey fact icons */
.sp-bar { width: 100%; min-height: var(--sp-bar-h); user-select: none; }
/* + toggle border: 56 px like STOP */
.sp-mode .q-btn { min-height: 54px; font-size: var(--wg-fs-lg); padding: 0 24px; }
.sp-speed { flex: 1; display: flex; align-items: center; gap: 16px; min-width: 240px; }
.sp-speed-value { font-size: var(--wg-fs-lg); font-weight: 600; width: 52px; text-align: right; }
/* the shell makes sliders 44 px high for touch, but Quasar keeps the track at the top: centre it */
.sp-speed .q-slider { justify-content: center; }

/* mode overlay: tap the dimmed side to switch to its mode */
.sp-overlay { position: absolute; inset: 0; z-index: 5; display: flex; align-items: center; justify-content: center;
              cursor: pointer; background: color-mix(in srgb, var(--wg-surface) 72%, transparent); }
.sp-overlay-btn { background: var(--wg-surface); color: var(--wg-primary); border: 2px solid var(--wg-primary);
                  border-radius: var(--wg-radius); padding: 12px 20px; font-size: var(--wg-fs-lg); font-weight: 600; }

/* robot */
.sp-view { flex: 1; min-height: 0; position: relative; border-radius: var(--wg-radius-sm); overflow: hidden;
           isolation: isolate; }  /* its loading overlay must stay below the sticky action bar when scrolling */
/* The scene fills the view absolutely: its size must not follow the canvas, or resizing the canvas to the scene
   (ResizeObserver in robot_view.py) would grow both a few pixels per frame. Its template sets position: relative. */
.sp-view > .sp-scene { position: absolute !important; inset: 0; }
.sp-scene > canvas { display: block; }
.sp-loading { position: absolute; inset: 0; z-index: 50; display: flex; flex-direction: column; gap: 8px;
              align-items: center; justify-content: center; background: var(--wg-sunken); color: var(--wg-muted); }
.sp-ellipsis { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.sp-command { display: flex; gap: 8px; align-items: baseline; min-width: 0; }

/* joints */
.sp-jrows { display: flex; flex-direction: column; gap: 6px; flex: 1; min-height: 0; }
.sp-jrow { flex: 1; min-height: 0; display: grid; grid-template-columns: 44px minmax(0, 1fr) 80px;
           grid-template-rows: auto minmax(0, 1fr); column-gap: 12px; row-gap: 2px; align-items: center;
           border-top: 1px solid var(--wg-divider); padding-top: 4px; }
.sp-jrow:first-child { border-top: none; padding-top: 0; }
.sp-jname { grid-row: 1 / span 2; display: flex; flex-direction: column; align-items: center; gap: 2px; }
.sp-jnum { font-size: var(--wg-fs-lg); font-weight: 600; line-height: 1.1; }
.sp-jname kbd { font-size: calc(11px * var(--wg-text-scale)); padding: 0 5px; color: var(--wg-muted); }
.sp-jpos { display: grid; grid-template-columns: 36px minmax(0, 1fr) 36px; gap: 8px; align-items: center;
           font-size: var(--wg-fs-xs); color: var(--wg-muted); font-variant-numeric: tabular-nums; }
.sp-jpos > :first-child { text-align: right; }
.sp-limit { height: 8px; border-radius: 4px; position: relative; border: 1px solid var(--wg-divider);
            background: linear-gradient(90deg, var(--wg-warning-soft) 0 6%, var(--wg-sunken) 6% 94%,
                                        var(--wg-warning-soft) 94%); }
.sp-limit-mark { position: absolute; top: -5px; width: 6px; height: 16px; margin-left: -3px; border-radius: 3px;
                 background: var(--wg-text); }
.sp-jangle { font-size: var(--wg-fs-lg); font-weight: 500; text-align: right; font-variant-numeric: tabular-nums; }
.sp-jrow .sp-slider { grid-column: 2 / span 2; }

/* spring-return velocity slider (components/jog_slider.js) */
.sp-slider { position: relative; height: 100%; min-height: 36px; max-height: 52px; touch-action: none;
             cursor: ew-resize; }
.sp-slider-rail { position: absolute; left: 0; right: 0; top: 50%; height: 12px; margin-top: -6px; border-radius: 6px;
                  background: var(--wg-sunken); border: 1px solid var(--wg-border); }
.sp-slider-fill { position: absolute; top: 50%; height: 12px; margin-top: -6px; border-radius: 6px; }
.sp-slider-fill.sp-pos { background: var(--wg-primary); }
.sp-slider-fill.sp-neg { background: var(--wg-warning); }
.sp-slider-zero { position: absolute; left: 50%; top: 15%; bottom: 15%; width: 2px; margin-left: -1px;
                  background: var(--wg-subtle); }
.sp-slider-sign { position: absolute; top: 50%; transform: translateY(-50%); font-size: var(--wg-fs-lg);
                  font-weight: 600;
                  color: var(--wg-subtle); }
.sp-minus { left: 6px; } .sp-plus { right: 6px; }
.sp-slider-thumb { position: absolute; top: 50%; width: 44px; height: 32px; margin: -16px 0 0 -22px; border-radius: 8px;
                   background: var(--wg-surface); border: 2px solid var(--wg-subtle); }
.sp-slider.sp-active .sp-slider-thumb.sp-pos { background: var(--wg-primary); border-color: var(--wg-primary); }
.sp-slider.sp-active .sp-slider-thumb.sp-neg { background: var(--wg-warning); border-color: var(--wg-warning); }
.sp-disabled { opacity: .45; pointer-events: none; }

/* spring-return pad and rocker (components/jog_pad.js) */
.sp-trans { flex: 1; min-height: 0; display: flex; gap: 12px; align-items: center; justify-content: center;
            container-type: size; }
.sp-pad { position: relative; touch-action: none; border-radius: var(--wg-radius); background: var(--wg-sunken);
          border: 2px solid var(--wg-border); cursor: move; }
.sp-pad-xy { width: min(100cqw - 90px, 100cqh); height: min(100cqw - 90px, 100cqh); flex: none; }
.sp-pad-y { width: 78px; height: min(100cqw - 90px, 100cqh); flex: none; }
.sp-pad.sp-active { border-color: var(--wg-primary); }
.sp-pad-hline, .sp-pad-vline { position: absolute; background: var(--wg-border); }
.sp-pad-hline { left: 14px; right: 14px; top: 50%; height: 2px; }
.sp-pad-vline { top: 14px; bottom: 14px; left: 50%; width: 2px; }
.sp-pad-label { position: absolute; font-size: var(--wg-fs); font-weight: 600; color: var(--wg-muted); }
.sp-left { left: 10px; top: 50%; transform: translateY(-50%); }
.sp-right { right: 10px; top: 50%; transform: translateY(-50%); }
.sp-up { top: 8px; left: 50%; transform: translateX(-50%); }
.sp-down { bottom: 8px; left: 50%; transform: translateX(-50%); }
.sp-puck { position: absolute; width: 56px; height: 56px; margin: -28px 0 0 -28px; border-radius: 50%;
           background: var(--wg-surface); border: 2px solid var(--wg-subtle); }
.sp-pad.sp-active .sp-puck { background: var(--wg-primary); border-color: var(--wg-primary); }
.sp-rot { display: grid; grid-template-columns: 32px minmax(0, 1fr); align-items: center; column-gap: 8px;
          height: 44px; }
.sp-rot-label { font-size: var(--wg-fs); font-weight: 600; }

@media (max-width: 1100px) {
  /* one column: only the control of the active mode, the robot below it (scrolling). The splitter wrappers are
     dissolved (display: contents), so the three panels are items of one column and can be ordered and hidden. */
  .sp-main { height: auto; min-height: 0; }
  .sp-outer.q-splitter--vertical { flex-direction: column; height: auto; gap: var(--wg-space); }
  .sp-outer > .q-splitter__panel, .sp-inner, .sp-inner > .q-splitter__panel { display: contents; }
  .sp-split > .q-splitter__separator { display: none; }
  .wg-panel.sp-panel { flex: none; }
  .sp-cart { height: 600px; } .sp-robot { height: 420px; order: 2; } .sp-joints { height: 640px; }
  .sp-main.sp-m-joint .sp-cart, .sp-main.sp-m-twist .sp-joints { display: none; }
}
@media (max-width: 720px) {  /* mode and STOP in one row, speed below */
  .sp-bar .wg-stop { margin-left: auto; padding: 0 20px; }
  .sp-mode .q-btn { padding: 0 16px; }
  .sp-speed { order: 3; flex-basis: 100%; }
}
"""

# The footer (the action bar) is 77 px high, more when it wraps (narrow) or with a larger text size: measured, as
# --sp-bar-space, for the height of the panels
BAR_JS = """
const footer = document.querySelector(".q-footer.wg-footer");
if (footer && !footer.sp_observer) {
  footer.sp_observer = new ResizeObserver(() =>
    document.documentElement.style.setProperty("--sp-bar-space", footer.offsetHeight + "px"));
  footer.sp_observer.observe(footer);
}
"""

# Full screen also locks the keyboard, so Ctrl+1 … 8 reach the page instead of switching browser tabs
KEYBOARD_LOCK_JS = """<script>
document.addEventListener("fullscreenchange", () => {
  if (document.fullscreenElement && navigator.keyboard) navigator.keyboard.lock().catch(() => {});
});
</script>"""


class PendantPage:
    def __init__(self, frame):
        self.frame = frame
        self.bridge = frame.bridge  # read bridge.node every time: it is replaced when the domain ID changes
        self._built_for = False  # the node the controls were built for (False: none built yet)
        self._chips = {}
        self.dark = bool(frame.dark.value)  # corrected by _sync_theme when the theme follows the system
        self.view = None
        self._split = [100 / 3, 50]  # [%] of the two splitters: kept when the page is rebuilt after a reconnect
        ui.add_css(CSS)
        ui.add_body_html(KEYBOARD_LOCK_JS)
        self.keys = KeyJog(7, on_jog=self._jog_key, on_stop=self.stop)

        with frame.status_bar:
            self.servo_chip = ui.element("div")
            self.states_chip = ui.element("div")
            self.crosstalk_chip = ui.element("button").on("click", self._show_crosstalk)
        self.main = ui.element("div").classes("sp-main")
        with frame.footer:  # the action bar is the footer
            self.bar = ui.element("div").classes("wg-actionbar sp-bar")

        self._add_shortcuts()
        self._rebuild()
        ui.timer(0.1, self._tick)
        ui.timer(0.5, self._update_status)
        ui.timer(0.5, self._sync_theme)
        ui.timer(0.1, lambda: ui.run_javascript(BAR_JS), once=True)

    @property
    def node(self):
        return self.bridge.node

    # ------------------------------------------------------------------ building

    def _rebuild(self):
        c = self.node
        self._built_for = c
        self.main.clear()
        self.bar.clear()
        self.view = None
        self.joint_widgets, self._shown_joints = {}, None
        if c is None:
            with self.main, ui.element("section").classes("wg-panel sp-wide"):
                with ui.element("div").classes("wg-empty"):
                    ui.icon("sym_o_sync", size="36px")
                    ui.label("Reconnecting to ROS")
                    ui.label("The controls come back when the new connection is up.").classes("wg-hint")
            return
        with self.main:
            outer = self._splitter(0, "sp-outer", limits=(15, 60))
            with outer.before:
                self._cartesian_panel(c)
            with outer.after:
                inner = self._splitter(1, "sp-inner", limits=(20, 80))
                with inner.before:
                    self._robot_panel(c)
                with inner.after:
                    self._joints_panel(c)
        with self.bar:
            self._action_bar(c)
        self._build_rows(c)
        self._refresh_labels(c)
        self._show_mode(c)

    def _splitter(self, index, classes, limits):
        """Side-by-side splitter (value: width of the left part [%]); the handle sits in the gap of the panels."""
        splitter = ui.splitter(
            value=self._split[index],
            limits=limits,
            on_change=lambda e: self._split.__setitem__(index, e.value),
        ).classes("sp-split " + classes)
        with splitter.separator:
            ui.icon("sym_o_drag_indicator", size="20px").tooltip("Drag to resize the panels")
        return splitter

    def _overlay(self, text, mode):
        with ui.element("div").classes("sp-overlay") as overlay:
            ui.label(text).classes("sp-overlay-btn")
        overlay.on("click", lambda: self.set_mode(mode))
        return overlay

    def _cartesian_panel(self, c):
        with ui.element("section").classes("wg-panel sp-panel sp-cart"):
            with ui.element("div").classes("wg-panel-head"):
                ui.label("Cartesian").classes("wg-h2")
                self.frame_toggle = (
                    ui.toggle(
                        {"base": "Base", "tool": "Tool"}, value=c.frame, on_change=lambda e: self._set_frame(e.value)
                    )
                    .props(TOGGLE)
                    .tooltip(f"Frame of the commands ({self.key_labels['base']} / {self.key_labels['tool']})")
                )
            with ui.element("div").classes("sp-row"):
                ui.label("Plane").classes("wg-label")
                self.plane_toggle = (
                    ui.toggle(list(PLANES), value=c.plane, on_change=lambda e: self._set_plane(e.value))
                    .props(TOGGLE)
                    .tooltip(f"Plane of the pad; the rocker drives the third axis ({self.key_labels['plane']})")
                )
            with ui.element("div").classes("sp-trans"):
                self.pad = JogPad("xy", on_jog=lambda x, y: self._input("pad", (x, y)))
                self.rocker = JogPad("y", on_jog=lambda x, y: self._input("rocker", y))
            ui.label("Rotation").classes("wg-label")
            for key in ("rx", "ry", "rz"):
                with ui.element("div").classes("sp-rot"):
                    ui.label(key.capitalize()).classes("sp-rot-label")
                    JogSlider(on_jog=lambda v, k=key: self._input(k, v))
            self.cart_overlay = self._overlay("Tap to jog in Cartesian mode", TWIST)

    def _robot_panel(self, c):
        with ui.element("section").classes("wg-panel sp-panel sp-robot"):
            with ui.element("div").classes("wg-panel-head"):
                ui.label("Robot").classes("wg-h2")
                self.view_hint = ui.label().classes("wg-hint sp-ellipsis")
                ui.button(icon="sym_o_restart_alt", on_click=self._reset_view).props("flat round").classes(
                    "wg-icon-btn"
                ).tooltip(f"Reset the view ({self.key_labels['view']})")
            with ui.element("div").classes("sp-view"):
                self.view = RobotView(c, self.dark)
                with ui.element("div").classes("sp-loading") as self.loading:
                    ui.spinner(size="40px")
                    self.loading_label = ui.label("Loading the robot")
                    ui.label(c.robot_description_topic).classes("wg-mono")
            with ui.element("div").classes("sp-command"):
                ui.label("Command").classes("wg-label")
                self.command_label = ui.label().classes("wg-mono wg-hint sp-ellipsis")
            self.loading_timer = ui.timer(0.5, self._watch_loading)

    def _joints_panel(self, c):
        with ui.element("section").classes("wg-panel sp-panel sp-joints"):
            with ui.element("div").classes("wg-panel-head"):
                ui.label("Joints").classes("wg-h2")
                ui.label("Hold 1–9 to jog, with Ctrl or Shift negative").classes("wg-hint sp-ellipsis")
            self.rows = ui.element("div").classes("sp-jrows")
            self.joint_overlay = self._overlay("Tap to jog in joint mode", JOINT)

    def _build_rows(self, c):
        self.rows.clear()
        self.joint_widgets = {}
        self._shown_joints = names = list(c.joint_names)
        self.keys.set_count(len(names))
        with self.rows:
            if not names:
                with ui.element("div").classes("wg-empty"):
                    ui.icon("sym_o_hourglass_empty", size="36px")
                    ui.label("No joint states yet")
                    ui.label("Start the robot driver. The joints appear with the first message on").classes("wg-hint")
                    ui.label(c.get_parameter("joint_states_topic").value).classes("wg-mono")
                return
            for i, name in enumerate(names):
                with ui.element("div").classes("sp-jrow"):
                    with ui.element("div").classes("sp-jname"):
                        ui.label(f"J{i + 1}").classes("sp-jnum").tooltip(name)
                        if i < 9:
                            ui.html(f"<kbd>{i + 1}</kbd>", sanitize=False)
                    with ui.element("div").classes("sp-jpos"):
                        lo = ui.label()
                        with ui.element("div").classes("sp-limit"):
                            mark = ui.element("div").classes("sp-limit-mark")
                        hi = ui.label()
                    angle = ui.label("–").classes("sp-jangle")
                    slider = JogSlider(on_jog=lambda v, n=name: self._input("j:" + n, v))
                    self.joint_widgets[name] = (lo, hi, mark, angle, slider)

    def _action_bar(self, c):
        self.mode_toggle = (
            ui.toggle({TWIST: "Cartesian", JOINT: "Joint"}, value=c.mode, on_change=lambda e: self.set_mode(e.value))
            .props(TOGGLE)
            .classes("sp-mode")
            .tooltip(f"Mode of MoveIt Servo ({self.key_labels['cartesian']} / {self.key_labels['joint']})")
        )
        with ui.element("div").classes("sp-speed"):
            ui.label("Speed").classes("wg-label")
            self.speed_value = ui.label().classes("sp-speed-value")
            self.speed_slider = (
                ui.slider(min=SPEED_MIN, max=100, step=SPEED_STEP, value=round(c.speed * 100), on_change=self._on_speed)
                .props("thumb-size=36px track-size=10px")
                .classes("flex-1")
                .tooltip(f"Scales every command ({self.key_labels['faster']} / {self.key_labels['slower']})")
            )
        ui.button("Stop", icon="sym_o_stop", on_click=self.stop).props("unelevated color=negative").classes(
            "wg-stop"
        ).tooltip("Releases all inputs (Esc). A software stop, not an emergency stop.")

    # ------------------------------------------------------------------ actions

    def _add_shortcuts(self):
        k = self.frame.shortcuts
        self.key_labels = {
            "cartesian": k.add("c", "Cartesian mode", lambda: self.set_mode(TWIST), group="Mode"),
            "joint": k.add("j", "Joint mode", lambda: self.set_mode(JOINT), group="Mode"),
            "faster": k.add("+", f"Speed +{SPEED_STEP} %", lambda: self._change_speed(SPEED_STEP), group="Speed"),
            "slower": k.add("-", f"Speed −{SPEED_STEP} %", lambda: self._change_speed(-SPEED_STEP), group="Speed"),
            "base": k.add("b", "Commands in the base frame", lambda: self._set_frame("base"), group="Cartesian"),
            "tool": k.add("t", "Commands in the tool frame", lambda: self._set_frame("tool"), group="Cartesian"),
            "plane": k.add("p", "Next plane of the pad (XY, XZ, YZ)", self._next_plane, group="Cartesian"),
            "view": k.add("v", "Reset the 3D view", self._reset_view, group="Robot"),
        }
        # Held digit keys are handled in the browser (components/key_jog.js); listed here for the help
        jogging = "Jogging (joint mode)"
        k.add("1…9", "Jog joint 1 … 9 positive while held", lambda: None, group=jogging)
        k.add("1…9", "Jog joint 1 … 9 negative while held (Shift works too)", lambda: None, ctrl=True, group=jogging)
        k.add("escape", "Stop: release all inputs", self.stop, group=jogging)

    def _input(self, key, value):
        c = self.node
        if c is not None:
            c.set_input(key, value)

    def _jog_key(self, index, value):
        c = self.node
        # no keyboard jogging while the settings are open
        if c is None or self.frame.settings.dialog.value:
            return
        if c.mode == JOINT and index < len(c.joint_names):
            c.set_input("k:" + c.joint_names[index], value)

    def stop(self):
        c = self.node
        if c is not None:
            c.stop()

    def set_mode(self, mode):
        c = self.node
        if c is None or self._built_for is not c:
            return
        if c.mode != mode:
            c.set_mode(mode)
        self._show_mode(c)

    def _show_mode(self, c):
        self.mode_toggle.value = c.mode
        # one-column layout (narrow browsers): only the active control is shown (CSS)
        joint = c.mode == JOINT
        self.main.classes(add="sp-m-joint" if joint else "sp-m-twist", remove="sp-m-twist" if joint else "sp-m-joint")
        self.cart_overlay.set_visibility(c.mode != TWIST)
        self.joint_overlay.set_visibility(c.mode != JOINT)
        self.view_hint.set_text(
            "Rings: positive direction of each joint" if c.mode == JOINT else "Arrow and ring: commanded tool motion"
        )

    def _set_frame(self, frame):
        c = self.node
        if c is not None and c.frame != frame:
            c.set_frame(frame)

    def _set_plane(self, plane):
        c = self.node
        if c is None:
            return
        if c.plane != plane:
            c.set_plane(plane)
        self._refresh_labels(c)

    def _next_plane(self):
        c = self.node
        if c is not None:
            planes = list(PLANES)
            self._set_plane(planes[(planes.index(c.plane) + 1) % len(planes)])

    def _refresh_labels(self, c):
        (h, v), r = PLANES[c.plane]
        self.pad.set_labels(
            {
                "left": f"-{AXIS_NAMES[h]}",
                "right": f"+{AXIS_NAMES[h]}",
                "up": f"+{AXIS_NAMES[v]}",
                "down": f"-{AXIS_NAMES[v]}",
            }
        )
        self.rocker.set_labels({"up": f"+{AXIS_NAMES[r]}", "down": f"-{AXIS_NAMES[r]}"})

    def _on_speed(self, e):
        c = self.node
        if c is not None and e.value is not None and round(c.speed * 100) != e.value:
            c.set_speed(e.value / 100)

    def _change_speed(self, delta):
        c = self.node
        if c is not None:
            c.set_speed(min(max(round(c.speed * 100) + delta, SPEED_MIN), 100) / 100)

    def _reset_view(self):
        if self.view is not None:
            self.view.reset_camera()

    def _show_crosstalk(self):
        c = self.node
        if c is not None and c.joint_states_warning:
            ui.notify(f"{c.joint_states_warning}. Another robot in the same ROS domain?", type="warning")

    # ------------------------------------------------------------------ live updates

    def _tick(self):
        c = self.node
        if c is not self._built_for:
            self._rebuild()
        if c is None:
            return
        self.view.update()
        if c.joint_names != self._shown_joints:
            self._build_rows(c)
        # changed elsewhere: another browser, a shortcut
        if self.mode_toggle.value != c.mode:
            self._show_mode(c)
        if self.frame_toggle.value != c.frame:
            self.frame_toggle.value = c.frame
        if self.plane_toggle.value != c.plane:
            self.plane_toggle.value = c.plane
        speed = round(c.speed * 100)
        if self.speed_slider.value != speed:
            self.speed_slider.value = speed
        self.speed_value.set_text(f"{speed} %")
        self.command_label.set_text(c.last_command)

        positions = c.snapshot_positions()
        model = c.model
        inputs = c.active_inputs()
        for name, (lo, hi, mark, angle, slider) in self.joint_widgets.items():
            slider.set_external(float(inputs.get("k:" + name, 0.0)))
            if name not in positions:
                continue
            q = positions[name]
            angle.set_text(f"{math.degrees(q):+.1f}°")
            if model is not None and name in model.joints:
                lower, upper = model.limits(model.joints[name])
                lo.set_text(f"{math.degrees(lower):.0f}°")
                hi.set_text(f"{math.degrees(upper):.0f}°")
                frac = (q - lower) / ((upper - lower) or 1.0)
                mark.style(f"left: {100 * min(max(frac, 0.0), 1.0):.1f}%")

    def _chip(self, chip, state):
        """state: (level ok / warn / bad, text), or None to hide the chip."""
        if self._chips.get(chip.id) == state:
            return
        self._chips[chip.id] = state
        chip.clear()
        chip.set_visibility(state is not None)
        if state is None:
            return
        level, text = state
        chip.classes(replace=f"wg-status wg-{level}")
        with chip:
            ui.icon(STATUS_ICONS[level], size="18px")
            ui.label(text)

    def _update_status(self):
        c = self.node
        if c is None:
            for chip in (self.servo_chip, self.states_chip, self.crosstalk_chip):
                self._chip(chip, None)
            return
        self._chip(self.servo_chip, c.servo_status)
        age = c.joint_states_age()
        if age is None:
            states = ("warn", "No joint states")
        elif age > 1.0:
            states = ("warn", f"Joint states {age:.0f} s old")
        else:
            states = ("ok", f"Joint states {age * 1000:.0f} ms")
        self._chip(self.states_chip, states)
        self._chip(self.crosstalk_chip, ("bad", "Several joint state publishers") if c.joint_states_warning else None)

    async def _watch_loading(self):
        c, view = self.node, self.view
        if c is None or view is None or self.loading.is_deleted:
            return
        if not await view.loading():
            self.loading.set_visibility(False)
            self.loading_timer.cancel()
            return
        self.loading_label.set_text(c.model_status if c.model is None else "Loading the robot meshes")

    async def _sync_theme(self):
        dark = self.frame.dark.value
        if dark is None:  # follows the system
            try:
                dark = await theme.system_is_dark()
            except TimeoutError:
                return
        self.dark = dark
        if self.view is not None:
            self.view.set_dark(dark)
