import json
from typing import Dict, Any, Optional
from .redis_client import redis_client


class Broadcast:
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
