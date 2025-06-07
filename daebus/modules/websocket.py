import json
import traceback
import asyncio
import uuid
import time
from typing import Dict, Any, Callable, List, Optional, Union, Set
import asyncio
from collections import defaultdict, deque

import websockets
from websockets.server import WebSocketServerProtocol
from websockets.exceptions import ConnectionClosed

from .logger import logger as _default_logger


class WebSocketRequest:
    """
    WebSocket request object that provides a consistent interface for message handlers.
    """
    def __init__(self, client_id: str, message: Dict[str, Any], websocket: WebSocketServerProtocol):
        self.client_id = client_id
        self.payload = message
        self.message_type = message.get('type')
        self.data = message.get('data', {})
        self.websocket = websocket


class WebSocketResponse:
    """
    WebSocket response object that provides methods to send messages back to clients.
    """
    def __init__(self, websocket: WebSocketServerProtocol, client_id: str):
        self.websocket = websocket
        self.client_id = client_id

    async def send(self, data: Any, message_type: str = "response", target_sid: Optional[str] = None) -> None:
        """
        Send a message to the client.

        Args:
            data: The data to send
            message_type: The type of message (default: "response")
            target_sid: Optional client ID to send to. If provided, sends to that client 
                      instead of the current one. The client must be connected.
        """
        message = {
            "type": message_type,
            "data": data
        }
        
        if target_sid is not None and target_sid != self.client_id:
            # Get the daemon to find the appropriate websocket server
            from .context import get_daemon
            daemon = get_daemon()
            if daemon and daemon.websocket:
                # Find the target client and send to it
                if target_sid in daemon.websocket.clients:
                    target_ws = daemon.websocket.clients[target_sid]
                    await target_ws.send(json.dumps(message))
                else:
                    # Log a warning if client doesn't exist
                    from .logger import logger
                    logger.warning(f"Client {target_sid} not found, message not sent")
        else:
            # Send to the current client
            await self.websocket.send(json.dumps(message))
        
    async def error(self, err: Union[Exception, str], message_type: str = "error", target_sid: Optional[str] = None) -> None:
        """
        Send an error message to the client.
        
        Args:
            err: The error that occurred (Exception or string)
            message_type: The type of message (default: "error")
            target_sid: Optional client ID to send to. If provided, sends to that client
                      instead of the current one. The client must be connected.
        """
        error_msg = str(err)
        error_data = {"error": error_msg}
        await self.send(error_data, message_type, target_sid)


