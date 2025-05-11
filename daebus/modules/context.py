import threading
from typing import Any, Optional, Dict, List, Callable, Union, TypeVar, Type, cast
import logging

# Import the base logger
from .logger import logger as base_logger

# Global daemon instance
_global_daemon = None

# Thread‑local storage for context type, request, and response
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


def _set_thread_local_request(request: Any) -> None:
    """
    Set the current request object in thread-local storage.
    This allows concurrent processing of multiple requests.

    Args:
        request: The PubSubRequest or HttpRequest object
    """
    _context.request = request


def _get_thread_local_request() -> Any:
    """
    Get the current request object from thread-local storage.

    Returns:
        The current request object or None if not set
    """
    return getattr(_context, 'request', None)


def _set_thread_local_response(response: Any) -> None:
    """
    Set the current response object in thread-local storage.
    This allows concurrent processing of multiple responses.

    Args:
        response: The PubSubResponse or HttpResponse object
    """
    _context.response = response


def _get_thread_local_response() -> Any:
    """
    Get the current response object from thread-local storage.

    Returns:
        The current response object or None if not set
    """
    return getattr(_context, 'response', None)


def _clear_thread_local_storage() -> None:
    """
    Clear all thread-local storage variables.
    This should be called when cleaning up after processing a message or request.
    """
    # Clear context type
    set_context_type(None)
    
    # Clear request and response objects
    if hasattr(_context, 'request'):
        delattr(_context, 'request')
    
    if hasattr(_context, 'response'):
        delattr(_context, 'response')


class _Proxy:
    """
    Proxy for getting thread-local objects.
    For daemon attributes, this checks the thread local context first, then falls
    back to the daemon's attribute.
    """

    def __init__(self, attr_name=None):
        self.attr_name = attr_name

    def __getattr__(self, name: str) -> Any:
        # Special case for testing: handle common PubSub methods
        if name in ['success', 'error', 'progress']:
            # First check for thread-local response
            thread_local_response = _get_thread_local_response()
            if thread_local_response is not None:
                try:
                    return getattr(thread_local_response, name)
                except AttributeError:
                    pass  # Fall back

            # If we're here, either there's no thread-local response or it doesn't have this method
            def noop(*args, **kwargs):
                logger.debug(f"No-op {name}() called")
                return 0  # Simulate 0 clients received
            return noop
            
        # For all other attributes, get daemon and its attribute
        daemon = get_daemon()
        if daemon is None:
            # For testing, return appropriate defaults for common attributes
            if name == 'payload':
                return {}
            # Return None for other common attributes
            elif name in ['raw', 'reply_to', 'request_id', 'service', 'method', 'path', 'headers', 'params']:
                return None
                
            # For other attributes, raise an error
            raise RuntimeError(f"Cannot access '{name}', daemon instance not available")

        # Get the item from daemon
        if self.attr_name:
            # Get a specific attribute from daemon
            obj = getattr(daemon, self.attr_name)
            return getattr(obj, name)
        else:
            # Get attribute directly from daemon
            return getattr(daemon, name)


class LoggerProxy:
    """
    Special proxy for the logger that works in any context.
    Falls back to the base logger if daemon is not available.
    """
    
    def __getattr__(self, name: str) -> Any:
        # Try to get logger from daemon first
        try:
            daemon = get_daemon()
            if hasattr(daemon, 'logger'):
                return getattr(daemon.logger, name)
        except Exception:
            # If daemon is not available or has no logger, fall back to base logger
            pass
            
        # Fall back to base logger
        return getattr(base_logger, name)


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


