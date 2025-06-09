import pytest
import json
import datetime
import decimal
from unittest.mock import MagicMock, AsyncMock, patch
from daebus import DaebusWebSocket, Daebus
from daebus.modules.websocket import WebSocketRequest, WebSocketResponse
from daebus.modules.http import DaebusJSONEncoder


@pytest.mark.asyncio
async def test_websocket_response_send_with_booleans():
    """Test that WebSocket responses handle boolean values correctly"""
    
    # Mock WebSocket connection
    mock_websocket = AsyncMock()
    mock_websocket.send = AsyncMock()
    
    # Create WebSocket response
    response = WebSocketResponse(mock_websocket, "test_client")
    
    # Send data with boolean values
    test_data = {
        'success': True,
        'completed': False,
        'user': {
            'active': True,
            'verified': False,
            'permissions': {
                'read': True,
                'write': False,
                'admin': False
            }
        },
        'features': [
            {'name': 'feature1', 'enabled': True},
            {'name': 'feature2', 'enabled': False}
        ]
    }
    
    await response.send(test_data)
    
    # Verify send was called
    mock_websocket.send.assert_called_once()
    
    # Parse the sent message to verify it's valid JSON
    sent_message = mock_websocket.send.call_args[0][0]
    parsed_message = json.loads(sent_message)
    
    # Verify the structure and boolean values are preserved
    assert parsed_message['type'] == 'response'
    assert parsed_message['data']['success'] is True
    assert parsed_message['data']['completed'] is False
    assert parsed_message['data']['user']['active'] is True
    assert parsed_message['data']['user']['verified'] is False
    assert parsed_message['data']['features'][0]['enabled'] is True
    assert parsed_message['data']['features'][1]['enabled'] is False


@pytest.mark.asyncio
async def test_websocket_response_send_with_complex_types():
    """Test that WebSocket responses handle complex data types correctly"""
    
    # Mock WebSocket connection
    mock_websocket = AsyncMock()
    mock_websocket.send = AsyncMock()
    
    # Create WebSocket response
    response = WebSocketResponse(mock_websocket, "test_client")
    
    # Send data with complex types
    test_data = {
        'timestamp': datetime.datetime(2023, 12, 25, 15, 30, 45),
        'users': [
            {
                'id': 1,
                'name': 'John',
                'active': True,
                'balance': decimal.Decimal('150.75'),
                'tags': {'admin', 'user', 'verified'},
                'created_at': datetime.date.today()
            },
            {
                'id': 2,
                'name': 'Jane',
                'active': False,
                'score': 95.7,
                'permissions': [True, False, True]
            }
        ],
        'metadata': {
            'total_count': 2,
            'has_more': False,
            'processing_time': datetime.timedelta(seconds=1.5),
            'binary_data': b'test binary data'
        }
    }
    
    await response.send(test_data)
    
    # Verify send was called
    mock_websocket.send.assert_called_once()
    
    # Parse the sent message to verify it's valid JSON
    sent_message = mock_websocket.send.call_args[0][0]
    parsed_message = json.loads(sent_message)
    
    # Verify the structure and data types are properly converted
    assert parsed_message['type'] == 'response'
    data = parsed_message['data']
    
    # Check datetime conversion
    assert data['timestamp'] == '2023-12-25T15:30:45'
    
    # Check user data
    assert data['users'][0]['active'] is True
    assert data['users'][1]['active'] is False
    assert data['users'][0]['balance'] == 150.75  # Decimal converted to float
    assert isinstance(data['users'][0]['tags'], list)  # Set converted to list
    assert set(data['users'][0]['tags']) == {'admin', 'user', 'verified'}
    
    # Check boolean arrays
    assert data['users'][1]['permissions'] == [True, False, True]
    
    # Check metadata
    assert data['metadata']['has_more'] is False
    assert data['metadata']['processing_time'] == '0:00:01.500000'
    assert data['metadata']['binary_data'] == 'test binary data'  # Binary decoded


@pytest.mark.asyncio 
async def test_websocket_broadcast_with_booleans():
    """Test that WebSocket broadcast handles boolean values correctly"""
    
    # Create WebSocket server
    ws = DaebusWebSocket(port=8765)
    
    # Mock clients
    mock_client1 = AsyncMock()
    mock_client2 = AsyncMock()
    ws.clients = {
        'client1': mock_client1,
        'client2': mock_client2
    }
    
    # Broadcast data with boolean values
    test_data = {
        'notification': 'New message',
        'urgent': True,
        'read': False,
        'user_settings': {
            'notifications_enabled': True,
            'email_alerts': False
        }
    }
    
    success_count = await ws.broadcast_to_all_async(test_data, "notification")
    
    # Verify both clients received the message
    assert success_count == 2
    mock_client1.send.assert_called_once()
    mock_client2.send.assert_called_once()
    
    # Parse the sent message to verify JSON is valid
    sent_message = mock_client1.send.call_args[0][0]
    parsed_message = json.loads(sent_message)
    
    # Verify boolean values are preserved
    assert parsed_message['type'] == 'notification'
    assert parsed_message['data']['urgent'] is True
    assert parsed_message['data']['read'] is False
    assert parsed_message['data']['user_settings']['notifications_enabled'] is True
    assert parsed_message['data']['user_settings']['email_alerts'] is False


