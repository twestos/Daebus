import pytest
from unittest.mock import MagicMock, patch
import json
from daebus import PubSubRequest, PubSubResponse


def test_pubsub_request_init():
    """Test PubSubRequest initialization"""
    payload = {
        "action": "test_action",
        "service": "test_service",
        "request_id": "123",
        "reply_to": "reply_channel",
        "data": {"foo": "bar"}
    }
    
    request = PubSubRequest(payload)
    
    assert request.raw["action"] == "test_action"
    assert request.service == "test_service"
    assert request.request_id == "123"
    assert request.reply_to == "reply_channel"
    assert request.payload == {}  # payload now contains parsed data from 'payload' field, not the raw dict


def test_pubsub_request_missing_fields():
    """Test PubSubRequest with missing fields"""
    payload = {
        "action": "test_action",
        # Missing service and reply_to
        "request_id": "123",
        "data": {"foo": "bar"}
    }
    
    request = PubSubRequest(payload)
    
    assert request.raw["action"] == "test_action"
    assert request.service is None
    assert request.request_id == "123"
    assert request.reply_to is None


def test_pubsub_request_raw_access():
    """Test PubSubRequest accessing raw data"""
    payload = {"action": "test_action", "nested": {"key": "value"}}
    request = PubSubRequest(payload)
    
    # Access via raw property for direct dictionary access
    assert request.raw["action"] == "test_action"
    assert request.raw["nested"]["key"] == "value"


def test_pubsub_response_init():
    """Test PubSubResponse initialization"""
    redis_mock = MagicMock()
    request = MagicMock()
    request.request_id = "123"
    request.reply_to = "reply_channel"
    
    response = PubSubResponse(redis_mock, request)
    
    assert response._redis is redis_mock
    assert response._req is request


def test_pubsub_response_success():
    """Test PubSubResponse success method"""
    redis_mock = MagicMock()
    request = MagicMock()
    request.request_id = "123"
    request.reply_to = "reply_channel"
    
    response = PubSubResponse(redis_mock, request)
    response.success({"result": "ok"})
    
    # Check that Redis publish was called with correct arguments
    redis_mock.publish.assert_called_once()
    channel, message = redis_mock.publish.call_args[0]
    
    assert channel == "reply_channel"
    
    # Parse the JSON message and check its contents
    message_data = json.loads(message)
    assert message_data["status"] == "success"
    assert message_data["request_id"] == "123"
    assert message_data["payload"]["result"] == "ok"


def test_pubsub_response_error():
    """Test PubSubResponse error method"""
    redis_mock = MagicMock()
    request = MagicMock()
    request.request_id = "123"
    request.reply_to = "reply_channel"
    
    response = PubSubResponse(redis_mock, request)
    response.error("Something went wrong")
    
    # Check that Redis publish was called with correct arguments
    redis_mock.publish.assert_called_once()
    channel, message = redis_mock.publish.call_args[0]
    
    assert channel == "reply_channel"
    
    # Parse the JSON message and check its contents
    message_data = json.loads(message)
    assert message_data["status"] == "error"
    assert message_data["request_id"] == "123"
    assert "error" in message_data["payload"]
    assert message_data["payload"]["error"] == "Something went wrong"


def test_pubsub_response_progress():
    """Test PubSubResponse progress method"""
    redis_mock = MagicMock()
    request = MagicMock()
    request.request_id = "123"
    request.reply_to = "reply_channel"
    
    response = PubSubResponse(redis_mock, request)
    response.progress({"status": "processing"}, 50)
    
    # Check that Redis publish was called with correct arguments
    redis_mock.publish.assert_called_once()
    channel, message = redis_mock.publish.call_args[0]
    
    assert channel == "reply_channel"
    
    # Parse the JSON message and check its contents
    message_data = json.loads(message)
    assert message_data["status"] == "progress"
    assert message_data["request_id"] == "123"
    assert message_data["payload"]["status"] == "processing"
    assert message_data["payload"]["progress_percentage"] == 50
    assert message_data["final"] is False


def test_pubsub_response_no_reply_channel():
    """Test PubSubResponse when no reply channel is specified"""
    redis_mock = MagicMock()
    request = MagicMock()
    request.request_id = "123"
    request.reply_to = None  # No reply channel
    request.service = "test_service"  # Need service for default channel
    
    response = PubSubResponse(redis_mock, request)
    
    # When no reply_to is specified, it should use service.responses channel
    response.success({"result": "ok"})
    redis_mock.publish.assert_called_once()
    channel, _ = redis_mock.publish.call_args[0]
    assert channel == "test_service.responses" 