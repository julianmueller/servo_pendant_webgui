"""Converts URDF meshes (Collada, STL, OBJ, ...) to glTF binaries the browser's 3D view can load."""

import hashlib
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from ament_index_python.packages import (
    PackageNotFoundError,
    get_package_share_directory,
)

CACHE_DIR = (
    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    / "servo_pendant_webgui"
    / "meshes"
)
URL_PREFIX = "/servo_pendant_webgui_meshes"


def resolve(uri):
    """package://pkg/path, file:///path or a plain path -> local file path (or None)."""
    if uri.startswith("package://"):
        package, _, rest = uri[len("package://") :].partition("/")
        try:
            return Path(get_package_share_directory(package)) / rest
        except PackageNotFoundError:
            return None
    if uri.startswith("file://"):
        return Path(unquote(urlparse(uri).path))
    return Path(uri)


def glb_url(uri, logger=None):
    """URL of the mesh as .glb (converted once and cached), or None if it cannot be loaded."""
    path = resolve(uri)
    if path is None or not path.is_file():
        if logger:
            logger.warn(f"Mesh not found: {uri}")
        return None
    stat = path.stat()
    key = hashlib.sha1(
        f"{path}:{stat.st_mtime_ns}:{stat.st_size}".encode()
    ).hexdigest()[:16]
    target = CACHE_DIR / f"{path.stem}_{key}.glb"
    if not target.exists():
        try:
            import trimesh  # imported lazily: only needed for the first conversion

            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            scene = trimesh.load(str(path), force="scene")
            data = scene.export(file_type="glb")
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
        except Exception as e:
            if logger:
                logger.warn(f"Could not convert mesh {uri}: {e}")
            return None
    return f"{URL_PREFIX}/{target.name}"
