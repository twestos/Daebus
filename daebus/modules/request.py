import json
from typing import Dict, Any, Optional, Union


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
