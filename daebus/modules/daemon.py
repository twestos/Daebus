import threading
import time
import json
import concurrent.futures
import traceback
from redis import Redis
from apscheduler.schedulers.background import BackgroundScheduler
from .context import set_daemon, set_context_type
from .pubsub import PubSubResponse, PubSubRequest, PubSubBroadcast
from .logger import logger as _default_logger
from .workflow import WorkflowRequest, WorkflowResponse  # Import the new workflow classes


class Daebus:
    def __init__(self, name: str, max_workers: int = 10):
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
        self.broadcast = PubSubBroadcast()
        self.cache = None
        self.request = None
        self.response = None
        self._running = False   # Flag to control thread lifecycle
        self.http = None        # HTTP endpoint if attached
        self.websocket = None   # WebSocket endpoint if attached
        self.max_workers = max_workers  # Maximum number of worker threads for message processing
        self.thread_pool = None  # Will be initialized in run()
        self.workflow_handlers = {}  # New dict for workflow handlers

        # Lifecycle hooks
        self._on_start_handlers = []

        # HTTP-specific request/response objects (set by HTTP handler)
        self.request_http = None
        self.response_http = None
        
        # WebSocket-specific request/response objects (set by WebSocket handler)
        self.request_ws = None
        self.response_ws = None

    def register_blueprint(self, blueprint):
        """
        Register a blueprint with the application.
        
        This registers all the actions, routes, listen handlers, socket handlers,
        background tasks, thread tasks and on_start handlers from the blueprint
        with the main application.
        
        Args:
            blueprint: The Blueprint instance to register
        
        Returns:
            self: For method chaining
        """
        # Register action handlers
        for action_name, handler in blueprint.action_handlers.items():
            if action_name in self.action_handlers:
                self.logger.warning(f"Action '{action_name}' already registered, overriding")
            self.action_handlers[action_name] = handler
            self.logger.debug(f"Registered action handler '{action_name}' from blueprint '{blueprint.name}'")
        
        # Register routes if HTTP component is attached
        if self.http:
            for path, route_info in blueprint.routes.items():
                if path in self.http.routes:
                    self.logger.warning(f"Route '{path}' already registered, overriding")
                self.http.routes[path] = route_info
                self.logger.debug(f"Registered route '{path}' from blueprint '{blueprint.name}'")
        elif blueprint.routes:
            self.logger.warning(f"Blueprint '{blueprint.name}' has routes but no HTTP component is attached")
        
        # Register listen handlers
        for channel, handler in blueprint.listen_handlers.items():
            if channel in self.listen_handlers:
                self.logger.warning(f"Listen handler for channel '{channel}' already registered, overriding")
            self.listen_handlers[channel] = handler
            self.logger.debug(f"Registered listen handler for channel '{channel}' from blueprint '{blueprint.name}'")
        
        # Register socket handlers if WebSocket component is attached
        if self.websocket:
            for message_type, handler in blueprint.socket_handlers.items():
                if message_type in self.websocket.message_handlers:
                    self.logger.warning(f"Socket handler for message type '{message_type}' already registered, overriding")
                self.websocket.message_handlers[message_type] = handler
                self.logger.debug(f"Registered socket handler for message type '{message_type}' from blueprint '{blueprint.name}'")
        elif blueprint.socket_handlers:
            self.logger.warning(f"Blueprint '{blueprint.name}' has socket handlers but no WebSocket component is attached")
        
        # Register background tasks
        for task in blueprint.background_tasks:
            name, interval, func = task
            # Check for name conflicts
            for existing_name, _, _ in self.background_tasks:
                if existing_name == name:
                    self.logger.warning(f"Background task '{name}' already registered, overriding")
                    # Remove the existing task with the same name
                    self.background_tasks = [t for t in self.background_tasks if t[0] != name]
                    break
            self.background_tasks.append(task)
            self.logger.debug(f"Registered background task '{name}' from blueprint '{blueprint.name}'")
        
        # Register thread tasks
        for name, task_info in blueprint.thread_tasks.items():
            if name in self.thread_tasks:
                self.logger.warning(f"Thread task '{name}' already registered, overriding")
            self.thread_tasks[name] = task_info
            self.logger.debug(f"Registered thread task '{name}' from blueprint '{blueprint.name}'")
        
        # Register on_start handlers
        for handler in blueprint.on_start_handlers:
            self._on_start_handlers.append(handler)
            self.logger.debug(f"Registered on_start handler from blueprint '{blueprint.name}'")
        
        return self

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

    def socket(self, message_type: str):
        """
        Register a handler for a specific WebSocket message type.

        Args:
            message_type: The type of message to handle

        Returns:
            A decorator to wrap the message handler

        Example:
            @app.socket("chat_message")
            def handle_chat_message(req, sid):
                # req is the raw message data
                # sid is the client ID (session ID)
                
                message = req.get('message', '')
                print(f"Got message from {sid}: {message}")
                
                # Return a response (will be sent automatically)
                return {"status": "received"}
        """
        if not self.websocket:
            raise RuntimeError("No WebSocket component attached. "
                               "Use app.attach(DaebusWebSocket()) before defining socket handlers.")

        return self.websocket.socket(message_type)
        
    def socket_connect(self):
        """
        Register a handler for WebSocket connect events.
        
        This is a shorthand for @app.socket('connect')
        
        Example:
            @app.socket_connect()
            def on_connect(req, sid):
                print(f"Client {sid} connected")
                return {"status": "connected"}
        """
        if not self.websocket:
            raise RuntimeError("No WebSocket component attached. "
                               "Use app.attach(DaebusWebSocket()) before defining socket handlers.")
                               
        return self.websocket.socket_connect()
        
    def socket_disconnect(self):
        """
        Register a handler for WebSocket disconnect events.
        
        This is a shorthand for @app.socket('disconnect')
        
        Example:
            @app.socket_disconnect()
            def on_disconnect(req, sid):
                print(f"Client {sid} disconnected")
        """
        if not self.websocket:
            raise RuntimeError("No WebSocket component attached. "
                               "Use app.attach(DaebusWebSocket()) before defining socket handlers.")
                               
        return self.websocket.socket_disconnect()
        
    def socket_register(self):
        """
        Register a handler for WebSocket client registration events.
        
        This is a shorthand for @app.socket('register')
        
        Example:
            @app.socket_register()
            def on_register(req, sid):
                user_data = req.get('user_data', {})
                print(f"Client {sid} registered with data: {user_data}")
                return {"status": "registered", "client_id": sid}
        """
        if not self.websocket:
            raise RuntimeError("No WebSocket component attached. "
                               "Use app.attach(DaebusWebSocket()) before defining socket handlers.")
                               
        return self.websocket.socket_register()

    def workflow(self, workflow_name: str):
        """
        Register a handler for a specific workflow type.
        
        Workflows allow for multi-step interactions between services where
        responses may be sent multiple times and additional input might be
        required during execution.
        
        Args:
            workflow_name: The name of the workflow to handle
            
        Example:
            @app.workflow("connect_wifi")
            def connect_to_wifi():
                ssid = request.payload.get("ssid")
                logger.info(f"Connecting to WiFi network: {ssid}")
                
                # Send initial status
                response.send({"status": "connecting", "message": f"Connecting to {ssid}..."})
                
                # Check if we need a password
                if needs_password(ssid):
                    response.send({"status": "need_password", "message": "Please provide WiFi password"})
                    
                    # The workflow will continue when client sends a message with the password
                    # We'll handle that in the next request
                    
                # When done, send the final response
                response.send({"status": "connected", "message": "Successfully connected"}, final=True)
        """
        def decorator(func):
            self.workflow_handlers[workflow_name] = func
            return func
        return decorator

    def run(self, service: str, debug: bool = False, redis_host: str = 'localhost', redis_port: int = 6379):
        # init
        set_daemon(self)
        self.service = service
        self.redis = Redis(host=redis_host, port=redis_port,
                           decode_responses=True)
        self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        self.cache = self.redis
        self._running = True
        
        # Initialize thread pool for concurrent message processing
        self.thread_pool = self._create_thread_pool()
        self.logger.info(f"Initialized thread pool with {self.max_workers} workers")

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
                # Submit the message to the thread pool for processing
                self._submit_to_thread_pool(self._process_message, message)

            # Subscribe to the main service channel with wrapped handler
            self.pubsub.subscribe(**{service: wrapped_main_service_handler})
            self.logger.info(f"Subscribed to main service channel: {service}")

            # Start the main service handler thread
            service_thread = threading.Thread(
                target=self._pubsub_listener, daemon=True)
            service_thread.start()

        # Workflow channel handler for workflow messages
        if self.workflow_handlers:
            self.logger.info(
                f"Setting up workflow channel handler for {len(self.workflow_handlers)} workflows")
                
            # Create a wrapped handler for workflow messages
            def wrapped_workflow_handler(message):
                # Submit the workflow message to the thread pool
                self._submit_to_thread_pool(self._process_workflow, message)
            
            # Subscribe to the service's workflow channel
            workflow_channel = f"{service}.workflows"
            workflow_pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
            workflow_pubsub.subscribe(**{workflow_channel: wrapped_workflow_handler})
            self.logger.info(f"Subscribed to workflow channel: {workflow_channel}")
            
            # Start the workflow handler thread
            workflow_thread = threading.Thread(
                target=lambda: self._pubsub_listener(workflow_pubsub), daemon=True)
            workflow_thread.start()

        # Regular channel listeners
        channels_to_subscribe = {}
        for channel, handler in self.listen_handlers.items():
            # Create a wrapped handler that submits to thread pool
            def wrapped_handler(message, h=handler):
                # Submit the message handler to the thread pool
                self._submit_to_thread_pool(self._process_listen_message, message, h)

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
                    # Set context type to pub/sub for consistency with action handlers
                    set_context_type('pubsub')
                    handler()
                except Exception as e:
                    self.logger.error(f"Error in on_start handler: {e}")
                finally:
                    # Always reset the context type
                    set_context_type(None)

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
            
            # Shutdown thread pool
            self.logger.info("Shutting down thread pool...")
            self.thread_pool.shutdown(wait=True, cancel_futures=True)
            
            # Shutdown scheduler
            self.scheduler.shutdown()
            self.pubsub.close()

    def _process_message(self, message):
        """
        Process a message in its own thread.
        Each message gets its own request and response instances.
        """
        try:
            # Set context type for this thread
            set_context_type('pubsub')
            
            # Parse the message data from JSON
            data = json.dumps(message["data"]) if isinstance(message["data"], dict) else message["data"]
            data = json.loads(data)

            # Extract the action from the payload
            action = data.get("action")
            if not action:
                self.logger.debug(f"Received message without action field")
                return

            # Look up the handler for this action
            handler = self.action_handlers.get(action)
            if not handler:
                self.logger.debug(f"No handler for action '{action}'")
                return

            # Set up thread-local request and response objects
            # Instead of modifying self.request/response, create local instances
            request = PubSubRequest(data)
            response = PubSubResponse(self.redis, request)
            
            # Also set the daemon's request/response in case proxy lookups fall back to them
            # This ensures backward compatibility with code that doesn't use the proxy pattern
            self.request = request
            self.response = response
            
            # Set thread-local request/response for this context
            from .context import _set_thread_local_request, _set_thread_local_response
            _set_thread_local_request(request)
            _set_thread_local_response(response)
            
            # Call the handler with the thread-local context
            try:
                handler()
            except AttributeError as e:
                if "'NoneType' object has no attribute 'success'" in str(e):
                    # This is a common error in tests, just log it at debug level
                    self.logger.debug(f"Response method not available: {e}")
                else:
                    # For other attribute errors, still log them as errors
                    self.logger.error(f"Error in action handler: {e}")
                    
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")
        finally:
            # Clean up thread-local storage
            from .context import _clear_thread_local_storage
            _clear_thread_local_storage()
            
            # Clear daemon's request/response to prevent leaking between threads
            self.request = None
            self.response = None

    def _process_listen_message(self, message, handler):
        """Process a message from a subscribed channel in its own thread"""
        try:
            # Set context type for this thread
            set_context_type('pubsub')
            
            # Parse the data
            data = json.dumps(message["data"]) if isinstance(message["data"], dict) else message["data"]
            data = json.loads(data)
            
            # Create request/response objects for the thread
            request = PubSubRequest(data)
            response = PubSubResponse(self.redis, request)
            
            # Set on daemon for backward compatibility
            self.request = request
            self.response = response
            
            # Set thread-local request/response for this context
            from .context import _set_thread_local_request, _set_thread_local_response
            _set_thread_local_request(request)
            _set_thread_local_response(response)
            
            # Call the handler
            try:
                handler(data)
            except AttributeError as e:
                if "'NoneType' object has no attribute 'success'" in str(e):
                    # This is a common error in tests, just log it at debug level
                    self.logger.debug(f"Response method not available: {e}")
                else:
                    # For other attribute errors, still log them as errors
                    self.logger.error(f"Error in channel handler: {e}")
            
        except Exception as e:
            self.logger.error(f"Error processing channel message: {e}")
        finally:
            # Clean up thread-local storage
            from .context import _clear_thread_local_storage
            _clear_thread_local_storage()
            
            # Clear daemon's request/response to prevent leaking between threads
            self.request = None
            self.response = None

    def _process_workflow(self, message):
        """
        Process a workflow message in its own thread.
        
        This handles both initial workflow requests and subsequent messages.
        """
        try:
            # Set context type for this thread 
            set_context_type('pubsub')  # Use pubsub context type for workflows
            
            # Parse the message data from JSON
            data = json.dumps(message["data"]) if isinstance(message["data"], dict) else message["data"]
            data = json.loads(data)
            
            # Extract workflow ID and workflow name
            workflow_id = data.get("workflow_id")
            workflow_name = data.get("workflow")
            
            if not workflow_id:
                self.logger.warning("Received workflow message without workflow_id")
                return
                
            # Create workflow request and response objects
            request = WorkflowRequest(data)
            response = WorkflowResponse(self.redis, request)
            
            # Set thread-local request/response for this context
            from .context import _set_thread_local_request, _set_thread_local_response
            _set_thread_local_request(request)
            _set_thread_local_response(response)
            
            # For new workflow requests, use the workflow handler
            if workflow_name and workflow_name in self.workflow_handlers:
                handler = self.workflow_handlers[workflow_name]
                try:
                    handler()
                except Exception as e:
                    self.logger.error(f"Error in workflow handler: {e}")
                    self.logger.error(traceback.format_exc())
                    # Send an error response
                    response.send({"status": "error", "error": str(e)}, final=True)
            else:
                # For subsequent messages in an existing workflow,
                # there's no specific handler to call - the workflow
                # is maintained by the service itself and should check
                # for new messages
                self.logger.debug(f"Received update for workflow {workflow_id}")
                # We could notify some kind of workflow manager here if needed
            
        except Exception as e:
            self.logger.error(f"Error processing workflow message: {e}")
            self.logger.error(traceback.format_exc())
        finally:
            # Clean up thread-local storage
            from .context import _clear_thread_local_storage
            _clear_thread_local_storage()

    def _pubsub_listener(self, pubsub_instance=None):
        """Listen for messages on the subscribed channels"""
        ps = pubsub_instance or self.pubsub

        for message in ps.listen():
            # The message handlers are automatically called by pubsub
            # This loop just keeps the thread running
            pass

    def _create_thread_pool(self):
        """
        Create a thread pool for concurrent message processing.
        This is in a separate method to make it easier to test.
        """
        return concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="daebus_worker"
        )
        
    def _submit_to_thread_pool(self, func, *args):
        """
        Submit a task to the thread pool with protection against pool exhaustion.
        
        If the thread pool's work queue is full, this will log a warning and
        retry with exponential backoff.
        """
        retries = 3
        backoff_time = 0.05  # Start with 50ms backoff
        
        for attempt in range(retries):
            try:
                # Check if we're shutting down
                if not self._running:
                    self.logger.debug("Not submitting task because daemon is shutting down")
                    return None
                
                # Submit the task to the thread pool
                return self.thread_pool.submit(func, *args)
                
            except concurrent.futures.BrokenExecutor:
                # Thread pool is broken, create a new one
                self.logger.warning("Thread pool is broken, creating a new one")
                self.thread_pool.shutdown(wait=False)
                self.thread_pool = self._create_thread_pool()
                
            except Exception as e:
                # If we can't submit the task, log and retry with backoff
                if attempt < retries - 1:
                    self.logger.warning(f"Failed to submit task to thread pool: {e}, "
                                       f"retrying in {backoff_time:.3f}s")
                    time.sleep(backoff_time)
                    backoff_time *= 2  # Exponential backoff
                else:
                    self.logger.error(f"Failed to submit task to thread pool after {retries} attempts: {e}")
                    return None
                    
        return None
