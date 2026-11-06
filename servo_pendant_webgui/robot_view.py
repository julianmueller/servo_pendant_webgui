"""
3D view of the robot: URDF visuals, joint direction rings (joint mode) and the jog directions at the tool (Cartesian).

Rings and arrows can be picked (components/scene_pick.js): hovering or tapping one lights it up and reports it to the
page, which highlights the control that drives it.
"""

import contextlib
import json
import math

import numpy as np
from nicegui import ui

from servo_pendant_webgui.mesh_cache import glb_url
from servo_pendant_webgui.ros_node import AXIS_NAMES, JOINT, TWIST
from servo_pendant_webgui.shell import theme
from servo_pendant_webgui.timers import page_timer

# Links without a material in the URDF
LINK_COLOR = theme.LIGHT["border"]

# Keys of the six Cartesian directions ('x+', 'x-', …), as reported by picking
AXIS_KEYS = [(f"{name.lower()}{'+' if sign > 0 else '-'}", i, sign) for i, name in enumerate(AXIS_NAMES)
             for sign in (1, -1)]

LABEL_STYLE = (
    "font: 600 12px var(--wg-font); color: var(--wg-text); padding: 0 4px; border-radius: 4px; "
    "background: color-mix(in srgb, var(--wg-surface) 82%, transparent)"
)


