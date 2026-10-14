"""NiceGUI teach-pendant page for MoveIt Servo (light theme, single screen, no scrolling)."""

import math

import numpy as np
from nicegui import ui

from servo_pendant_webgui.components import JogPad, JogSlider, KeyJog
from servo_pendant_webgui.mesh_cache import glb_url
from servo_pendant_webgui.servo_commander import AXIS_NAMES, JOINT, PLANES, TWIST

POSITIVE = "#1f6feb"  # blue: moving in positive direction
NEGATIVE = "#e8590c"  # orange: moving in negative direction
IDLE_RING = "#8c959f"

CSS = f"""
html, body {{ overflow: hidden; background: #e6eaee; }}
.nicegui-content {{ padding: 0 !important; }}
.sd-root {{ position: fixed; inset: 0; display: grid; grid-template-rows: 40px minmax(0, 1fr) 84px;
            color: #24292f; font-family: system-ui, sans-serif; user-select: none; }}
.sd-top {{ display: flex; align-items: center; gap: 18px; padding: 0 12px; background: #fff;
           border-bottom: 1px solid #d0d7de; }}
.sd-alert {{ color: {NEGATIVE} !important; font-weight: 800; }}
.sd-brand {{ font-weight: 800; letter-spacing: .12em; font-size: 15px; }}
.sd-status {{ font: 12px ui-monospace, monospace; color: #57606a; white-space: nowrap; overflow: hidden;
              text-overflow: ellipsis; }}
.sd-main {{ display: grid; grid-template-columns: minmax(300px, 27%) minmax(0, 1fr) minmax(400px, 34%); gap: 10px;
            padding: 10px; min-height: 0; }}
.sd-panel {{ position: relative; background: #fff; border: 1px solid #d0d7de; border-radius: 10px; padding: 10px 12px;
             display: flex; flex-direction: column; gap: 8px; min-height: 0; overflow: hidden; }}
.sd-title {{ font-size: 12px; font-weight: 800; letter-spacing: .14em; color: #57606a; }}
.sd-bottom {{ display: flex; align-items: center; gap: 22px; padding: 0 14px; background: #fff;
              border-top: 1px solid #d0d7de; }}
.sd-toggle .q-btn {{ font-size: 16px; font-weight: 800; letter-spacing: .06em; padding: 6px 18px; }}
.sd-toggle-big .q-btn {{ font-size: 18px; padding: 10px 26px; }}
.q-btn.sd-stop {{ font-size: 18px; font-weight: 800; letter-spacing: .06em; padding: 10px 26px;
                  min-height: 48px; color: #fff !important; background: #d1242f !important; }}
.sd-overlay {{ position: absolute; inset: 0; background: #ffffffb0; display: flex; align-items: center;
               justify-content: center; z-index: 5; cursor: pointer; }}
.sd-loading {{ position: absolute; inset: 0; display: flex; flex-direction: column; gap: 12px; align-items: center;
               justify-content: center; background: #e9eef3; z-index: 50; color: #57606a; font-weight: 700; }}
.sd-overlay-btn {{ background: #fff; border: 2px solid {POSITIVE}; color: {POSITIVE}; border-radius: 10px;
                   padding: 14px 22px; font-weight: 800; font-size: 16px; box-shadow: 0 4px 14px #0002; }}

/* joints */
.sd-jrows {{ display: flex; flex-direction: column; gap: 6px; flex: 1; min-height: 0; }}
.sd-jrow {{ flex: 1; min-height: 0; display: grid; grid-template-columns: 50px minmax(0, 1fr) 84px;
            grid-template-rows: auto minmax(0, 1fr); column-gap: 10px; row-gap: 3px; align-items: center;
            border-top: 1px solid #eaeef2; padding-top: 4px; }}
.sd-jrow:first-child {{ border-top: none; }}
.sd-jname {{ grid-row: 1 / span 2; display: flex; flex-direction: column; align-items: center; line-height: 1.1; }}
.sd-jnum {{ font-size: 20px; font-weight: 900; }}
.sd-jkey {{ font: 700 10px ui-monospace, monospace; color: #57606a; border: 1px solid #c4ccd4; border-radius: 4px;
            padding: 0 5px; margin-top: 2px; }}
.sd-jpos {{ display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 6px; align-items: center;
            font: 11px ui-monospace, monospace; color: #57606a; }}
.sd-limit {{ height: 10px; background: linear-gradient(90deg, #ffd8c2 0 6%, #eaeef2 6% 94%, #ffd8c2 94%);
             border-radius: 5px; position: relative; }}
.sd-limit-mark {{ position: absolute; top: -3px; width: 6px; height: 16px; margin-left: -3px; border-radius: 3px;
                  background: #24292f; }}
.sd-jangle {{ font: 700 17px ui-monospace, monospace; text-align: right; }}
.sd-jrow .sd-slider {{ grid-column: 2 / span 2; }}
.sd-hint {{ font-size: 11px; color: #57606a; }}

/* velocity slider */
.sd-slider {{ position: relative; height: 100%; min-height: 30px; max-height: 52px; touch-action: none; cursor: ew-resize; }}
.sd-slider-rail {{ position: absolute; left: 0; right: 0; top: 50%; height: 12px; margin-top: -6px; border-radius: 6px;
                   background: #eaeef2; border: 1px solid #d0d7de; }}
.sd-slider-fill {{ position: absolute; top: 50%; height: 12px; margin-top: -6px; border-radius: 6px; }}
.sd-slider-fill.sd-pos {{ background: {POSITIVE}; }}
.sd-slider-fill.sd-neg {{ background: {NEGATIVE}; }}
.sd-slider-zero {{ position: absolute; left: 50%; top: 15%; bottom: 15%; width: 2px; margin-left: -1px; background: #8c959f; }}
.sd-slider-sign {{ position: absolute; top: 50%; transform: translateY(-50%); font-weight: 900; font-size: 18px;
                   color: #8c959f; }}
.sd-minus {{ left: 6px; }} .sd-plus {{ right: 6px; }}
.sd-slider-thumb {{ position: absolute; top: 50%; width: 44px; height: 30px; margin: -15px 0 0 -22px; border-radius: 8px;
                    background: #fff; border: 2px solid #8c959f; box-shadow: 0 2px 5px #0003; }}
.sd-slider.sd-active .sd-slider-thumb.sd-pos {{ background: {POSITIVE}; border-color: {POSITIVE}; }}
.sd-slider.sd-active .sd-slider-thumb.sd-neg {{ background: {NEGATIVE}; border-color: {NEGATIVE}; }}
.sd-disabled {{ opacity: .45; pointer-events: none; }}

/* pad / rocker */
.sd-trans {{ flex: 1; min-height: 0; display: flex; gap: 10px; align-items: center; justify-content: center;
             container-type: size; }}
.sd-pad {{ position: relative; touch-action: none; border-radius: 12px; background: #f6f8fa;
           border: 2px solid #d0d7de; cursor: move; }}
.sd-pad-xy {{ width: min(100cqw - 88px, 100cqh); height: min(100cqw - 88px, 100cqh); flex: none; }}
.sd-pad-y {{ width: 78px; height: min(100cqw - 88px, 100cqh); flex: none; }}
.sd-pad.sd-active {{ border-color: {POSITIVE}; }}
.sd-pad-hline, .sd-pad-vline {{ position: absolute; background: #d0d7de; }}
.sd-pad-hline {{ left: 14px; right: 14px; top: 50%; height: 2px; }}
.sd-pad-vline {{ top: 14px; bottom: 14px; left: 50%; width: 2px; }}
.sd-pad-label {{ position: absolute; font: 800 16px system-ui, sans-serif; color: #57606a; }}
.sd-left {{ left: 10px; top: 50%; transform: translateY(-50%); }}
.sd-right {{ right: 10px; top: 50%; transform: translateY(-50%); }}
.sd-up {{ top: 8px; left: 50%; transform: translateX(-50%); }}
.sd-down {{ bottom: 8px; left: 50%; transform: translateX(-50%); }}
.sd-puck {{ position: absolute; width: 56px; height: 56px; margin: -28px 0 0 -28px; border-radius: 50%;
            background: #fff; border: 2px solid #8c959f; box-shadow: 0 2px 6px #0003; }}
.sd-pad.sd-active .sd-puck {{ background: {POSITIVE}; border-color: {POSITIVE}; }}
.sd-rot {{ display: grid; grid-template-columns: 34px minmax(0, 1fr); align-items: center; column-gap: 8px; height: 44px; }}
.sd-rot-label {{ font-weight: 900; font-size: 15px; }}
@media (max-width: 1400px) {{
  .sd-toggle .q-btn {{ font-size: 14px; padding: 4px 10px; }}
  .sd-toggle-big .q-btn {{ font-size: 16px; padding: 8px 18px; }}
  .sd-main {{ grid-template-columns: minmax(280px, 27%) minmax(0, 1fr) minmax(380px, 34%); }}
}}
"""


