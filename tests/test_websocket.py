import pytest
import asyncio
import json
import threading
import time
import websockets
from unittest.mock import MagicMock, patch

from daebus import Daebus, DaebusHttp, DaebusWebSocket


class TestWebSocket:
    @pytest.fixture
    def setup_app(self):
        """Setup a Daebus app with HTTP and WebSocket servers"""
        # Create the app
        app = Daebus("test_app")
        
        # Mock redis to avoid actual connection
        with patch('daebus.modules.daemon.Redis'), \
             patch('daebus.modules.daemon.BackgroundScheduler'):
            
            # Setup port for testing
            test_port = 8765
            
            # Attach HTTP and WebSocket components
            http = app.attach(DaebusHttp(port=test_port))
            ws = app.attach(DaebusWebSocket())
            
            # Mock thread starting to avoid actual server
            with patch.object(app, 'start_thread'):
                # Setup app without actually running it
                app.service = "test_service"
                app._running = True
                
                # Register WebSocket message handlers
                @app.socket("ping")
                def handle_ping(req, sid):
                    return {"pong": True, "client_id": sid}
                
                @app.socket("echo")
                def handle_echo(req, sid):
                    return req
                
                @app.socket("multi_response")
                def handle_multi(req, sid):
                    # Send an immediate response
                    app.websocket.send({"status": "processing"})
                    
                    # Return a value which will also be sent
                    return {"status": "complete"}
                
                @app.socket("broadcast")
                def handle_broadcast(req, sid):
                    # Broadcast to all clients
                    app.websocket.broadcast_to_all(
                        {"message": req.get("message", ""), "sender": sid},
                        message_type="announcement"
                    )
                    return {"status": "broadcast_sent"}
                
                # Mock connection and disconnection handlers
                app.websocket.connection_handlers = []
                app.websocket.disconnection_handlers = []
                
                @app.websocket.on_connect
                def handle_connect(client_id):
                    app.connect_handler_called = True
                    app.connected_client_id = client_id
                
                @app.websocket.on_disconnect
                def handle_disconnect(client_id):
                    app.disconnect_handler_called = True
                    app.disconnected_client_id = client_id
                
                # Setup attribute for tracking handler calls
                app.connect_handler_called = False
                app.disconnect_handler_called = False
                app.connected_client_id = None
                app.disconnected_client_id = None
                
                # Return the app for the test
                return app
    
    @pytest.mark.asyncio
    async def test_message_handling(self, setup_app):
        """Test that WebSocket messages are properly handled"""
        app = setup_app
        
        # Mock WebSocketServerProtocol
        mock_websocket = MagicMock()
        mock_send_results = []
        
        # Capture send() calls
        async def mock_send(data):
            mock_send_results.append(json.loads(data))
            return None  # Ensure we return a proper value
        
        mock_websocket.send = mock_send
        
        # Create a message
        message = json.dumps({
            "type": "ping",
            "data": {}
        })
        
        # Process the message
        client_id = "test_client_1"
        app.websocket.clients[client_id] = mock_websocket
        
        # Parse message data
        message_data = json.loads(message)
        data = message_data.get("data", {})
        
        # Directly call the handler function with the new signature
        handler = app.websocket.message_handlers["ping"]
        
        # Setup context for backward compatibility
        from daebus.modules.websocket import WebSocketRequest, WebSocketResponse
        request = WebSocketRequest(client_id, message_data, mock_websocket)
        response = WebSocketResponse(mock_websocket, client_id)
        
        # Setup context
        from daebus.modules.context import set_context_type, _set_thread_local_request, _set_thread_local_response
        set_context_type('websocket')
        _set_thread_local_request(request)
        _set_thread_local_response(response)
        
        try:
            # Call the handler with the new signature
            result = handler(data, client_id)
            
            # If the handler returns a value, it should be sent as a response
            if result is not None and not hasattr(result, '__await__'):
                await response.send(result)
                
            # If the result is awaitable, await it and send the result
            elif hasattr(result, '__await__'):
                result_value = await result
                if result_value is not None:
                    await response.send(result_value)
        finally:
            # Clean up context
            from daebus.modules.context import _clear_thread_local_storage
            _clear_thread_local_storage()
        
        # Verify the response
        assert len(mock_send_results) == 1
        assert mock_send_results[0]["type"] == "response"
        assert mock_send_results[0]["data"]["pong"] is True
        assert mock_send_results[0]["data"]["client_id"] == client_id
    
    @pytest.mark.asyncio
    async def test_echo_handler(self, setup_app):
        """Test echo handler that returns the input data"""
        app = setup_app
        
        # Mock WebSocketServerProtocol
        mock_websocket = MagicMock()
        mock_send_results = []
        
        # Capture send() calls
        async def mock_send(data):
            mock_send_results.append(json.loads(data))
            return None
        
        mock_websocket.send = mock_send
        
        # Create a message with test data
        test_data = {"message": "Hello, World!", "timestamp": 12345}
        message = json.dumps({
            "type": "echo",
            "data": test_data
        })
        
        # Process the message
        client_id = "test_client_2"
        app.websocket.clients[client_id] = mock_websocket
        
        # Parse message data
        message_data = json.loads(message)
        data = message_data.get("data", {})
        
        # Directly call the handler function with new signature
        handler = app.websocket.message_handlers["echo"]
        
        # Setup context for backward compatibility
        from daebus.modules.websocket import WebSocketRequest, WebSocketResponse
        request = WebSocketRequest(client_id, message_data, mock_websocket)
        response = WebSocketResponse(mock_websocket, client_id)
        
        # Setup context
        from daebus.modules.context import set_context_type, _set_thread_local_request, _set_thread_local_response
        set_context_type('websocket')
        _set_thread_local_request(request)
        _set_thread_local_response(response)
        
        try:
            # Call the handler with the new signature
            result = handler(data, client_id)
            
            # If the handler returns a value, it should be sent as a response
            if result is not None and not hasattr(result, '__await__'):
                await response.send(result)
                
            # If the result is awaitable, await it and send the result
            elif hasattr(result, '__await__'):
                result_value = await result
                if result_value is not None:
                    await response.send(result_value)
        finally:
            # Clean up context
            from daebus.modules.context import _clear_thread_local_storage
            _clear_thread_local_storage()
        
        # Verify the response
        assert len(mock_send_results) == 1
        assert mock_send_results[0]["type"] == "response"
        assert mock_send_results[0]["data"] == test_data
    
    def test_multiple_responses(self, setup_app, monkeypatch):
        """Test handler that sends multiple responses"""
        app = setup_app
        mock_send_results = []
        
        # Create a mock websocket for testing
        mock_websocket = MagicMock()
        
        # Create an async mock for send method
        async def mock_send(data):
            mock_send_results.append(json.loads(data))
            return None
        
        mock_websocket.send = mock_send
        
        # Setup the request data
        message = {
            "type": "multi_response",
            "data": {}
        }
        data = message.get("data", {})
        
        # Setup mock for app.websocket.send
        def mock_send_sync(data, message_type="response"):
            # Create an event loop that's separate from the test's event loop
            loop = asyncio.new_event_loop()
            try:
                # Run the async send in the separate loop
                coro = mock_websocket.send(json.dumps({
                    "type": message_type,
                    "data": data
                }))
                loop.run_until_complete(coro)
            finally:
                loop.close()
        
        # Patch the send method
        monkeypatch.setattr(app.websocket, "send", mock_send_sync)
        
        # Create request and response objects for backward compatibility
        client_id = "test_client_3"
        app.websocket.clients[client_id] = mock_websocket
        
        from daebus.modules.websocket import WebSocketRequest, WebSocketResponse
        request = WebSocketRequest(client_id, message, mock_websocket)
        response = WebSocketResponse(mock_websocket, client_id)
        
        # Store on daemon
        app.daemon = MagicMock()
        app.websocket.daemon = app.daemon
        app.daemon.request_ws = request
        app.daemon.response_ws = response
        
        # Setup context
        from daebus.modules.context import set_context_type, _set_thread_local_request, _set_thread_local_response
        set_context_type('websocket')
        _set_thread_local_request(request)
        _set_thread_local_response(response)
        
        try:
            # Call the handler with new signature
            handler = app.websocket.message_handlers["multi_response"]
            result = handler(data, client_id)
            
            # Handle the returned result
            if result is not None:
                # Create a separate event loop to handle the async result
                loop = asyncio.new_event_loop()
                try:
                    if hasattr(result, '__await__'):
                        # Handle async result
                        result = loop.run_until_complete(result)
                        
                    # Send the result
                    if result is not None:
                        loop.run_until_complete(response.send(result))
                finally:
                    loop.close()
        finally:
            # Clean up context
            from daebus.modules.context import _clear_thread_local_storage
            _clear_thread_local_storage()
        
        # Verify we received both messages
        assert len(mock_send_results) == 2
        assert any(r["data"]["status"] == "processing" for r in mock_send_results)
        assert any(r["data"]["status"] == "complete" for r in mock_send_results)
    
    def test_broadcast(self, setup_app, monkeypatch):
        """Test broadcasting to all clients"""
        app = setup_app
        
        # Create multiple mock clients
        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        mock_send_results1 = []
        mock_send_results2 = []
        
        # Capture send() calls for client 1
        async def mock_send1(data):
            mock_send_results1.append(json.loads(data))
            return None
        
        # Capture send() calls for client 2
        async def mock_send2(data):
            mock_send_results2.append(json.loads(data))
            return None
        
        mock_client1.send = mock_send1
        mock_client2.send = mock_send2
        
        # Add clients to the app
        client_id1 = "test_client_4"
        client_id2 = "test_client_5"
        app.websocket.clients[client_id1] = mock_client1
        app.websocket.clients[client_id2] = mock_client2
        
        # Create a message
        broadcast_message = "Hello everyone!"
        message = {
            "type": "broadcast",
            "data": {"message": broadcast_message}
        }
        data = message.get("data", {})
        
        # Setup mock for app.websocket.broadcast_to_all
        def mock_broadcast_sync(data, message_type="broadcast"):
            # Create an event loop that's separate from the test's event loop
            loop = asyncio.new_event_loop()
            try:
                # Manually send to each client
                for client_id, client in app.websocket.clients.items():
                    message_json = json.dumps({
                        "type": message_type,
                        "data": data
                    })
                    loop.run_until_complete(client.send(message_json))
            finally:
                loop.close()
        
        # Patch the broadcast method
        monkeypatch.setattr(app.websocket, "broadcast_to_all", mock_broadcast_sync)
        
        # Create request and response objects for backward compatibility
        from daebus.modules.websocket import WebSocketRequest, WebSocketResponse
        request = WebSocketRequest(client_id1, message, mock_client1)
        response = WebSocketResponse(mock_client1, client_id1)
        
        # Store on daemon
        app.daemon = MagicMock()
        app.websocket.daemon = app.daemon
        app.daemon.request_ws = request
        app.daemon.response_ws = response
        
        # Setup context
        from daebus.modules.context import set_context_type, _set_thread_local_request, _set_thread_local_response
        set_context_type('websocket')
        _set_thread_local_request(request)
        _set_thread_local_response(response)
        
        try:
            # Call the handler with new signature
            handler = app.websocket.message_handlers["broadcast"]
            result = handler(data, client_id1)
            
            # Handle the returned result
            if result is not None:
                # Create a separate event loop to handle the async result
                loop = asyncio.new_event_loop()
                try:
                    if hasattr(result, '__await__'):
                        # Handle async result
                        result = loop.run_until_complete(result)
                        
                    # Send the result
                    if result is not None:
                        loop.run_until_complete(response.send(result))
                finally:
                    loop.close()
        finally:
            # Clean up context
            from daebus.modules.context import _clear_thread_local_storage
            _clear_thread_local_storage()
            
        # Check that both clients received the broadcast
        assert any(msg["type"] == "announcement" and 
                  msg["data"]["message"] == broadcast_message and
                  msg["data"]["sender"] == client_id1
                  for msg in mock_send_results1)
        
        assert any(msg["type"] == "announcement" and 
                  msg["data"]["message"] == broadcast_message and
                  msg["data"]["sender"] == client_id1
                  for msg in mock_send_results2)
        
        # Check that the first client also got a response
        assert any(msg["type"] == "response" and 
                  msg["data"]["status"] == "broadcast_sent"
                  for msg in mock_send_results1)
    
    @pytest.mark.asyncio
    async def test_connection_handlers(self, setup_app):
        """Test connection and disconnection handlers"""
        app = setup_app
        
        # Reset tracking variables
        app.connect_handler_called = False
        app.disconnect_handler_called = False
        app.connected_client_id = None
        app.disconnected_client_id = None
        
        # Mock WebSocketServerProtocol
        mock_websocket = MagicMock()
        
        # Create a connection handler instance
        from daebus.modules.websocket import WebSocketResponse
        
        # Directly call the connection handler (simulating a new connection)
        client_id = "test_client_6"
        
        # Call the handlers directly
        for handler in app.websocket.connection_handlers:
            handler(client_id)
        
        # Verify the connection handler was called
        assert app.connect_handler_called is True
        assert app.connected_client_id == client_id
        
        # Now simulate a disconnection
        for handler in app.websocket.disconnection_handlers:
            handler(client_id)
            
        # Verify the disconnection handler was called
        assert app.disconnect_handler_called is True
        assert app.disconnected_client_id == client_id
    
    @pytest.mark.asyncio
    async def test_client_management(self, setup_app):
        """Test client management methods"""
        app = setup_app
        
        # Create mock clients
        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        
        # Add clients to the app
        client_id1 = "test_client_7"
        client_id2 = "test_client_8"
        app.websocket.clients.clear()  # Clear any existing clients
        app.websocket.clients[client_id1] = mock_client1
        app.websocket.clients[client_id2] = mock_client2
        
        # Test get_clients
        clients = app.websocket.get_clients()
        assert len(clients) == 2
        assert client_id1 in clients
        assert client_id2 in clients
        
        # Test get_client_count
        assert app.websocket.get_client_count() == 2
        
        # Test is_client_connected
        assert app.websocket.is_client_connected(client_id1) is True
        assert app.websocket.is_client_connected(client_id2) is True
        assert app.websocket.is_client_connected("nonexistent_client") is False
        
        # Test removing a client
        app.websocket.clients.pop(client_id1)
        assert app.websocket.get_client_count() == 1
        assert app.websocket.is_client_connected(client_id1) is False
        assert app.websocket.is_client_connected(client_id2) is True 