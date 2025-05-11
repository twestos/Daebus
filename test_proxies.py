"""
Simple test script to verify that our context-aware proxies are working correctly.

This script manually sets up contexts and tests the behavior of request and response
proxies in both HTTP and pub/sub contexts.

Run this script directly to see the results:
    python test_proxies.py
"""

import sys
import traceback
from Daebus.modules.context import (
    set_daemon, set_context_type, get_context_type,
    RequestProxy, ResponseProxy
)
from Daebus.modules.http import HttpRequest, HttpResponse
from Daebus.modules.request import PubSubRequest
from Daebus.modules.response import PubSubResponse


class MockDaemon:
    """Mock daemon class for testing the proxy system"""

    def __init__(self):
        self.logger = MockLogger()

        # Create request and response objects for pub/sub
        self.request = PubSubRequest({
            'action': 'test',
            'payload': {'foo': 'bar'},
            'request_id': '123',
            'service': 'test_service',
            'reply_to': 'test_channel'
        })
        self.response = PubSubResponse(None, self.request)

        # Create request and response objects for HTTP
        self.request_http = HttpRequest({
            'method': 'GET',
            'path': '/test',
            'headers': {'Content-Type': 'application/json'},
            'params': {'id': '123'},
            'json': {'foo': 'bar'}
        })
        self.response_http = HttpResponse(None)


class MockLogger:
    """Mock logger for testing"""

    def __init__(self):
        pass

    def warning(self, msg):
        print(f"WARNING: {msg}")

    def error(self, msg):
        print(f"ERROR: {msg}")

    def info(self, msg):
        print(f"INFO: {msg}")

    def debug(self, msg):
        print(f"DEBUG: {msg}")


def test_pubsub_context():
    """Test pub/sub context behavior"""
    set_context_type('pubsub')
    print("\n--- Testing pub/sub context ---")

    print("Request attributes:")
    print(f"  payload: {request.payload}")
    print(f"  request_id: {request.request_id}")
    print(f"  service: {request.service}")
    print(f"  reply_to: {request.reply_to}")

    try:
        print(f"  path (HTTP-specific): {request.path}")
    except Exception as e:
        print(f"  path (HTTP-specific): ERROR: {e}")

    print("\nResponse methods:")
    try:
        result = response.success({'message': 'Success'})
        print(f"  success(): {result}")
    except Exception as e:
        print(f"  success(): ERROR: {e}")

    try:
        result = response.error(Exception("Test error"))
        print(f"  error(): {result}")
    except Exception as e:
        print(f"  error(): ERROR: {e}")

    try:
        result = response.send({'message': 'Test'}, 200)
        print(f"  send(): {result}")
    except Exception as e:
        print(f"  send(): ERROR: {e}")


def test_http_context():
    """Test HTTP context behavior"""
    set_context_type('http')
    print("\n--- Testing HTTP context ---")

    print("Request attributes:")
    print(f"  payload: {request.payload}")
    print(f"  path: {request.path}")
    print(f"  method: {request.method}")
    print(f"  headers: {request.headers}")

    try:
        print(f"  reply_to (pub/sub specific): {request.reply_to}")
    except Exception as e:
        print(f"  reply_to (pub/sub specific): ERROR: {e}")

    print("\nResponse methods:")
    try:
        result = response.send({'message': 'Test'}, 200)
        print(f"  send(): {result}")
    except Exception as e:
        print(f"  send(): ERROR: {e}")

    try:
        result = response.success({'message': 'Success'})
        print(f"  success(): {result}")
    except Exception as e:
        print(f"  success(): ERROR: {e}")

    try:
        result = response.error(Exception("Test error"))
        print(f"  error(): {result}")
    except Exception as e:
        print(f"  error(): ERROR: {e}")


def test_no_context():
    """Test behavior when no context is set"""
    set_context_type(None)
    print("\n--- Testing with no context set ---")

    print("Request attributes:")
    print(f"  payload: {request.payload}")

    try:
        result = response.success({'message': 'Success'})
        print(f"  success(): {result}")
    except Exception as e:
        print(f"  success(): ERROR: {e}")


if __name__ == "__main__":
    # Create daemon and set up the context
    daemon = MockDaemon()
    set_daemon(daemon)

    # Create proxies
    request = RequestProxy()
    response = ResponseProxy()

    print("=== Testing Context-Aware Proxies ===")

    try:
        # Test pub/sub context
        test_pubsub_context()

        # Test HTTP context
        test_http_context()

        # Test with no context set
        test_no_context()

        print("\n=== All tests completed ===")
    except Exception as e:
        print(f"\nTest failed with exception: {e}")
        traceback.print_exc()
