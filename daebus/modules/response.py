import json
from typing import Dict, Any, Optional, Union


class PubSubResponse:
    """
    Response object for pub/sub messaging context.

    This class handles sending responses back through Redis pub/sub channels
    after handling a request. It provides methods for success, error, and progress responses.
    """

    def __init__(self, redis_client: Any, request: Any):
        self._redis = redis_client
        self._req = request

    def success(self, payload: Dict[str, Any], final: bool = True) -> int:
        """
        Send a success response through pub/sub.

        Args:
            payload (dict): The response data
            final (bool): Whether this is the final response for this request
                          If False, the client will expect more responses

        Returns:
            int: Number of clients that received the message
        """
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

    def progress(self, payload: Dict[str, Any], progress_percentage: Optional[float] = None) -> int:
        """
        Send a progress update for long-running operations.

        Args:
            payload (dict): Progress information
            progress_percentage (float, optional): Progress as a percentage (0-100)

        Returns:
            int: Number of clients that received the message
        """
        if progress_percentage is not None:
            payload = payload.copy()
            # Ensure progress percentage is between 0 and 100
            payload['progress_percentage'] = min(
                max(0, progress_percentage), 100)

        return self._send(payload, status='progress', final=False)

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
