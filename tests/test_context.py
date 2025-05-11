import pytest
from unittest.mock import MagicMock, patch
from daebus.modules import context
from daebus.modules.context import (
    set_daemon, get_daemon, set_context_type, get_context_type,
    request, response, broadcast, cache, logger
)


def test_daemon_context():
    """Test setting and getting daemon in context"""
    # Create a mock daemon
    mock_daemon = MagicMock()
    mock_daemon.name = "test_daemon"
    
    # Set the daemon in context
    set_daemon(mock_daemon)
    
    # Get the daemon from context
    daemon = get_daemon()
    
    # Check it's the same object
    assert daemon is mock_daemon
    assert daemon.name == "test_daemon"


def test_get_daemon_not_set():
    """Test getting daemon when not set"""
    # Store the current global daemon
    original_daemon = context._global_daemon
    
    # Set the global daemon to None
    context._global_daemon = None
    
    try:
        # Trying to get daemon should raise RuntimeError
        with pytest.raises(RuntimeError, match="Daebus not initialized"):
            get_daemon()
    finally:
        # Restore the original daemon to not affect other tests
        context._global_daemon = original_daemon


def test_context_type():
    """Test setting and getting context type"""
    # Set context type to http
    set_context_type('http')
    assert get_context_type() == 'http'
    
    # Set context type to pubsub
    set_context_type('pubsub')
    assert get_context_type() == 'pubsub'
    
    # Set context type to None
    set_context_type(None)
    assert get_context_type() is None


def test_invalid_context_type():
    """Test setting invalid context type"""
    with pytest.raises(ValueError, match="Invalid context type"):
        set_context_type('invalid')


def test_request_proxy_http_context():
    """Test request proxy in HTTP context"""
    # Create a mock daemon with HTTP request
    mock_daemon = MagicMock()
    mock_http_request = MagicMock()
    mock_http_request.method = "GET"
    mock_http_request.path = "/test"
    mock_daemon.request_http = mock_http_request
    
    # Set the daemon and context type
    set_daemon(mock_daemon)
    set_context_type('http')
    
    # Check request proxy forwards to HTTP request
    assert request.method == "GET"
    assert request.path == "/test"


def test_request_proxy_pubsub_context():
    """Test request proxy in pub/sub context"""
    # Create a mock daemon with pub/sub request
    mock_daemon = MagicMock()
    mock_pubsub_request = MagicMock()
    mock_pubsub_request.service = "test_service"
    mock_pubsub_request.request_id = "123"
    mock_daemon.request = mock_pubsub_request
    
    # Set the daemon and context type
    set_daemon(mock_daemon)
    set_context_type('pubsub')
    
    # Check request proxy forwards to pub/sub request
    assert request.service == "test_service"
    assert request.request_id == "123"


def test_response_proxy_http_context():
    """Test response proxy in HTTP context"""
    # Create a mock daemon with HTTP response
    mock_daemon = MagicMock()
    mock_http_response = MagicMock()
    mock_http_response.send = MagicMock(return_value=None)
    mock_daemon.response_http = mock_http_response
    
    # Set the daemon and context type
    set_daemon(mock_daemon)
    set_context_type('http')
    
    # Call HTTP response method
    response.send({"status": "ok"})
    
    # Check it was forwarded correctly
    mock_http_response.send.assert_called_once_with({"status": "ok"})


def test_response_proxy_pubsub_context():
    """Test response proxy in pub/sub context"""
    # Create a mock daemon with pub/sub response
    mock_daemon = MagicMock()
    mock_pubsub_response = MagicMock()
    mock_pubsub_response.success = MagicMock(return_value=None)
    mock_daemon.response = mock_pubsub_response
    
    # Set the daemon and context type
    set_daemon(mock_daemon)
    set_context_type('pubsub')
    
    # Call pub/sub response method
    response.success({"result": "ok"})
    
    # Check it was forwarded correctly
    mock_pubsub_response.success.assert_called_once_with({"result": "ok"})


def test_response_proxy_wrong_context():
    """Test response proxy with method from wrong context"""
    # Create a mock daemon
    mock_daemon = MagicMock()
    mock_daemon.logger = MagicMock()
    
    # Set the daemon and context type to HTTP
    set_daemon(mock_daemon)
    set_context_type('http')
    
    # Trying to call pub/sub method in HTTP context should raise AttributeError
    with pytest.raises(AttributeError, match="Method 'success\\(\\)' is for pub/sub responses"):
        response.success({"result": "ok"})
        
    # Set context type to pub/sub
    set_context_type('pubsub')
    
    # Trying to call HTTP method in pub/sub context should raise AttributeError
    with pytest.raises(AttributeError, match="Method 'send\\(\\)' is for HTTP responses"):
        response.send({"status": "ok"}) 