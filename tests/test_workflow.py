import json
import threading
import time
import pytest
from unittest.mock import MagicMock, patch

from daebus import Daebus, DaebusWorkflow
from daebus.modules.context import request, response, set_context_type, _set_thread_local_request, _set_thread_local_response, _clear_thread_local_storage
from daebus.modules.workflow import WorkflowRequest, WorkflowResponse


class TestWorkflow:
    def test_workflow_initialization(self):
        """Test that workflow is properly initialized"""
        workflow = DaebusWorkflow("test-service")
        
        assert workflow.target_service == "test-service"
        assert not workflow.is_active
        assert workflow.workflow_id is not None
        assert workflow.workflow_channel.startswith("workflow:")
        
    def test_workflow_registration(self):
        """Test that workflow handlers can be registered"""
        app = Daebus("test-app")
        
        @app.workflow("test_workflow")
        def handle_test_workflow():
            pass
            
        assert "test_workflow" in app.workflow_handlers
        assert app.workflow_handlers["test_workflow"] == handle_test_workflow
        
    @patch('daebus.modules.workflow.Redis')
    def test_workflow_message_flow(self, mock_redis):
        """Test the complete workflow message flow"""
        # Set up mock Redis
        mock_redis_instance = MagicMock()
        mock_redis.return_value = mock_redis_instance
        
        # Set up mock pubsub
        mock_pubsub = MagicMock()
        mock_redis_instance.pubsub.return_value = mock_pubsub
        
        # Capture sent messages
        sent_messages = []
        def mock_publish(channel, message):
            sent_messages.append((channel, json.loads(message)))
            return 1
        mock_redis_instance.publish = mock_publish
        
        # Create workflow
        workflow = DaebusWorkflow("test-service")
        
        # Patch the start method to avoid creating a real thread
        original_start = workflow.start
        def patched_start(workflow_name, payload, callback, timeout=None):
            # Skip thread creation but set is_active flag
            workflow.callback = callback
            workflow.is_active = True
            
            # Prepare initial message (same as in original start method)
            msg = {
                'workflow': workflow_name,
                'payload': payload,
                'workflow_id': workflow.workflow_id,
                'reply_to': workflow.workflow_channel,
                'service': workflow.target_service
            }
            
            # Publish message to the service's workflow channel
            channel = f"{workflow.target_service}.workflows"
            workflow.redis.publish(channel, json.dumps(msg))
            
            return workflow.workflow_id
            
        # Replace the start method
        workflow.start = lambda *args, **kwargs: patched_start(*args, **kwargs)
        
        # Create a callback function for workflow updates
        received_messages = []
        def callback(data):
            received_messages.append(data)
            
        # Start the workflow
        workflow_id = workflow.start("connect_wifi", {"ssid": "Test-Network"}, callback)
        
        # Check that the initial message was sent correctly
        assert len(sent_messages) == 1
        channel, message = sent_messages[0]
        assert channel == "test-service.workflows"
        assert message["workflow"] == "connect_wifi"
        assert message["payload"] == {"ssid": "Test-Network"}
        assert message["workflow_id"] == workflow.workflow_id
        assert message["reply_to"] == workflow.workflow_channel
        
        # Simulate a response from the service
        response_data = {
            "payload": {"status": "connecting", "message": "Connecting to Test-Network..."},
            "workflow_id": workflow_id,
            "final": False
        }
        
        # Process the first message directly
        callback(response_data)
        
        # Send additional data to the workflow (as if from the client)
        workflow.send({"password": "password123"})
        
        # Check that the data was sent correctly
        assert len(sent_messages) == 2
        channel, message = sent_messages[1]
        assert channel == "test-service.workflows"
        assert message["payload"] == {"password": "password123"}
        assert message["workflow_id"] == workflow.workflow_id
        
        # Simulate final response from the service
        final_response = {
            "payload": {"status": "connected", "message": "Successfully connected"},
            "workflow_id": workflow_id,
            "final": True
        }
        
        # Process the final response
        callback(final_response)
        
        # Check that all messages were received
        assert len(received_messages) == 2
        assert received_messages[0]["payload"]["status"] == "connecting"
        assert received_messages[1]["payload"]["status"] == "connected"
        
        # Clean up
        workflow.unsubscribe()
        
    def test_workflow_handler(self):
        """Test workflow handler in a service"""
        # Create a simple workflow handler
        def handle_wifi_connection():
            if hasattr(handle_wifi_connection, 'already_called'):
                # Second message handling
                password = request.payload.get("password")
                assert password == "secure123"
                
                # Send final response
                response.send({"status": "connected", "message": "Connected successfully"}, final=True)
            else:
                # First message handling - mark as called for next time
                handle_wifi_connection.already_called = True
                
                ssid = request.payload.get("ssid")
                assert ssid == "TestWiFi"
                
                # First step - ask for password
                response.send({"status": "need_password", "message": "Please provide password"})
        
        # Mock Redis client
        mock_redis = MagicMock()
        sent_messages = []
        mock_redis.publish = lambda channel, message: sent_messages.append((channel, json.loads(message)))
        
        # Step 1: Create request/response for first message
        data1 = {
            "workflow": "connect_wifi",
            "payload": {"ssid": "TestWiFi"},
            "workflow_id": "test-workflow-123",
            "reply_to": "workflow:test-channel",
            "service": "test-app"
        }
        
        request1 = WorkflowRequest(data1)
        response1 = WorkflowResponse(mock_redis, request1)
        
        # Set context for first message
        set_context_type('pubsub')
        _set_thread_local_request(request1)
        _set_thread_local_response(response1)
        
        try:
            # Call handler directly for first message
            handle_wifi_connection()
            
            # Check first response
            assert len(sent_messages) == 1
            channel, message = sent_messages[0]
            assert channel == "workflow:test-channel"
            assert message["workflow_id"] == "test-workflow-123"
            assert message["payload"]["status"] == "need_password"
            assert not message["final"]
            
            # Step 2: Create request/response for second message
            data2 = {
                "payload": {"password": "secure123"},
                "workflow_id": "test-workflow-123",
                "reply_to": "workflow:test-channel"
            }
            
            request2 = WorkflowRequest(data2)
            response2 = WorkflowResponse(mock_redis, request2)
            
            # Update context for second message
            _set_thread_local_request(request2)
            _set_thread_local_response(response2)
            
            # Call handler directly for second message
            handle_wifi_connection()
            
            # Check second response
            assert len(sent_messages) == 2
            channel, message = sent_messages[1]
            assert channel == "workflow:test-channel"
            assert message["workflow_id"] == "test-workflow-123"
            assert message["payload"]["status"] == "connected"
            assert message["final"]
            
        finally:
            # Clean up
            _clear_thread_local_storage() 