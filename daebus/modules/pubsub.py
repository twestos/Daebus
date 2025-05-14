import json
from typing import Dict, Any, Optional, Union
from .redis_client import redis_client


class PubSubBroadcast:
    """
    Broadcast messages to Redis pub/sub channels.

    This class provides a convenient way to broadcast messages to any Redis pub/sub channel.
    """

    def __init__(self, custom_redis_client=None):
        # Use the provided client or fall back to the global redis_client
        self._redis = custom_redis_client if custom_redis_client is not None else redis_client
        if self._redis is None:
            raise RuntimeError("Redis client not available")

    def send(self, channel: str, payload: Dict[str, Any]) -> int:
        """
        Send a message to a channel using Redis pub/sub.

        Args:
            channel: The channel name to publish to
            payload: Dictionary containing the message data

        Returns:
            int: Number of clients that received the message

        Raises:
            ValueError: If channel is empty or not a string
            TypeError: If payload is not a dictionary
            RuntimeError: If message cannot be sent
        """
        if not channel or not isinstance(channel, str):
            raise ValueError(f"Invalid channel name: {channel}")

        if not isinstance(payload, dict):
            raise TypeError(
                f"Payload must be a dictionary, got {type(payload).__name__}")

        try:
            msg = json.dumps(payload)
            return self._redis.publish(channel, msg)
        except Exception as e:
            raise RuntimeError(f"Failed to broadcast message: {e}") from e


class PubSubRequest:
    """
    Request object for pub/sub messaging context.

    This class represents requests received through Redis pub/sub channels,
    providing access to the payload, reply channel, and other metadata.
    """

    def __init__(self, data: Union[str, Dict[str, Any]]):
        # data can be raw JSON string or a parsed dictionary from pubsub message
        if isinstance(data, str):
            # Parse from string
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in request data: {e}")
        elif not isinstance(data, dict):
            raise TypeError(
                f"Expected string or dict, got {type(data).__name__}")

        self.raw = data

        # Extract the payload if it exists
        if isinstance(data.get('payload'), str):
            try:
                self.payload = json.loads(data.get('payload', '{}'))
            except json.JSONDecodeError:
                self.payload = {}  # Default to empty dict on parse error
        else:
            self.payload = data.get('payload', {})

        # Extract request metadata
        self.reply_to: Optional[str] = data.get('reply_to')
        self.request_id: Optional[str] = data.get('request_id')
        self.service: Optional[str] = data.get('service')

    def __repr__(self) -> str:
        """String representation for debugging"""
        return f"PubSubRequest(service={self.service!r}, request_id={self.request_id!r})"


class PubSubResponse:
    """
    Response object for pub/sub messaging context.

    This class handles sending responses back through Redis pub/sub channels
    after handling a request. It provides methods for sending standard responses and errors.
    """

    def __init__(self, redis_client: Any, request: Any):
        self._redis = redis_client
        self._req = request

    def send(self, payload: Dict[str, Any], final: bool = True) -> int:
        """
        Send a success response through pub/sub.
        This is the standardized interface method for all contexts.

        Args:
            payload (dict): The response data
            final (bool): Whether this is the final response for this request
                          If False, the client will expect more responses

        Returns:
            int: Number of clients that received the message
        """
        # Send with success status
        return self._send(payload, status='success', final=final)

    def error(self, err: Union[Exception, str], final: bool = True) -> int:
        """
        Send an error response through pub/sub.

        Args:
            err (Exception or str): The error that occurred
            final (bool): Whether this is the final response for this request
                          If False, the client will expect more responses

        Returns:
            int: Number of clients that received the message
        """
        error_msg = str(err)
        return self._send({'error': error_msg}, status='error', final=final)

    def _send(self, payload: Dict[str, Any], status: str, final: bool = True) -> int:
        """
        Internal method to send a response through pub/sub.

        Args:
            payload (dict): The response data
            status (str): The status of the response ('success', 'error', 'progress')
            final (bool): Whether this is the final response

        Returns:
            int: Number of clients that received the message
        """
        if self._redis is None:
            raise RuntimeError("Redis client not available")

        if self._req is None or not hasattr(self._req, 'request_id'):
            raise ValueError("Invalid request object")

        msg = {
            'status': status,
            'payload': payload,
            'request_id': self._req.request_id,
            'final': final
        }

        # Use the reply_to channel if provided, otherwise construct a response channel
        channel = getattr(self._req, 'reply_to', None)
        if not channel:
            # Default response channel
            service = getattr(self._req, 'service', 'unknown')
            channel = f"{service}.responses"

        try:
            # Convert message to JSON and publish to Redis
            msg_str = json.dumps(msg)
            return self._redis.publish(channel, msg_str)
        except Exception as e:
            raise RuntimeError(f"Failed to send response: {e}") from e
