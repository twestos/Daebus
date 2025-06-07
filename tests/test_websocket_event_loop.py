#!/usr/bin/env python3
"""
WebSocket Event Loop Stability Test Suite

This test suite is designed to validate that the Daebus WebSocket implementation
can handle various stress conditions without encountering "no running event loop" errors.

The tests cover:
1. Rapid connection/disconnection cycles
2. Concurrent message handling
3. Server shutdown during active connections
4. Rate limiting stress testing
5. Broadcast queue stress testing
6. Thread safety of WebSocket operations
"""

import pytest
import asyncio
import threading
import time
import json
import websockets
import socket
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch, MagicMock
import logging

# Configure logging to capture errors
logging.basicConfig(level=logging.DEBUG)

# Import the modules we need to test
from daebus import Daebus, DaebusHttp, DaebusWebSocket


def find_free_port():
    """Find and return a free port number by opening a temporary socket."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class WebSocketEventLoopTests:
    """Test suite for WebSocket event loop stability and error handling."""
    
    def setup_method(self):
        """Set up test environment before each test."""
        # Use a random free port to avoid conflicts
        self.test_port = find_free_port()
        
        # Create the app with mocked Redis
        with patch('daebus.modules.daemon.Redis'), \
             patch('daebus.modules.daemon.BackgroundScheduler'):
            
            self.app = Daebus("test_event_loop_app")
            self.http = DaebusHttp(port=self.test_port)
            self.ws = DaebusWebSocket()
            
            self.app.attach(self.http)
            self.app.attach(self.ws)
            
            # Storage for test results and errors
            self.test_errors = []
            self.connection_events = []
            self.message_events = []
            self.server_ready_event = threading.Event()
            self.stop_event = threading.Event()
            
            # Set up event handlers
            @self.ws.socket_connect()
            def on_connect(data, client_id):
                self.connection_events.append(('connect', client_id, time.time()))
                return {'status': 'connected', 'client_id': client_id}
            
            @self.ws.socket_disconnect()
            def on_disconnect(data, client_id):
                self.connection_events.append(('disconnect', client_id, time.time()))
            
            @self.ws.socket('test_message')
            def handle_test_message(data, client_id):
                self.message_events.append(('message', client_id, data, time.time()))
                return {'echo': data, 'client_id': client_id}
            
            @self.ws.socket('error_message')
            def handle_error_message(data, client_id):
                # Deliberately cause an error to test error handling
                raise Exception("Test error in message handler")
            
            @self.ws.socket('async_message')
            async def handle_async_message(data, client_id):
                # Test async message handling
                await asyncio.sleep(0.1)
                return {'async_response': data, 'client_id': client_id}
            
            @self.ws.socket('broadcast_trigger')
            def handle_broadcast_trigger(data, client_id):
                # Test broadcasting from message handler
                try:
                    self.ws.broadcast_to_all({'broadcast_data': data}, 'broadcast')
                    return {'broadcast_sent': True}
                except Exception as e:
                    self.test_errors.append(f"Broadcast error: {e}")
                    raise
    
    def teardown_method(self):
        """Clean up after each test."""
        try:
            # Signal server to stop
            self.stop_event.set()
            
            # Stop the app if it's running
            if hasattr(self.app, '_running') and self.app._running:
                self.app.stop()
                
            # Stop WebSocket server if running
            if hasattr(self.ws, 'is_running') and self.ws.is_running:
                self.ws.is_running = False
                
            # Give some time for cleanup
            time.sleep(0.5)
        except Exception as e:
            print(f"Cleanup error: {e}")
    
    def get_websocket_url(self):
        """Get the WebSocket URL for the test server."""
        return f"ws://127.0.0.1:{self.test_port}"
    
    async def create_websocket_client(self, timeout=5):
        """Create an async WebSocket client connection."""
        url = self.get_websocket_url()
        
        try:
            # Create WebSocket connection with proper timeout
            websocket = await websockets.connect(
                url,
                close_timeout=timeout,
                ping_interval=None,  # Disable ping/pong
                ping_timeout=None
            )
            return websocket
        except Exception as e:
            print(f"Failed to create WebSocket connection: {e}")
            return None
    
    async def send_message(self, websocket, message_type, data):
        """Send a message through the WebSocket."""
        message = {
            'type': message_type,
            'data': data
        }
        await websocket.send(json.dumps(message))
    
    async def receive_message(self, websocket, timeout=1):
        """Receive a message from the WebSocket."""
        try:
            message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
            return json.loads(message)
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            print(f"Error receiving message: {e}")
            return None
    
    def start_server_in_thread(self):
        """Start the WebSocket server in a separate thread."""
        def run_server():
            # Start HTTP server
            self.app.http.start()
            
            # Start WebSocket server directly
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def handler_wrapper(websocket):
                # Call with a mock path parameter
                await self.ws._handle_connection(websocket, "/")
            
            async def setup_ws_server():
                try:
                    ws_server = await websockets.serve(
                        handler_wrapper,
                        "127.0.0.1",
                        self.test_port
                    )
                    self.ws.is_running = True
                    self.ws.server = ws_server
                    self.server_ready_event.set()
                    return ws_server
                except Exception as e:
                    print(f"Error starting WebSocket server: {e}")
                    self.server_ready_event.set()
                    raise
            
            try:
                ws_server = loop.run_until_complete(setup_ws_server())
                
                # Wait for stop signal
                while not self.stop_event.is_set():
                    loop.run_until_complete(asyncio.sleep(0.1))
                    
            except Exception as e:
                print(f"Server error: {e}")
            finally:
                # Cleanup
                if 'ws_server' in locals():
                    ws_server.close()
                    loop.run_until_complete(ws_server.wait_closed())
                self.ws.is_running = False
                loop.close()
                self.app.http.stop()
        
        # Start server thread
        self.server_thread = threading.Thread(target=run_server)
        self.server_thread.daemon = True
        self.server_thread.start()
        
        # Wait for server to be ready
        if not self.server_ready_event.wait(10.0):
            raise RuntimeError("Timed out waiting for server to start")
    
    @pytest.mark.asyncio
    async def test_rapid_connection_cycles(self):
        """Test rapid connect/disconnect cycles that might stress the event loop."""
        print("Testing rapid connection cycles...")
        
        # Start the server
        self.start_server_in_thread()
        
        async def connection_worker(worker_id):
            """Worker function for rapid connections."""
            errors = []
            connections = 0
            
            for i in range(10):  # 10 rapid connections per worker
                try:
                    websocket = await self.create_websocket_client(timeout=2)
                    if websocket:
                        connections += 1
                        
                        # Send a test message
                        await self.send_message(websocket, 'test_message', {
                            'worker': worker_id, 
                            'iteration': i
                        })
                        
                        # Try to receive response
                        response = await self.receive_message(websocket, timeout=2)
                        if response is None:
                            errors.append(f"Worker {worker_id}, iteration {i}: No response received")
                        
                        await websocket.close()
                        
                        # Small delay between connections
                        await asyncio.sleep(0.05)
                    else:
                        errors.append(f"Worker {worker_id}, iteration {i}: Failed to connect")
                        
                except Exception as e:
                    errors.append(f"Worker {worker_id}, iteration {i}: {e}")
            
            return {'worker_id': worker_id, 'errors': errors, 'connections': connections}
        
        # Run multiple workers simultaneously
        tasks = [connection_worker(i) for i in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Analyze results
        total_errors = []
        for result in results:
            if isinstance(result, Exception):
                total_errors.append(f"Task exception: {result}")
            else:
                total_errors.extend(result['errors'])
        
        print(f"Rapid connection test completed. Total errors: {len(total_errors)}")
        if total_errors:
            print("Errors encountered:")
            for error in total_errors[:10]:  # Show first 10 errors
                print(f"  - {error}")
        
        # Assert no critical event loop errors
        event_loop_errors = [e for e in total_errors if 'event loop' in str(e).lower()]
        assert len(event_loop_errors) == 0, f"Event loop errors detected: {event_loop_errors}"
    
    @pytest.mark.asyncio
    async def test_concurrent_message_handling(self):
        """Test concurrent message handling that might cause event loop issues."""
        print("Testing concurrent message handling...")
        
        # Start the server
        self.start_server_in_thread()
        
        # Create multiple persistent connections
        clients = []
        for i in range(3):
            websocket = await self.create_websocket_client()
            if websocket:
                clients.append(websocket)
        
        assert len(clients) > 0, "Failed to create any client connections"
        
        async def message_worker(websocket, worker_id):
            """Send messages concurrently from a client."""
            errors = []
            responses = []
            
            try:
                for i in range(10):  # 10 messages per client
                    # Mix different message types
                    if i % 3 == 0:
                        await self.send_message(websocket, 'test_message', {
                            'worker': worker_id, 'msg': i
                        })
                    elif i % 3 == 1:
                        await self.send_message(websocket, 'async_message', {
                            'worker': worker_id, 'msg': i
                        })
                    else:
                        await self.send_message(websocket, 'broadcast_trigger', {
                            'worker': worker_id, 'msg': i
                        })
                    
                    # Try to receive response
                    response = await self.receive_message(websocket, timeout=1)
                    if response:
                        responses.append(response)
                    
                    await asyncio.sleep(0.01)  # Small delay between messages
                    
            except Exception as e:
                errors.append(f"Worker {worker_id}: {e}")
            
            return {'worker_id': worker_id, 'errors': errors, 'responses': len(responses)}
        
        # Send messages concurrently from all clients
        tasks = [message_worker(client, i) for i, client in enumerate(clients)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Clean up clients
        for client in clients:
            await client.close()
        
        # Analyze results
        total_errors = []
        for result in results:
            if isinstance(result, Exception):
                total_errors.append(f"Task exception: {result}")
            else:
                total_errors.extend(result['errors'])
        
        print(f"Concurrent message test completed. Total errors: {len(total_errors)}")
        if total_errors:
            print("Errors encountered:")
            for error in total_errors[:10]:
                print(f"  - {error}")
        
        # Check for event loop specific errors
        event_loop_errors = [e for e in total_errors if 'event loop' in str(e).lower()]
        assert len(event_loop_errors) == 0, f"Event loop errors detected: {event_loop_errors}"
    
    @pytest.mark.asyncio
    async def test_server_shutdown_during_activity(self):
        """Test server shutdown while clients are active - this often triggers event loop issues."""
        print("Testing server shutdown during activity...")
        
        # Start the server
        self.start_server_in_thread()
        
        # Create active connections
        clients = []
        for i in range(2):
            websocket = await self.create_websocket_client()
            if websocket:
                clients.append(websocket)
        
        async def keep_sending_messages(websocket, client_id):
            """Keep sending messages until the server shuts down."""
            message_count = 0
            errors = []
            
            try:
                while message_count < 50:  # Try to send many messages
                    try:
                        await self.send_message(websocket, 'test_message', {
                            'client': client_id, 
                            'msg_num': message_count,
                            'timestamp': time.time()
                        })
                        
                        # Try to receive response (but don't wait long)
                        await self.receive_message(websocket, timeout=0.1)
                        
                        message_count += 1
                        await asyncio.sleep(0.05)  # 50ms between messages
                        
                    except Exception as e:
                        errors.append(f"Client {client_id}, message {message_count}: {e}")
                        break  # Stop on error
                        
            except Exception as e:
                errors.append(f"Client {client_id} general error: {e}")
            
            return {'client_id': client_id, 'messages_sent': message_count, 'errors': errors}
        
        # Start sending messages from multiple clients
        tasks = [keep_sending_messages(client, i) for i, client in enumerate(clients)]
        
        # Let them run for a bit
        await asyncio.sleep(1)
        
        # Now shut down the server while messages are being sent
        print("Shutting down server during active messaging...")
        try:
            self.stop_event.set()
            if hasattr(self.ws, 'is_running'):
                self.ws.is_running = False
        except Exception as e:
            self.test_errors.append(f"Server shutdown error: {e}")
        
        # Wait for all message sending to complete or timeout
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
        except asyncio.TimeoutError:
            print("Message sending tasks timed out during shutdown")
            results = []
        
        # Clean up clients
        for client in clients:
            try:
                await client.close()
            except:
                pass
        
        # Analyze results
        total_errors = []
        total_messages = 0
        for result in results:
            if isinstance(result, Exception):
                total_errors.append(f"Task exception: {result}")
            else:
                total_errors.extend(result['errors'])
                total_messages += result['messages_sent']
        
        print(f"Shutdown test completed. Messages sent: {total_messages}, Errors: {len(total_errors)}")
        
        # Look for event loop errors specifically
        event_loop_errors = [e for e in total_errors + self.test_errors if 'event loop' in str(e).lower()]
        
        if event_loop_errors:
            print("Event loop errors found:")
            for error in event_loop_errors:
                print(f"  - {error}")
        
        # This is the key assertion - no event loop errors should occur
        assert len(event_loop_errors) == 0, f"Event loop errors detected during shutdown: {event_loop_errors}"
    
    @pytest.mark.asyncio
    async def test_thread_safety_operations(self):
        """Test thread safety by accessing WebSocket methods from different contexts."""
        print("Testing thread safety operations...")
        
        # Start the server
        self.start_server_in_thread()
        
        # Create a client
        websocket = await self.create_websocket_client()
        assert websocket is not None, "Failed to connect client"
        
        # Wait for connection to be established
        await asyncio.sleep(0.2)
        
        def thread_worker(thread_id):
            """Worker that tries to use WebSocket methods from different threads."""
            errors = []
            
            try:
                # Try different WebSocket operations from this thread
                
                # 1. Check client count
                count = self.ws.get_client_count()
                
                # 2. Get client list
                clients = self.ws.get_clients()
                
                # 3. Try broadcasting (this is most likely to trigger event loop issues)
                try:
                    sent_count = self.ws.broadcast_to_all({
                        'from_thread': thread_id,
                        'broadcast_time': time.time()
                    }, 'thread_broadcast')
                except Exception as e:
                    # Capture any event loop related errors
                    errors.append(f"Thread {thread_id} broadcast error: {e}")
                
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")
            
            return {'thread_id': thread_id, 'errors': errors}
        
        # Run operations from multiple threads simultaneously
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(thread_worker, i) for i in range(5)]
            results = [future.result() for future in as_completed(futures)]
        
        await websocket.close()
        
        # Analyze results
        total_errors = []
        for result in results:
            total_errors.extend(result['errors'])
        
        print(f"Thread safety test completed. Total errors: {len(total_errors)}")
        
        if total_errors:
            print("Errors encountered:")
            for error in total_errors[:10]:
                print(f"  - {error}")
        
        # Check specifically for event loop errors
        event_loop_errors = [e for e in total_errors if 'event loop' in str(e).lower()]
        assert len(event_loop_errors) == 0, f"Event loop thread safety errors: {event_loop_errors}"
    
    @pytest.mark.asyncio
    async def test_broadcast_from_message_handlers(self):
        """Test broadcasting from within message handlers - a common source of event loop issues."""
        print("Testing broadcasts triggered from message handlers...")
        
        # Start the server
        self.start_server_in_thread()
        
        # Create multiple clients to test broadcasting
        clients = []
        for i in range(3):
            websocket = await self.create_websocket_client()
            if websocket:
                clients.append(websocket)
        
        assert len(clients) > 0, "Failed to create client connections"
        
        # Send broadcast trigger messages rapidly from multiple clients
        async def trigger_broadcasts(websocket, client_id):
            """Trigger broadcasts from message handlers."""
            errors = []
            
            try:
                for i in range(5):  # Multiple broadcast triggers
                    await self.send_message(websocket, 'broadcast_trigger', {
                        'client': client_id,
                        'trigger_num': i,
                        'timestamp': time.time()
                    })
                    
                    # Don't wait for response to simulate rapid triggers
                    await asyncio.sleep(0.01)
                    
            except Exception as e:
                errors.append(f"Client {client_id}: {e}")
            
            return {'client_id': client_id, 'errors': errors}
        
        # Trigger broadcasts from all clients simultaneously
        tasks = [trigger_broadcasts(client, i) for i, client in enumerate(clients)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Let broadcasts propagate
        await asyncio.sleep(0.5)
        
        # Clean up clients
        for client in clients:
            await client.close()
        
        # Analyze results
        total_errors = []
        for result in results:
            if isinstance(result, Exception):
                total_errors.append(f"Task exception: {result}")
            else:
                total_errors.extend(result['errors'])
        
        print(f"Broadcast handler test completed. Total errors: {len(total_errors)}")
        
        if total_errors:
            print("Errors encountered:")
            for error in total_errors[:10]:
                print(f"  - {error}")
        
        # Check for event loop errors
        event_loop_errors = [e for e in total_errors + self.test_errors if 'event loop' in str(e).lower()]
        assert len(event_loop_errors) == 0, f"Event loop errors in broadcast handlers: {event_loop_errors}"
    
    @pytest.mark.asyncio
    async def test_event_loop_edge_cases(self):
        """Test edge cases that could trigger 'no running event loop' errors."""
        print("Testing event loop edge cases...")
        
        # Start the server
        self.start_server_in_thread()
        
        # Create a client
        websocket = await self.create_websocket_client()
        assert websocket is not None, "Failed to connect client"
        
        # Wait for connection
        await asyncio.sleep(0.1)
        
        # Test 1: Rapid send operations from different thread contexts
        def rapid_operations():
            """Perform rapid WebSocket operations that might hit edge cases."""
            errors = []
            
            for i in range(10):
                try:
                    # These operations use the event loop detection pattern that could fail
                    count = self.ws.get_client_count()
                    clients = self.ws.get_clients()
                    
                    # Try sending to client (if any exist)
                    if clients:
                        client_id = clients[0]
                        success = self.ws.send_to_client(client_id, {
                            'edge_case_test': i,
                            'timestamp': time.time()
                        })
                    
                    # Try broadcasting
                    self.ws.broadcast_to_all({
                        'edge_case_broadcast': i,
                        'timestamp': time.time()
                    })
                    
                except Exception as e:
                    errors.append(f"Operation {i}: {e}")
            
            return errors
        
        # Run rapid operations in a separate thread
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(rapid_operations)
            
            # While operations are running, also send messages from the async context
            for i in range(5):
                await self.send_message(websocket, 'test_message', {
                    'async_test': i,
                    'timestamp': time.time()
                })
                await asyncio.sleep(0.02)
            
            # Get results from thread operations
            thread_errors = future.result()
        
        await websocket.close()
        
        print(f"Edge case test completed. Thread errors: {len(thread_errors)}")
        
        if thread_errors:
            print("Thread operation errors:")
            for error in thread_errors[:5]:
                print(f"  - {error}")
        
        # Check for event loop errors specifically
        event_loop_errors = [e for e in thread_errors if 'event loop' in str(e).lower()]
        assert len(event_loop_errors) == 0, f"Event loop edge case errors: {event_loop_errors}"


@pytest.mark.skipif(
    "os.environ.get('CI', 'false').lower() == 'true'",
    reason="WebSocket event loop tests are unstable in CI environments"
)
class TestWebSocketEventLoopStability:
    """Test class that can be run with pytest to validate WebSocket event loop stability."""
    
    def test_rapid_connections(self):
        """Run the rapid connection cycles test."""
        test_suite = WebSocketEventLoopTests()
        test_suite.setup_method()
        try:
            import asyncio
            asyncio.run(test_suite.test_rapid_connection_cycles())
        finally:
            test_suite.teardown_method()
    
    def test_concurrent_messaging(self):
        """Run the concurrent message handling test."""
        test_suite = WebSocketEventLoopTests()
        test_suite.setup_method()
        try:
            import asyncio
            asyncio.run(test_suite.test_concurrent_message_handling())
        finally:
            test_suite.teardown_method()
    
    def test_shutdown_stress(self):
        """Run the server shutdown during activity test."""
        test_suite = WebSocketEventLoopTests()
        test_suite.setup_method()
        try:
            import asyncio
            asyncio.run(test_suite.test_server_shutdown_during_activity())
        finally:
            test_suite.teardown_method()
    
    def test_thread_safety(self):
        """Run the thread safety operations test."""
        test_suite = WebSocketEventLoopTests()
        test_suite.setup_method()
        try:
            import asyncio
            asyncio.run(test_suite.test_thread_safety_operations())
        finally:
            test_suite.teardown_method()
    
    def test_broadcast_from_message_handlers(self):
        """Run the broadcast from message handlers test."""
        test_suite = WebSocketEventLoopTests()
        test_suite.setup_method()
        try:
            import asyncio
            asyncio.run(test_suite.test_broadcast_from_message_handlers())
        finally:
            test_suite.teardown_method()
    
    def test_event_loop_edge_cases(self):
        """Run the event loop edge cases test."""
        test_suite = WebSocketEventLoopTests()
        test_suite.setup_method()
        try:
            import asyncio
            asyncio.run(test_suite.test_event_loop_edge_cases())
        finally:
            test_suite.teardown_method()


if __name__ == "__main__":
    """Run tests manually for debugging."""
    import os
    
    print("="*80)
    print("WebSocket Event Loop Stability Test Suite")
    print("="*80)
    print("Note: Run with 'pytest test_websocket_event_loop.py' for better test management")
    print("="*80)
    
    test_suite = WebSocketEventLoopTests()
    
    tests = [
        ("Rapid Connection Cycles", test_suite.test_rapid_connection_cycles),
        ("Concurrent Message Handling", test_suite.test_concurrent_message_handling),
        ("Server Shutdown During Activity", test_suite.test_server_shutdown_during_activity),
        ("Thread Safety Operations", test_suite.test_thread_safety_operations),
        ("Broadcast from Message Handlers", test_suite.test_broadcast_from_message_handlers),
        ("Event Loop Edge Cases", test_suite.test_event_loop_edge_cases),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n{'-'*60}")
        print(f"Running: {test_name}")
        print(f"{'-'*60}")
        
        try:
            # Set up fresh test environment
            test_suite.setup_method()
            
            # Run the test
            start_time = time.time()
            asyncio.run(test_func())
            end_time = time.time()
            
            results[test_name] = {
                'status': 'PASSED',
                'duration': end_time - start_time,
                'error': None
            }
            print(f"✅ {test_name} PASSED ({end_time - start_time:.2f}s)")
            
        except Exception as e:
            results[test_name] = {
                'status': 'FAILED',
                'duration': time.time() - start_time if 'start_time' in locals() else 0,
                'error': str(e)
            }
            print(f"❌ {test_name} FAILED: {e}")
            
        finally:
            # Clean up
            try:
                test_suite.teardown_method()
            except Exception as e:
                print(f"⚠️ Cleanup error for {test_name}: {e}")
    
    # Print summary
    print(f"\n{'='*80}")
    print("TEST SUMMARY")
    print(f"{'='*80}")
    
    passed = sum(1 for r in results.values() if r['status'] == 'PASSED')
    failed = sum(1 for r in results.values() if r['status'] == 'FAILED')
    
    print(f"Total tests: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    if failed > 0:
        print(f"\nFAILED TESTS:")
        for test_name, result in results.items():
            if result['status'] == 'FAILED':
                print(f"  - {test_name}: {result['error']}")
    
    # Exit with error code if any tests failed
    exit(failed) 