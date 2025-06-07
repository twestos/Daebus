#!/usr/bin/env python3
"""
Test WebSocket and HTTP server port behavior

This test verifies how the HTTP and WebSocket servers handle port configuration
and whether they can operate on the same port or automatically separate.
"""

import pytest
import time
import socket
from unittest.mock import patch
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daebus.modules.daemon import Daebus
from daebus.modules.http import DaebusHttp
from daebus.modules.websocket import DaebusWebSocket


def find_free_port():
    """Find and return a free port number."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class TestWebSocketHttpPortBehavior:
    """Test cases for HTTP and WebSocket port behavior."""
    
    def setup_method(self):
        """Set up test environment."""
        self.test_port = find_free_port()
        self.app = None
        self.cleanup_needed = False
        
    def teardown_method(self):
        """Clean up after test."""
        if self.cleanup_needed and self.app:
            try:
                # Stop servers
                if hasattr(self.app, 'http') and self.app.http:
                    self.app.http.stop()
                if hasattr(self.app, 'websocket') and self.app.websocket:
                    self.app.websocket.is_running = False
                    
                # Give some time for cleanup
                time.sleep(0.5)
            except Exception as e:
                print(f"Cleanup error: {e}")

    def test_current_port_separation_behavior(self):
        """Test the current behavior where HTTP and WebSocket use different ports."""
        
        # Mock Redis to avoid actual connection
        with patch('daebus.modules.daemon.Redis'), \
             patch('daebus.modules.daemon.BackgroundScheduler'):
            
            self.app = Daebus("test_port_separation")
            
            # Set up HTTP server on test port
            http = DaebusHttp(port=self.test_port)
            self.app.attach(http)
            
            # Set up WebSocket server (should automatically use different port)
            websocket = DaebusWebSocket()
            self.app.attach(websocket)
            
            self.cleanup_needed = True
            
            # Verify port configuration
            assert http.port == self.test_port
            assert websocket.port == self.test_port + 1  # Should be HTTP port + 1
            assert websocket.actual_port == self.test_port + 1
            
            print(f"HTTP configured for port: {http.port}")
            print(f"WebSocket configured for port: {websocket.port}")
            print(f"WebSocket actual port: {websocket.actual_port}")

    def test_explicit_websocket_port_with_http(self):
        """Test behavior when WebSocket port is explicitly specified along with HTTP."""
        
        with patch('daebus.modules.daemon.Redis'), \
             patch('daebus.modules.daemon.BackgroundScheduler'):
            
            self.app = Daebus("test_explicit_ports")
            
            # Set up HTTP server
            http = DaebusHttp(port=self.test_port)
            self.app.attach(http)
            
            # Set up WebSocket server with explicit different port
            websocket_port = self.test_port + 2
            websocket = DaebusWebSocket(port=websocket_port)
            self.app.attach(websocket)
            
            self.cleanup_needed = True
            
            # Verify ports
            assert http.port == self.test_port
            assert websocket.port == websocket_port
            assert websocket.actual_port == websocket_port

    def test_websocket_port_conflict_detection(self):
        """Test that WebSocket detects and resolves port conflicts with HTTP."""
        
        with patch('daebus.modules.daemon.Redis'), \
             patch('daebus.modules.daemon.BackgroundScheduler'):
            
            self.app = Daebus("test_conflict_detection")
            
            # Set up HTTP server
            http = DaebusHttp(port=self.test_port)
            self.app.attach(http)
            
            # Try to set up WebSocket on the same port (should be auto-resolved)
            websocket = DaebusWebSocket(port=self.test_port)  # Same port as HTTP
            self.app.attach(websocket)
            
            self.cleanup_needed = True
            
            # Verify that WebSocket was moved to a different port
            assert http.port == self.test_port
            assert websocket.port == self.test_port + 1  # Should be auto-adjusted
            assert websocket.actual_port == self.test_port + 1

    def test_websocket_without_http_requires_port(self):
        """Test that WebSocket requires explicit port when no HTTP server is present."""
        
        with patch('daebus.modules.daemon.Redis'), \
             patch('daebus.modules.daemon.BackgroundScheduler'):
            
            self.app = Daebus("test_no_http")
            
            # Try to attach WebSocket without HTTP and without explicit port
            websocket = DaebusWebSocket()  # No port specified
            
            with pytest.raises(RuntimeError) as exc_info:
                self.app.attach(websocket)
            
            assert "WebSocket port must be specified" in str(exc_info.value)

    def test_handler_registration_and_port_configuration(self):
        """Test that HTTP and WebSocket handlers are properly registered with correct ports."""
        
        with patch('daebus.modules.daemon.Redis'), \
             patch('daebus.modules.daemon.BackgroundScheduler'):
            
            self.app = Daebus("test_handlers")
            
            # Set up servers
            http = DaebusHttp(port=self.test_port)
            websocket = DaebusWebSocket()
            
            self.app.attach(http)
            self.app.attach(websocket)
            
            self.cleanup_needed = True
            
            # Add test routes and handlers
            @self.app.route("/test")
            def test_route(req):
                return {"message": "HTTP server works", "port": self.test_port}
            
            @self.app.socket("test_message")
            def test_socket_handler(data, client_id):
                return {"message": "WebSocket works", "echo": data, "client": client_id}
            
            # Verify HTTP route registration
            assert "/test" in http.routes
            route_info = http.routes["/test"]
            assert route_info["function"] == test_route
            assert "GET" in route_info["methods"]
            
            # Verify WebSocket handler registration
            assert "test_message" in websocket.message_handlers
            assert websocket.message_handlers["test_message"] == test_socket_handler
            
            # Verify port configuration
            assert http.port == self.test_port
            assert websocket.port == self.test_port + 1
            assert websocket.actual_port == self.test_port + 1
            
            print(f"✅ HTTP route registered on port {http.port}")
            print(f"✅ WebSocket handler registered on port {websocket.actual_port}")
            print(f"✅ Port separation working: HTTP={http.port}, WebSocket={websocket.actual_port}")

    def test_get_websocket_port_method(self):
        """Test the get_websocket_port() method."""
        
        with patch('daebus.modules.daemon.Redis'), \
             patch('daebus.modules.daemon.BackgroundScheduler'):
            
            self.app = Daebus("test_get_port")
            
            # Set up servers
            http = DaebusHttp(port=self.test_port)
            websocket = DaebusWebSocket()
            
            self.app.attach(http)
            self.app.attach(websocket)
            
            self.cleanup_needed = True
            
            # After attach, should return the configured port
            actual_port = websocket.get_websocket_port()
            assert actual_port == self.test_port + 1  # Should be HTTP port + 1
            
            print(f"✅ get_websocket_port() returns {actual_port} (HTTP port + 1)")

    def test_port_info_logging(self, caplog):
        """Test that proper port information is logged."""
        
        with patch('daebus.modules.daemon.Redis'), \
             patch('daebus.modules.daemon.BackgroundScheduler'):
            
            self.app = Daebus("test_logging")
            
            # Set up servers
            http = DaebusHttp(port=self.test_port)
            websocket = DaebusWebSocket()
            
            self.app.attach(http)
            
            # Clear any existing log records
            caplog.clear()
            
            # Attach WebSocket (this should log port information)
            self.app.attach(websocket)
            
            self.cleanup_needed = True
            
            # Check that appropriate logs were created
            log_messages = [record.message for record in caplog.records]
            
            # Should log that WebSocket will use port + 1
            port_plus_one_logged = any(f"port {self.test_port + 1}" in msg for msg in log_messages)
            assert port_plus_one_logged, f"Expected port {self.test_port + 1} to be logged. Messages: {log_messages}"
            
            # Should log connection instructions
            connection_info_logged = any("For same-port WebSocket support" in msg for msg in log_messages)
            assert connection_info_logged, f"Expected connection info to be logged. Messages: {log_messages}"


if __name__ == "__main__":
    # Run a quick manual test
    test_instance = TestWebSocketHttpPortBehavior()
    test_instance.setup_method()
    
    try:
        print("Testing current port separation behavior...")
        test_instance.test_current_port_separation_behavior()
        print("✅ Port separation test passed")
        
        test_instance.teardown_method()
        test_instance.setup_method()
        
        print("Testing conflict detection...")
        test_instance.test_websocket_port_conflict_detection()
        print("✅ Conflict detection test passed")
        
        print("\n🎉 All manual tests passed!")
        print(f"HTTP and WebSocket use separate ports to avoid conflicts.")
        print(f"Run 'pytest tests/test_websocket_same_port.py' for full test suite.")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
    finally:
        test_instance.teardown_method() 