"""
Start-up options (command line) and the ROS connection settings, which are saved so they survive a restart.

Shared webgui shell (from the nicegui-ros2-webgui skill): keep it identical across the webgui packages.
"""

import argparse
import json
import os
import re
import socket
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from rclpy.utilities import remove_ros_args

# ROS_AUTOMATIC_DISCOVERY_RANGE (Jazzy and newer): value -> text shown in the settings
DISCOVERY_RANGES = {
    "SUBNET": "Local network (default)",
    "LOCALHOST": "This computer only",
    "OFF": "Off (static peers only)",
    "SYSTEM_DEFAULT": "Middleware default",
}
MAX_DOMAIN_ID = 232  # rmw limit; 0..101 are safe on every OS
NODE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
NAMESPACE_RE = re.compile(r"^(/[A-Za-z_][A-Za-z0-9_]*)+$")


@dataclass
class RosConnection:
    """What the webgui's ROS context and node are created with. Changing it restarts the node (RosBridge.reconnect)."""

    domain_id: int = 0
    namespace: str = ""
    node_name: str = ""  # empty: the name the node class gives itself (the package name)
    discovery_range: str = "SUBNET"
    static_peers: str = ""  # hosts separated by ";" (ROS_STATIC_PEERS)

    @classmethod
    def from_environment(cls):
        try:
            domain_id = int(os.environ.get("ROS_DOMAIN_ID", "0") or 0)
        except ValueError:
            domain_id = 0
        discovery = os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE", "")
        if not discovery:
            discovery = "LOCALHOST" if os.environ.get("ROS_LOCALHOST_ONLY") == "1" else "SUBNET"
        return cls(
            domain_id=domain_id,
            discovery_range=discovery if discovery in DISCOVERY_RANGES else "SUBNET",
            static_peers=os.environ.get("ROS_STATIC_PEERS", ""),
        )

    def validate(self):
        """Error text, or None if the settings can be used."""
        if not 0 <= int(self.domain_id) <= MAX_DOMAIN_ID:
            return f"The domain ID must be between 0 and {MAX_DOMAIN_ID}."
        if self.discovery_range not in DISCOVERY_RANGES:
            return f"Unknown discovery range {self.discovery_range}."
        if self.namespace and not NAMESPACE_RE.match("/" + self.namespace.strip("/")):
            return "The namespace may only contain letters, digits, '_' and '/', and no part may start with a digit."
        if self.node_name and not NODE_NAME_RE.match(self.node_name):
            return "The node name may only contain letters, digits and '_', and may not start with a digit."
        return None


class SettingsStore:
    """
    Server-side settings of one webgui package, as JSON in $ROS_HOME/<package>/settings.json (~/.ros by default).
    Order at start-up: command line > saved file > environment.
    """

    def __init__(self, package):
        self.package = package
        self.path = Path(os.environ.get("ROS_HOME", "~/.ros")).expanduser() / package / "settings.json"

    def _read(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def load_connection(self, options):
        saved = self._read().get("ros", {})
        known = {f.name for f in fields(RosConnection)}
        connection = RosConnection(
            **{**asdict(RosConnection.from_environment()), **{k: v for k, v in saved.items() if k in known}}
        )
        if options.domain_id is not None:
            connection.domain_id = options.domain_id
        if options.namespace is not None:
            connection.namespace = options.namespace
        if options.node_name is not None:
            connection.node_name = options.node_name
        if connection.validate():
            connection = RosConnection.from_environment()
        return connection

    def save_connection(self, connection):
        data = self._read()
        data["ros"] = asdict(connection)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n")


FIRST_PORT = 8080  # without --port, a webgui takes the first free port from here upwards
PORT_RANGE = 100  # ... up to FIRST_PORT + PORT_RANGE - 1


def parse_args(argv, description):
    """Web server and ROS options. ROS arguments (--ros-args ...) are left for rclpy."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--host", default="0.0.0.0", help="address to serve on (default: all, use 127.0.0.1 for this computer only)"
    )
    parser.add_argument(
        "--port", type=int, default=None, help=f"web server port (default: the first free one from {FIRST_PORT})"
    )
    parser.add_argument("--domain-id", type=int, default=None, help="ROS domain ID (default: saved, else ROS_DOMAIN_ID)")
    parser.add_argument("--namespace", default=None, help="ROS namespace of the node (default: saved, else none)")
    parser.add_argument(
        "--node-name", default=None, help="ROS name of the node (default: saved, else the package name)"
    )
    return parser.parse_args(remove_ros_args(argv)[1:])


def port_is_free(host, port):
    """True if the web server could serve on the port.

    It is tried the way the server will use it, by binding a socket to it. Connecting to it would miss a server on
    another interface, and a port that is bound but not answering.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as the server does: a closed port is free at once
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def choose_port(host, port):
    """The port to serve on.

    Given with --port: that one, or stop with a clear message if it is taken. Not given: the first free port from
    FIRST_PORT upwards, so several webguis start side by side without any setup. (Webguis started at the same
    instant can still pick the same port; the later one then stops.)
    """
    if port is not None:
        if not port_is_free(host, port):
            sys.exit(f"Port {port} is already in use (another webgui?). Start without --port to take a free one.")
        return port
    for candidate in range(FIRST_PORT, FIRST_PORT + PORT_RANGE):
        if port_is_free(host, candidate):
            return candidate
    sys.exit(f"No free port from {FIRST_PORT} to {FIRST_PORT + PORT_RANGE - 1}. Start with --port <free port>.")
