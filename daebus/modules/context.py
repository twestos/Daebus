import threading
from typing import Any, Optional, Dict, List, Callable, Union, TypeVar, Type, cast

# Global daemon instance
_global_daemon = None

# Thread‑local storage for context type only
_context = threading.local()

T = TypeVar('T')  # Generic type for return values


def set_daemon(daemon: Any) -> None:
    """
    Set the daemon instance globally.

    Args:
        daemon: The Daebus daemon instance
    """
    global _global_daemon
    _global_daemon = daemon


def get_daemon() -> Any:
    """
    Get the daemon instance from the global variable.

    Returns:
        The Daebus daemon instance

    Raises:
        RuntimeError: If no daemon has been set
    """
    if _global_daemon is None:
        raise RuntimeError("Daebus not initialized; call app.run() first")
    return _global_daemon


def set_context_type(context_type: Optional[str]) -> None:
    """
    Set the current context type (http or pubsub) in thread-local storage.

    Args:
        context_type: Either 'http', 'pubsub', or None
    """
    if context_type is not None and context_type not in ('http', 'pubsub'):
        raise ValueError(
            f"Invalid context type: {context_type}. Expected 'http', 'pubsub', or None")
    _context.context_type = context_type


def get_context_type() -> Optional[str]:
    """
    Get the current context type (http or pubsub) from thread-local storage.

    Returns:
        str: The context type ('http', 'pubsub') or None if not set
    """
    return getattr(_context, 'context_type', None)


class _Proxy:
    """Simple proxy for daemon attributes"""

    def __getattr__(self, name: str) -> Any:
        daemon = get_daemon()
        try:
            return getattr(daemon, name)
        except AttributeError:
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'") from None


class _ContextObjectProxy:
    """
    A base class for proxies that need to switch between HTTP and pub/sub implementations.
    """

    def __init__(self, default_attr: str, http_attr: str):
        self.default_attr = default_attr  # pub/sub attribute name
        self.http_attr = http_attr        # HTTP attribute name

    def __getattr__(self, name: str) -> Any:
        daemon = get_daemon()
        context_type = get_context_type()

        # Select the appropriate underlying object based on context
        try:
            if context_type == 'http':
                if hasattr(daemon, self.http_attr):
                    # Use HTTP-specific object
                    target_obj = getattr(daemon, self.http_attr)
                else:
                    # Fall back to default if HTTP object doesn't exist
                    target_obj = getattr(daemon, self.default_attr)
            else:
                # Use pub/sub (default) object
                target_obj = getattr(daemon, self.default_attr)

            # Get the method or attribute from the target object
            return getattr(target_obj, name)
        except AttributeError:
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'") from None


class RequestProxy(_ContextObjectProxy):
    """
    Proxy for request objects that switches between pub/sub and HTTP implementations.
    This allows different request methods and attributes for each context.
    """

    # Common attributes across both request types
    COMMON_ATTRS: List[str] = ['payload', 'raw']

    # HTTP-specific attributes
    HTTP_ATTRS: List[str] = ['method', 'path', 'headers', 'params']

    # Pub/Sub-specific attributes
    PUBSUB_ATTRS: List[str] = ['reply_to', 'request_id', 'service']

    def __init__(self):
        super().__init__('request', 'request_http')

    def __getattr__(self, name: str) -> Any:
        daemon = get_daemon()
        context_type = get_context_type()

        # Provide better error messages for potentially misused attributes
        if context_type == 'http' and name in self.PUBSUB_ATTRS:
            # Special case for reply_to and request_id which may be accessed by generic code
            if name in ['reply_to', 'request_id']:
                # These are allowed but will return None in HTTP context
                pass
            else:
                self.logger.warning(
                    f"Accessing pub/sub-specific attribute '{name}' in HTTP context. "
                    f"This may not work as expected."
                )
        elif context_type == 'pubsub' and name in self.HTTP_ATTRS:
            self.logger.warning(
                f"Accessing HTTP-specific attribute '{name}' in pub/sub context. "
                f"This may not work as expected."
            )

        try:
            # Get the actual attribute from the appropriate object
            return super().__getattr__(name)
        except AttributeError:
            # Create a more helpful error message
            if name in self.HTTP_ATTRS:
                hint = "This attribute is only available in HTTP context."
            elif name in self.PUBSUB_ATTRS:
                hint = "This attribute is only available in pub/sub context."
            else:
                hint = (f"Common attributes: {', '.join(self.COMMON_ATTRS)}. "
                        f"HTTP attributes: {', '.join(self.HTTP_ATTRS)}. "
                        f"Pub/Sub attributes: {', '.join(self.PUBSUB_ATTRS)}.")

            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'. {hint}")

    @property
    def logger(self) -> Any:
        """Get the logger from the daemon"""
        daemon = get_daemon()
        return daemon.logger


class ResponseProxy(_ContextObjectProxy):
    """
    Proxy for response objects that switches between pub/sub and HTTP implementations.
    This provides different response methods for each context:
    - For pub/sub: success(), error(), progress()
    - For HTTP: send()
    """

    # HTTP-specific methods
    HTTP_METHODS: List[str] = ['send']

    # Pub/Sub-specific methods
    PUBSUB_METHODS: List[str] = ['success', 'error', 'progress']

    def __init__(self):
        super().__init__('response', 'response_http')

    def __getattr__(self, name: str) -> Any:
        daemon = get_daemon()
        context_type = get_context_type()

        # Validate method usage in the appropriate context
        if context_type == 'http' and name in self.PUBSUB_METHODS:
            raise AttributeError(
                f"Method '{name}()' is for pub/sub responses and cannot be used in HTTP context. "
                f"Use 'response.send()' for HTTP responses."
            )
        elif context_type == 'pubsub' and name in self.HTTP_METHODS:
            raise AttributeError(
                f"Method '{name}()' is for HTTP responses and cannot be used in pub/sub context. "
                f"Use 'response.success()' or 'response.error()' for pub/sub responses."
            )

        # Call the parent implementation to get the method from the appropriate object
        try:
            method = super().__getattr__(name)
            return method
        except AttributeError:
            # Create a more helpful error message
            if name in self.HTTP_METHODS:
                hint = "This method is only available in HTTP context."
            elif name in self.PUBSUB_METHODS:
                hint = "This method is only available in pub/sub context."
            else:
                hint = f"Available methods in HTTP context: {', '.join(self.HTTP_METHODS)}. " \
                    f"Available methods in pub/sub context: {', '.join(self.PUBSUB_METHODS)}."

            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'. {hint}")


# proxies for handler context
debug = _Proxy()
request = RequestProxy()
response = ResponseProxy()
broadcast = _Proxy()
cache = _Proxy()  # raw redis client
logger = _Proxy()
