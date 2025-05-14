import json
import time
import uuid
import threading
from typing import Dict, Any, Callable, Optional, List
from redis import Redis
from .logger import logger as _default_logger


class DaebusWorkflow:
    """
    Workflow handler for multi-step async communication between services.
    
    A workflow allows for continuous back-and-forth communication between services
    where one service can send multiple responses over time, and the calling service
    can receive these updates through a callback function.
    
    This is useful for long-running processes like connecting to WiFi, where the
    network manager needs to send status updates and possibly request additional
    information (like passwords) during the connection process.
    
    Example:
        # On the client side:
        workflow = DaebusWorkflow("network-manager")
        
        def handle_updates(data):
            if data.get("status") == "need_password":
                workflow.send({"password": "my_wifi_password"})
            elif data.get("status") == "connected":
                print("Successfully connected!")
                workflow.unsubscribe()  # Stop receiving updates
        
        # Start workflow and subscribe to updates
        workflow.start("connect_wifi", {"ssid": "MyNetwork"}, handle_updates)
    """
    
    def __init__(self, target_service: str, redis_host: str = 'localhost', redis_port: int = 6379, timeout: int = 60):
        """
        Initialize a workflow to communicate with a specific service.
        
        Args:
            target_service: Name of the service to communicate with
            redis_host: Redis host address
            redis_port: Redis port
            timeout: Workflow timeout in seconds (default: 60 seconds)
        """
        self.target_service = target_service
        self.redis = Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.logger = _default_logger.getChild(f"workflow:{target_service}")
        self.timeout = timeout
        
        # Generate a unique workflow ID and channel
        self.workflow_id = str(uuid.uuid4())
        self.workflow_channel = f"workflow:{self.workflow_id}"
        
        # Set up pubsub for receiving workflow messages
        self.response_pubsub = None
        self.response_thread = None
        self.callback = None
        self.is_active = False
        
    def start(self, workflow_name: str, payload: Dict[str, Any], callback: Callable[[Dict[str, Any]], None], timeout: Optional[int] = None) -> str:
        """
        Start a new workflow with the target service.
        
        Args:
            workflow_name: The name of the workflow to start
            payload: Initial data to send with the workflow
            callback: Function that will be called for each update
            timeout: Override default timeout
            
        Returns:
            str: The workflow ID
        """
        if self.is_active:
            raise RuntimeError("Workflow is already active. Call unsubscribe() first.")
            
        # Set up the callback
        self.callback = callback
        self.is_active = True
        timeout = timeout or self.timeout
        
        # Set up pubsub for receiving workflow responses
        self.response_pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        self.response_pubsub.subscribe(self.workflow_channel)
        
        # Start the listener thread
        self.response_thread = threading.Thread(
            target=self._response_listener,
            args=(timeout,),
            daemon=True
        )
        self.response_thread.start()
        
        # Prepare initial message
        msg = {
            'workflow': workflow_name,
            'payload': payload,
            'workflow_id': self.workflow_id,
            'reply_to': self.workflow_channel,
            'service': self.target_service
        }
        
        # Publish message to the service's workflow channel
        channel = f"{self.target_service}.workflows"
        self.redis.publish(channel, json.dumps(msg))
        self.logger.debug(f"Started workflow '{workflow_name}' with ID {self.workflow_id}")
        
        return self.workflow_id
        
    def send(self, payload: Dict[str, Any]) -> None:
        """
        Send data to the active workflow.
        
        Args:
            payload: Data to send to the workflow
        """
        if not self.is_active:
            raise RuntimeError("No active workflow. Call start() first.")
            
        # Prepare message
        msg = {
            'payload': payload,
            'workflow_id': self.workflow_id,
        }
        
        # Publish to the service's workflow channel
        channel = f"{self.target_service}.workflows"
        self.redis.publish(channel, json.dumps(msg))
        self.logger.debug(f"Sent data to workflow {self.workflow_id}")
        
    def _response_listener(self, timeout: int) -> None:
        """
        Listen for responses from the workflow.
        
        Args:
            timeout: Maximum time to listen for (in seconds)
        """
        start_time = time.time()
        
        try:
            for message in self.response_pubsub.listen():
                # Check if we're still active
                if not self.is_active:
                    break
                    
                # Check timeout
                if time.time() - start_time > timeout:
                    self.logger.warning(f"Workflow {self.workflow_id} timed out after {timeout} seconds")
                    self.unsubscribe()
                    # Call callback with timeout error
                    if self.callback:
                        self.callback({
                            "status": "error",
                            "error": "Workflow timed out",
                            "final": True
                        })
                    break
                
                if message["type"] != "message":
                    continue
                    
                try:
                    # Parse the message
                    data = json.loads(message["data"])
                    workflow_id = data.get("workflow_id")
                    
                    # Verify this is for our workflow
                    if workflow_id != self.workflow_id:
                        continue
                        
                    # Check if this is the final message
                    is_final = data.get("final", False)
                    
                    # Call the callback with the data
                    if self.callback:
                        self.callback(data)
                        
                    # If this is the final message, clean up
                    if is_final:
                        self.logger.debug(f"Workflow {self.workflow_id} completed")
                        self.unsubscribe()
                        break
                        
                except Exception as e:
                    self.logger.error(f"Error processing workflow response: {e}")
            
        except Exception as e:
            self.logger.error(f"Error in workflow response listener: {e}")
        finally:
            # Ensure we clean up if the thread exits for any reason
            self.unsubscribe()
            
    def unsubscribe(self) -> None:
        """
        Stop the workflow and clean up resources.
        """
        if not self.is_active:
            return
            
        self.is_active = False
        
        if self.response_pubsub:
            try:
                self.response_pubsub.unsubscribe()
                self.response_pubsub.close()
            except Exception as e:
                self.logger.error(f"Error closing workflow pubsub: {e}")
                
        self.response_pubsub = None
        self.logger.debug(f"Unsubscribed from workflow {self.workflow_id}")