def _align(axis_world, local_axis):
    """Rotation matrix mapping the local unit axis (1 = y, 2 = z) onto axis_world."""
    d = np.asarray(axis_world, dtype=float)
    d = d / (np.linalg.norm(d) or 1.0)
    helper = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
    u = np.cross(d, helper)
    u /= np.linalg.norm(u)
    if local_axis == 1:  # columns x, y=d, z
        return np.column_stack([u, d, np.cross(u, d)])
    return np.column_stack([u, np.cross(d, u), d])  # columns x, y, z=d


_Y_TO_Z = np.array(
    [[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]]
)  # three.js cylinders are along y, URDF ones along z


class RobotView:
    """Robot from the URDF visuals; rings show each joint's positive direction, the moving one is coloured."""

    RING_RADIUS, RING_TUBE, RING_LENGTH = 0.103, 0.006, 1.5 * math.pi
    FLOOR_SIZE, FLOOR_THICKNESS = 1.6, 0.01

    def __init__(self, commander):
        self.c = commander
        self.scene = ui.scene(grid=False, background_color="#e9eef3").classes("w-full h-full")
        ui.timer(0.5, self.reset_camera, once=True)  # the camera can only be moved once the scene is live
        self.model = None
        self.visual_objects = []  # (object, link, 4x4 visual origin, is_cylinder)
        self.rings = {}  # joint -> (group, [parts], label)
        self._sent = {}
        with self.scene:
            self._floor()
            self.scene.axes_helper(0.2)
            self.tool_axes = self.scene.axes_helper(0.1)
            self.tcp_ring, self.tcp_ring_parts = self._ring_group()
            self.arrow = self.scene.cylinder(0.01, 0.01, 1.0, 12).material(POSITIVE)
            self.arrow_head = self.scene.cylinder(0, 0.026, 0.06, 16).material(POSITIVE)
        for obj in (self.tcp_ring, self.arrow, self.arrow_head):
            obj.visible(False)

    def _floor(self):
        """Solid floor slab (visible from above and below) with a 10 cm grid on top."""
        half, t = self.FLOOR_SIZE / 2, self.FLOOR_THICKNESS
        self.scene.box(self.FLOOR_SIZE, self.FLOOR_SIZE, t).material("#f4f6f8").move(0, 0, -t / 2 - 0.001)
        for k in range(-8, 9):
            self.scene.line([k / 10, -half, 0.0005], [k / 10, half, 0.0005]).material("#c4ccd4")
            self.scene.line([-half, k / 10, 0.0005], [half, k / 10, 0.0005]).material("#c4ccd4")

    def _ring_group(self, label=None):
        """A 3D ring (tube arc + cone head) in the XY plane of a group, arrow head pointing to positive rotation."""
        r, segments = self.RING_RADIUS, 6
        step = self.RING_LENGTH / segments
        parts = []
        with self.scene.group() as group:
            for k in range(segments):  # each 45 deg piece as a quadratic Bezier tube (control point on the bisector)
                a0, a1 = k * step, (k + 1) * step
                rm = r / math.cos(step / 2)
                parts.append(
                    self.scene.quadratic_bezier_tube(
                        [r * math.cos(a0), r * math.sin(a0), 0.0],
                        [rm * math.cos((a0 + a1) / 2), rm * math.sin((a0 + a1) / 2), 0.0],
                        [r * math.cos(a1), r * math.sin(a1), 0.0],
                        tubular_segments=12,
                        radius=self.RING_TUBE,
                        radial_segments=8,
                    )
                )
            end = self.RING_LENGTH
            tangent = np.array([-math.sin(end), math.cos(end), 0.0])
            tip = np.array([r * math.cos(end), r * math.sin(end), 0.0]) + tangent * 0.024
            parts.append(
                self.scene.cylinder(0, 0.022, 0.048, 16).move(*map(float, tip)).rotate_R(_align(tangent, 1).tolist())
            )
            if label is not None:
                self.scene.text(
                    label,
                    "font: 700 12px system-ui; color: #24292f; background: #ffffffd0; padding: 0 4px; "
                    "border-radius: 4px",
                ).move(-(r + 0.04), 0.0, 0.0)
        return group, parts

    async def loading(self):
        """True while the robot model is missing or its meshes are still loading in the browser."""
        if self.model is None:
            return True
        try:
            pending = await ui.run_javascript(
                f"[...getElement({self.scene.id}).objects.values()].filter(o => o.ready_promise).length",
                timeout=2.0,
            )
        except TimeoutError:
            return True
        return bool(pending)

    def reset_camera(self):
        self.scene.move_camera(x=1.0, y=-0.85, z=0.8, look_at_x=0.2, look_at_y=0, look_at_z=0.38, duration=0)

    # ------------------------------------------------------------------ #

    def _build(self, model):
        logger = self.c.get_logger()
        with self.scene:
            for link, visuals in model.visuals.items():
                for v in visuals:
                    if v.kind == "mesh":
                        url = glb_url(v.filename, logger)
                        if url is None:
                            continue
                        obj = self.scene.gltf(url).scale(*v.scale)
                    elif v.kind == "box":
                        obj = self.scene.box(*v.size).material(v.color or "#c8ced5", v.opacity)
                    elif v.kind == "cylinder":
                        obj = self.scene.cylinder(v.size[0], v.size[0], v.size[1], 24).material(
                            v.color or "#c8ced5", v.opacity
                        )
                    else:
                        obj = self.scene.sphere(v.size[0]).material(v.color or "#c8ced5", v.opacity)
                    self.visual_objects.append((obj, link, v.origin, v.kind == "cylinder"))
            for name, joint in model.joints.items():
                if joint.type in ("revolute", "continuous") and joint.mimic is None:
                    self.rings[name] = self._ring_group(self._label(name))
        self.model = model

    def _label(self, name):
        names = list(self.c.joint_names)
        return f"J{names.index(name) + 1}" if name in names else name

    def _clear(self):
        for obj, *_ in self.visual_objects:
            obj.delete()
        for group, _ in self.rings.values():
            group.delete()
        self.visual_objects, self.rings, self._sent = [], {}, {}

    def _send(self, obj, key, *, pos=None, R=None, scale=None, color=None, opacity=1.0, visible=None):
        """Only push changes to the browser."""
        state = (
            None if pos is None else tuple(np.round(pos, 4)),
            None if R is None else tuple(np.round(R, 3).flat),
            None if scale is None else tuple(np.round(scale, 4)),
            color,
            opacity,
            visible,
        )
        if self._sent.get(key) == state:
            return
        self._sent[key] = state
        if visible is not None:
            obj.visible(visible)
        if visible is False:
            return
        if pos is not None:
            obj.move(*map(float, pos))
        if R is not None:
            obj.rotate_R(np.asarray(R).tolist())
        if scale is not None:
            obj.scale(*map(float, scale))
        if color is not None:
            obj.material(color, opacity)

    _FLIP = np.diag([1.0, -1.0, -1.0])  # 180 deg about x: the arc runs the other way round, the head turns around

    def _place_ring(self, group, parts, key, center, axis, color, opacity=1.0, sign=1):
        """Ring group around `axis` at `center`; the arrow head shows the direction of rotation (`sign`)."""
        Rz = _align(axis, 2)
        self._send(group, key + "g", pos=center, R=Rz if sign > 0 else Rz @ self._FLIP, visible=True)
        if self._sent.get(key + "c") != (color, opacity):
            self._sent[key + "c"] = (color, opacity)
            for part in parts:
                part.material(color, opacity)

    def update(self):
        model = self.c.model
        if model is None:
            return
        if self.model is not model:
            self._clear()
            self._build(model)
        # One message per update instead of one per move/rotate: keeps NiceGUI's reconnect history from being
        # flooded (replaying it showed old poses = glitches) and applies all poses in the same browser frame.
        with self.scene._batch_calls():  # pylint: disable=protected-access
            self._update(model)

    def _update(self, model):
        links, joints = model.forward(self.c.snapshot_positions())
        inputs = self.c.active_inputs()
        joint_mode = self.c.mode == JOINT

        for i, (obj, link, origin, is_cylinder) in enumerate(self.visual_objects):
            if link not in links:
                continue
            T = links[link] @ origin
            R = T[:3, :3] @ _Y_TO_Z if is_cylinder else T[:3, :3]
            self._send(obj, f"v{i}", pos=T[:3, 3], R=R)

        # joint mode: every joint's positive direction; the moving one coloured, its head in the direction of motion
        jog = self.c.joint_velocities(inputs) if joint_mode else {}
        for name, (group, parts) in self.rings.items():
            if not joint_mode or name not in joints:
                self._send(group, name + "g", visible=False)
                continue
            center, axis = joints[name]
            v = jog.get(name, 0.0)
            if abs(v) > 1e-9:
                self._place_ring(group, parts, name, center, axis, POSITIVE if v > 0 else NEGATIVE, sign=v)
            else:
                self._place_ring(group, parts, name, center, axis, IDLE_RING, opacity=0.55)

        # cartesian mode: arrow for the translation, ring for the rotation at the tool
        tool = links.get(self.c.tool_frame)
        if tool is not None:
            self._send(self.tool_axes, "tool_axes", pos=tool[:3, 3], R=tool[:3, :3])
        arrow_shown = ring_shown = False
        if not joint_mode and tool is not None:
            linear, angular = self.c.cartesian_command(inputs)
            if self.c.frame == "tool":
                to_world = tool[:3, :3]
            else:
                base = links.get(self.c.base_frame)
                to_world = base[:3, :3] if base is not None else np.eye(3)
            lin_w, ang_w = to_world @ linear, to_world @ angular
            tcp = tool[:3, 3]
            if np.linalg.norm(lin_w) > 1e-9:
                d = lin_w / np.linalg.norm(lin_w)
                length = 0.1 + 0.2 * min(1.0, np.linalg.norm(lin_w) / max(self.c.max_linear * self.c.speed, 1e-9))
                self._send(self.arrow, "arrow", pos=tcp + d * length / 2, R=_align(d, 1), scale=(1, length, 1),
                           visible=True)
                self._send(self.arrow_head, "arrow_head", pos=tcp + d * (length + 0.03), R=_align(d, 1), visible=True)
                arrow_shown = True
            if np.linalg.norm(ang_w) > 1e-9:
                self._place_ring(self.tcp_ring, self.tcp_ring_parts, "tcp", tcp, ang_w, POSITIVE)
                ring_shown = True
        if not arrow_shown:
            self._send(self.arrow, "arrow", visible=False)
            self._send(self.arrow_head, "arrow_head", visible=False)
        if not ring_shown:
            self._send(self.tcp_ring, "tcpg", visible=False)


