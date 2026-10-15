#!/usr/bin/env python3
import sys
import threading

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.signals import SignalHandlerOptions
from nicegui import app, ui

from servo_pendant_webgui.servo_commander import ServoCommander
from servo_pendant_webgui.mesh_cache import (
    CACHE_DIR as MESH_CACHE,
    URL_PREFIX as MESH_URL,
)
from servo_pendant_webgui.web_panel import build_page


def main():
    # Ctrl-C is handled by the web server, which then shuts ROS down below
    rclpy.init(args=sys.argv, signal_handler_options=SignalHandlerOptions.NO)
    commander = ServoCommander()
    executor = SingleThreadedExecutor()
    executor.add_node(commander)

    def spin():
        try:
            executor.spin()
        except ExternalShutdownException:
            pass

    threading.Thread(target=spin, name="ros_spin", daemon=True).start()

    MESH_CACHE.mkdir(parents=True, exist_ok=True)
    app.add_static_files(MESH_URL, MESH_CACHE)  # URDF meshes converted to glTF for the 3D view
    build_page(commander)
    # A closed or lost browser tab must never leave the robot moving
    app.on_disconnect(commander.release_all)

    def shutdown():
        commander.release_all()
        executor.shutdown()
        commander.destroy_node()
        rclpy.try_shutdown()

    app.on_shutdown(shutdown)

    try:
        ui.run(
            host=commander.host,
            port=commander.port,
            title="Servo Pendant",
            dark=False,  # each page applies the theme stored in its browser
            reload=False,
            show=False,
            favicon="🕹️",
            uvicorn_logging_level="warning",
        )
    except KeyboardInterrupt:
        # Ctrl-C: the server has already shut down (and ROS with it), asyncio only re-raises the signal
        pass
    print("Server stopped")


if __name__ == "__main__":
    main()
