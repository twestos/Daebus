import pytest
import asyncio
import json
import threading
import time
import websockets
from unittest.mock import patch

from daebus import Daebus, DaebusHttp, DaebusWebSocket


def test_websocket_e2e():
    """
    End-to-end test of WebSocket functionality.
    
    This test:
    1. Starts a real server (though with mocked Redis)
    2. Connects to it with a real WebSocket client
    3. Sends and receives messages
    4. Tests broadcasting
    """
    # Use a different port for this test to avoid conflicts
    test_port = 8766
    
    # Setup a stop event for the server thread
    stop_event = threading.Event()
    
    # Create a place to store test results
    connected_event = threading.Event()
    
    # Create the app in a separate thread
    def run_server():
        # Create the app
        app = Daebus("test_e2e_app")
        
        # Mock redis to avoid actual connection
        with patch('daebus.modules.daemon.Redis'), \
             patch('daebus.modules.daemon.BackgroundScheduler'):
            
            # Attach HTTP and WebSocket components
            app.attach(DaebusHttp(port=test_port))
            app.attach(DaebusWebSocket())
            
            # Register handlers
            @app.socket("ping")
            def handle_ping(req):
                return {"pong": True, "received_at": time.time()}
            
            @app.socket("echo")
            def handle_echo(req):
                return req.data
            
            @app.socket("broadcast")
            def handle_broadcast(req):
                app.websocket.broadcast_to_all(
                    {"message": req.data.get("message", ""), "from": req.client_id},
                    message_type="announcement"
                )
                return {"status": "broadcast_sent"}
            
            @app.websocket.on_connect
            def handle_connect(client_id):
                # Set the connected event to signal client connection
                connected_event.set()
                # Don't broadcast on connect for cleaner testing
            
            # Start the server (but don't block)
            # We use some internal attributes to avoid actually connecting to Redis
            app.service = "test_service"
            app._running = True
            
            # Start HTTP server
            app.http.start()
            
            # Start the WebSocket server directly
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Create a wrapper function to adapt the handler signature
            async def handler_wrapper(websocket):
                # Call with a mock path parameter
                await app.websocket._handle_connection(websocket, "/")
            
            # Start the WebSocket server directly
            async def setup_ws_server():
                ws_server = await websockets.serve(
                    handler_wrapper,
                    "127.0.0.1",  # Use localhost IP to avoid DNS lookup
                    test_port
                )
                return ws_server
                
            ws_server = loop.run_until_complete(setup_ws_server())
            app.websocket.is_running = True
            app.websocket.server = ws_server
            
            # Wait for the stop event
            try:
                while not stop_event.is_set():
                    loop.run_until_complete(asyncio.sleep(0.1))
            finally:
                # Clean up
                ws_server.close()
                loop.run_until_complete(ws_server.wait_closed())
                app.websocket.is_running = False
                loop.close()
                
                # Stop HTTP server
                app.http.stop()
    
    # Start the server thread
    server_thread = threading.Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Give the server a moment to start
    time.sleep(2)  # Increase delay to ensure server is ready
    
    # Define the client operations
    async def run_client_test():
        # Try a few times if the connection fails initially
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                # Create a WebSocket client with explicit timeout
                uri = f"ws://127.0.0.1:{test_port}"
                async with websockets.connect(
                    uri,
                    close_timeout=5.0,
                    ping_interval=None,  # Don't send pings
                    ping_timeout=None    # Don't expect pings
                ) as websocket:
                    # Wait for connection event with a timeout
                    if not connected_event.wait(5.0):
                        pytest.fail("Timed out waiting for connection event")
                        
                    # Send a ping message
                    ping_msg = json.dumps({
                        "type": "ping",
                        "data": {}
                    })
                    await websocket.send(ping_msg)
                    
                    # Read the response with a timeout
                    try:
                        response = await asyncio.wait_for(websocket.recv(), 2.0)
                        response_data = json.loads(response)
                        
                        # Print response for debugging
                        print(f"Ping response: {response_data}")
                        
                        # Verify the ping response
                        assert response_data["type"] == "response"
                        assert response_data["data"]["pong"] is True
                    except asyncio.TimeoutError:
                        pytest.fail("Timed out waiting for ping response")
                    
                    # Send an echo message
                    test_payload = {"message": "Hello, WebSocket!", "timestamp": time.time()}
                    echo_msg = json.dumps({
                        "type": "echo",
                        "data": test_payload
                    })
                    await websocket.send(echo_msg)
                    
                    # Read the echo response with a timeout
                    try:
                        response = await asyncio.wait_for(websocket.recv(), 2.0)
                        response_data = json.loads(response)
                        
                        # Verify the echo response
                        assert response_data["type"] == "response"
                        assert response_data["data"] == test_payload
                    except asyncio.TimeoutError:
                        pytest.fail("Timed out waiting for echo response")
                    
                    # Test broadcasting
                    async with websockets.connect(
                        uri,
                        close_timeout=5.0,
                        ping_interval=None,
                        ping_timeout=None
                    ) as websocket2:
                        # Give the second connection time to establish
                        await asyncio.sleep(0.5)
                        
                        # Send a broadcast from the first connection
                        broadcast_msg = "Hello from client 1!"
                        broadcast_data = json.dumps({
                            "type": "broadcast",
                            "data": {"message": broadcast_msg}
                        })
                        await websocket.send(broadcast_data)
                        
                        # Read responses from both connections
                        try:
                            # Read confirmation from first connection
                            response1 = await asyncio.wait_for(websocket.recv(), 2.0)
                            response_data1 = json.loads(response1)
                            
                            # Verify the confirmation
                            assert response_data1["type"] == "response"
                            assert response_data1["data"]["status"] == "broadcast_sent"
                            
                            # Read broadcast from second connection
                            response2 = await asyncio.wait_for(websocket2.recv(), 2.0)
                            response_data2 = json.loads(response2)
                            
                            # Verify the broadcast message
                            assert response_data2["type"] == "announcement"
                            assert response_data2["data"]["message"] == broadcast_msg
                        except asyncio.TimeoutError:
                            pytest.fail("Timed out waiting for broadcast messages")
                    
                    # Successfully completed the test
                    return
                    
            except (ConnectionRefusedError, OSError) as e:
                if attempt < max_attempts - 1:
                    # If not the last attempt, wait and retry
                    time.sleep(1)
                    continue
                else:
                    # Last attempt failed, re-raise the exception
                    pytest.fail(f"Failed to connect after {max_attempts} attempts: {str(e)}")
    
    try:
        # Create a new event loop for the client
        client_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(client_loop)
        
        # Run the client test
        try:
            client_loop.run_until_complete(run_client_test())
        finally:
            client_loop.close()
            
    except Exception as e:
        pytest.fail(f"WebSocket test failed: {str(e)}")
    
    finally:
        # Signal the server to stop
        stop_event.set()
        
        # Wait for server thread to complete
        server_thread.join(timeout=5.0) 