@pytest.mark.asyncio
async def test_websocket_send_to_client_with_complex_data():
    """Test sending to specific client with complex data"""
    
    # Create WebSocket server
    ws = DaebusWebSocket(port=8765)
    
    # Mock client
    mock_client = AsyncMock()
    ws.clients = {'target_client': mock_client}
    
    # Send complex data
    test_data = {
        'user_profile': {
            'verified': True,
            'premium': False,
            'last_login': datetime.datetime.now(),
            'subscription_price': decimal.Decimal('9.99'),
            'favorite_categories': {'tech', 'science', 'music'}
        },
        'stats': {
            'posts_count': 42,
            'likes_received': 1337,
            'active_today': True
        }
    }
    
    success = await ws.send_to_client_async('target_client', test_data, "profile_update")
    
    # Verify message was sent successfully
    assert success is True
    mock_client.send.assert_called_once()
    
    # Parse and verify the message
    sent_message = mock_client.send.call_args[0][0]
    parsed_message = json.loads(sent_message)
    
    assert parsed_message['type'] == 'profile_update'
    data = parsed_message['data']
    
    # Verify boolean values
    assert data['user_profile']['verified'] is True
    assert data['user_profile']['premium'] is False
    assert data['stats']['active_today'] is True
    
    # Verify complex types are converted
    assert isinstance(data['user_profile']['favorite_categories'], list)
    assert data['user_profile']['subscription_price'] == 9.99


def test_websocket_json_encoder_directly():
    """Test the DaebusJSONEncoder directly with WebSocket-style data"""
    
    # Test data that might come from WebSocket handlers
    websocket_data = {
        'message_id': 'msg_123',
        'success': True,
        'error': False,
        'data': {
            'users_online': [
                {'username': 'alice', 'typing': True},
                {'username': 'bob', 'typing': False}
            ],
            'room_settings': {
                'public': True,
                'moderated': False,
                'max_users': 100
            },
            'timestamp': datetime.datetime.now(),
            'metadata': b'room metadata'
        }
    }
    
    # This should serialize without errors
    serialized = json.dumps(websocket_data, cls=DaebusJSONEncoder, indent=2)
    deserialized = json.loads(serialized)
    
    # Verify structure is preserved
    assert deserialized['success'] is True
    assert deserialized['error'] is False
    assert deserialized['data']['users_online'][0]['typing'] is True
    assert deserialized['data']['users_online'][1]['typing'] is False
    assert deserialized['data']['room_settings']['public'] is True
    assert deserialized['data']['room_settings']['moderated'] is False
    
    # Verify complex types are handled
    assert isinstance(deserialized['data']['timestamp'], str)
    assert isinstance(deserialized['data']['metadata'], str)


@pytest.mark.asyncio
async def test_websocket_error_responses_with_booleans():
    """Test that error responses also handle boolean data correctly"""
    
    # Mock WebSocket connection
    mock_websocket = AsyncMock()
    mock_websocket.send = AsyncMock()
    
    # Create WebSocket response
    response = WebSocketResponse(mock_websocket, "test_client")
    
    # Send error with boolean flags
    error_data = {
        'code': 'VALIDATION_ERROR',
        'retryable': True,
        'critical': False,
        'details': {
            'field_errors': {
                'email': {'required': True, 'valid': False},
                'password': {'required': True, 'strong': False}
            }
        }
    }
    
    await response.error("Validation failed", "error")
    
    # Verify error was sent
    mock_websocket.send.assert_called_once()
    
    # The error method sends a simple error message, but let's test sending complex error data
    await response.send(error_data, "detailed_error")
    
    # Check the detailed error call
    assert mock_websocket.send.call_count == 2
    sent_message = mock_websocket.send.call_args[0][0]
    parsed_message = json.loads(sent_message)
    
    # Verify boolean values in error details
    assert parsed_message['type'] == 'detailed_error'
    data = parsed_message['data']
    assert data['retryable'] is True
    assert data['critical'] is False
    assert data['details']['field_errors']['email']['required'] is True
    assert data['details']['field_errors']['email']['valid'] is False


@pytest.mark.asyncio
async def test_websocket_handler_response_serialization():
    """Test that WebSocket message handler responses are properly serialized"""
    
    # Create a mock daemon and WebSocket server
    daemon = MagicMock()
    daemon.name = "test_daemon"
    
    ws = DaebusWebSocket(port=8765)
    ws.daemon = daemon
    
    # Register a handler that returns complex data with booleans
    @ws.socket("test_message")
    def handle_test_message(data, client_id):
        return {
            'received': True,
            'processed': False,
            'client_info': {
                'id': client_id,
                'authenticated': True,
                'admin': False
            },
            'timestamp': datetime.datetime.now(),
            'data_received': data
        }
    
    # Mock WebSocket connection
    mock_websocket = AsyncMock()
    mock_websocket.send = AsyncMock()
    
    # Create WebSocket request and response objects
    message = {
        'type': 'test_message',
        'data': {
            'action': 'ping',
            'include_stats': True
        }
    }
    
    request = WebSocketRequest("test_client", message, mock_websocket)
    response = WebSocketResponse(mock_websocket, "test_client")
    
    # Simulate calling the handler and sending the response
    handler = ws.message_handlers['test_message']
    result = handler(message['data'], "test_client")
    
    await response.send(result)
    
    # Verify the response was sent
    mock_websocket.send.assert_called_once()
    sent_message = mock_websocket.send.call_args[0][0]
    parsed_message = json.loads(sent_message)
    
    # Verify the response structure and boolean values
    assert parsed_message['type'] == 'response'
    data = parsed_message['data']
    
    assert data['received'] is True
    assert data['processed'] is False
    assert data['client_info']['authenticated'] is True
    assert data['client_info']['admin'] is False
    assert data['data_received']['include_stats'] is True


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"]) 