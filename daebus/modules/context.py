import threading
from typing import Any, Optional, List, TypeVar

# Import the base logger
from .logger import logger as base_logger

# Global daemon instance
_global_daemon = None

# Thread‑local storage for context type, request, and response
_context = threading.local()

T = TypeVar('T')  # Generic type for return values

# Export internal functions that are used by other modules
__all__ = [
    'set_daemon', 'get_daemon', 'set_context_type', 'get_context_type',
    '_set_thread_local_request', '_get_thread_local_request',
    '_set_thread_local_response', '_get_thread_local_response',
    '_clear_thread_local_storage'
]

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
    Set the current context type (http, pubsub, websocket) in thread-local storage.

    Args:
        context_type: Either 'http', 'pubsub', 'websocket', or None
    """
    if context_type is not None and context_type not in ('http', 'pubsub', 'websocket'):
        raise ValueError(
            f"Invalid context type: {context_type}. Expected 'http', 'pubsub', 'websocket', or None")
    _context.context_type = context_type


def get_context_type() -> Optional[str]:
    """
    Get the current context type (http, pubsub, websocket) from thread-local storage.

    Returns:
        str: The context type ('http', 'pubsub', 'websocket') or None if not set
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


class RequestProxy:
    """
    Proxy for request objects that supports HTTP, pub/sub, and WebSocket requests.
    Also supports thread-local request objects for concurrent processing.
    """

    # Common attributes across all request types
    COMMON_ATTRS: List[str] = ['payload', 'raw']

    # HTTP-specific attributes
    HTTP_ATTRS: List[str] = ['method', 'path', 'headers', 'params']

    # Pub/Sub-specific attributes
    PUBSUB_ATTRS: List[str] = ['reply_to', 'request_id', 'service']
    
    # WebSocket-specific attributes
    WEBSOCKET_ATTRS: List[str] = ['client_id', 'message_type', 'data', 'websocket']

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
        if context_type == 'http' and name in self.PUBSUB_ATTRS + self.WEBSOCKET_ATTRS:
            # Special case for reply_to and request_id which may be accessed by generic code
            if name in ['reply_to', 'request_id']:
                # These are allowed but will return None in HTTP context
                pass
            else:
                # Only log this at debug level
                logger.debug(
                    f"Accessing non-HTTP attribute '{name}' in HTTP context"
                )
        elif context_type == 'pubsub' and name in self.HTTP_ATTRS + self.WEBSOCKET_ATTRS:
            # Only log this at debug level
            logger.debug(
                f"Accessing non-pub/sub attribute '{name}' in pub/sub context"
            )
        elif context_type == 'websocket' and name in self.HTTP_ATTRS + self.PUBSUB_ATTRS:
            # Only log this at debug level
            logger.debug(
                f"Accessing non-WebSocket attribute '{name}' in WebSocket context"
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
            elif context_type == 'websocket':
                if hasattr(daemon, 'request_ws') and daemon.request_ws is not None:
                    # Use WebSocket-specific request
                    request_obj = daemon.request_ws
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
            elif name in self.WEBSOCKET_ATTRS:
                hint = "This attribute is only available in WebSocket context."
            else:
                hint = (f"Common attributes: {', '.join(self.COMMON_ATTRS)}. "
                        f"HTTP attributes: {', '.join(self.HTTP_ATTRS)}. "
                        f"Pub/Sub attributes: {', '.join(self.PUBSUB_ATTRS)}. "
                        f"WebSocket attributes: {', '.join(self.WEBSOCKET_ATTRS)}.")

            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'. {hint}")


class ResponseProxy:
    """
    Proxy for response objects that supports HTTP, pub/sub, and WebSocket responses.
    Also supports thread-local response objects for concurrent processing.
    """

    # HTTP-specific methods
    HTTP_METHODS: List[str] = ['send']

    # Pub/Sub-specific methods
    PUBSUB_METHODS: List[str] = ['success', 'error', 'progress']
    
    # WebSocket-specific methods
    WEBSOCKET_METHODS: List[str] = ['send', 'success', 'error', 'progress', 'broadcast_to_all',
                                  'send_to_client', 'broadcast_to_clients']

    def __getattr__(self, name: str) -> Any:
        # First check for thread-local response
        thread_local_response = _get_thread_local_response()
        if thread_local_response is not None:
            try:
                return getattr(thread_local_response, name)
            except AttributeError:
                pass  # Fall back to daemon's response
                
        # Special method handling for standardized interface
        if name == 'send':
            # Unified send method for all contexts
            def unified_send(*args, **kwargs):
                context_type = get_context_type()
                
                # Get the response object
                resp_obj = thread_local_response or self._get_response_object()
                
                if resp_obj is None:
                    logger.debug(f"No response object available, ignoring send() call")
                    return 0  # Default return
                
                if context_type == 'http':
                    # HTTP context: response.send(data, status_code=200)
                    return resp_obj.send(*args, **kwargs)
                elif context_type == 'pubsub':
                    # PubSub context: response.send(payload, final=True)
                    payload = args[0] if args else kwargs.get('payload', {})
                    final = kwargs.get('final', True)
                    return resp_obj.send(payload, final=final)
                elif context_type == 'websocket':
                    # WebSocket context: response.send(data, message_type="response", target_sid=None)
                    data = args[0] if args else kwargs.get('data', {})
                    message_type = kwargs.get('message_type', "response")
                    target_sid = kwargs.get('target_sid', None)
                    
                    if hasattr(resp_obj, 'send'):
                        # Include target_sid if provided
                        return resp_obj.send(data, message_type=message_type, target_sid=target_sid)
                    else:
                        # Fall back to daemon's websocket.send if available
                        daemon = get_daemon()
                        if hasattr(daemon, 'websocket') and daemon.websocket is not None:
                            # If target_sid is provided, use send_to_client, otherwise use send
                            if target_sid:
                                return daemon.websocket.send_to_client(target_sid, data, message_type)
                            else:
                                return daemon.websocket.send(data, message_type=message_type)
                return 0  # Default return for unknown context
            
            return unified_send
            
        elif name == 'error':
            # Unified error method for all contexts
            def unified_error(*args, **kwargs):
                context_type = get_context_type()
                
                # Get the response object
                resp_obj = thread_local_response or self._get_response_object()
                
                if resp_obj is None:
                    logger.debug(f"No response object available, ignoring error() call")
                    return 0  # Default return
                
                if context_type == 'http':
                    # HTTP context: response.error(err, status_code=400)
                    err = args[0] if args else kwargs.get('err', "Unknown error")
                    status_code = kwargs.get('status_code', 400)
                    # Handle HttpResponse that may not have an error method
                    if hasattr(resp_obj, 'error'):
                        return resp_obj.error(err, status_code=status_code)
                    else:
                        return resp_obj.send({"error": str(err)}, status_code)
                elif context_type == 'pubsub':
                    # PubSub context: response.error(err, final=True)
                    err = args[0] if args else kwargs.get('err', "Unknown error")
                    final = kwargs.get('final', True)
                    return resp_obj.error(err, final=final)
                elif context_type == 'websocket':
                    # WebSocket context: response.error(err, message_type="error", target_sid=None)
                    err = args[0] if args else kwargs.get('err', "Unknown error")
                    message_type = kwargs.get('message_type', "error")
                    target_sid = kwargs.get('target_sid', None)
                    
                    # Format error as object
                    error_payload = {"error": str(err)}
                    
                    if hasattr(resp_obj, 'error'):
                        # Use error method if available
                        return resp_obj.error(err, message_type=message_type, target_sid=target_sid)
                    elif hasattr(resp_obj, 'send'):
                        # Fall back to send method
                        return resp_obj.send(error_payload, message_type=message_type, target_sid=target_sid)
                    else:
                        # Fall back to daemon's websocket
                        daemon = get_daemon()
                        if hasattr(daemon, 'websocket') and daemon.websocket is not None:
                            # If target_sid is provided, use send_to_client, otherwise use send
                            if target_sid:
                                return daemon.websocket.send_to_client(target_sid, error_payload, message_type)
                            else:
                                return daemon.websocket.send(error_payload, message_type=message_type)
                return 0  # Default return for unknown context
                
            return unified_error
            
        # For legacy method support - redirect to standardized methods
        elif name == 'success':
            # Handle success method calls by routing to send
            def legacy_success(payload, **kwargs):
                logger.debug("Using deprecated 'success' method, please use 'send' instead")
                return self.send(payload, **kwargs)
            return legacy_success
            
        elif name == 'progress':
            # Handle progress method calls by routing to send with progress type
            def legacy_progress(payload, progress_percentage=None, **kwargs):
                logger.debug("Using deprecated 'progress' method, please use 'send' instead")
                
                # Format payload with progress percentage if provided
                if progress_percentage is not None:
                    if isinstance(payload, dict):
                        payload = payload.copy()
                        payload['progress_percentage'] = min(max(0, progress_percentage), 100)
                    else:
                        # Convert non-dict payload to dict with progress info
                        payload = {
                            'data': payload,
                            'progress_percentage': min(max(0, progress_percentage), 100)
                        }
                
                # Use context-specific messaging
                context_type = get_context_type()
                if context_type == 'websocket':
                    return self.send(payload, message_type="progress")
                elif context_type == 'pubsub':
                    # PubSub responses need final=False for progress updates
                    return self.send(payload, final=False)
                else:
                    # HTTP context just uses regular send
                    return self.send(payload)
                    
            return legacy_progress
                
        # Fall back to daemon's response
        daemon = get_daemon()
        if daemon is None:
            # Special handling for common methods in tests
            if name in self.PUBSUB_METHODS or name in self.WEBSOCKET_METHODS:
                # Return a no-op function for test cases
                def noop(*args, **kwargs):
                    logger.debug(f"No-op {name}() called")
                    return 0  # Simulate 0 clients received
                return noop
            
            raise RuntimeError("Daemon instance not available")
            
        context_type = get_context_type()

        # Check if method is allowed in current context
        if context_type == 'http' and name in self.PUBSUB_METHODS and name not in self.HTTP_METHODS:
            raise AttributeError(f"Method '{name}' is not available in HTTP context")
        elif context_type == 'pubsub' and name in self.HTTP_METHODS and name not in self.PUBSUB_METHODS:
            raise AttributeError(f"Method '{name}' is not available in pub/sub context")
        
        # WebSocket context handling
        if context_type == 'websocket':
            # If we're in a WebSocket context, we want to handle some methods specially
            if name in ['broadcast_to_all', 'send_to_client', 'broadcast_to_clients']:
                # These methods should be forwarded to the websocket component
                if hasattr(daemon, 'websocket') and daemon.websocket is not None:
                    return getattr(daemon.websocket, name)
                
        # Get the appropriate response object based on context
        response_obj = self._get_response_object()
                    
        if response_obj is not None:
            if hasattr(response_obj, name):
                return getattr(response_obj, name)
            else:
                # Method not found on response object
                raise AttributeError(f"'{response_obj.__class__.__name__}' object has no attribute '{name}'")
                
        # If we get here, no response object is available
        # Special handling for common response methods
        if name in self.PUBSUB_METHODS or name in self.WEBSOCKET_METHODS:
            # Return a no-op function for test cases
            def noop(*args, **kwargs):
                logger.debug(f"No-op {name}() called")
                return 0  # Simulate 0 clients received
            return noop
                
        raise AttributeError(f"No response object available (context: {context_type})")

    def _get_response_object(self) -> Optional[Any]:
        """Get the appropriate response object based on current context"""
        daemon = get_daemon()
        context_type = get_context_type()
        
        if daemon is None:
            return None
            
        if context_type == 'http':
            if hasattr(daemon, 'response_http') and daemon.response_http is not None:
                return daemon.response_http
            elif hasattr(daemon, 'response') and daemon.response is not None:
                return daemon.response
        elif context_type == 'websocket':
            if hasattr(daemon, 'response_ws') and daemon.response_ws is not None:
                return daemon.response_ws
            elif hasattr(daemon, 'response') and daemon.response is not None:
                return daemon.response
        else:  # pubsub or no context
            if hasattr(daemon, 'response') and daemon.response is not None:
                return daemon.response
                
        return None


# proxies for handler context
debug = _Proxy()
request = RequestProxy()
response = ResponseProxy()
broadcast = _Proxy('broadcast')
cache = _Proxy('cache')  # raw redis client
logger = LoggerProxy()
