"""Robot model from the URDF, parsed by yourdfpy: links, joints and visuals, and forward kinematics for the 3D view."""

import io
import math

import numpy as np
import yourdfpy


class UrdfModel:
    """
    The URDF as a yourdfpy.URDF (`urdf`), with what the panel needs on top. Meshes are not loaded here: the 3D view
    loads them itself, converted to glTF.
    """

    def __init__(self, xml):
        self.urdf = yourdfpy.URDF.load(io.BytesIO(xml.encode()), load_meshes=False)
        self.links = list(self.urdf.link_map)  # link names, in URDF order
        self.joints = self.urdf.joint_map  # name -> yourdfpy.Joint
        self.root = self.urdf.base_link
        self._actuated = set(self.urdf.actuated_joint_names)
        self._materials = {m.name: m for m in self.urdf.robot.materials}  # named materials, defined once

    def visuals(self):
        """(link name, yourdfpy.Visual) of every visual of the robot."""
        for link in self.urdf.robot.links:
            for visual in link.visuals:
                yield link.name, visual

    def mesh_filenames(self):
        return {v.geometry.mesh.filename for _, v in self.visuals() if v.geometry.mesh is not None}

    def color(self, visual):
        """('#rrggbb', opacity) of the visual's material, or (None, 1.0) if it has none."""
        material = visual.material
        if material is not None and material.color is None:
            material = self._materials.get(material.name)
        if material is None or material.color is None:
            return None, 1.0
        rgba = np.clip(material.color.rgba, 0.0, 1.0)
        return "#" + "".join(f"{round(255 * v):02x}" for v in rgba[:3]), float(rgba[3])

    @staticmethod
    def mesh_scale(mesh):
        """(x, y, z) scale of a yourdfpy.Mesh (the URDF may give none, one or three values)."""
        return tuple(float(s) for s in np.broadcast_to(1.0 if mesh.scale is None else mesh.scale, 3))

    @staticmethod
    def limits(joint):
        """(lower, upper) position limits of a joint; +-pi when the URDF has none (continuous joints)."""
        limit = joint.limit
        lower = limit.lower if limit is not None and limit.lower is not None else -math.pi
        upper = limit.upper if limit is not None and limit.upper is not None else math.pi
        return lower, upper

    def forward(self, positions):
        """Returns (link name -> 4x4 world transform, joint name -> (world origin, world axis))."""
        self.urdf.update_cfg({n: q for n, q in positions.items() if n in self._actuated})
        links = {link: self.urdf.get_transform(link) for link in self.links}
        joints = {}
        for joint in self.joints.values():
            if joint.parent in links:
                frame = links[joint.parent] @ (np.eye(4) if joint.origin is None else joint.origin)
                joints[joint.name] = (frame[:3, 3].copy(), frame[:3, :3] @ joint.axis)
        return links, joints