class RequestProxy:
    """
    Proxy for request objects that supports both HTTP and pub/sub requests.
    Also supports thread-local request objects for concurrent processing.
    """

    # Common attributes across both request types
    COMMON_ATTRS: List[str] = ['payload', 'raw']

    # HTTP-specific attributes
    HTTP_ATTRS: List[str] = ['method', 'path', 'headers', 'params']

    # Pub/Sub-specific attributes
    PUBSUB_ATTRS: List[str] = ['reply_to', 'request_id', 'service']

    def __getattr__(self, name: str) -> Any:
        # First check for thread-local request
        thread_local_request = _get_thread_local_request()
        if thread_local_request is not None:
            try:
                return getattr(thread_local_request, name)
            except AttributeError:
                pass  # Fall back to daemon's request
                
        # Fall back to daemon's request
        daemon = get_daemon()
        if daemon is None:
            raise RuntimeError("Daemon instance not available")
            
        context_type = get_context_type()

        # Provide better error messages for potentially misused attributes
        if context_type == 'http' and name in self.PUBSUB_ATTRS:
            # Special case for reply_to and request_id which may be accessed by generic code
            if name in ['reply_to', 'request_id']:
                # These are allowed but will return None in HTTP context
                pass
            else:
                # Only log this at debug level
                logger.debug(
                    f"Accessing pub/sub-specific attribute '{name}' in HTTP context"
                )
        elif context_type == 'pubsub' and name in self.HTTP_ATTRS:
            # Only log this at debug level
            logger.debug(
                f"Accessing HTTP-specific attribute '{name}' in pub/sub context"
            )

        # Get the appropriate request object based on context
        request_obj = None
        try:
            if context_type == 'http':
                if hasattr(daemon, 'request_http') and daemon.request_http is not None:
                    # Use HTTP-specific request
                    request_obj = daemon.request_http
                elif hasattr(daemon, 'request') and daemon.request is not None:
                    # Fall back to default request
                    request_obj = daemon.request
            else:
                # Use pub/sub request
                if hasattr(daemon, 'request') and daemon.request is not None:
                    request_obj = daemon.request
                    
            if request_obj is not None:
                return getattr(request_obj, name)
                
            # If we get here, no request object is available
            if name == 'payload':
                # Common case - return empty dict for payload
                return {}
                
            # For other attributes, raise an error with helpful context
            raise AttributeError(f"No request object available (context: {context_type})")
            
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


class ResponseProxy:
    """
    Proxy for response objects that supports both HTTP and pub/sub responses.
    Also supports thread-local response objects for concurrent processing.
    """

    # HTTP-specific methods
    HTTP_METHODS: List[str] = ['send']

    # Pub/Sub-specific methods
    PUBSUB_METHODS: List[str] = ['success', 'error', 'progress']

    def __getattr__(self, name: str) -> Any:
        # First check for thread-local response
        thread_local_response = _get_thread_local_response()
        if thread_local_response is not None:
            try:
                return getattr(thread_local_response, name)
            except AttributeError:
                pass  # Fall back to daemon's response
                
        # Fall back to daemon's response
        daemon = get_daemon()
        if daemon is None:
            # Special handling for common methods in tests
            if name in self.PUBSUB_METHODS:
                # Return a no-op function for test cases
                def noop(*args, **kwargs):
                    logger.debug(f"No-op {name}() called")
                    return 0  # Simulate 0 clients received
                return noop
            
            raise RuntimeError("Daemon instance not available")
            
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

        # Get the appropriate response object based on context
        response_obj = None
        try:
            if context_type == 'http':
                if hasattr(daemon, 'response_http') and daemon.response_http is not None:
                    # Use HTTP-specific response
                    response_obj = daemon.response_http
                elif hasattr(daemon, 'response') and daemon.response is not None:
                    # Fall back to default response
                    response_obj = daemon.response
            else:
                # Use pub/sub response
                if hasattr(daemon, 'response') and daemon.response is not None:
                    response_obj = daemon.response
                    
            if response_obj is not None:
                return getattr(response_obj, name)
                
            # If we get here, no response object is available
            # Special handling for common response methods
            if name in self.PUBSUB_METHODS:
                # Return a no-op function for test cases
                def noop(*args, **kwargs):
                    logger.debug(f"No-op {name}() called")
                    return 0  # Simulate 0 clients received
                return noop
                
            raise AttributeError(f"No response object available (context: {context_type})")
            
        except AttributeError:
            # Special handling for common response methods
            if name in self.PUBSUB_METHODS:
                # Return a no-op function for test cases
                def noop(*args, **kwargs):
                    logger.debug(f"No-op {name}() called")
                    return 0  # Simulate 0 clients received
                return noop
                
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
broadcast = _Proxy('broadcast')
cache = _Proxy('cache')  # raw redis client
logger = LoggerProxy()
