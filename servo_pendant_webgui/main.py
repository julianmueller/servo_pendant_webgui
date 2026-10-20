#!/usr/bin/env python3
"""Servo pendant: entry point. Starts the ROS bridge, registers the page and runs the web server."""

import sys

from fastapi import Request
from nicegui import app, ui

from servo_pendant_webgui.mesh_cache import CACHE_DIR as MESH_CACHE, URL_PREFIX as MESH_URL
from servo_pendant_webgui.page import PendantPage
from servo_pendant_webgui.ros_node import ServoCommander
from servo_pendant_webgui.settings import SETTINGS_SECTIONS
from servo_pendant_webgui.shell import theme
from servo_pendant_webgui.shell.config import SettingsStore, choose_port, parse_args
from servo_pendant_webgui.shell.frame import AppFrame
from servo_pendant_webgui.shell.ros_bridge import RosBridge

PACKAGE = "servo_pendant_webgui"
TITLE = "Servo pendant"
ICON = "sym_o_precision_manufacturing"  # Material Symbols name, also used in the header


def main():
    options = parse_args(sys.argv, TITLE)
    options.port = choose_port(options.host, options.port)  # --port, else the first free one from 8080
    store = SettingsStore(PACKAGE)
    bridge = RosBridge(ServoCommander, store.load_connection(options), sys.argv)
    theme.install()
    MESH_CACHE.mkdir(parents=True, exist_ok=True)
    app.add_static_files(MESH_URL, MESH_CACHE)  # URDF meshes converted to glTF for the 3D view

    @ui.page("/")
    def index(request: Request):
        frame = AppFrame(bridge, store, request, TITLE, ICON, extra_settings=SETTINGS_SECTIONS)
        with frame.content:
            PendantPage(frame)

    def release_all():
        node = bridge.node
        if node is not None:
            node.release_all()

    # A closed or lost browser tab must never leave the robot moving
    app.on_disconnect(release_all)
    app.on_shutdown(release_all)
    app.on_shutdown(bridge.shutdown)
    try:
        ui.run(
            host=options.host,
            port=options.port,
            title=TITLE,
            favicon="🕹️",
            reload=False,
            show=False,
            uvicorn_logging_level="warning",
            timeout_graceful_shutdown=1,  # open pages must not keep the server alive
        )
    except KeyboardInterrupt:  # Ctrl-C: the server and ROS are already shut down
        pass


if __name__ == "__main__":
    main()
