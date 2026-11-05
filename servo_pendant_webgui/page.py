"""
The pendant (workbench layout, like a robot teach pendant): Cartesian jogging left, the robot in the middle, the
joints right, and mode, speed and STOP in the action bar at the bottom. The three panels fill the browser width, a
third each at the start, and their borders can be dragged: each border moves only itself, the robot in the middle
takes up the difference. One screen without scrolling from 1280×800; on narrow screens one column with scrolling:
the control of the active mode, the robot below it.

The pendant starts paused (no mode): both sides dimmed, nothing sent. Choosing a mode resumes Servo in it; Pause
pauses Servo again and remembers the mode, to resume it.

The joint rings and Cartesian arrows of the 3D view can be picked: hovering one, or tapping it, highlights the control
that drives it (the joint's row, or the half of the pad or rocker). Tapping an arrow also switches to the plane whose
rocker drives that axis alone (X: YZ, Y: XZ, Z: XY).

The page is rebuilt whenever the bridge has a new node (domain change in the settings), since every control talks to
the node it was built for.
"""

import math
import time

from nicegui import ui

from servo_pendant_webgui.components import JogPad, JogSlider, KeyJog, scene_pick_script
from servo_pendant_webgui.robot_view import RobotView
from servo_pendant_webgui.ros_node import AXIS_NAMES, JOINT, MODE_NAMES, PLANES, TWIST
from servo_pendant_webgui.shell import theme

SPEED_MIN, SPEED_STEP = 5, 5  # [%]
TOGGLE = "no-caps unelevated toggle-color=primary"
STATUS_ICONS = {"ok": "sym_o_check_circle", "warn": "sym_o_warning", "bad": "sym_o_error"}
PICK_HIGHLIGHT = 2.5  # [s] a control picked by tapping its ring or arrow in the 3D view stays highlighted
ROCKER_PLANES = {rocker: plane for plane, (_, rocker) in PLANES.items()}  # axis -> plane whose rocker drives it