def build_page(commander):
    c = commander

    @ui.page("/")
    def index():
        ui.add_css(CSS)
        ui.colors(primary=POSITIVE)
        toggle_props = "unelevated toggle-color=primary color=grey-3 text-color=grey-9"

        def jog_key(index, value):
            if c.mode == JOINT and index < len(c.joint_names):
                c.set_input("k:" + c.joint_names[index], value)

        keys = KeyJog(len(c.joint_names) or 7, on_jog=jog_key, on_stop=c.stop)

        with ui.element("div").classes("sd-root"):
            # ---------------- top bar ----------------
            with ui.element("div").classes("sd-top"):
                ui.label("SERVO PENDANT").classes("sd-brand")
                servo_label = ui.label().classes("sd-status")
                state_label = ui.label().classes("sd-status")
                ui.space()
                command_label = ui.label().classes("sd-status")
                ui.button(
                    icon="fullscreen",
                    on_click=lambda: ui.run_javascript(
                        "document.documentElement.requestFullscreen()"
                        ".then(() => navigator.keyboard && navigator.keyboard.lock()).catch(() => {})"
                    ),
                ).props("flat round dense color=grey-8").tooltip(
                    "Full screen (also lets Ctrl+1..9 reach the page)"
                )

            with ui.element("div").classes("sd-main"):
                # ---------------- cartesian (left) ----------------
                with ui.element("div").classes("sd-panel"):
                    with ui.row().classes("items-center w-full no-wrap"):
                        ui.label("CARTESIAN").classes("sd-title")
                        ui.space()
                        ui.toggle(
                            {"base": "BASE", "tool": "TOOL"},
                            value=c.frame,
                            on_change=lambda e: (
                                c.set_frame(e.value),
                                refresh_labels(),
                            ),
                        ).props(toggle_props).classes("sd-toggle")
                    with ui.row().classes("items-center w-full no-wrap"):
                        ui.toggle(
                            list(PLANES),
                            value=c.plane,
                            on_change=lambda e: (
                                c.set_plane(e.value),
                                refresh_labels(),
                            ),
                        ).props(toggle_props).classes("sd-toggle")
                    with ui.element("div").classes("sd-trans"):
                        pad = JogPad(
                            "xy", on_jog=lambda x, y: c.set_input("pad", (x, y))
                        )
                        rocker = JogPad(
                            "y", on_jog=lambda x, y: c.set_input("rocker", y)
                        )
                    ui.label("ROTATION").classes("sd-title")
                    for key, text in (("rx", "RX"), ("ry", "RY"), ("rz", "RZ")):
                        with ui.element("div").classes("sd-rot"):
                            ui.label(text).classes("sd-rot-label")
                            JogSlider(on_jog=lambda v, k=key: c.set_input(k, v))
                    with ui.element("div").classes("sd-overlay") as cart_overlay:
                        ui.label("Tap to jog in CARTESIAN mode").classes(
                            "sd-overlay-btn"
                        )
                    cart_overlay.on("click", lambda: set_mode(TWIST))

                # ---------------- 3D view (centre) ----------------
                with ui.element("div").classes("sd-panel"):
                    with ui.row().classes("items-center w-full no-wrap"):
                        ui.label("ROBOT").classes("sd-title")
                        ui.space()
                        view_hint = ui.label().classes("sd-hint")
                        ui.button(
                            icon="restart_alt",
                            on_click=lambda: view.reset_camera(),
                        ).props("flat round dense color=grey-8").tooltip("Reset view")
                    with (
                        ui.element("div")
                        .classes("w-full")
                        .style("flex: 1; min-height: 0; position: relative")
                    ):
                        view = RobotView(c)
                        with ui.element("div").classes("sd-loading") as loading_overlay:
                            ui.spinner(size="3em", thickness=4)
                            loading_label = ui.label("Loading robot ...")

                # ---------------- joints (right) ----------------
                with ui.element("div").classes("sd-panel"):
                    with ui.row().classes("items-center w-full no-wrap"):
                        ui.label("JOINTS").classes("sd-title")
                        ui.space()
                        ui.label(
                            "keys 1-9: jog +   Ctrl / Shift + key: jog -   Esc: STOP"
                        ).classes("sd-hint")
                    rows = ui.element("div").classes("sd-jrows")
                    with ui.element("div").classes("sd-overlay") as joint_overlay:
                        ui.label("Tap to jog in JOINT mode").classes(
                            "sd-overlay-btn"
                        )
                    joint_overlay.on("click", lambda: set_mode(JOINT))

            # ---------------- bottom bar ----------------
            with ui.element("div").classes("sd-bottom"):
                mode_toggle = (
                    ui.toggle({TWIST: "CARTESIAN", JOINT: "JOINT"}, value=c.mode)
                    .props(toggle_props)
                    .classes("sd-toggle sd-toggle-big")
                )
                ui.label("SPEED").classes("sd-title")
                speed_value = ui.label(f"{round(c.speed * 100)} %").classes(
                    "text-xl font-black w-16 text-right"
                )
                ui.slider(
                    min=5,
                    max=100,
                    step=5,
                    value=round(c.speed * 100),
                    on_change=lambda e: (
                        c.set_speed(e.value / 100),
                        speed_value.set_text(f"{e.value} %"),
                    ),
                ).props("thumb-size=40px track-size=12px").classes("flex-1")
                ui.button("STOP", on_click=c.stop, color="red-8").classes(
                    "sd-stop"
                ).props("unelevated").tooltip(
                    "Releases all inputs and calls the driver stop service (software stop, not an E-stop)"
                )

        # ---------------- joint rows ----------------
        joint_widgets = {}

        def build_rows():
            rows.clear()
            joint_widgets.clear()
            keys.set_count(len(c.joint_names))
            with rows:
                if not c.joint_names:
                    ui.label("Waiting for joint states ...").classes("sd-hint")
                    return
                for i, name in enumerate(list(c.joint_names)):
                    with ui.element("div").classes("sd-jrow"):
                        with ui.element("div").classes("sd-jname"):
                            ui.label(f"J{i + 1}").classes("sd-jnum")
                            ui.label(str(i + 1) if i < 9 else "").classes(
                                "sd-jkey"
                            ).tooltip(name)
                        with ui.element("div").classes("sd-jpos"):
                            lo = ui.label("")
                            with ui.element("div").classes("sd-limit"):
                                mark = ui.element("div").classes("sd-limit-mark")
                            hi = ui.label("")
                        angle = ui.label("--").classes("sd-jangle")
                        slider = JogSlider(
                            on_jog=lambda v, n=name: c.set_input("j:" + n, v)
                        )
                        joint_widgets[name] = (lo, hi, mark, angle, slider)

        shown_joints = list(c.joint_names)
        build_rows()

        def refresh_labels():
            (h, v), r = PLANES[c.plane]
            pad.set_labels(
                {
                    "left": f"-{AXIS_NAMES[h]}",
                    "right": f"+{AXIS_NAMES[h]}",
                    "up": f"+{AXIS_NAMES[v]}",
                    "down": f"-{AXIS_NAMES[v]}",
                }
            )
            rocker.set_labels({"up": f"+{AXIS_NAMES[r]}", "down": f"-{AXIS_NAMES[r]}"})

        def show_mode():
            mode_toggle.value = c.mode
            cart_overlay.set_visibility(c.mode != TWIST)
            joint_overlay.set_visibility(c.mode != JOINT)
            view_hint.set_text(
                "rings: positive direction of each joint"
                if c.mode == JOINT
                else "arrow / ring: commanded motion of the tool"
            )

        def set_mode(mode):
            if c.mode != mode:
                c.set_mode(mode)
            show_mode()

        mode_toggle.on_value_change(lambda e: set_mode(e.value))
        refresh_labels()
        show_mode()

        def tick():
            nonlocal shown_joints
            view.update()
            if c.joint_names != shown_joints:
                shown_joints = list(c.joint_names)
                build_rows()
            if mode_toggle.value != c.mode:  # changed from another client
                show_mode()
            positions = c.snapshot_positions()
            model = c.model
            inputs = c.active_inputs()
            for name, (lo, hi, mark, angle, slider) in joint_widgets.items():
                slider.set_external(float(inputs.get("k:" + name, 0.0)))
                if name not in positions:
                    continue
                q = positions[name]
                angle.set_text(f"{math.degrees(q):+.1f}°")
                if model is not None and name in model.joints:
                    j = model.joints[name]
                    lo.set_text(f"{math.degrees(j.lower):.0f}°")
                    hi.set_text(f"{math.degrees(j.upper):.0f}°")
                    frac = (q - j.lower) / ((j.upper - j.lower) or 1.0)
                    mark.style(f"left: {100 * min(max(frac, 0.0), 1.0):.1f}%")
            age = c.joint_states_age()
            servo_label.set_text(c.servo_status)
            if not c.robot_active:
                servo_label.set_text(f"ROBOT NOT ACTIVE ({c.robot_mode}): commands are discarded  |  {c.servo_status}")
            servo_label.classes(add="sd-alert" if not c.robot_active else None,
                                remove="sd-alert" if c.robot_active else None)
            if c.joint_states_warning:
                servo_label.set_text(f"{c.servo_status}  |  WARNING: {c.joint_states_warning}")
            state_label.set_text(
                (
                    "joint states: none"
                    if age is None
                    else f"joint states: {age * 1000:.0f} ms"
                )
                + (
                    "  |  model ok"
                    if model is not None
                    else "  |  waiting for /robot_description"
                )
            )
            command_label.set_text(c.last_command)

        ui.timer(0.1, tick)

        async def watch_loading():
            if not await view.loading():
                loading_overlay.set_visibility(False)
                loading_timer.cancel()
                return
            loading_label.set_text(
                c.model_status if c.model is None else "Loading robot meshes ..."
            )

        loading_timer = ui.timer(0.5, watch_loading)
