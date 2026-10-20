"""3D view of the robot: URDF visuals, joint direction rings (joint mode) and the commanded tool motion (Cartesian)."""

import math

import numpy as np
from nicegui import ui

from servo_pendant_webgui.mesh_cache import glb_url
from servo_pendant_webgui.ros_node import JOINT
from servo_pendant_webgui.shell import theme

# Links without a material in the URDF
LINK_COLOR = theme.LIGHT["border"]


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
    """Robot from the URDF visuals; rings show each joint's positive direction, the moving one is coloured."""

    RING_RADIUS, RING_TUBE, RING_LENGTH = 0.103, 0.006, 1.5 * math.pi
    FLOOR_SIZE, FLOOR_THICKNESS = 1.6, 0.01

    def __init__(self, commander, dark=False):
        self.c = commander
        self.dark = dark
        self.colors = view_colors(dark)
        self.scene = ui.scene(grid=False, background_color=self.colors["background"]).classes(
            "w-full h-full"
        )
        ui.timer(
            0.5, self.reset_camera, once=True
        )  # the camera can only be moved once the scene is live
        self.model = None
        self.visual_objects = []  # (object, link, 4x4 visual origin, is_cylinder)
        self.rings = {}  # joint -> (group, [parts], label)
        self._sent = {}
        with self.scene:
            self._floor()
            self.scene.axes_helper(0.2)
            self.tool_axes = self.scene.axes_helper(0.1)
            self.tcp_ring, self.tcp_ring_parts = self._ring_group()
            self.arrow = self.scene.cylinder(0.01, 0.01, 1.0, 12).material(self.colors["positive"])
            self.arrow_head = self.scene.cylinder(0, 0.026, 0.06, 16).material(self.colors["positive"])
        for obj in (self.tcp_ring, self.arrow, self.arrow_head):
            obj.visible(False)

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
        """Colours of the other theme. The rings follow with the next update."""
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
        self.arrow.material(self.colors["positive"])
        self.arrow_head.material(self.colors["positive"])

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
                self.scene.text(
                    label,
                    "font: 600 12px var(--wg-font); color: var(--wg-text); padding: 0 4px; border-radius: 4px; "
                    "background: color-mix(in srgb, var(--wg-surface) 82%, transparent)",
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
                self._place_ring(
                    group,
                    parts,
                    name,
                    center,
                    axis,
                    self.colors["positive" if v > 0 else "negative"],
                    sign=v,
                )
            else:
                self._place_ring(
                    group, parts, name, center, axis, self.colors["idle"], opacity=0.55
                )

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
                length = 0.1 + 0.2 * min(
                    1.0,
                    np.linalg.norm(lin_w) / max(self.c.max_linear * self.c.speed, 1e-9),
                )
                self._send(
                    self.arrow,
                    "arrow",
                    pos=tcp + d * length / 2,
                    R=_align(d, 1),
                    scale=(1, length, 1),
                    visible=True,
                )
                self._send(
                    self.arrow_head,
                    "arrow_head",
                    pos=tcp + d * (length + 0.03),
                    R=_align(d, 1),
                    visible=True,
                )
                arrow_shown = True
            if np.linalg.norm(ang_w) > 1e-9:
                self._place_ring(
                    self.tcp_ring, self.tcp_ring_parts, "tcp", tcp, ang_w, self.colors["positive"]
                )
                ring_shown = True
        if not arrow_shown:
            self._send(self.arrow, "arrow", visible=False)
            self._send(self.arrow_head, "arrow_head", visible=False)
        if not ring_shown:
            self._send(self.tcp_ring, "tcpg", visible=False)
