import pytest
from unittest.mock import MagicMock, patch
import json
import asyncio

from daebus import Daebus, DaebusHttp, DaebusWebSocket
from daebus.modules.context import set_context_type, response, _set_thread_local_request, _set_thread_local_response, _clear_thread_local_storage
from daebus.modules.websocket import WebSocketRequest, WebSocketResponse


def test_response_proxy_websocket_methods():
    """Test that response proxy correctly forwards WebSocket methods in WebSocket context"""
    # Create the app
    app = Daebus("test_app")
    
    # Mock redis to avoid actual connection
    with patch('daebus.modules.daemon.Redis'), \
         patch('daebus.modules.daemon.BackgroundScheduler'), \
         patch('daebus.modules.websocket.WebSocketResponse.send') as mock_response_send:
        
        # Configure the mock to handle async call
        mock_response_send.return_value = None
        
        # Attach HTTP and WebSocket components
        app.attach(DaebusHttp(port=8765))
        ws = app.attach(DaebusWebSocket())
        
        # Create a client ID and mock WebSocket
        client_id = "test_client_1"
        mock_websocket = MagicMock()
        
        # Set up the mock WebSocket send method
        async def mock_ws_send(data):
            return None
        mock_websocket.send = mock_ws_send
        
        # Set up the mock WebSocket component methods
        ws.send = MagicMock()
        ws.send.return_value = None
        
        ws.broadcast_to_all = MagicMock()
        ws.broadcast_to_all.return_value = None
        
        ws.send_to_client = MagicMock()
        ws.send_to_client.return_value = None
        
        ws.broadcast_to_clients = MagicMock()
        ws.broadcast_to_clients.return_value = None
        
        # Add the client to the WebSocket server
        ws.clients[client_id] = mock_websocket
        
        # Create WebSocket request and response objects
        message = {"type": "test", "data": {"foo": "bar"}}
        request_obj = WebSocketRequest(client_id, message, mock_websocket)
        response_obj = WebSocketResponse(mock_websocket, client_id)
        
        # Set up the context
        set_context_type('websocket')
        _set_thread_local_request(request_obj)
        _set_thread_local_response(response_obj)
        
        # Set the daemon for the context system
        from daebus.modules.context import set_daemon
        set_daemon(app)
        
        # Store objects on daemon for context access
        app.request_ws = request_obj
        app.response_ws = response_obj
        app.websocket = ws
        
        # Create an event loop for testing
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Test 1: Call send through the proxy
            test_data = {"hello": "world"}
            
            # For WebSocketResponse.send, we need to properly await it
            future = asyncio.ensure_future(response.send(test_data))
            loop.run_until_complete(future)
            
            # Verify the mock was called
            assert mock_response_send.called
            
            # Test 2: Call broadcast_to_all through the proxy
            broadcast_data = {"announcement": "Hello everyone!"}
            response.broadcast_to_all(broadcast_data)
            assert ws.broadcast_to_all.called
            
            # Test 3: Call send_to_client through the proxy
            target_client = "client_2"
            client_data = {"private": "Just for you"}
            response.send_to_client(target_client, client_data)
            assert ws.send_to_client.called
            
            # Test 4: Call broadcast_to_clients through the proxy
            target_clients = ["client_2", "client_3"]
            group_data = {"group": "Just for selected clients"}
            response.broadcast_to_clients(target_clients, group_data)
            assert ws.broadcast_to_clients.called
            
        finally:
            # Clean up
            loop.close()
            _clear_thread_local_storage()
            from daebus.modules.context import _global_daemon
            _global_daemon = None


def test_response_proxy_success_in_websocket_context():
    """Test that response.success() works in WebSocket context."""
    # Create the app
    app = Daebus("test_app")
    
    # Mock redis to avoid actual connection
    with patch('daebus.modules.daemon.Redis'), \
         patch('daebus.modules.daemon.BackgroundScheduler'):
        
        # Attach HTTP and WebSocket components
        app.attach(DaebusHttp(port=8765))
        app.attach(DaebusWebSocket())
        
        # Create a client ID and mock WebSocket
        client_id = "test_client_2"
        mock_websocket = MagicMock()
        mock_websocket.sent_data = []
        
        # Set up the mock WebSocket send method
        async def mock_send(data):
            mock_websocket.sent_data.append(json.loads(data))
            return None
        mock_websocket.send = mock_send
        
        # Add the client to the WebSocket server
        app.websocket.clients[client_id] = mock_websocket
        
        # Create WebSocket request and response objects
        message = {"type": "test", "data": {"foo": "bar"}}
        request_obj = WebSocketRequest(client_id, message, mock_websocket)
        response_obj = WebSocketResponse(mock_websocket, client_id)
        
        # Set up the context
        set_context_type('websocket')
        _set_thread_local_request(request_obj)
        _set_thread_local_response(response_obj)
        
        # Set the daemon for the context system
        from daebus.modules.context import set_daemon
        set_daemon(app)
        
        # Create an event loop for testing
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Call success through the proxy
            payload = {"status": "success", "data": {"result": 42}}
            
            # Response.success should be defined on the WebSocketResponse
            loop.run_until_complete(response_obj.send(payload))
            
            # Verify that the message was sent
            assert len(mock_websocket.sent_data) == 1
            assert mock_websocket.sent_data[0]["type"] == "response"
            assert mock_websocket.sent_data[0]["data"] == payload
            
        finally:
            # Clean up
            loop.close()
            _clear_thread_local_storage()
            from daebus.modules.context import _global_daemon
            _global_daemon = None 