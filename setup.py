from collections.abc import Sequence
from pathlib import Path

from setuptools import find_packages, setup

package_name = "servo_pendant_webgui"


def get_data_files(
    folder: str, file_endings: Sequence[str] = [""]
) -> tuple[str, list[str]]:
    folder_path = Path("share") / package_name / folder
    files = []
    for ext in file_endings:
        files.extend(str(f) for f in Path(folder).glob(ext))
    return (str(folder_path), files)


setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    package_data={package_name: ["components/*.js"]},
    include_package_data=True,
    install_requires=["setuptools", "nicegui", "trimesh", "pycollada", "yourdfpy"],
    zip_safe=True,
    maintainer="jmueller",
    maintainer_email="julian.mueller@iwb.tum.de",
    description="Touch-friendly web teach pendant (NiceGUI) for MoveIt Servo",
    license="GPL-3.0-only",
    extras_require={
        "test": [
            "pytest",
        ],
    },
    entry_points={
        "console_scripts": [
            "servo_pendant_webgui = servo_pendant_webgui.servo_pendant_node:main",
        ],
    },
)
