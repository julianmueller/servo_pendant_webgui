"""
The ROS side of a webgui: its own rclpy context (domain ID, discovery), the node and the executor thread.

Shared webgui shell (from the nicegui-ros2-webgui skill): keep it identical across the webgui packages.

The domain ID and the discovery settings are fixed when a context is created, so changing them creates a new
context and a new node while the web server keeps running. Pages must therefore never keep the node: they read
`bridge.node` whenever they need it (it is None while reconnecting).
"""

import os
import threading

import rclpy
from rclpy.context import Context
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.signals import SignalHandlerOptions
from rclpy.utilities import get_rmw_implementation_identifier


class RosBridge:
    def __init__(self, node_factory, connection, ros_args):
        """
        node_factory(context=..., namespace=..., parameter_overrides=...) creates the app's node (a Node subclass
        that passes **kwargs on); ros_args: sys.argv (for --ros-args).
        """
        self._factory = node_factory
        self._ros_args = ros_args
        self._lock = threading.Lock()
        self._context = self._executor = self._thread = None
        self.node = None
        self.connection = connection
        self.generation = 0  # counts the (re)connections, e.g. to re-read data that belongs to an old node
        self._start()

    def _start(self, parameters=()):
        c = self.connection
        # Read by the middleware when the context is created (this process only)
        os.environ["ROS_DOMAIN_ID"] = str(c.domain_id)
        os.environ["ROS_AUTOMATIC_DISCOVERY_RANGE"] = c.discovery_range
        os.environ.pop("ROS_LOCALHOST_ONLY", None)  # deprecated, conflicts with the discovery range
        if c.static_peers.strip():
            os.environ["ROS_STATIC_PEERS"] = c.static_peers.strip()
        else:
            os.environ.pop("ROS_STATIC_PEERS", None)

        context = Context()
        # Ctrl-C is handled by the web server, which then calls shutdown()
        rclpy.init(
            args=self._ros_args,
            context=context,
            domain_id=c.domain_id,
            signal_handler_options=SignalHandlerOptions.NO,
        )
        # parameters changed while the old node ran are kept
        node = self._factory(context=context, namespace=c.namespace or None, parameter_overrides=list(parameters))
        executor = SingleThreadedExecutor(context=context)
        executor.add_node(node)
        thread = threading.Thread(target=self._spin, args=(executor, node), name="ros_spin", daemon=True)
        self._context, self._executor, self._thread = context, executor, thread
        thread.start()
        self.node = node
        self.generation += 1
        node.get_logger().info(f"ROS domain {c.domain_id}, discovery {c.discovery_range}")

    @staticmethod
    def _spin(executor, node):
        while executor.context.ok():
            try:
                executor.spin()
                return
            except ExternalShutdownException:
                return
            except Exception as e:  # keep ROS running after an error in a callback
                if not executor.context.ok():
                    return
                node.get_logger().error(f"callback failed: {e!r}")

    def _stop(self):
        node, self.node = self.node, None
        if self._executor is not None:
            self._executor.shutdown(timeout_sec=1.0)
        if node is not None:
            node.destroy_node()
        if self._context is not None:
            rclpy.try_shutdown(context=self._context)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._context = self._executor = self._thread = None

    def reconnect(self, connection):
        """New context with other settings. Blocking (about a second): call it with `await run.io_bound(...)`."""
        with self._lock:
            parameters = []
            if self.node is not None:
                parameters = [p for p in self.node.get_parameters_by_prefix("").values() if p.name != "use_sim_time"]
            self._stop()
            self.connection = connection
            self._start(parameters)

    def shutdown(self):
        with self._lock:
            self._stop()

    def info(self):
        """Facts about the connection for the settings (name -> text)."""
        node = self.node
        return {
            "Node": node.get_fully_qualified_name() if node else "reconnecting",
            "ROS distribution": os.environ.get("ROS_DISTRO", "unknown"),
            "Middleware": get_rmw_implementation_identifier(),
        }

    def other_nodes(self):
        """Names of the other nodes that are discovered, or None while reconnecting."""
        node = self.node
        if node is None:
            return None
        own = node.get_fully_qualified_name()
        try:
            names = node.get_node_names_and_namespaces()
        except Exception:  # the node is being destroyed
            return None
        return sorted({f"{ns.rstrip('/')}/{name}" for name, ns in names} - {own})


def call_service(client, request, timeout=5.0):
    """
    Service call from the web server side, without blocking it: `response = await run.io_bound(call_service, client,
    request)`. The node's executor thread completes the future; raises TimeoutError with a readable text.
    """
    if not client.wait_for_service(timeout_sec=min(timeout, 2.0)):
        raise TimeoutError(f"service {client.srv_name} is not available")
    done = threading.Event()
    future = client.call_async(request)
    future.add_done_callback(lambda _: done.set())
    if not done.wait(timeout):
        future.cancel()
        raise TimeoutError(f"service {client.srv_name} did not answer within {timeout:g} s")
    return future.result()
