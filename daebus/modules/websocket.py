import json
import traceback
import asyncio
import uuid
from typing import Dict, Any, Callable, List, Optional, Union

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
        self.client_counter = 0
        self.logger = _default_logger.getChild('websocket')
        self.client_id_generator = None  # Custom client ID generator function

    def attach(self, daemon: Any) -> None:
        """
        Attach to a Daebus instance.

        Args:
            daemon: The Daebus instance to attach to
        """
        self.daemon = daemon
        
        # We need to make sure the HTTP server is also attached to use its port
        if not daemon.http:
            raise RuntimeError("DaebusWebSocket requires DaebusHttp to be attached first. "
                               "Use app.attach(DaebusHttp()) before app.attach(DaebusWebSocket()).")
        
        # Use HTTP server's port if one wasn't specified
        if self.port is None:
            self.port = daemon.http.port
        
        # Store self on the daemon
        daemon.websocket = self
        
        # Add a thread for the WebSocket server
        @daemon.thread("websocket_server", auto_start=True)
        def run_websocket_server(running):
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Start the WebSocket server
            start_server = websockets.serve(
                self._handle_connection, 
                "0.0.0.0", 
                self.port
            )
            
            # Mark as running
            self.is_running = True
            
            # Run the server
            server = loop.run_until_complete(start_server)
            self.server = server
            
            self.logger.info(f"WebSocket server listening on port {self.port}")
            
            # Keep the server running until the daemon is shut down
            try:
                while running() and self.is_running:
                    loop.run_until_complete(asyncio.sleep(1))
            except Exception as e:
                self.logger.error(f"Error in WebSocket server: {e}")
            finally:
                # Clean up
                server.close()
                loop.run_until_complete(server.wait_closed())
                loop.close()
                self.is_running = False
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

    # Core methods for sending messages

    async def broadcast_to_all_async(self, data: Any, message_type: str = "broadcast") -> None:
        """
        Broadcast a message to all connected clients asynchronously.

        Args:
            data: The data to send
            message_type: The type of message (default: "broadcast")
        """
        message = {
            "type": message_type,
            "data": data
        }
        message_json = json.dumps(message)
        
        # Send to all clients
        for client_id, websocket in list(self.clients.items()):
            try:
                await websocket.send(message_json)
            except Exception as e:
                self.logger.warning(f"Failed to broadcast to client {client_id}: {e}")

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
        """
        response = self._get_current_response()
        
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
        
    def broadcast_to_all(self, data: Any, message_type: str = "broadcast") -> None:
        """
        Broadcast a message to all connected clients.
        
        Args:
            data: The data to send
            message_type: The type of message (default: "broadcast")
        """
        # Check if we're already in an event loop
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # We're in an event loop, create a task
                loop.create_task(self.broadcast_to_all_async(data, message_type))
                return
        except RuntimeError:
            # No running event loop, use a new one
            pass
            
        # No event loop running, create one
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self.broadcast_to_all_async(data, message_type))
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

    # Internal methods

    async def _handle_connection(self, websocket: WebSocketServerProtocol, path: str) -> None:
        """
        Handle a new WebSocket connection.

        Args:
            websocket: The WebSocket connection
            path: The connection path
        """
        # Generate a unique client ID
        client_id = self.generate_client_id(websocket, path)
        
        # Store the client
        self.clients[client_id] = websocket
        
        try:
            # Call connection handlers
            for handler in self.connection_handlers:
                try:
                    handler(client_id)
                except Exception as e:
                    self.logger.error(f"Error in connection handler: {e}")
            
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
                except Exception as e:
                    self.logger.error(f"Error in connect handler: {e}")
            
            # Handle messages
            async for message_raw in websocket:
                try:
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
                        
                        # Handle async results
                        if hasattr(result, '__await__'):
                            result_value = await result
                            if result_value is not None:
                                await response.send(result_value)
                                
                    except Exception as e:
                        # Send error response on exception
                        self.logger.error(f"Error in message handler: {e}")
                        self.logger.error(traceback.format_exc())
                        await response.send({"error": str(e)}, "error")
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
                except Exception as e:
                    # Log any other errors
                    self.logger.error(f"Error handling WebSocket message: {e}")
        except ConnectionClosed:
            # Connection was closed, this is normal
            pass
        except Exception as e:
            # Log any other errors
            self.logger.error(f"Error in WebSocket connection: {e}")
        finally:
            # Clean up the client
            self.clients.pop(client_id, None)
            
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
            
            # Call disconnection handlers
            for handler in self.disconnection_handlers:
                try:
                    handler(client_id)
                except Exception as e:
                    self.logger.error(f"Error in disconnection handler: {e}") 