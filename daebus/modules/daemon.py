import threading
import time
import json
from redis import Redis, ResponseError
from apscheduler.schedulers.background import BackgroundScheduler

from .context import set_daemon, set_context_type
from .request import PubSubRequest
from .response import PubSubResponse
from .broadcast import Broadcast
from .redis_client import redis_client
from .logger import logger as _default_logger


class Daebus:
    def __init__(self, name: str):
        self.name = name
        self.action_handlers = {}
        self.listen_handlers = {}
        self.background_tasks = []
        self.thread_tasks = {}  # Store thread tasks by name
        self.threads = {}       # Active thread instances
        self.redis = None
        self.pubsub = None
        self.scheduler = None
        self.logger = _default_logger.getChild(name)
        self.broadcast = Broadcast()
        self.cache = None
        self.request = None
        self.response = None
        self._running = False   # Flag to control thread lifecycle
        self.http = None        # HTTP endpoint if attached

        # Lifecycle hooks
        self._on_start_handlers = []

        # HTTP-specific request/response objects (set by HTTP handler)
        self.request_http = None
        self.response_http = None

    def on_start(self):
        """
        Register a function to run when the service starts up.
        This happens after all connections and threads are established.

        Example:
            @app.on_start()
            def initialize():
                # Perform initialization steps
                # Broadcast a startup message
                # Initialize cache
                logger.info("Service has started and is ready!")
        """
        def decorator(func):
            self._on_start_handlers.append(func)
            return func
        return decorator

    def action(self, action_name: str):
        """
        Register a handler for a specific action on the service's main channel.

        Args:
            action_name: The name of the action to handle
        """
        def decorator(func):
            self.action_handlers[action_name] = func
            return func
        return decorator

    def listen(self, channel: str):
        """
        Register a handler for messages on a specific channel.

        Args:
            channel: The channel name to listen to
        """
        def decorator(func):
            self.listen_handlers[channel] = func
            return func
        return decorator

    def background(self, name: str, interval: int):
        """
        Register a background task to run at regular intervals.

        Args:
            name: Name of the background task
            interval: Interval in seconds
        """
        def decorator(func):
            self.background_tasks.append((name, interval, func))
            return func
        return decorator

    def thread(self, name: str, auto_start: bool = True):
        """
        Register a long-running function to run in a dedicated background thread.

        The decorated function should contain its own event loop or blocking operation.
        It will be passed a 'running' function that returns the current state of the app.

        Args:
            name: Name for this thread task
            auto_start: Whether to start the thread automatically on app startup

        Example:

        @app.thread("socket_connection")
        def run_socket_client(running):
            while running():
                # Your long-running code here
                try:
                    # Connect to a socket
                    # Process data
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"Error in socket thread: {e}")
                    time.sleep(5)  # Backoff on error
        """
        def decorator(func):
            self.thread_tasks[name] = {
                "func": func,
                "auto_start": auto_start
            }
            return func
        return decorator

    def start_thread(self, name: str):
        """
        Manually start a registered thread by name.

        Args:
            name: Name of the thread task to start

        Returns:
            bool: True if thread was started, False if it doesn't exist or is already running
        """
        if name not in self.thread_tasks:
            self.logger.warning(f"Thread task '{name}' not found")
            return False

        if name in self.threads and self.threads[name].is_alive():
            self.logger.warning(f"Thread '{name}' is already running")
            return False

        # Create a wrapper that passes the running function
        def thread_wrapper():
            thread_func = self.thread_tasks[name]["func"]
            try:
                # Pass a function that returns the current running state
                thread_func(lambda: self._running)
            except Exception as e:
                self.logger.error(f"Unhandled error in thread '{name}': {e}")

        # Create and start the thread
        thread = threading.Thread(
            target=thread_wrapper, name=f"daebus_{name}", daemon=True)
        thread.start()
        self.threads[name] = thread
        self.logger.info(f"Started thread '{name}'")
        return True

    def stop_thread(self, name: str, timeout: float = 5.0):
        """
        Request a thread to stop and wait for it to terminate.

        This works by setting the running flag to False, which the thread
        should check periodically using the provided function.

        Args:
            name: Name of the thread to stop
            timeout: Maximum time to wait for thread to stop (seconds)

        Returns:
            bool: True if thread was stopped, False otherwise
        """
        if name not in self.threads:
            self.logger.warning(f"Thread '{name}' not found or not running")
            return False

        thread = self.threads[name]
        if not thread.is_alive():
            del self.threads[name]
            return True

        # Set a temporary flag for this thread
        temp_flag = {"running": False}

        # Create a wrapper that returns the temporary flag
        def temp_wrapper():
            return temp_flag["running"]

        # Monkey patch the running function in the thread
        # (This will only work if the thread actually checks the running state)
        self.thread_tasks[name]["func"].__globals__["running"] = temp_wrapper

        # Wait for the thread to terminate
        thread.join(timeout)

        # Check if it's still alive
        if thread.is_alive():
            self.logger.warning(
                f"Thread '{name}' did not stop within {timeout} seconds")
            return False

        del self.threads[name]
        return True

    def attach(self, component):
        """
        Attach a component (like HTTP endpoints) to this Daebus instance.

        Args:
            component: The component to attach

        Returns:
            The component, for chaining
        """
        if hasattr(component, 'attach'):
            component.attach(self)
            return component
        raise TypeError(
            f"Cannot attach component of type {type(component)}, missing attach method")

    def route(self, path, methods=None):
        """
        Register an HTTP route handler if an HTTP component is attached.

        Args:
            path: The URL path to handle
            methods: List of HTTP methods to accept (default: ['GET'])

        Returns:
            A decorator to wrap the route handler
        """
        if not self.http:
            raise RuntimeError("No HTTP component attached. "
                               "Use app.attach(DaebusHttp()) before defining routes.")

        return self.http.route(path, methods)

    def run(self, service: str, debug: bool = False, redis_host: str = 'localhost', redis_port: int = 6379):
        # init
        set_daemon(self)
        self.service = service
        self.redis = Redis(host=redis_host, port=redis_port,
                           decode_responses=True)
        self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        self.cache = self.redis
        self._running = True

        # Start HTTP server if attached
        if self.http:
            self.http.start()
            self.logger.info(f"Started HTTP server on port {self.http.port}")

        # Start thread tasks that are configured for auto-start
        for name, task_info in self.thread_tasks.items():
            if task_info.get("auto_start", True):
                self.start_thread(name)

        if self.thread_tasks:
            self.logger.info(
                f"Registered {len(self.thread_tasks)} thread tasks")

        # scheduler
        self.scheduler = BackgroundScheduler()
        for name, sec, func in self.background_tasks:
            self.scheduler.add_job(func, 'interval', seconds=sec, id=name)
        self.scheduler.start()
        self.logger.info(
            f"Started scheduler with {len(self.background_tasks)} jobs")

        # Main service channel handler for action routing
        if self.action_handlers:
            self.logger.info(
                f"Setting up main service channel handler for {len(self.action_handlers)} actions")

            # Create a wrapped handler for the pubsub that properly handles context type
            def wrapped_main_service_handler(message):
                # Set context type to pub/sub for this thread
                set_context_type('pubsub')
                try:
                    self._main_service_handler(message)
                finally:
                    # Always reset context type
                    set_context_type(None)

            # Subscribe to the main service channel with wrapped handler
            self.pubsub.subscribe(**{service: wrapped_main_service_handler})
            self.logger.info(f"Subscribed to main service channel: {service}")

            # Start the main service handler thread
            service_thread = threading.Thread(
                target=self._pubsub_listener, daemon=True)
            service_thread.start()

        # Regular channel listeners
        channels_to_subscribe = {}
        for channel, handler in self.listen_handlers.items():
            # Create a wrapped handler that sets the context type
            def wrapped_handler(message, h=handler):
                # Set context type to pub/sub for this thread
                set_context_type('pubsub')
                try:
                    return h(json.loads(message["data"]))
                finally:
                    # Always reset context type
                    set_context_type(None)

            channels_to_subscribe[channel] = wrapped_handler
            self.logger.info(f"Preparing to subscribe to channel: {channel}")

        # Subscribe to all explicit channels
        if channels_to_subscribe:
            other_pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
            other_pubsub.subscribe(**channels_to_subscribe)
            channel_thread = threading.Thread(
                target=lambda: self._pubsub_listener(other_pubsub), daemon=True)
            channel_thread.start()
            self.logger.info(
                f"Subscribed to {len(channels_to_subscribe)} additional channels")

        # Run on_start handlers if any exist
        if self._on_start_handlers:
            self.logger.info(
                f"Running {len(self._on_start_handlers)} on_start handlers")
            for handler in self._on_start_handlers:
                try:
                    handler()
                except Exception as e:
                    self.logger.error(f"Error in on_start handler: {e}")

        # keep main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            # Signal all threads to stop
            self._running = False
            # Wait for threads to terminate (give them a chance to clean up)
            for name, thread in list(self.threads.items()):
                self.logger.info(
                    f"Waiting for thread '{name}' to terminate...")
                thread.join(2.0)  # Wait up to 2 seconds per thread
                if thread.is_alive():
                    self.logger.warning(
                        f"Thread '{name}' did not terminate gracefully")
            # Shutdown scheduler
            self.scheduler.shutdown()
            self.pubsub.close()

    def _main_service_handler(self, message):
        """
        Handle messages on the main service channel and route to the appropriate action handler.
        """
        try:
            data = json.loads(message["data"])

            # Extract the action from the payload
            action = data.get("action")
            if not action:
                self.logger.warning(
                    f"Received message without action field: {data}")
                return

            # Look up the handler for this action
            handler = self.action_handlers.get(action)
            if not handler:
                self.logger.warning(f"No handler for action '{action}'")
                return

            # Set up request and response objects
            self.request = PubSubRequest(data)
            self.response = PubSubResponse(self.redis, self.request)

            self.logger.debug(f"Routing action '{action}' with data: {data}")
            handler()

        except Exception as e:
            self.logger.error(f"Error in main service handler: {e}")

    def _pubsub_listener(self, pubsub_instance=None):
        """Listen for messages on the subscribed channels"""
        ps = pubsub_instance or self.pubsub

        for message in ps.listen():
            # The message handlers are automatically called by pubsub
            # This loop just keeps the thread running
            pass
