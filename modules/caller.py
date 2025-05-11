import json
import time
import uuid
import threading
from redis import Redis
from .logger import logger as _default_logger


class DaebusCaller:
    def __init__(self, target_service, redis_host='localhost', redis_port=6379, timeout=5):
        """
        Initialize a caller to communicate with a specific service.

        Args:
            target_service (str): Name of the service to communicate with
            redis_host (str): Redis host address
            redis_port (int): Redis port
            timeout (int): Request timeout in seconds
        """
        self.target_service = target_service
        self.redis = Redis(host=redis_host, port=redis_port,
                           decode_responses=True)
        self.logger = _default_logger.getChild(f"caller:{target_service}")
        self.timeout = timeout
        self.pending_requests = {}
        self.progress_callbacks = {}

        # Set up pubsub for receiving responses
        self.response_pubsub = self.redis.pubsub(
            ignore_subscribe_messages=True)
        self.response_channel = f"caller:{uuid.uuid4()}"
        self.response_pubsub.subscribe(self.response_channel)

        # Start response listener thread
        self.response_thread = threading.Thread(
            target=self._response_listener, daemon=True)
        self.response_thread.start()

    def _response_listener(self):
        """Listen for responses to our requests"""
        for message in self.response_pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                data = json.loads(message["data"])
                request_id = data.get("request_id")
                status = data.get("status")
                # Default to True for backward compatibility
                final = data.get("final", True)

                if request_id in self.pending_requests:
                    # Handle progress updates separately
                    if status == 'progress' and not final:
                        # Execute progress callback if registered
                        if request_id in self.progress_callbacks:
                            try:
                                self.progress_callbacks[request_id](
                                    data.get('payload', {}))
                            except Exception as e:
                                self.logger.error(
                                    f"Error in progress callback: {e}")
                    elif final:
                        # This is the final response, store it to unblock the waiting thread
                        self.pending_requests[request_id] = data
                        self.logger.debug(
                            f"Received final response for request {request_id}")
                        # Clean up progress callback
                        if request_id in self.progress_callbacks:
                            del self.progress_callbacks[request_id]
                    else:
                        # Non-final, non-progress update (might be a partial result)
                        self.logger.debug(
                            f"Received non-final response for request {request_id}")
                        # Execute progress callback if registered
                        if request_id in self.progress_callbacks:
                            try:
                                self.progress_callbacks[request_id](
                                    data.get('payload', {}))
                            except Exception as e:
                                self.logger.error(
                                    f"Error in progress callback: {e}")
            except Exception as e:
                self.logger.error(f"Error processing response: {e}")

    def send_request(self, action, payload, timeout=None, on_progress=None):
        """
        Send a request to the target service and wait for a response.

        Args:
            action (str): The action to trigger on the target service
            payload (dict): Data to send with the request
            timeout (int, optional): Override default timeout
            on_progress (callable, optional): Callback for progress updates
                                            Function signature: func(payload_dict)

        Returns:
            dict: Response payload from the service
        """
        timeout = timeout or self.timeout
        request_id = str(uuid.uuid4())

        # Register this request ID as pending
        self.pending_requests[request_id] = None

        # Register progress callback if provided
        if on_progress and callable(on_progress):
            self.progress_callbacks[request_id] = on_progress

        # Prepare message
        msg = {
            'action': action,
            'payload': payload,
            'reply_to': self.response_channel,
            'request_id': request_id,
            'service': self.target_service
        }

        # Publish message to the service's main channel
        self.redis.publish(self.target_service, json.dumps(msg))
        self.logger.debug(
            f"Sent request to {self.target_service} action '{action}': {payload}")

        # Wait for final response
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.pending_requests[request_id] is not None:
                response = self.pending_requests[request_id]
                del self.pending_requests[request_id]

                # Also clean up progress callback if it's still there
                if request_id in self.progress_callbacks:
                    del self.progress_callbacks[request_id]

                status = response.get('status')
                payload = response.get('payload', {})

                if status == 'error':
                    error_msg = payload.get('error', 'Unknown error')
                    self.logger.error(
                        f"Error from {self.target_service}: {error_msg}")
                    raise Exception(error_msg)

                return payload

            time.sleep(0.01)  # Short sleep to prevent CPU spinning

        # Clean up if timed out
        del self.pending_requests[request_id]

        # Also clean up progress callback
        if request_id in self.progress_callbacks:
            del self.progress_callbacks[request_id]

        raise TimeoutError(
            f"Request to {self.target_service}.{action} timed out after {timeout}s")

    def send_message(self, channel, payload):
        """
        Send a message to a specific channel without expecting a response.

        Args:
            channel (str): Channel to send the message to
            payload (dict): Data to send with the message

        Returns:
            int: Number of clients that received the message
        """
        return self.redis.publish(channel, json.dumps(payload))

    def send_to_service(self, payload, action=None):
        """
        Send a message directly to the target service's main channel.

        Args:
            payload (dict): Data to send with the message
            action (str, optional): Action to route the message to

        Returns:
            int: Number of clients that received the message
        """
        if action:
            # If action is provided, add it to the payload
            msg = payload.copy()
            msg['action'] = action
            return self.redis.publish(self.target_service, json.dumps(msg))
        else:
            # Otherwise just send the payload directly
            return self.redis.publish(self.target_service, json.dumps(payload))

    def close(self):
        """Close pubsub connections and clean up resources"""
        self.response_pubsub.unsubscribe()
        self.response_pubsub.close()