def view_colors(dark):
    """Colours of the 3D view (three.js needs values, not CSS variables), from the palette of the theme."""
    t = theme.DARK if dark else theme.LIGHT
    return {
        "background": t["sunken"] if dark else t["bg"],
        "floor": t["surface"] if dark else t["sunken"],
        "grid": t["border"],
        "positive": t["primary"],  # moving in the positive direction
        "negative": t["warning"],  # moving in the negative direction
        "idle": t["subtle"],
    }


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
    """
    Robot from the URDF visuals; rings show each joint's positive direction, arrows the six Cartesian directions.

    The moving one is coloured, as is the one in `highlight` (picked in the view or by the page).
    """

    RING_RADIUS, RING_TUBE, RING_LENGTH = 0.103, 0.006, 1.5 * math.pi
    # Cartesian arrows along the local y axis of their group: gap at the tool, shaft, head [m]
    ARROW_GAP, ARROW_SHAFT, ARROW_HEAD, ARROW_RADIUS, ARROW_HEAD_RADIUS = 0.02, 0.13, 0.04, 0.006, 0.017
    IDLE_OPACITY = 0.3  # of the arrows nobody commands or points at
    FLOOR_SIZE, FLOOR_THICKNESS = 1.6, 0.01

    def __init__(self, commander, dark=False, on_pick=None):
        """
        Build the scene; the robot follows with the first update that has a model.

        on_pick(kind, key): kind 'hover' (key None: nothing under the mouse) or 'press'; key 'j:<joint>' for a joint
        ring, 'x+' … 'z-' for a Cartesian arrow.
        """
        self.c = commander
        self.dark = dark
        self.colors = view_colors(dark)
        self.on_pick = on_pick
        self.highlight = None  # key of the ring or arrow shown solid (hovered, or picked a moment ago)
        self.scene = ui.scene(grid=False, background_color=self.colors["background"]).classes("sp-scene")
        self.scene.on("pick3d", self._handle_pick)
        self.scene.on("init", self._install_picking)  # again after a remount (e.g. a lost WebGL context)
        page_timer(0.5, self._start, once=True)  # the camera can only be moved once the scene is live
        self.model = None
        self.visual_objects = []  # (object, link, 4x4 visual origin, is_cylinder)
        self.rings = {}  # joint -> (group, [parts])
        self._sent = {}
        with self.scene:
            self._floor()
            self.tcp_ring, self.tcp_ring_parts = self._ring_group()
            self.arrows = {key: self._arrow_group(i, sign) for key, i, sign in AXIS_KEYS}
        self.tcp_ring.visible(False)
        for group, _ in self.arrows.values():
            group.visible(False)

    def _floor(self):
        """Solid floor slab (visible from above and below) with a 10 cm grid on top."""
        half, t = self.FLOOR_SIZE / 2, self.FLOOR_THICKNESS
        self.floor = (
            self.scene.box(self.FLOOR_SIZE, self.FLOOR_SIZE, t)
            .material(self.colors["floor"])
            .move(0, 0, -t / 2 - 0.001)
        )
        self.grid = []
        for k in range(-8, 9):
            self.grid.append(
                self.scene.line([k / 10, -half, 0.0005], [k / 10, half, 0.0005])
            )
            self.grid.append(
                self.scene.line([-half, k / 10, 0.0005], [half, k / 10, 0.0005])
            )
        for line in self.grid:
            line.material(self.colors["grid"])

    def set_dark(self, dark):
        """Colours of the other theme. The rings and arrows follow with the next update."""
        if dark == self.dark:
            return
        self.dark, self.colors = dark, view_colors(dark)
        background = self.colors["background"]
        self.scene.props(f"background-color={background}")  # for a reconnecting browser
        ui.run_javascript(
            f"getElement({self.scene.id}).renderer?.setClearColor('{background}')"
        )
        self.floor.material(self.colors["floor"])
        for line in self.grid:
            line.material(self.colors["grid"])

    def _ring_group(self, label=None):
        """A 3D ring (tube arc + cone head) in the XY plane of a group, arrow head pointing to positive rotation."""
        r, segments = self.RING_RADIUS, 6
        step = self.RING_LENGTH / segments
        parts = []
        with self.scene.group() as group:
            for k in range(
                segments
            ):  # each 45 deg piece as a quadratic Bezier tube (control point on the bisector)
                a0, a1 = k * step, (k + 1) * step
                rm = r / math.cos(step / 2)
                parts.append(
                    self.scene.quadratic_bezier_tube(
                        [r * math.cos(a0), r * math.sin(a0), 0.0],
                        [
                            rm * math.cos((a0 + a1) / 2),
                            rm * math.sin((a0 + a1) / 2),
                            0.0,
                        ],
                        [r * math.cos(a1), r * math.sin(a1), 0.0],
                        tubular_segments=12,
                        radius=self.RING_TUBE,
                        radial_segments=8,
                    )
                )
            end = self.RING_LENGTH
            tangent = np.array([-math.sin(end), math.cos(end), 0.0])
            tip = (
                np.array([r * math.cos(end), r * math.sin(end), 0.0]) + tangent * 0.024
            )
            parts.append(
                self.scene.cylinder(0, 0.022, 0.048, 16)
                .move(*map(float, tip))
                .rotate_R(_align(tangent, 1).tolist())
            )
            if label is not None:
                self.scene.text(label, LABEL_STYLE).move(-(r + 0.04), 0.0, 0.0)
        return group, parts

    def _ring_outline(self):
        """Return the outline of a ring in its group's frame, for picking: the arc and the head."""
        r, end = self.RING_RADIUS, self.RING_LENGTH
        points = [[r * math.cos(a), r * math.sin(a), 0.0] for a in np.linspace(0.0, end, 19)]
        points.append([r * math.cos(end) - 0.048 * math.sin(end), r * math.sin(end) + 0.048 * math.cos(end), 0.0])
        return points

    def _arrow_group(self, axis, sign):
        """Arrow (shaft + cone head + label) along the local y axis of a group; the group is turned onto the axis."""
        gap, shaft, head = self.ARROW_GAP, self.ARROW_SHAFT, self.ARROW_HEAD
        with self.scene.group() as group:
            parts = [
                self.scene.cylinder(self.ARROW_RADIUS, self.ARROW_RADIUS, shaft, 12).move(0, gap + shaft / 2, 0),
                self.scene.cylinder(0, self.ARROW_HEAD_RADIUS, head, 16).move(0, gap + shaft + head / 2, 0),
            ]
            label = f"{'+' if sign > 0 else '-'}{AXIS_NAMES[axis]}"  # as on the pad
            self.scene.text(label, LABEL_STYLE).move(0, gap + shaft + head + 0.025, 0)
        return group, parts

    def _arrow_outline(self):
        """Return the outline of an arrow in its group's frame, for picking."""
        return [[0.0, self.ARROW_GAP, 0.0], [0.0, self.ARROW_GAP + self.ARROW_SHAFT + self.ARROW_HEAD, 0.0]]

    def _handle_pick(self, e):
        args = e.args[0] if isinstance(e.args, list) and e.args else e.args or {}
        kind, key = args.get("type"), args.get("key")
        if kind in ("hover", "press") and self.on_pick is not None:
            self.on_pick(kind, key)

    def _install_picking(self, _=None):
        """
        Tell the browser what can be picked: every ring and arrow group with its outline (in the group's frame).

        The rings and arrows are drawn over the robot, so the ones behind or inside it stay visible.
        """
        ring = self._ring_outline()
        items = [{"id": group.id, "key": "j:" + name, "points": ring} for name, (group, _) in self.rings.items()]
        arrow = self._arrow_outline()
        items += [{"id": group.id, "key": key, "points": arrow} for key, (group, _) in self.arrows.items()]
        groups = [*self.rings.values(), *self.arrows.values(), (self.tcp_ring, self.tcp_ring_parts)]
        overlay = [part.id for _, parts in groups for part in parts]
        ui.run_javascript(f"window.spScenePick?.install({self.scene.id}, {json.dumps(items)}, {json.dumps(overlay)})")

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

    def _start(self):
        self.reset_camera()
        # three.js only follows window resizes: follow the panel size too (splitters, one-column layout)
        ui.run_javascript(
            f"const s = getElement({self.scene.id}); if (s && !s.sp_resize) "
            "{ s.sp_resize = new ResizeObserver(() => s.resize()); s.sp_resize.observe(s.$el); }"
        )
        self._install_picking()

    def reset_camera(self):
        self.scene.move_camera(
            x=1.0,
            y=-0.85,
            z=0.8,
            look_at_x=0.2,
            look_at_y=0,
            look_at_z=0.38,
            duration=0,
        )

    # ------------------------------------------------------------------ #

    def _build(self, model):
        logger = self.c.get_logger()
        with self.scene:
            for link, v in model.visuals():
                g = v.geometry
                color, opacity = model.color(v)
                color = color or LINK_COLOR
                if g.mesh is not None:
                    url = glb_url(g.mesh.filename, logger)
                    if url is None:
                        continue
                    obj = self.scene.gltf(url).scale(*model.mesh_scale(g.mesh))
                elif g.box is not None:
                    obj = self.scene.box(*map(float, g.box.size)).material(color, opacity)
                elif g.cylinder is not None:
                    r = g.cylinder.radius
                    obj = self.scene.cylinder(r, r, g.cylinder.length, 24).material(
                        color, opacity
                    )
                elif g.sphere is not None:
                    obj = self.scene.sphere(g.sphere.radius).material(color, opacity)
                else:
                    continue
                origin = np.eye(4) if v.origin is None else v.origin
                self.visual_objects.append((obj, link, origin, g.cylinder is not None))
            for name, joint in model.joints.items():
                if joint.type in ("revolute", "continuous") and joint.mimic is None:
                    self.rings[name] = self._ring_group(self._label(name))
        self.model = model
        self._install_picking()

    def _label(self, name):
        names = list(self.c.joint_names)
        return f"J{names.index(name) + 1}" if name in names else name

    def _clear(self):
        for obj, *_ in self.visual_objects:
            obj.delete()
        for group, _ in self.rings.values():
            group.delete()
        self.visual_objects, self.rings, self._sent = [], {}, {}

    def _send(
        self,
        obj,
        key,
        *,
        pos=None,
        R=None,
        scale=None,
        color=None,
        opacity=1.0,
        visible=None,
    ):
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

    def _paint(self, parts, key, color, opacity=1.0):
        if self._sent.get(key + "c") != (color, opacity):
            self._sent[key + "c"] = (color, opacity)
            for part in parts:
                part.material(color, opacity)

    _FLIP = np.diag(
        [1.0, -1.0, -1.0]
    )  # 180 deg about x: the arc runs the other way round, the head turns around

    def _place_ring(self, group, parts, key, center, axis, color, opacity=1.0, sign=1):
        """Ring group around `axis` at `center`; the arrow head shows the direction of rotation (`sign`)."""
        Rz = _align(axis, 2)
        self._send(
            group,
            key + "g",
            pos=center,
            R=Rz if sign > 0 else Rz @ self._FLIP,
            visible=True,
        )
        self._paint(parts, key, color, opacity)

    def update(self):
        model = self.c.model
        if model is None:
            return
        if self.model is not model:
            self._clear()
            self._build(model)
        # One message per update instead of one per move/rotate: keeps NiceGUI's reconnect history from being
        # flooded (replaying it showed old poses = glitches) and applies all poses in the same browser frame.
        # Scene._batch_calls only exists in newer NiceGUI (3.17 has it, 3.3 does not): send unbatched otherwise.
        batch = getattr(self.scene, "_batch_calls", None)
        with batch() if batch else contextlib.nullcontext():
            self._update(model)

    def _relative_to_base(self, links, joints):
        """Re-express the URDF-root transforms in the base frame of the settings, so that it sits at the scene
        origin (floor, grid and camera target). Unchanged if the base frame is not a URDF link."""
        base = links.get(self.c.base_frame)
        if base is None:
            return links, joints
        inv = np.linalg.inv(base)
        R, t = inv[:3, :3], inv[:3, 3]
        links = {name: inv @ T for name, T in links.items()}
        joints = {name: (R @ c + t, R @ a) for name, (c, a) in joints.items()}
        return links, joints

    def _update(self, model):
        links, joints = self._relative_to_base(*model.forward(self.c.snapshot_positions()))
        inputs = self.c.active_inputs()
        joint_mode = self.c.mode == JOINT

        for i, (obj, link, origin, is_cylinder) in enumerate(self.visual_objects):
            if link not in links:
                continue
            T = links[link] @ origin
            R = T[:3, :3] @ _Y_TO_Z if is_cylinder else T[:3, :3]
            self._send(obj, f"v{i}", pos=T[:3, 3], R=R)

        # joint mode: every joint's positive direction; the moving one coloured, its head in the direction of motion,
        # the highlighted one solid in the positive colour
        jog = self.c.joint_velocities(inputs) if joint_mode else {}
        for name, (group, parts) in self.rings.items():
            if not joint_mode or name not in joints:
                self._send(group, name + "g", visible=False)
                continue
            center, axis = joints[name]
            v = jog.get(name, 0.0)
            if abs(v) > 1e-9:
                color, opacity, sign = self.colors["positive" if v > 0 else "negative"], 1.0, v
            elif self.highlight == "j:" + name:
                color, opacity, sign = self.colors["positive"], 1.0, 1
            else:
                color, opacity, sign = self.colors["idle"], 0.55, 1
            self._place_ring(group, parts, name, center, axis, color, opacity, sign)

        # cartesian mode: the six directions of the command frame at the tool, see-through; the commanded and the
        # highlighted ones solid. A ring at the tool for the commanded rotation.
        tool = links.get(self.c.tool_frame)
        cartesian = self.c.mode == TWIST and tool is not None  # paused (no mode): neither rings nor arrows
        ring_shown = False
        if cartesian:
            linear, angular = self.c.cartesian_command(inputs)
            if self.c.frame == "tool":
                to_world = tool[:3, :3]
            else:
                base = links.get(self.c.base_frame)
                to_world = base[:3, :3] if base is not None else np.eye(3)
            tcp = tool[:3, 3]
            for key, i, sign in AXIS_KEYS:
                group, parts = self.arrows[key]
                self._send(group, key + "g", pos=tcp, R=_align(to_world[:, i] * sign, 1), visible=True)
                solid = linear[i] * sign > 1e-9 or self.highlight == key
                color = self.colors["positive" if sign > 0 else "negative"]
                self._paint(parts, key, color, 1.0 if solid else self.IDLE_OPACITY)
            ang_w = to_world @ angular
            if np.linalg.norm(ang_w) > 1e-9:
                self._place_ring(
                    self.tcp_ring, self.tcp_ring_parts, "tcp", tcp, ang_w, self.colors["positive"]
                )
                ring_shown = True
        else:
            for key, (group, _) in self.arrows.items():
                self._send(group, key + "g", visible=False)
        if not ring_shown:
            self._send(self.tcp_ring, "tcpg", visible=False)