class WorkflowRequest:
    """
    Request object for workflow messages.
    
    This extends PubSubRequest with workflow-specific fields.
    """
    
    def __init__(self, data: Dict[str, Any]):
        # Parse the data
        self.raw = data
        
        # Extract the payload
        if isinstance(data.get('payload'), str):
            try:
                self.payload = json.loads(data.get('payload', '{}'))
            except json.JSONDecodeError:
                self.payload = {}
        else:
            self.payload = data.get('payload', {})
            
        # Extract workflow metadata
        self.workflow_id = data.get('workflow_id')
        self.reply_to = data.get('reply_to')
        self.service = data.get('service')
        self.workflow = data.get('workflow')  # The workflow name/action
        
    def __repr__(self) -> str:
        return f"WorkflowRequest(workflow={self.workflow!r}, workflow_id={self.workflow_id!r})"


class WorkflowResponse:
    """
    Response object for workflow messages.
    
    This handles sending responses back to the workflow initiator.
    """
    
    def __init__(self, redis_client: Redis, request: WorkflowRequest):
        self._redis = redis_client
        self._req = request
        
    def send(self, payload: Dict[str, Any], final: bool = False) -> int:
        """
        Send a response to the workflow initiator.
        
        Args:
            payload: The data to send
            final: Whether this is the final response in the workflow
            
        Returns:
            int: Number of clients that received the message
        """
        if self._redis is None:
            raise RuntimeError("Redis client not available")
            
        if self._req is None or not hasattr(self._req, 'workflow_id'):
            raise ValueError("Invalid workflow request object")
            
        msg = {
            'payload': payload,
            'workflow_id': self._req.workflow_id,
            'final': final
        }
        
        # Use the reply_to channel from the request
        channel = self._req.reply_to
        if not channel:
            raise ValueError("No reply channel available for workflow response")
            
        try:
            # Convert message to JSON and publish to Redis
            msg_str = json.dumps(msg)
            return self._redis.publish(channel, msg_str)
        except Exception as e:
            raise RuntimeError(f"Failed to send workflow response: {e}") from e 