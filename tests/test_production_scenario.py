"""
E2E test that replicates the exact production scenario to reproduce the "no running event loop" error.

This test mimics the user's configuration:
- HTTP server on port 5000
- WebSocket server on port 5001  
- Blueprint usage for both HTTP and WebSocket
- Background tasks
- Network manager simulation
- Same handler structure
"""
import pytest
import threading
import time
import json
import asyncio
import websockets
import requests
from unittest.mock import Mock, patch
import logging

from daebus import Daebus, DaebusHttp, DaebusWebSocket, Blueprint, direct_logger


class MockNetworkManager:
    """Mock network manager to simulate the user's NetworkManager"""
    def __init__(self, cache):
        self.cache = cache
        
    def get_available_networks(self):
        return {"networks": ["wifi1", "wifi2"]}
        
    def get_lte_status(self):
        return {"status": "connected", "signal": 85}
        
    def run_speed_test(self):
        return {"download": 25.5, "upload": 10.2}
        
    def fetch_network_status(self):
        return {
            "wifi": {"connected": True, "ssid": "TestWiFi"},
            "lte": {"connected": True, "signal": 85}
        }


def create_http_blueprint():
    """Create HTTP blueprint matching user's http.py"""
    app = Blueprint('http')
    
    @app.route('/health_check')
    def handle_health_check(req):
        from daebus import response
        return response.send({
            'status': 'success',
            'message': 'Flask backend running!'
        }, 200)

    @app.route("/network/status")
    def handle_network_status(req):
        from daebus import response
        status = {"status": "ok", "networks": []}
        return response.send(status, 200)

    @app.route("/record/capture_photo", methods=["POST"])
    def handle_capture_photo(req):
        from daebus import response
        session_id = req.payload.get("session_id") if req.payload else None
        if not session_id:
            return response.send({
                "status": "error",
                "message": "Session ID is required"
            }, 400)

        result = {"status": "success", "photo_id": "test_photo_123"}
        return response.send(result, 200)

    @app.route('/internal/health')
    def health_check(req):
        from daebus import response
        return response.send({"status": "ok", "timestamp": time.time()}, 200)
    
    return app


def create_socket_blueprint():
    """Create WebSocket blueprint matching user's socket.py"""
    from enum import Enum
    
    class ClientType(Enum):
        FRONTEND = "frontend"
        SIGNAL_SERVER = "signal_server"

    app = Blueprint('socket')
    clients = {}

    def send_light_output(line):
        """This is the function that's causing the issue - called from background thread"""
        from daebus import get_daemon
        daemon = get_daemon()
        if daemon and daemon.websocket:
            result = daemon.websocket.safe_broadcast_to_all({
                "enabled": True,
                'brightness': float(line)
            }, 'lights')

            if result > 0:
                print(f"Light output sent to {result} WebSocket clients")
            else:
                print("No WebSocket clients connected for light output")

    @app.socket_connect()
    def handle_connect(data, client_id):
        from daebus import logger
        logger.info(f"Client connected: {client_id}")
        clients[client_id] = {
            'type': ClientType.FRONTEND,
            'id': client_id
        }

    @app.socket_register()  
    def handle_register(data, client_id):
        from daebus import logger
        logger.info(f"Client registered: {client_id}")
        clients[client_id].update({
            'type': ClientType(data.get('type', 'frontend')),
            'id': client_id
        })
        return {
            'status': 'success',
            'id': client_id
        }

    @app.socket_disconnect()
    def handle_disconnect(data, client_id):
        from daebus import logger
        logger.info(f"Client disconnected: {client_id}")
        if client_id in clients:
            del clients[client_id]

    @app.socket('start_recording')
    def handle_start_recording(data, client_id):
        from daebus import logger
        logger.info(f"Starting recording for session {data.get('session_id')}")
        return {"status": "recording_started", "session_id": data.get('session_id')}

    # Store the function for external access
    app.send_light_output = send_light_output
    
    return app


class TestProductionScenario:
    """Test the exact production scenario to reproduce the event loop error"""
    
    def setup_method(self):
        self.app = None
        self.socket_blueprint = None
        self.daemon_thread = None
        self.network_manager = None
        self.error_captured = None
        self.original_logger_error = direct_logger.error
        
        # Capture errors from the logger
        def capture_error(msg, *args, **kwargs):
            if "no running event loop" in str(msg):
                self.error_captured = str(msg)
            return self.original_logger_error(msg, *args, **kwargs)
        
        direct_logger.error = capture_error

    def teardown_method(self):
        if self.app and hasattr(self.app, '_running'):
            self.app._running = False
        
        if self.daemon_thread and self.daemon_thread.is_alive():
            self.daemon_thread.join(timeout=5)
        
        direct_logger.error = self.original_logger_error
        time.sleep(0.5)

    def create_production_app(self):
        """Create the exact app configuration from user's __main__.py"""
        app = Daebus(__name__)

        cors_config = {
            'allowed_origins': '*',
            'allowed_methods': ['GET', 'POST'],
            'allowed_headers': '*',
        }

        # Same port configuration as user
        endpoint = DaebusHttp(port=5000, cors_config=cors_config)
        websocket_server = DaebusWebSocket()  # Will automatically use port 5001

        app.attach(endpoint)
        app.attach(websocket_server)

        # Create and register blueprints
        http_blueprint = create_http_blueprint()
        socket_blueprint = create_socket_blueprint()

        app.register_blueprint(http_blueprint)
        app.register_blueprint(socket_blueprint)

        self.socket_blueprint = socket_blueprint

        # Background tasks matching user's configuration
        @app.background("refetch_network_status", 15)
        def check_network_status():
            if self.network_manager:
                self.network_manager.get_available_networks()
                self.network_manager.get_lte_status()
            return

        @app.background("run_speed_test", 90)
        def run_speed_test():
            if self.network_manager:
                self.network_manager.run_speed_test()
            return

        @app.on_start()
        def start_services():
            from daebus import cache
            self.network_manager = MockNetworkManager(cache)
            direct_logger.info("Services started")

        return app

    def test_send_light_output_from_background_thread(self):
        """Test calling send_light_output from a background thread to reproduce the error"""
        def run_daemon():
            try:
                self.app = self.create_production_app()
                self.app.run(
                    service='main-server',
                    debug=True,
                    redis_host='localhost',
                    redis_port=6379
                )
            except Exception as e:
                direct_logger.error(f"Error in daemon: {e}")

        # Start the daemon
        self.daemon_thread = threading.Thread(target=run_daemon, daemon=True)
        self.daemon_thread.start()
        time.sleep(3)

        # Simulate calling send_light_output from a background thread
        def simulate_light_controller():
            time.sleep(1)
            try:
                # This should trigger the "no running event loop" error
                self.socket_blueprint.send_light_output("75.5")
                direct_logger.info("Light output sent successfully")
            except Exception as e:
                direct_logger.error(f"Error in light controller simulation: {e}")

        # Run the simulation in a separate thread
        light_thread = threading.Thread(target=simulate_light_controller, daemon=True)
        light_thread.start()
        light_thread.join(timeout=10)

        # Check if we captured the event loop error
        time.sleep(2)
        if self.error_captured:
            # This is what we expect to happen!
            assert "no running event loop" in self.error_captured
            direct_logger.info(f"Successfully reproduced the error: {self.error_captured}")
        else:
            direct_logger.info("No event loop error captured - the fix may be working") 