CSS = """
:root { --sp-bar-h: 77px; --sp-bar-space: var(--sp-bar-h); }  /* space: the footer's measured height (BAR_JS) */
.sp-main { display: flex; user-select: none; min-height: 560px;
           height: calc(100dvh - var(--wg-header-h) - var(--sp-bar-space) - 2 * var(--wg-space)); }
.sp-main > .sp-wide { flex: 1; justify-content: center; }
.wg-panel.sp-panel { position: relative; gap: 8px; min-height: 0; overflow: hidden; flex: 1; }

/* resizable panels: ONE row of three columns. The left and right columns have their own widths (--sp-l, --sp-r:
   fractions of the width without the two gaps, so 1/3 each gives three equal panels) and the robot in the middle
   takes the rest -- so dragging the left border resizes only the left panel and the robot, never the joints.
   Each handle IS the gap between two panels, so its icon is centred in it by construction; it is 44 px wide to grab
   (also by touch), reaching over the panel edges. Dragging is done in the browser (SPLIT_JS). */
.sp-cols { display: flex; width: 100%; height: 100%; --sp-gap: var(--wg-space); --sp-l: 0.3333; --sp-r: 0.3333; }
.sp-col { display: flex; flex-direction: row; align-items: stretch; min-width: 0; overflow: hidden; }
.sp-col-l { flex: 0 0 calc((100% - 2 * var(--sp-gap)) * var(--sp-l)); }
.sp-col-r { flex: 0 0 calc((100% - 2 * var(--sp-gap)) * var(--sp-r)); }
.sp-col-c { flex: 1 1 0; }
.sp-handle { flex: 0 0 var(--sp-gap); position: relative; z-index: 6; cursor: col-resize; touch-action: none;
             color: var(--wg-subtle); }
.sp-handle::before { content: ""; position: absolute; top: 0; bottom: 0; left: 50%; width: 44px; margin-left: -22px; }
.sp-handle > .q-icon { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
                       pointer-events: none; }
.sp-handle:hover, .sp-cols.sp-dragging > .sp-handle.sp-active { color: var(--wg-primary); }
.sp-cols.sp-dragging { cursor: col-resize; }

/* Servo's status (moveit_msgs/ServoStatus), over the top of the 3D view while it is not NO_WARNING. Over the view,
   not above it: a row appearing would resize the view, and the scene with it. Above the loading overlay (50) too:
   a halt is news even while the meshes load. */
.sp-report { position: absolute; top: 8px; left: 8px; right: 8px; z-index: 60; pointer-events: none;
             display: flex; gap: 10px; align-items: flex-start; padding: 8px 12px; border-radius: var(--wg-radius-sm);
             background: var(--wg-surface); border: 1px solid var(--wg-border); border-left-width: 4px; }
.sp-report.wg-warn { border-left-color: var(--wg-warning); }
.sp-report.wg-bad { border-left-color: var(--wg-negative); }
.sp-report.wg-warn > .q-icon { color: var(--wg-warning); }
.sp-report.wg-bad > .q-icon { color: var(--wg-negative); }
.sp-report-title { font-weight: 600; }
.sp-report-text { display: flex; flex-direction: column; min-width: 0; }
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
/* Pause is the same size as STOP (the shell's .wg-stop: 56 px high, large bold label), and both share one width, so
   neither looks the lesser of the two and Pause / Paused does not change the button's width. em: follows the text. */
.q-btn.sp-pause { min-height: 56px; font-size: var(--wg-fs-lg); font-weight: 600; padding: 0 28px; }
.sp-bar .q-btn.sp-pause, .sp-bar .q-btn.wg-stop { min-width: 9.5em; }
.sp-speed { flex: 1; display: flex; align-items: center; gap: 16px; min-width: 240px; }
.sp-speed-value { font-size: var(--wg-fs-lg); font-weight: 600; width: 52px; text-align: right; }
/* the shell makes sliders 44 px high for touch, but Quasar keeps the track at the top: centre it */
.sp-speed .q-slider { justify-content: center; margin: 0 var(--wg-space); }  /* the thumb sticks out half its size at the ends */

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
          border: 2px solid var(--wg-border); cursor: move; overflow: hidden; }
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
/* the control of the ring or arrow picked in the 3D view (hovered, or tapped a moment ago): the joint's row, or the
   half of the pad or rocker for the direction, in its colour (positive: primary, negative: warning) */
.sp-pad.sp-hl-pos { border-color: var(--wg-primary); }
.sp-pad.sp-hl-neg { border-color: var(--wg-warning); }
.sp-pad-glow { position: absolute; pointer-events: none; }
.sp-glow-left { left: 0; top: 0; bottom: 0; width: 50%; }
.sp-glow-right { right: 0; top: 0; bottom: 0; width: 50%; }
.sp-glow-up { left: 0; right: 0; top: 0; height: 50%; }
.sp-glow-down { left: 0; right: 0; bottom: 0; height: 50%; }
.sp-pad-glow.sp-hl-pos { background: color-mix(in srgb, var(--wg-primary) 16%, transparent); }
.sp-pad-glow.sp-hl-neg { background: color-mix(in srgb, var(--wg-warning) 18%, transparent); }
.sp-pad-label.sp-hl-pos { color: var(--wg-primary); }
.sp-pad-label.sp-hl-neg { color: var(--wg-warning); }
.sp-jrow { transition: background-color .15s, box-shadow .15s; }
.sp-jrow.sp-hl { --sp-hl: color-mix(in srgb, var(--wg-primary) 14%, transparent); border-radius: var(--wg-radius-sm);
                 background: var(--sp-hl); box-shadow: 0 0 0 6px var(--sp-hl); }  /* spread: room around the row */
.sp-jrow.sp-hl .sp-jnum, .sp-jrow.sp-hl .sp-plus { color: var(--wg-primary); }
.sp-jrow.sp-hl .sp-slider-rail { border-color: var(--wg-primary); }
.sp-rot { display: grid; grid-template-columns: 32px minmax(0, 1fr); align-items: center; column-gap: 8px;
          height: 44px; }
.sp-rot-label { font-size: var(--wg-fs); font-weight: 600; }

@media (max-width: 1100px) {
  /* one column: only the control of the active mode, the robot below it (scrolling); paused, both. The column
     wrappers are dissolved (display: contents), so the three panels are items of one column and can be ordered and
     hidden. */
  .sp-main { height: auto; min-height: 0; }
  .sp-cols { flex-direction: column; height: auto; gap: var(--wg-space); }
  .sp-col { display: contents; }
  .sp-handle { display: none; }
  .wg-panel.sp-panel { flex: none; }
  .sp-cart { height: 600px; } .sp-robot { height: 420px; order: 2; } .sp-joints { height: 640px; }
  .sp-main.sp-m-joint .sp-cart, .sp-main.sp-m-twist .sp-joints { display: none; }
}
@media (max-width: 720px) {  /* mode, Pause and STOP in one row, speed below */
  .sp-bar .sp-pause { margin-left: auto; }
  .sp-bar .q-btn.sp-pause, .sp-bar .q-btn.wg-stop { padding: 0 20px; min-width: 8.5em; }
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


# Panel widths [fraction of the width without the gaps] for the left (Cartesian) and right (joints) column; the robot
# in the middle takes the rest and keeps at least SPLIT_CENTER_MIN
SPLIT_DEFAULT, SPLIT_MIN, SPLIT_MAX, SPLIT_CENTER_MIN = 1 / 3, 0.15, 0.6, 0.2

# Dragging a column border: a pointer interaction, so it runs in the browser and Python only hears the result
# (`sp_split`) to keep it across a rebuild. Relative to where the drag started, so grabbing the 44 px handle off its
# centre does not make the border jump. Double-click: three equal panels again.
SPLIT_JS = f"""<script>
(() => {{
  const MIN = {SPLIT_MIN}, MAX = {SPLIT_MAX}, CENTER_MIN = {SPLIT_CENTER_MIN}, THIRD = {SPLIT_DEFAULT};
  const clamp = (v, hi) => Math.min(Math.max(v, MIN), Math.min(MAX, hi));
  const read = (cols) => {{
    const css = getComputedStyle(cols);
    return [parseFloat(css.getPropertyValue("--sp-l")) || THIRD, parseFloat(css.getPropertyValue("--sp-r")) || THIRD];
  }};
  const apply = (cols, l, r) => {{
    cols.style.setProperty("--sp-l", l);
    cols.style.setProperty("--sp-r", r);
  }};
  document.addEventListener("pointerdown", (e) => {{
    const handle = e.target.closest && e.target.closest(".sp-handle");
    if (!handle || e.button > 0) return;
    e.preventDefault();
    const cols = handle.parentElement, left = handle.dataset.side === "l";
    const [l0, r0] = read(cols), x0 = e.clientX;
    let l = l0, r = r0;
    try {{ handle.setPointerCapture(e.pointerId); }} catch (_) {{}}  // keeps the drag if the pointer leaves the handle
    handle.classList.add("sp-active");
    cols.classList.add("sp-dragging");
    const move = (ev) => {{
      const inner = cols.getBoundingClientRect().width - 2 * handle.offsetWidth;
      if (inner <= 0) return;
      const dx = (ev.clientX - x0) / inner;
      if (left) l = clamp(l0 + dx, 1 - CENTER_MIN - r);
      else r = clamp(r0 - dx, 1 - CENTER_MIN - l);
      apply(cols, l, r);
    }};
    const up = () => {{
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      handle.classList.remove("sp-active");
      cols.classList.remove("sp-dragging");
      if (l !== l0 || r !== r0) emitEvent("sp_split", {{l, r}});
    }};
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  }});
  document.addEventListener("dblclick", (e) => {{
    const handle = e.target.closest && e.target.closest(".sp-handle");
    if (!handle) return;
    apply(handle.parentElement, THIRD, THIRD);
    emitEvent("sp_split", {{l: THIRD, r: THIRD}});
  }});
}})();
</script>"""


class PendantPage:
    def __init__(self, frame):
        self.frame = frame
        self.bridge = frame.bridge  # read bridge.node every time: it is replaced when the domain ID changes
        self._built_for = False  # the node the controls were built for (False: none built yet)
        self._chips = {}
        self.dark = bool(frame.dark.value)  # corrected by _sync_theme when the theme follows the system
        self.view = None
        self._hover = None  # key of the ring or arrow under the mouse in the 3D view
        self._pressed = (None, 0.0)  # (key, monotonic time until which it stays highlighted) of the last tap
        self._shown_highlight = None
        # widths of the left and right column (see SPLIT_JS): kept when the page is rebuilt after a reconnect
        self._split = [SPLIT_DEFAULT, SPLIT_DEFAULT]
        self._cols = None
        ui.add_css(CSS)
        ui.add_body_html(KEYBOARD_LOCK_JS)
        ui.add_body_html(SPLIT_JS)
        ui.on("sp_split", self._on_split)
        ui.add_body_html(scene_pick_script())
        self.keys = KeyJog(7, on_jog=self._jog_key, on_stop=self.stop)

        with frame.status_bar:
            # click: send the command type to Servo again (a manual fallback; it is also sent automatically)
            self.servo_chip = ui.element("button").on("click", self._send_command_type)
            self.report_chip = ui.element("div")  # Servo's own status: slowing down or halted
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
        self._shown_highlight = None
        if c is None:
            with self.main, ui.element("section").classes("wg-panel sp-wide"):
                with ui.element("div").classes("wg-empty"):
                    ui.icon("sym_o_sync", size="36px")
                    ui.label("Reconnecting to ROS")
                    ui.label("The controls come back when the new connection is up.").classes("wg-hint")
            return
        with self.main, ui.element("div").classes("sp-cols").style(self._split_style()) as self._cols:
            with ui.element("div").classes("sp-col sp-col-l"):
                self._cartesian_panel(c)
            self._handle("l")
            with ui.element("div").classes("sp-col sp-col-c"):
                self._robot_panel(c)
            self._handle("r")
            with ui.element("div").classes("sp-col sp-col-r"):
                self._joints_panel(c)
        with self.bar:
            self._action_bar(c)
        self._build_rows(c)
        self._refresh_labels(c)
        self._show_mode(c)

    def _handle(self, side):
        """The border between two columns: the gap itself, dragged in the browser (SPLIT_JS)."""
        with ui.element("div").classes("sp-handle").props(f'data-side="{side}"'):
            ui.icon("sym_o_drag_indicator", size="20px")
            ui.tooltip("Drag to resize the panels, double-click for equal ones")

    def _split_style(self):
        left, right = self._split
        return f"--sp-l: {left:.4f}; --sp-r: {right:.4f}"

    def _on_split(self, e):
        """A border was dragged: keep the widths (the browser has applied them already)."""
        try:
            left, right = float(e.args["l"]), float(e.args["r"])
        except (KeyError, TypeError, ValueError):
            return
        left = min(max(left, SPLIT_MIN), SPLIT_MAX)
        right = min(max(right, SPLIT_MIN), SPLIT_MAX, 1 - SPLIT_CENTER_MIN - left)
        self._split = [left, right]
        if self._cols is not None and not self._cols.is_deleted:
            # the same values the browser already shows, so a later update of the element does not undo the drag
            self._cols.style(self._split_style())

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
                self.view = RobotView(c, self.dark, on_pick=self._on_pick)
                with ui.element("div").classes("sp-report") as self.report:
                    self.report_icon = ui.icon(STATUS_ICONS["warn"], size="22px")
                    with ui.element("div").classes("sp-report-text"):
                        self.report_title = ui.label().classes("sp-report-title")
                        self.report_message = ui.label().classes("wg-hint")
                self.report.set_visibility(False)
                self._shown_report = None
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
            self.joint_overlay = self._overlay("Tap to jog in Joint mode", JOINT)

    def _build_rows(self, c):
        self.rows.clear()
        self.joint_widgets = {}
        self._shown_highlight = None
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
                with ui.element("div").classes("sp-jrow") as row:
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
                    self.joint_widgets[name] = (lo, hi, mark, angle, slider, row)

    def _action_bar(self, c):
        # on click, not on change: a click on the active mode sends Servo's command type again
        self.mode_toggle = (
            ui.toggle({TWIST: "Cartesian", JOINT: "Joint"}, value=c.mode)
            .on("click", lambda: self.set_mode(self.mode_toggle.value))
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
        self.pause_button = (
            ui.button("Pause", icon="sym_o_pause", on_click=self.toggle_pause)
            .props("no-caps outline")
            .classes("sp-pause")
            .tooltip(
                f"Pause Servo, or resume the mode before ({self.key_labels['pause']}). Paused, nothing is sent; "
                "tapping a panel also resumes in its mode."
            )
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
            "pause": k.add("x", "Pause Servo / resume the mode before", self.toggle_pause, group="Mode"),
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
        """Switches the mode; the mode that is already active sends Servo's command type again."""
        c = self.node
        if c is None or self._built_for is not c:
            return
        c.set_mode(mode)
        self._show_mode(c)

    def toggle_pause(self):
        """Pause Servo (no mode), or resume the mode that was active before."""
        c = self.node
        if c is None or self._built_for is not c:
            return
        c.toggle_pause()
        self._show_mode(c)

    def _send_command_type(self):
        c = self.node
        if c is None:
            return
        if c.paused:
            ui.notify("Paused: choose a mode first (tap a panel)", type="info")
            return
        c.send_command_type()
        ui.notify(f"Sent the {MODE_NAMES[c.mode]} command type to Servo", type="info")

    def _show_mode(self, c):
        self.mode_toggle.value = c.mode  # None while paused: neither button lit
        # one-column layout (narrow browsers): only the active control is shown (CSS); paused, both
        modes = {JOINT: "sp-m-joint", TWIST: "sp-m-twist"}
        self.main.classes(add=modes.get(c.mode, ""), remove=" ".join(v for k, v in modes.items() if k != c.mode))
        # paused: both panels dimmed, each offering its mode (which resumes Servo)
        self.cart_overlay.set_visibility(c.mode != TWIST)
        self.joint_overlay.set_visibility(c.mode != JOINT)
        if c.paused:
            hint = "Paused: tap a panel to jog"
        elif c.mode == JOINT:
            hint = "Tap a ring to find its slider"
        else:
            hint = "Tap an arrow to find its control"
        self.view_hint.set_text(hint)
        if c.paused:
            self.pause_button.props(remove="outline").props("unelevated color=primary")
            self.pause_button.set_text("Paused")
            self.pause_button.props("icon=sym_o_play_arrow")
        else:
            self.pause_button.props(remove="unelevated color=primary").props("outline")
            self.pause_button.set_text("Pause")
            self.pause_button.props("icon=sym_o_pause")

    def _show_report(self, c):
        """Servo's status (moveit_msgs/ServoStatus): a chip, and the message over the 3D view; hidden at NO_WARNING."""
        report = c.servo_report()
        if report == self._shown_report:
            return
        self._shown_report = report
        self.report.set_visibility(report is not None)
        self._chip(self.report_chip, report[:2] if report is not None else None)
        if report is None:
            return
        level, title, message = report
        self.report.classes(replace=f"sp-report wg-{level}")
        self.report_icon.props(f"name={STATUS_ICONS[level]}")
        self.report_title.set_text(title)
        self.report_message.set_text(message)
        self.report_message.set_visibility(bool(message))

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

    def _on_pick(self, kind, key):
        """Handle a ring or arrow in the 3D view that was hovered (key None: none any more) or tapped."""
        c = self.node
        if c is None or self._built_for is not c:
            return
        if kind == "hover":
            self._hover = key
        elif key is not None:
            self._pressed = (key, time.monotonic() + PICK_HIGHLIGHT)
            if key.startswith("j:"):
                target = self.joint_widgets.get(key[2:], (None,))[-1]
            else:  # the rocker of the plane drives the axis alone
                self._set_plane(ROCKER_PLANES[AXIS_NAMES.index(key[0].upper())])
                target = self.rocker
            if target is not None:  # one-column layout: the control may be scrolled away
                ui.run_javascript(
                    f"getHtmlElement({target.id})?.scrollIntoView({{block: 'nearest', behavior: 'smooth'}})"
                )
        self._show_highlight(c)
        if self.view is not None:
            self.view.update()  # the ring or arrow solid at once, not with the next tick

    def _highlighted(self, c):
        """Return the ring or arrow to highlight: hovered, or tapped a moment ago; only those of the active mode."""
        key, until = self._pressed
        key = self._hover or (key if time.monotonic() < until else None)
        if key is None or c.paused or key.startswith("j:") != (c.mode == JOINT):
            return None
        return key

    def _show_highlight(self, c):
        key = self._highlighted(c)
        if self.view is not None:
            self.view.highlight = key
        if self._shown_highlight == (key, c.plane):
            return
        self._shown_highlight = (key, c.plane)
        for name, (*_, row) in self.joint_widgets.items():
            if key == "j:" + name:
                row.classes(add="sp-hl")
            else:
                row.classes(remove="sp-hl")
        pad = rocker = (None,)
        if key is not None and not key.startswith("j:"):
            axis, sign = AXIS_NAMES.index(key[0].upper()), 1 if key[1] == "+" else -1
            (h, v), _ = PLANES[c.plane]
            if axis == h:
                pad = ("right" if sign > 0 else "left", sign)
            elif axis == v:
                pad = ("up" if sign > 0 else "down", sign)
            else:
                rocker = ("up" if sign > 0 else "down", sign)
        self.pad.set_highlight(*pad)
        self.rocker.set_highlight(*rocker)

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
        self._show_highlight(c)
        self.view.update()
        self._show_report(c)
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
        for name, (lo, hi, mark, angle, slider, _) in self.joint_widgets.items():
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
            if chip is self.servo_chip:
                ui.icon("sym_o_sync", size="18px")
                ui.tooltip("Send the command type to Servo again. It is also sent on every mode change, whenever "
                           "a jog starts and when Servo rejects a command.")  # fmt: skip

    def _update_status(self):
        c = self.node
        if c is None:
            for chip in (self.servo_chip, self.report_chip, self.states_chip, self.crosstalk_chip):
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
