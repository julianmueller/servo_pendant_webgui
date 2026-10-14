"""Minimal URDF parser and forward kinematics, enough to draw a stick-figure robot."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import numpy as np


def _rpy_to_matrix(roll, pitch, yaw):
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ])


def _axis_angle(axis, angle):
    x, y, z = axis
    c, s, t = np.cos(angle), np.sin(angle), 1.0 - np.cos(angle)
    return np.array([
        [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
        [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
        [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
    ])


def _floats(text, default):
    return [float(v) for v in text.split()] if text else list(default)


@dataclass
class UrdfJoint:
    name: str
    type: str
    parent: str
    child: str
    origin: np.ndarray  # 4x4, parent link -> joint frame
    axis: np.ndarray
    lower: float = -np.pi
    upper: float = np.pi
    mimic: tuple | None = None  # (joint, multiplier, offset)


@dataclass
class UrdfVisual:
    origin: np.ndarray  # 4x4, link -> visual
    kind: str  # 'mesh' | 'box' | 'cylinder' | 'sphere'
    filename: str = ''
    scale: tuple = (1.0, 1.0, 1.0)
    size: tuple = ()  # box: (x, y, z); cylinder: (radius, length); sphere: (radius,)
    color: str | None = None  # '#rrggbb' from the URDF material, if any
    opacity: float = 1.0  # alpha of the URDF material


def _origin(element):
    T = np.eye(4)
    o = element.find('origin') if element is not None else None
    if o is not None:
        T[:3, :3] = _rpy_to_matrix(*_floats(o.get('rpy'), (0, 0, 0)))
        T[:3, 3] = _floats(o.get('xyz'), (0, 0, 0))
    return T


def _color(material, named):
    """('#rrggbb', opacity) of a URDF material, or (None, 1.0)."""
    if material is None:
        return None, 1.0
    c = material.find('color')
    rgba = _floats(c.get('rgba'), (0.7, 0.7, 0.7, 1)) if c is not None else named.get(material.get('name'))
    if rgba is None:
        return None, 1.0
    color = '#' + ''.join(f'{int(round(255 * min(max(v, 0.0), 1.0))):02x}' for v in rgba[:3])
    return color, float(rgba[3]) if len(rgba) > 3 else 1.0


@dataclass
class UrdfModel:
    joints: dict = field(default_factory=dict)
    visuals: dict = field(default_factory=dict)  # link -> [UrdfVisual]
    root: str = ''

    @classmethod
    def from_xml(cls, xml):
        model = cls()
        tree = ET.fromstring(xml)
        children = set()
        links = [link.get('name') for link in tree.findall('link')]
        named = {}
        for m in tree.findall('material'):
            c = m.find('color')
            if c is not None:
                named[m.get('name')] = _floats(c.get('rgba'), (0.7, 0.7, 0.7, 1))
        for link in tree.findall('link'):
            for v in link.findall('visual'):
                g = v.find('geometry')
                if g is None or len(g) == 0:
                    continue
                shape = g[0]
                color, opacity = _color(v.find('material'), named)
                visual = UrdfVisual(origin=_origin(v), kind=shape.tag, color=color, opacity=opacity)
                if shape.tag == 'mesh':
                    visual.filename = shape.get('filename', '')
                    visual.scale = tuple(_floats(shape.get('scale'), (1, 1, 1)))
                elif shape.tag == 'box':
                    visual.size = tuple(_floats(shape.get('size'), (0.1, 0.1, 0.1)))
                elif shape.tag == 'cylinder':
                    visual.size = (float(shape.get('radius', 0.05)), float(shape.get('length', 0.1)))
                elif shape.tag == 'sphere':
                    visual.size = (float(shape.get('radius', 0.05)),)
                else:
                    continue
                model.visuals.setdefault(link.get('name'), []).append(visual)
        for j in tree.findall('joint'):
            origin = _origin(j)
            a = j.find('axis')
            axis = np.array(_floats(a.get('xyz') if a is not None else None, (1, 0, 0)))
            axis = axis / (np.linalg.norm(axis) or 1.0)
            joint = UrdfJoint(
                name=j.get('name'), type=j.get('type'), parent=j.find('parent').get('link'),
                child=j.find('child').get('link'), origin=origin, axis=axis,
            )
            lim = j.find('limit')
            if lim is not None and joint.type != 'continuous':
                joint.lower = float(lim.get('lower', joint.lower))
                joint.upper = float(lim.get('upper', joint.upper))
            m = j.find('mimic')
            if m is not None:
                joint.mimic = (m.get('joint'), float(m.get('multiplier', 1.0)), float(m.get('offset', 0.0)))
            model.joints[joint.name] = joint
            children.add(joint.child)
        roots = [link for link in links if link not in children]
        model.root = roots[0] if roots else ''
        return model

    def forward(self, positions):
        """Returns (link -> 4x4 world transform, joint name -> (world origin, world axis))."""
        links = {self.root: np.eye(4)}
        joints = {}
        pending = list(self.joints.values())
        while pending:
            progressed = False
            for joint in list(pending):
                if joint.parent not in links:
                    continue
                q = positions.get(joint.name, 0.0)
                if joint.mimic is not None:
                    q = positions.get(joint.mimic[0], 0.0) * joint.mimic[1] + joint.mimic[2]
                frame = links[joint.parent] @ joint.origin
                motion = np.eye(4)
                if joint.type in ('revolute', 'continuous'):
                    motion[:3, :3] = _axis_angle(joint.axis, q)
                elif joint.type == 'prismatic':
                    motion[:3, 3] = joint.axis * q
                links[joint.child] = frame @ motion
                joints[joint.name] = (frame[:3, 3].copy(), frame[:3, :3] @ joint.axis)
                pending.remove(joint)
                progressed = True
            if not progressed:  # disconnected parts of the tree are ignored
                break
        return links, joints