class DaebusWebSocket:
    """
    WebSocket server for Daebus that integrates with the HTTP server.
    """
    def __init__(self, port: Optional[int] = None):
        self.port = port
        self.daemon = None
        self.is_running = False
        self.server = None
        self.message_handlers: Dict[str, Callable] = {}
        self.connection_handlers: List[Callable] = []
        self.disconnection_handlers: List[Callable] = []
        self.clients: Dict[str, WebSocketServerProtocol] = {}
        self.client_metadata: Dict[str, Dict[str, Any]] = {}  # Store extra client information
        self.client_counter = 0
        self.logger = _default_logger.getChild('websocket')
        self.client_id_generator = None  # Custom client ID generator function
        
        # Rate limiting settings
        self.rate_limit_enabled = False
        self.rate_limit_messages = 60  # Max messages per minute
        self.rate_limit_window = 60    # Window size in seconds
        self.rate_limit_counters = defaultdict(lambda: deque(maxlen=1000))  # Client message timestamps
        
        # Note: Batched broadcasting removed as it was unused
        
        # Actual port being used (may differ from self.port if there's a conflict)
        self.actual_port = None

    def attach(self, daemon: Any) -> None:
        """
        Attach to a Daebus instance.

        Args:
            daemon: The Daebus instance to attach to
        """
        self.daemon = daemon
        
        # Store self on the daemon
        daemon.websocket = self
        
        if daemon.http:
            # HTTP server exists - use a different port to avoid conflicts
            if self.port is None:
                # Use HTTP port + 1 as default
                self.port = daemon.http.port + 1
                self.logger.info(f"WebSocket will use port {self.port} (HTTP port + 1)")
            elif self.port == daemon.http.port:
                # Same port specified - use different port
                self.port = daemon.http.port + 1
                self.logger.warning(f"WebSocket port conflict detected. Using port {self.port} instead of {daemon.http.port}")
            
            self.logger.info("For same-port WebSocket support, connect to:")
            self.logger.info(f"  HTTP:      http://your-server:{daemon.http.port}")
            self.logger.info(f"  WebSocket: ws://your-server:{self.port}")
        else:
            # No HTTP server - require explicit port configuration
            if self.port is None:
                raise RuntimeError(
                    "WebSocket port must be specified when no HTTP server is attached. "
                    "Use DaebusWebSocket(port=YOUR_PORT) or attach an HTTP server first."
                )
        
        self.actual_port = self.port
        
        # Start the WebSocket server
        self._start_websocket_server(daemon)

    def _start_websocket_server(self, daemon: Any) -> None:
        """
        Start the WebSocket server.
        """
        # Add a thread for the WebSocket server
        @daemon.thread("websocket_server", auto_start=True)
        def run_websocket_server(running):
            async def websocket_main():
                """Main async function for the WebSocket server"""
                server = None
                
                try:
                    # Start the WebSocket server
                    server = await websockets.serve(
                        self._handle_connection, 
                        "0.0.0.0", 
                        self.port
                    )
                    
                    # Store server reference for external access
                    self.server = server
                    
                    # Only mark as running AFTER the server is successfully started
                    self.is_running = True
                    
                    self.logger.info(f"WebSocket server listening on port {self.port}")
                    
                    # No additional tasks needed for startup
                    
                    # Keep the server running until the daemon is shut down
                    try:
                        while running() and self.is_running:
                            await asyncio.sleep(1)
                    finally:
                        # Mark as not running first
                        self.is_running = False
                        
                        # Close the server
                        if server is not None:
                            server.close()
                            await server.wait_closed()
                        
                except Exception as e:
                    self.logger.error(f"Error in WebSocket server: {e}")
                    import traceback
                    self.logger.debug(traceback.format_exc())
                    raise
                finally:
                    self.is_running = False
                    
            # Run the async main function using asyncio.run()
            try:
                asyncio.run(websocket_main())
            except Exception as e:
                self.logger.error(f"Failed to start WebSocket server: {e}")
                import traceback
                self.logger.debug(traceback.format_exc())
            finally:
                # Final cleanup - disconnect clients using a separate event loop
                try:
                    client_count = self.disconnect_all_clients()
                    if client_count > 0:
                        self.logger.info(f"Disconnected {client_count} WebSocket clients during shutdown")
                except Exception as e:
                    self.logger.debug(f"Error disconnecting clients during final cleanup: {e}")
                    
                self.logger.info("WebSocket server stopped")

    def socket(self, message_type: str):
        """
        Register a handler for a specific message type.

        Args:
            message_type: The type of message to handle

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
        def decorator(func):
            self.message_handlers[message_type] = func
            return func
        return decorator
    
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
        return self.socket('connect')
    
    def socket_disconnect(self):
        """
        Register a handler for WebSocket disconnect events.
        
        This is a shorthand for @app.socket('disconnect')
        
        Example:
            @app.socket_disconnect()
            def on_disconnect(req, sid):
                print(f"Client {sid} disconnected")
        """
        return self.socket('disconnect')
    
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
        return self.socket('register')

    def on_connect(self, func):
        """Register a handler for new WebSocket connections."""
        self.connection_handlers.append(func)
        return func

    def on_disconnect(self, func):
        """Register a handler for WebSocket disconnections."""
        self.disconnection_handlers.append(func)
        return func

    def set_client_id_generator(self, generator_func: Callable[[WebSocketServerProtocol, str], str]) -> None:
        """
        Set a custom function to generate client IDs when clients connect.
        
        The generator function should accept the WebSocket connection and path,
        and return a string ID for the client.
        
        Args:
            generator_func: Function that takes (websocket, path) and returns a client ID string
            
        Example:
            def custom_id_generator(websocket, path):
                # Generate an ID based on remote address and a timestamp
                addr = websocket.remote_address[0]
                timestamp = int(time.time())
                return f"client_{addr}_{timestamp}"
                
            websocket.set_client_id_generator(custom_id_generator)
        """
        self.client_id_generator = generator_func
        
    def generate_client_id(self, websocket: WebSocketServerProtocol, path: str) -> str:
        """
        Generate a client ID for a new connection.
        
        If a custom generator is set, it will be used. Otherwise, a UUID
        will be generated.
        
        Args:
            websocket: The WebSocket connection
            path: The connection path
            
        Returns:
            str: The generated client ID
        """
        # Use custom generator if set
        if self.client_id_generator:
            try:
                client_id = self.client_id_generator(websocket, path)
                if client_id and isinstance(client_id, str):
                    return client_id
                self.logger.warning("Custom client ID generator returned invalid ID, using default")
            except Exception as e:
                self.logger.error(f"Error in custom client ID generator: {e}")
                self.logger.warning("Using default client ID generator")
        
        # Default UUID generator
        return f"user_{str(uuid.uuid4())}"

    def get_websocket_port(self) -> Optional[int]:
        """
        Get the actual port the WebSocket server is configured to use.
        
        This may be different from the originally requested port if there was a conflict
        with the HTTP server.
        
        Returns:
            int: The WebSocket server port, or None if not configured
        """
        return self.actual_port

    # Core methods for sending messages

    async def broadcast_to_all_async(self, data: Any, message_type: str = "broadcast") -> int:
        """
        Broadcast a message to all connected clients asynchronously.

        Args:
            data: The data to send
            message_type: The type of message (default: "broadcast")
            
        Returns:
            int: Number of clients that received the message successfully
        """
        message = {
            "type": message_type,
            "data": data
        }
        message_json = json.dumps(message)
        
        # Count successful sends
        success_count = 0
        
        # Send to all clients
        for client_id, websocket in list(self.clients.items()):
            try:
                await websocket.send(message_json)
                success_count += 1
            except ConnectionClosed:
                # Connection is already closed, remove client
                self.logger.debug(f"Client {client_id} connection closed, removing from clients list")
                self.clients.pop(client_id, None)
            except Exception as e:
                self.logger.warning(f"Failed to broadcast to client {client_id}: {e}")
                
        return success_count

    def _get_current_response(self) -> WebSocketResponse:
        """
        Get the current WebSocket response object for the current thread context.
        
        Returns:
            The WebSocketResponse object
        
        Raises:
            RuntimeError: If not in a WebSocket context or no response object is available
        """
        from .context import get_context_type, _get_thread_local_response
        
        # Check if we're in a WebSocket context
        context_type = get_context_type()
        if context_type != 'websocket':
            raise RuntimeError(f"Not in a WebSocket context (current: {context_type})")
            
        # Get the response object
        response = _get_thread_local_response()
        if not response:
            if self.daemon and self.daemon.response_ws:
                response = self.daemon.response_ws
            else:
                raise RuntimeError("No WebSocket response object available")
                
        return response

    def send(self, data: Any, message_type: str = "response") -> None:
        """
        Send a message to the current client.
        
        Args:
            data: The data to send
            message_type: The type of message (default: "response")
            
        Note: This method requires being called from within a WebSocket message handler context.
        For sending messages from callbacks or other contexts, use safe_broadcast_to_all() or 
        safe_send_to_client() instead.
        """
        try:
            response = self._get_current_response()
        except RuntimeError as e:
            self.logger.error(f"Cannot send message: {e}")
            self.logger.error("Use safe_broadcast_to_all() or safe_send_to_client() for sending from callbacks")
            return
        
        # Check if we're already in an event loop
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # We're in an event loop, create a task
                loop.create_task(response.send(data, message_type))
                return
        except RuntimeError:
            # No running event loop, use asyncio.run
            pass
            
        # No event loop running, create one
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(response.send(data, message_type))
        finally:
            loop.close()
        
    def broadcast_to_all(self, data: Any, message_type: str = "broadcast") -> int:
        """
        Broadcast a message to all connected clients.
        
        Args:
            data: The data to send
            message_type: The type of message (default: "broadcast")
            
        Returns:
            int: Number of clients the message was successfully sent to
        """
        # Check if we're already in an event loop
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # We're in an event loop, create a task
                loop.create_task(self.broadcast_to_all_async(data, message_type))
                return len(self.clients)
        except RuntimeError:
            # No running event loop, use a new one
            pass
            
        # No event loop running, create one
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self.broadcast_to_all_async(data, message_type))
            return len(self.clients)
        finally:
            loop.close()
        
    async def send_to_client_async(self, client_id: str, data: Any, message_type: str = "message") -> bool:
        """
        Send a message to a specific client asynchronously.
        
        Args:
            client_id: The ID of the client to send to
            data: The data to send
            message_type: The type of message (default: "message")
            
        Returns:
            bool: True if the message was sent, False if the client is not connected
        """
        if client_id not in self.clients:
            self.logger.warning(f"Cannot send to client {client_id}: Client not connected")
            return False
            
        message = {
            "type": message_type,
            "data": data
        }
        message_json = json.dumps(message)
        
        try:
            await self.clients[client_id].send(message_json)
            return True
        except Exception as e:
            self.logger.warning(f"Failed to send to client {client_id}: {e}")
            return False
    
    def send_to_client(self, client_id: str, data: Any, message_type: str = "message") -> bool:
        """
        Send a message to a specific client.
        
        Args:
            client_id: The ID of the client to send to
            data: The data to send
            message_type: The type of message (default: "message")
            
        Returns:
            bool: True if the message was sent, False if the client is not connected
        """
        # Check if the client is connected
        if client_id not in self.clients:
            self.logger.warning(f"Cannot send to client {client_id}: Client not connected")
            return False
            
        # Check if we're already in an event loop
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # We're in an event loop, create a task
                task = loop.create_task(self.send_to_client_async(client_id, data, message_type))
                # We can't directly return the result of the task since it's async
                # Instead, we'll just return True to indicate the message was queued
                return True
        except RuntimeError:
            # No running event loop, use a new one
            pass
            
        # No event loop running, create one
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.send_to_client_async(client_id, data, message_type))
        finally:
            loop.close()

    def safe_send_to_client(self, client_id: str, data: Any, message_type: str = "message") -> bool:
        """
        Thread-safe method to send a message to a specific client.
        
        This method is specifically designed to be called from callbacks,
        background tasks, or other non-WebSocket contexts.
        
        Args:
            client_id: The ID of the client to send to
            data: The data to send
            message_type: The type of message (default: "message")
            
        Returns:
            bool: True if the message was sent, False if the client is not connected
        """
        if not self.is_running:
            self.logger.debug("WebSocket server not running")
            return False
            
        if client_id not in self.clients:
            self.logger.warning(f"Cannot send to client {client_id}: Client not connected")
            return False
            
        try:
            # First try using the daemon's thread pool if available and the daemon is fully initialized
            if (self.daemon and 
                hasattr(self.daemon, 'thread_pool') and 
                self.daemon.thread_pool and
                hasattr(self.daemon, '_running') and 
                self.daemon._running):
                try:
                    # Submit the send task to the daemon's thread pool
                    future = self.daemon.thread_pool.submit(self._safe_send_worker, client_id, data, message_type)
                    
                    # Wait a short time for the result, but don't block indefinitely
                    return future.result(timeout=1.0)
                except Exception as e:
                    self.logger.debug(f"Thread pool send failed, falling back: {e}")
                    # Fall through to fallback method
            
            # Fall back to creating a new event loop (safer during startup)
            return self._fallback_send_to_client(client_id, data, message_type)
                
        except Exception as e:
            self.logger.error(f"Error in safe_send_to_client: {e}")
            return False
            
    def _safe_send_worker(self, client_id: str, data: Any, message_type: str) -> bool:
        """
        Worker function that runs in the thread pool to safely send messages.
        """
        try:
            # Create a new event loop for this worker
            loop = asyncio.new_event_loop()
            
            try:
                # Set this as the event loop for this thread
                asyncio.set_event_loop(loop)
                
                # Run the async send
                return loop.run_until_complete(self.send_to_client_async(client_id, data, message_type))
            finally:
                # Always clean up the loop
                try:
                    # Cancel any remaining tasks
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass  # Ignore cleanup errors
                finally:
                    loop.close()
        except Exception as e:
            self.logger.error(f"Error in send worker: {e}")
            return False
            
    def _fallback_send_to_client(self, client_id: str, data: Any, message_type: str) -> bool:
        """
        Fallback send method when thread pool is not available.
        """
        try:
            loop = asyncio.new_event_loop()
            
            try:
                # Set this as the event loop for this thread
                asyncio.set_event_loop(loop)
                
                return loop.run_until_complete(self.send_to_client_async(client_id, data, message_type))
            finally:
                # Always clean up the loop
                try:
                    # Cancel any remaining tasks
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass  # Ignore cleanup errors
                finally:
                    loop.close()
        except Exception as e:
            self.logger.error(f"Error in fallback send: {e}")
            return False

    async def broadcast_to_clients_async(self, client_ids: List[str], data: Any, message_type: str = "message") -> Dict[str, bool]:
        """
        Broadcast a message to a specific set of clients asynchronously.
        
        Args:
            client_ids: List of client IDs to send to
            data: The data to send
            message_type: The type of message (default: "message")
            
        Returns:
            Dict[str, bool]: Map of client_id to success/failure status
        """
        results = {}
        message = {
            "type": message_type,
            "data": data
        }
        message_json = json.dumps(message)
        
        for client_id in client_ids:
            if client_id not in self.clients:
                self.logger.warning(f"Cannot send to client {client_id}: Client not connected")
                results[client_id] = False
                continue
                
            try:
                await self.clients[client_id].send(message_json)
                results[client_id] = True
            except Exception as e:
                self.logger.warning(f"Failed to send to client {client_id}: {e}")
                results[client_id] = False
                
        return results
    
    def broadcast_to_clients(self, client_ids: List[str], data: Any, message_type: str = "message") -> Dict[str, bool]:
        """
        Broadcast a message to a specific set of clients.
        
        Args:
            client_ids: List of client IDs to send to
            data: The data to send
            message_type: The type of message (default: "message")
            
        Returns:
            Dict[str, bool]: Map of client_id to success/failure status
        """
        # Filter out invalid client IDs
        valid_client_ids = [cid for cid in client_ids if cid in self.clients]
        
        if not valid_client_ids:
            self.logger.warning(f"No valid clients in {client_ids}")
            return {cid: False for cid in client_ids}
            
        # Check if we're already in an event loop
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # We're in an event loop, create a task
                task = loop.create_task(self.broadcast_to_clients_async(valid_client_ids, data, message_type))
                # We can't directly return the result of the task since it's async
                # Instead, we'll just return a placeholder result
                return {cid: True for cid in valid_client_ids}
        except RuntimeError:
            # No running event loop, use a new one
            pass
            
        # No event loop running, create one
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self.broadcast_to_clients_async(valid_client_ids, data, message_type))
            
            # Combine the results with the invalid clients
            for cid in client_ids:
                if cid not in result:
                    result[cid] = False
                    
            return result
        finally:
            loop.close()
        
    # Client management methods
        
    def get_clients(self) -> List[str]:
        """
        Get a list of all connected client IDs.
        
        Returns:
            List of client IDs
        """
        return list(self.clients.keys())
        
    def get_client_count(self) -> int:
        """
        Get the number of connected clients.
        
        Returns:
            Number of connected clients
        """
        return len(self.clients)
        
    def is_client_connected(self, client_id: str) -> bool:
        """
        Check if a client is connected.
        
        Args:
            client_id: The client ID to check
            
        Returns:
            True if the client is connected, False otherwise
        """
        return client_id in self.clients

    def get_client_metadata(self, client_id: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata about a specific client connection.
        
        Args:
            client_id: The client ID to get metadata for
            
        Returns:
            Dict containing client metadata or None if client not found
        """
        if client_id not in self.clients:
            return None
            
        # Return stored metadata if available
        if client_id in self.client_metadata:
            # Add some derived fields
            metadata = self.client_metadata[client_id].copy()
            
            # Calculate uptime
            if "connected_at" in metadata:
                metadata["uptime_seconds"] = time.time() - metadata["connected_at"]
                
            # Calculate idle time
            if "last_activity" in metadata:
                metadata["idle_seconds"] = time.time() - metadata["last_activity"]
                
            return metadata
            
        # If no stored metadata, fetch basic info from websocket
        websocket = self.clients[client_id]
        
        try:
            # Get basic connection info
            remote_addr = websocket.remote_address if hasattr(websocket, 'remote_address') else None
            path = websocket.path if hasattr(websocket, 'path') else None
            secure = websocket.secure if hasattr(websocket, 'secure') else False
            
            metadata = {
                "client_id": client_id,
                "remote_address": remote_addr,
                "path": path,
                "secure": secure
            }
            
            return metadata
        except Exception as e:
            self.logger.warning(f"Error getting metadata for client {client_id}: {e}")
            return {"client_id": client_id, "error": str(e)}

    def get_clients_by_filter(self, filter_func: Callable[[str, Dict[str, Any]], bool]) -> List[str]:
        """
        Get a list of client IDs that match a filter function.
        
        Args:
            filter_func: A function that takes (client_id, metadata) and returns True/False
            
        Returns:
            List of client IDs that match the filter
            
        Example:
            # Get all clients connected for more than 5 minutes
            old_clients = ws.get_clients_by_filter(
                lambda cid, meta: time.time() - meta.get("connected_at", 0) > 300
            )
            
            # Get all clients connected from a specific IP prefix
            local_clients = ws.get_clients_by_filter(
                lambda _, meta: meta.get("remote_address", [""])[0].startswith("192.168.")
            )
        """
        result = []
        
        for client_id in self.clients:
            metadata = self.get_client_metadata(client_id) or {}
            if filter_func(client_id, metadata):
                result.append(client_id)
                
        return result
        
    def disconnect_client(self, client_id: str, code: int = 1000, reason: str = "Server closed connection") -> bool:
        """
        Forcibly disconnect a client.
        
        Args:
            client_id: The client ID to disconnect
            code: WebSocket close code (default: 1000 - normal closure)
            reason: Close reason message
            
        Returns:
            True if the client was disconnected, False if it wasn't connected
        """
        if client_id not in self.clients:
            return False
            
        websocket = self.clients[client_id]
        
        # Create a task to close the connection
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(websocket.close(code=code, reason=reason))
                return True
        except RuntimeError:
            # No running event loop
            pass
            
        # Fall back to creating a new event loop if needed
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(websocket.close(code=code, reason=reason))
            return True
        except Exception as e:
            self.logger.warning(f"Error disconnecting client {client_id}: {e}")
            return False
        finally:
            loop.close()

    def disconnect_all_clients(self, code: int = 1000, reason: str = "Server shutting down") -> int:
        """
        Disconnect all connected clients.
        
        Args:
            code: WebSocket close code
            reason: Close reason message
            
        Returns:
            Number of clients disconnected
        """
        count = 0
        
        for client_id in list(self.clients.keys()):
            if self.disconnect_client(client_id, code, reason):
                count += 1
                
        return count
        
    def graceful_shutdown(self, timeout: float = 5.0, message: Optional[Dict[str, Any]] = None) -> None:
        """
        Perform a graceful shutdown of the WebSocket server.
        
        This method:
        1. Sends an optional shutdown message to all clients
        2. Waits a moment for clients to receive it
        3. Disconnects all clients
        4. Closes the server
        
        Args:
            timeout: Time to wait after sending shutdown message (seconds)
            message: Optional message to send to all clients before disconnecting
        """
        if not self.is_running or not self.server:
            self.logger.info("WebSocket server not running, nothing to shut down")
            return
            
        self.logger.info(f"Starting graceful shutdown of WebSocket server with {len(self.clients)} connected clients")
        
        # Send shutdown message to all clients if provided
        if message:
            # Default shutdown message
            default_message = {
                "type": "server_shutdown",
                "data": {
                    "message": "Server is shutting down",
                    "reconnect": False
                }
            }
            
            # Use provided message or default
            shutdown_message = message if isinstance(message, dict) else default_message
            
            # Broadcast the message
            self.broadcast_to_all(shutdown_message, message_type="server_shutdown")
            
            # Wait for the message to be delivered
            if timeout > 0:
                self.logger.info(f"Waiting {timeout} seconds for shutdown message delivery")
                time.sleep(timeout)
                
        # Disconnect all clients
        client_count = self.disconnect_all_clients()
        self.logger.info(f"Disconnected {client_count} WebSocket clients")
        
        # Close the server
        if self.server:
            self.logger.info("Closing WebSocket server")
            loop = asyncio.new_event_loop()
            try:
                self.server.close()
                loop.run_until_complete(self.server.wait_closed())
            except Exception as e:
                self.logger.error(f"Error closing WebSocket server: {e}")
            finally:
                loop.close()
                
        # Mark as not running
        self.is_running = False
        self.server = None
        self.logger.info("WebSocket server shutdown complete")

    # Internal methods

    async def _handle_connection(self, websocket: WebSocketServerProtocol) -> None:
        """
        Handle a new WebSocket connection.

        Args:
            websocket: The WebSocket connection
        """
        # Get the path from the websocket object
        path = getattr(websocket, 'path', '/')
        
        # Generate a unique client ID
        client_id = self.generate_client_id(websocket, path)
        
        # Store the client
        self.clients[client_id] = websocket
        
        # Store client metadata
        self.client_metadata[client_id] = {
            "connected_at": time.time(),
            "path": path,
            "remote_address": websocket.remote_address if hasattr(websocket, 'remote_address') else None,
            "secure": websocket.secure if hasattr(websocket, 'secure') else False,
            "messages_received": 0,
            "messages_sent": 0,
            "last_activity": time.time()
        }
        
        try:
            # Call connection handlers
            for handler in self.connection_handlers:
                try:
                    handler(client_id)
                except Exception as e:
                    self.logger.error(f"Error in connection handler: {e}")
                    self.logger.debug(traceback.format_exc())
            
            # Handle 'connect' event if there's a handler
            connect_handler = self.message_handlers.get('connect')
            if connect_handler:
                try:
                    # Empty data for connect event
                    connect_data = {}
                    
                    # Call the handler with (data, client_id)
                    result = connect_handler(connect_data, client_id)
                    
                    # Send the result if not None
                    if result is not None:
                        await websocket.send(json.dumps({
                            "type": "response",
                            "data": result
                        }))
                        
                        # Update message metrics
                        if client_id in self.client_metadata:
                            self.client_metadata[client_id]["messages_sent"] += 1
                            self.client_metadata[client_id]["last_activity"] = time.time()
                except Exception as e:
                    self.logger.error(f"Error in connect handler: {e}")
                    self.logger.debug(traceback.format_exc())
            
            # Handle messages
            async for message_raw in websocket:
                try:
                    # Update message metrics
                    if client_id in self.client_metadata:
                        self.client_metadata[client_id]["messages_received"] += 1
                        self.client_metadata[client_id]["last_activity"] = time.time()
                    
                    # Update rate limit counter
                    self.record_message_received(client_id)
                    
                    # Check for rate limiting
                    if self.is_rate_limited(client_id):
                        # Client is rate limited, send error and skip processing
                        await websocket.send(json.dumps({
                            "type": "error",
                            "error": "Rate limit exceeded",
                            "retry_after": self.rate_limit_window
                        }))
                        continue
                        
                    # Parse the message
                    message = json.loads(message_raw)
                    
                    # Extract the message type
                    message_type = message.get('type')
                    
                    if not message_type:
                        # Respond with an error if no message type was provided
                        await websocket.send(json.dumps({
                            "type": "error",
                            "error": "No message type provided"
                        }))
                        continue
                    
                    # Get the handler for this message type
                    handler = self.message_handlers.get(message_type)
                    
                    if not handler:
                        # Respond with an error if no handler was found
                        await websocket.send(json.dumps({
                            "type": "error",
                            "error": f"No handler found for message type '{message_type}'"
                        }))
                        continue
                    
                    # Create request and response objects for context (backward compatibility)
                    request = WebSocketRequest(client_id, message, websocket)
                    response = WebSocketResponse(websocket, client_id)
                    
                    # Extract the data from the message
                    data = message.get('data', {})
                    
                    # Call the handler with the context
                    from .context import set_context_type, _set_thread_local_request, _set_thread_local_response
                    set_context_type('websocket')
                    
                    try:
                        # Store on daemon for context access
                        if self.daemon:
                            self.daemon.request_ws = request
                            self.daemon.response_ws = response
                        
                        # Set thread-local request/response for this context
                        _set_thread_local_request(request)
                        _set_thread_local_response(response)
                        
                        # Call the handler with (data, client_id)
                        result = handler(data, client_id)
                        
                        # If the handler returns a value, send it as a response
                        if result is not None and not hasattr(result, '__await__'):
                            await response.send(result)
                            
                            # Update message metrics
                            if client_id in self.client_metadata:
                                self.client_metadata[client_id]["messages_sent"] += 1
                                self.client_metadata[client_id]["last_activity"] = time.time()
                        
                        # Handle async results
                        if hasattr(result, '__await__'):
                            result_value = await result
                            if result_value is not None:
                                await response.send(result_value)
                                
                                # Update message metrics
                                if client_id in self.client_metadata:
                                    self.client_metadata[client_id]["messages_sent"] += 1
                                    self.client_metadata[client_id]["last_activity"] = time.time()
                                
                    except Exception as e:
                        # Send error response on exception
                        self.logger.error(f"Error in message handler: {e}")
                        self.logger.error(traceback.format_exc())
                        await response.send({"error": str(e)}, "error")
                        
                        # Update message metrics
                        if client_id in self.client_metadata:
                            self.client_metadata[client_id]["messages_sent"] += 1
                            self.client_metadata[client_id]["last_activity"] = time.time()
                    finally:
                        # Reset context and cleanup
                        from .context import _clear_thread_local_storage
                        _clear_thread_local_storage()
                        
                        if self.daemon:
                            self.daemon.request_ws = None
                            self.daemon.response_ws = None
                    
                except json.JSONDecodeError:
                    # Respond with an error for invalid JSON
                    await websocket.send(json.dumps({
                        "type": "error",
                        "error": "Invalid JSON"
                    }))
                    
                    # Update message metrics
                    if client_id in self.client_metadata:
                        self.client_metadata[client_id]["messages_sent"] += 1
                        self.client_metadata[client_id]["last_activity"] = time.time()
                except Exception as e:
                    # Log any other errors
                    self.logger.error(f"Error handling WebSocket message: {e}")
                    self.logger.debug(traceback.format_exc())
        except ConnectionClosed:
            # Connection was closed, this is normal
            pass
        except Exception as e:
            # Log any other errors
            self.logger.error(f"Error in WebSocket connection: {e}")
            self.logger.debug(traceback.format_exc())
        finally:
            # Clean up the client
            self.clients.pop(client_id, None)
            self.client_metadata.pop(client_id, None)
            
            # Also clean up any rate limiting data
            if client_id in self.rate_limit_counters:
                del self.rate_limit_counters[client_id]
            
            # Handle 'disconnect' event if there's a handler
            disconnect_handler = self.message_handlers.get('disconnect')
            if disconnect_handler:
                try:
                    # Empty data for disconnect event
                    disconnect_data = {}
                    
                    # Call the handler with (data, client_id)
                    disconnect_handler(disconnect_data, client_id)
                except Exception as e:
                    self.logger.error(f"Error in disconnect handler: {e}")
                    self.logger.debug(traceback.format_exc())
            
            # Call disconnection handlers
            for handler in self.disconnection_handlers:
                try:
                    handler(client_id)
                except Exception as e:
                    self.logger.error(f"Error in disconnection handler: {e}")
                    self.logger.debug(traceback.format_exc())

    def enable_rate_limiting(self, max_messages: int = 60, window_seconds: int = 60) -> None:
        """
        Enable rate limiting for clients to prevent abuse.
        
        Args:
            max_messages: Maximum number of messages allowed in the time window
            window_seconds: Time window in seconds
        """
        self.rate_limit_enabled = True
        self.rate_limit_messages = max_messages
        self.rate_limit_window = window_seconds
        self.logger.info(f"Rate limiting enabled: {max_messages} messages per {window_seconds} seconds")
        
    def disable_rate_limiting(self) -> None:
        """Disable rate limiting for clients."""
        self.rate_limit_enabled = False
        self.logger.info("Rate limiting disabled")
        
    def is_rate_limited(self, client_id: str) -> bool:
        """
        Check if a client is currently rate limited.
        
        Args:
            client_id: The client ID to check
            
        Returns:
            True if the client is rate limited, False otherwise
        """
        if not self.rate_limit_enabled:
            return False
            
        # Get timestamp queue for this client
        timestamps = self.rate_limit_counters[client_id]
        
        # No messages yet, not rate limited
        if not timestamps:
            return False
            
        # Calculate time window
        now = time.time()
        window_start = now - self.rate_limit_window
        
        # Count messages in the window
        # First, remove old timestamps
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()
            
        # Then check if we're over the limit
        return len(timestamps) >= self.rate_limit_messages
        
    def record_message_received(self, client_id: str) -> None:
        """
        Record that a client sent a message for rate limiting purposes.
        
        Args:
            client_id: The client ID that sent a message
        """
        if not self.rate_limit_enabled:
            return
            
        # Add current timestamp to the queue
        self.rate_limit_counters[client_id].append(time.time())
        
    # Batched broadcasting methods removed - feature was unused

    def safe_broadcast_to_all(self, data: Any, message_type: str = "broadcast") -> int:
        """
        Thread-safe broadcast method that can be called from any context.
        
        This method is specifically designed to be called from callbacks,
        background tasks, or other non-WebSocket contexts.
        
        Args:
            data: The data to send
            message_type: The type of message (default: "broadcast")
            
        Returns:
            int: Number of clients the message was successfully sent to
        """
        if not self.is_running or not self.clients:
            self.logger.debug("WebSocket server not running or no clients connected")
            return 0
            
        # Use a thread-safe approach by submitting to the WebSocket server's event loop
        try:
            # First try using the daemon's thread pool if available and the daemon is fully initialized
            if (self.daemon and 
                hasattr(self.daemon, 'thread_pool') and 
                self.daemon.thread_pool and
                hasattr(self.daemon, '_running') and 
                self.daemon._running):
                try:
                    # Submit the broadcast task to the daemon's thread pool
                    future = self.daemon.thread_pool.submit(self._safe_broadcast_worker, data, message_type)
                    
                    # Wait a short time for the result, but don't block indefinitely
                    return future.result(timeout=1.0)
                except Exception as e:
                    self.logger.debug(f"Thread pool broadcast failed, falling back: {e}")
                    # Fall through to fallback method
            
            # Fall back to creating a new event loop (safer during startup)
            return self._fallback_broadcast(data, message_type)
                
        except Exception as e:
            self.logger.error(f"Error in safe_broadcast_to_all: {e}")
            return 0
            
    def _safe_broadcast_worker(self, data: Any, message_type: str) -> int:
        """
        Worker function that runs in the thread pool to safely broadcast messages.
        """
        try:
            # Create a new event loop for this worker
            loop = asyncio.new_event_loop()
            
            try:
                # Set this as the event loop for this thread
                asyncio.set_event_loop(loop)
                
                # Run the async broadcast
                return loop.run_until_complete(self.broadcast_to_all_async(data, message_type))
            finally:
                # Always clean up the loop
                try:
                    # Cancel any remaining tasks
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass  # Ignore cleanup errors
                finally:
                    loop.close()
        except Exception as e:
            self.logger.error(f"Error in broadcast worker: {e}")
            return 0
            
    def _fallback_broadcast(self, data: Any, message_type: str) -> int:
        """
        Fallback broadcast method when thread pool is not available.
        """
        try:
            loop = asyncio.new_event_loop()
            
            try:
                # Set this as the event loop for this thread
                asyncio.set_event_loop(loop)
                
                return loop.run_until_complete(self.broadcast_to_all_async(data, message_type))
            finally:
                # Always clean up the loop
                try:
                    # Cancel any remaining tasks
                    pending = asyncio.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass  # Ignore cleanup errors
                finally:
                    loop.close()
        except Exception as e:
            self.logger.error(f"Error in fallback broadcast: {e}")
            return 0 