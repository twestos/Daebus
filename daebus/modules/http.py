import threading
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver
import io
import time
import re
import email.parser
from typing import Dict, Any, Tuple, Optional, List, Union, Callable, Set

from .logger import logger as _default_logger
from .context import set_context_type, get_context_type


class HttpRequest:
    """
    HTTP request object that mimics the pub/sub Request interface.
    This allows route handlers to use a consistent interface regardless of context.
    """

    def __init__(self, raw_request: Dict[str, Any]):
        self.raw = raw_request
        self.payload = raw_request.get('json') or raw_request.get(
            'form') or raw_request.get('query') or {}
        self.method = raw_request.get('method', 'GET')
        self.path = raw_request.get('path', '/')
        self.headers = raw_request.get('headers', {})
        self.params = raw_request.get('params', {})

        # Add pub/sub compatibility fields
        self.reply_to = None  # Not used in HTTP context
        self.request_id = f"http-{int(time.time()*1000)}"
        self.service = "http"  # Indicates this is an HTTP request


class HttpResponse:
    """
    HTTP response object that mimics the pub/sub Response interface
    but returns HTTP-formatted responses instead of publishing to Redis.
    """

    def __init__(self, http_handler: Optional[BaseHTTPRequestHandler] = None):
        self.handler = http_handler
        self._response_data: Any = None
        self._status_code: int = 200

    def send(self, data: Any, status_code: int = 200) -> Tuple[Any, int]:
        """
        Send an HTTP response with the specified data and status code.
        This is the preferred method for HTTP responses.

        Args:
            data: The response data (will be JSON serialized)
            status_code: HTTP status code (default: 200)

        Returns:
            tuple: (data, status_code) for HTTP response
        """
        self._response_data = data
        self._status_code = status_code
        return data, status_code

    def success(self, payload: Dict[str, Any], final: bool = True) -> Tuple[Dict[str, Any], int]:
        """
        Create a successful HTTP response.
        This method is provided for compatibility with pub/sub handlers.
        For HTTP-specific handlers, prefer using `send()`.

        Args:
            payload (dict): The response data
            final (bool): Ignored in HTTP context

        Returns:
            tuple: (payload, status_code) for HTTP response
        """
        response_data = {
            'status': 'success',
            'payload': payload
        }
        self._response_data = response_data
        self._status_code = 200
        return payload, 200

    def error(self, err: Exception, final: bool = True) -> Tuple[Dict[str, str], int]:
        """
        Create an error HTTP response.
        This method is provided for compatibility with pub/sub handlers.
        For HTTP-specific handlers, prefer using `send({"error": "message"}, 4xx)`.

        Args:
            err (Exception): The error that occurred
            final (bool): Ignored in HTTP context

        Returns:
            tuple: (error_payload, status_code) for HTTP response
        """
        error_msg = str(err)
        response_data = {
            'status': 'error',
            'error': error_msg
        }
        self._response_data = response_data
        self._status_code = 400  # Bad request by default
        return {'error': error_msg}, 400

    def progress(self, payload: Dict[str, Any], progress_percentage: Optional[float] = None) -> Tuple[Dict[str, Any], int]:
        """
        Send a progress update. 

        In HTTP context, this doesn't really make sense as HTTP is request/response,
        but we provide this for API compatibility. It will simply return the payload
        with progress information.

        Args:
            payload (dict): Progress information
            progress_percentage (float, optional): Progress as a percentage (0-100)

        Returns:
            tuple: (payload, status_code) for HTTP response
        """
        if progress_percentage is not None:
            payload = payload.copy()
            payload['progress_percentage'] = min(
                max(0, progress_percentage), 100)

        response_data = {
            'status': 'progress',
            'payload': payload,
            'final': False
        }
        self._response_data = response_data
        self._status_code = 200
        return payload, 200

    def set_status(self, status_code: int) -> 'HttpResponse':
        """
        Set the HTTP status code for the response.

        Args:
            status_code (int): HTTP status code

        Returns:
            self: For method chaining
        """
        self._status_code = status_code
        return self

    def get_response(self) -> Tuple[Any, int]:
        """
        Get the current response data and status code.

        Returns:
            tuple: (response_data, status_code)
        """
        return self._response_data, self._status_code


def parse_multipart_form(content_type: str, data: bytes) -> Dict[str, Any]:
    """
    Parse multipart form data without using the deprecated cgi module.

    Args:
        content_type: The Content-Type header value
        data: The raw form data bytes

    Returns:
        dict: Parsed form data
    """
    boundary = None
    for part in content_type.split(';'):
        part = part.strip()
        if part.startswith('boundary='):
            boundary = part[9:]
            # Remove quotes if present
            if boundary.startswith('"') and boundary.endswith('"'):
                boundary = boundary[1:-1]
            break

    if not boundary:
        return {}

    # Parse the multipart data
    result = {}

    # Create a message parser
    parser = email.parser.BytesParser()

    # Ensure the data starts with the boundary
    if not data.startswith(b'--' + boundary.encode('utf-8')):
        data = b'--' + boundary.encode('utf-8') + b'\r\n' + data

    # Sometimes we need to fix the message format if it doesn't end properly
    if not data.endswith(b'--\r\n'):
        if not data.endswith(b'\r\n'):
            data += b'\r\n'
        data += b'--' + boundary.encode('utf-8') + b'--\r\n'

    try:
        # Parse the multipart message
        message = parser.parse(io.BytesIO(data), headersonly=False)

        if message.is_multipart():
            for part in message.get_payload():
                # Get content disposition
                content_disp = part.get('Content-Disposition', '')
                if 'form-data' not in content_disp:
                    continue

                # Extract field name
                name_match = re.search(r'name="([^"]*)"', content_disp)
                if not name_match:
                    continue

                field_name = name_match.group(1)

                # Check if this is a file upload
                filename_match = re.search(r'filename="([^"]*)"', content_disp)

                if filename_match:
                    # File upload
                    filename = filename_match.group(1)
                    payload = part.get_payload(decode=True)
                    result[field_name] = {
                        'filename': filename,
                        'value': payload
                    }
                else:
                    # Regular form field
                    payload = part.get_payload(decode=True)
                    try:
                        # Try to decode as text
                        result[field_name] = payload.decode('utf-8')
                    except UnicodeDecodeError:
                        # Keep as binary if can't decode
                        result[field_name] = payload
    except Exception as e:
        _default_logger.error(f"Error parsing multipart form data: {e}")
        return {}  # Return empty dict on parsing error

    return result


class DaebusHttpHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Daebus HTTP server."""

    # These will be set by DaebusHttp when creating the server
    routes: Dict[str, Dict[str, Any]] = {}
    logger = None
    daemon = None
    cors_config = None

    def log_message(self, format: str, *args: Any) -> None:
        """Override to use Daebus logger instead of stderr"""
        if self.logger:
            self.logger.debug(format % args)

    def _get_route_handler(self, path: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
        """Find the appropriate route handler for the given path"""
        # First try exact match
        if path in self.routes:
            return self.routes[path], {}

        # Check for parametrized routes
        for route_path, route_info in self.routes.items():
            if '<' in route_path and '>' in route_path:
                # This is a parametrized route
                route_parts = route_path.split('/')
                path_parts = path.split('/')

                if len(route_parts) != len(path_parts):
                    continue

                params = {}
                match = True

                for i, (route_part, path_part) in enumerate(zip(route_parts, path_parts)):
                    if route_part.startswith('<') and route_part.endswith('>'):
                        # This is a parameter
                        param_name = route_part[1:-1]
                        params[param_name] = path_part
                    elif route_part != path_part:
                        match = False
                        break

                if match:
                    return route_info, params

        return None, {}

    def _parse_json_body(self) -> Optional[Dict[str, Any]]:
        """Parse JSON request body if present"""
        content_type = self.headers.get('Content-Type', '').lower()
        if 'application/json' not in content_type:
            return None

        content_length = int(self.headers.get('Content-Length', 0))
        if content_length <= 0:
            return None

        try:
            body = self.rfile.read(content_length).decode('utf-8')
            return json.loads(body)
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse JSON request body")
            return None
        except Exception as e:
            self.logger.error(f"Error reading request body: {e}")
            return None

    def _parse_form_data(self) -> Optional[Dict[str, Any]]:
        """Parse form data from request body"""
        content_type = self.headers.get('Content-Type', '').lower()
        content_length = int(self.headers.get('Content-Length', 0))

        if content_length <= 0:
            return None

        # Read the request body
        try:
            body = self.rfile.read(content_length)

            if 'multipart/form-data' in content_type:
                # Use custom multipart form parsing
                return parse_multipart_form(content_type, body)
            elif 'application/x-www-form-urlencoded' in content_type:
                # Parse URL-encoded form data
                return dict(urllib.parse.parse_qsl(body.decode('utf-8')))
        except Exception as e:
            self.logger.error(f"Error parsing form data: {e}")

        return None

    def _send_response(self, status_code: int, data: Any) -> None:
        """Send a JSON response"""
        try:
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json')

            # Add CORS headers if configured
            if self.cors_config:
                origin = self.headers.get('Origin')

                # Handle 'Access-Control-Allow-Origin'
                if origin:
                    allowed_origins = self.cors_config.get(
                        'allowed_origins', [])
                    if '*' in allowed_origins or origin in allowed_origins:
                        self.send_header('Access-Control-Allow-Origin', origin)
                    elif allowed_origins:  # If we have origins but this one isn't allowed, don't send header
                        pass
                    else:  # No origins specified, default to '*'
                        self.send_header('Access-Control-Allow-Origin', '*')

                # Handle other CORS headers
                if self.cors_config.get('allow_credentials'):
                    self.send_header(
                        'Access-Control-Allow-Credentials', 'true')

                if self.cors_config.get('allowed_headers'):
                    headers = ','.join(self.cors_config['allowed_headers'])
                    self.send_header('Access-Control-Allow-Headers', headers)

                if self.cors_config.get('allowed_methods'):
                    methods = ','.join(self.cors_config['allowed_methods'])
                    self.send_header('Access-Control-Allow-Methods', methods)

                if self.cors_config.get('max_age'):
                    self.send_header('Access-Control-Max-Age',
                                     str(self.cors_config['max_age']))

                if self.cors_config.get('expose_headers'):
                    headers = ','.join(self.cors_config['expose_headers'])
                    self.send_header('Access-Control-Expose-Headers', headers)

            self.end_headers()

            # Convert data to JSON and encode as bytes
            try:
                response = json.dumps(data).encode('utf-8')
                self.wfile.write(response)
            except (TypeError, ValueError) as e:
                # Handle case where data is not JSON serializable
                self.logger.error(f"Error serializing response to JSON: {e}")
                error_response = json.dumps(
                    {"error": "Internal server error"}).encode('utf-8')
                self.wfile.write(error_response)
            except Exception as e:
                self.logger.error(f"Error sending response: {e}")
        except Exception as e:
            self.logger.error(f"Failed to send HTTP response: {e}")

    def _handle_request(self, method: str, raw_request: Dict[str, Any],
                        route_info: Dict[str, Any], params: Dict[str, str]) -> Tuple[Any, int]:
        """
        Common logic for handling all types of requests

        Args:
            method: HTTP method (GET, POST, etc.)
            raw_request: Dictionary with request data
            route_info: Route handler information
            params: Path parameters extracted from URL

        Returns:
            tuple: (response_data, status_code)
        """
        try:
            # Create the request and response objects for this context
            if self.daemon:
                http_request = HttpRequest(raw_request)
                http_response = HttpResponse(self)

                # Set these on the daemon for use by context-aware proxies
                self.daemon.request_http = http_request
                self.daemon.response_http = http_response

                # Set the context type to HTTP for this thread
                set_context_type('http')

                try:
                    # Call the handler function with the request parameter and any URL params
                    result = route_info['function'](http_request, **params)
                except Exception as handler_error:
                    # Catch exceptions from the handler function itself
                    self.logger.error(
                        f"Error in route handler: {handler_error}")
                    return {"error": str(handler_error)}, 500
                finally:
                    # Always reset the context type, even if an exception occurred
                    set_context_type(None)

                # Check if we already have a response from http_response methods
                if http_response._response_data is not None:
                    data, status_code = http_response.get_response()
                    if isinstance(data, tuple) and len(data) == 2:
                        # Extract data if it's a tuple (ignore status code)
                        data, _ = data
                    return data, status_code

                # Handle different return types from the route handler
                if isinstance(result, tuple) and len(result) == 2:
                    data, status_code = result
                else:
                    data, status_code = result, 200

                return data, status_code
            else:
                # Direct route function call without Daebus context
                result = route_info['function'](raw_request, **params)

                if isinstance(result, tuple) and len(result) == 2:
                    return result
                return result, 200

        except Exception as e:
            if self.logger:
                self.logger.error(
                    f"Error handling {method} {raw_request.get('path', '')}: {e}")
            return {"error": "Internal server error", "details": str(e)}, 500

    def do_GET(self) -> None:
        """Handle GET requests"""
        try:
            path = urllib.parse.urlparse(self.path).path
            query = dict(urllib.parse.parse_qsl(
                urllib.parse.urlparse(self.path).query))

            route_info, params = self._get_route_handler(path)

            if not route_info or 'GET' not in route_info['methods']:
                self._send_response(404, {"error": "Not Found", "path": path})
                return

            # Create a request object similar to what Flask provides
            raw_request = {
                'method': 'GET',
                'path': path,
                'query': query,
                'params': params,
                'headers': dict(self.headers.items()),
                'json': None,
                'form': None
            }

            data, status_code = self._handle_request(
                'GET', raw_request, route_info, params)
            self._send_response(status_code, data)
        except Exception as e:
            self.logger.error(f"Unhandled error in do_GET: {e}")
            self._send_response(
                500, {"error": "Internal server error", "details": str(e)})

    def do_POST(self) -> None:
        """Handle POST requests"""
        try:
            path = urllib.parse.urlparse(self.path).path

            route_info, params = self._get_route_handler(path)

            if not route_info or 'POST' not in route_info['methods']:
                self._send_response(404, {"error": "Not Found", "path": path})
                return

            # Parse request body (JSON or form data)
            json_body = self._parse_json_body()
            form_data = None
            if json_body is None:
                form_data = self._parse_form_data()

            # Create a request object similar to what Flask provides
            raw_request = {
                'method': 'POST',
                'path': path,
                'params': params,
                'headers': dict(self.headers.items()),
                'json': json_body,
                'form': form_data
            }

            data, status_code = self._handle_request(
                'POST', raw_request, route_info, params)
            self._send_response(status_code, data)
        except Exception as e:
            self.logger.error(f"Unhandled error in do_POST: {e}")
            self._send_response(
                500, {"error": "Internal server error", "details": str(e)})

    def do_PUT(self) -> None:
        """Handle PUT requests"""
        try:
            path = urllib.parse.urlparse(self.path).path

            route_info, params = self._get_route_handler(path)

            if not route_info or 'PUT' not in route_info['methods']:
                self._send_response(404, {"error": "Not Found", "path": path})
                return

            json_body = self._parse_json_body()

            raw_request = {
                'method': 'PUT',
                'path': path,
                'params': params,
                'headers': dict(self.headers.items()),
                'json': json_body
            }

            data, status_code = self._handle_request(
                'PUT', raw_request, route_info, params)
            self._send_response(status_code, data)
        except Exception as e:
            self.logger.error(f"Unhandled error in do_PUT: {e}")
            self._send_response(
                500, {"error": "Internal server error", "details": str(e)})

    def do_DELETE(self) -> None:
        """Handle DELETE requests"""
        try:
            path = urllib.parse.urlparse(self.path).path

            route_info, params = self._get_route_handler(path)

            if not route_info or 'DELETE' not in route_info['methods']:
                self._send_response(404, {"error": "Not Found", "path": path})
                return

            raw_request = {
                'method': 'DELETE',
                'path': path,
                'params': params,
                'headers': dict(self.headers.items())
            }

            data, status_code = self._handle_request(
                'DELETE', raw_request, route_info, params)
            self._send_response(status_code, data)
        except Exception as e:
            self.logger.error(f"Unhandled error in do_DELETE: {e}")
            self._send_response(
                500, {"error": "Internal server error", "details": str(e)})

    def do_OPTIONS(self) -> None:
        """Handle OPTIONS requests for CORS preflight"""
        try:
            path = urllib.parse.urlparse(self.path).path
            route_info, _ = self._get_route_handler(path)

            # If route exists, return appropriate CORS headers
            if route_info:
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')

                # Add CORS headers if configured
                if self.cors_config:
                    origin = self.headers.get('Origin')

                    # Handle 'Access-Control-Allow-Origin'
                    if origin:
                        allowed_origins = self.cors_config.get(
                            'allowed_origins', [])
                        if '*' in allowed_origins or origin in allowed_origins:
                            self.send_header(
                                'Access-Control-Allow-Origin', origin)
                        elif allowed_origins:  # If we have origins but this one isn't allowed, don't send header
                            pass
                        else:  # No origins specified, default to '*'
                            self.send_header(
                                'Access-Control-Allow-Origin', '*')

                    # Handle other CORS headers
                    if self.cors_config.get('allow_credentials'):
                        self.send_header(
                            'Access-Control-Allow-Credentials', 'true')

                    # Get the request's Access-Control-Request-Headers
                    request_headers = self.headers.get(
                        'Access-Control-Request-Headers')
                    if request_headers and self.cors_config.get('allowed_headers'):
                        if '*' in self.cors_config['allowed_headers']:
                            self.send_header(
                                'Access-Control-Allow-Headers', request_headers)
                        else:
                            headers = ','.join(
                                self.cors_config['allowed_headers'])
                            self.send_header(
                                'Access-Control-Allow-Headers', headers)

                    # Get available methods for this route
                    if route_info and 'methods' in route_info:
                        route_methods = route_info['methods']
                        if self.cors_config.get('allowed_methods'):
                            if '*' in self.cors_config['allowed_methods']:
                                methods = ','.join(route_methods)
                                self.send_header(
                                    'Access-Control-Allow-Methods', methods)
                            else:
                                # Intersection of configured methods and route methods
                                allowed = [
                                    m for m in route_methods if m in self.cors_config['allowed_methods']]
                                if allowed:
                                    methods = ','.join(allowed)
                                    self.send_header(
                                        'Access-Control-Allow-Methods', methods)
                        else:
                            # Default to route's methods if none configured
                            methods = ','.join(route_methods)
                            self.send_header(
                                'Access-Control-Allow-Methods', methods)

                    if self.cors_config.get('max_age'):
                        self.send_header('Access-Control-Max-Age',
                                         str(self.cors_config['max_age']))

                self.end_headers()
                return

            # If no route exists, return 404
            self._send_response(404, {"error": "Not Found", "path": path})

        except Exception as e:
            self.logger.error(f"Unhandled error in do_OPTIONS: {e}")
            self._send_response(
                500, {"error": "Internal server error", "details": str(e)})


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    allow_reuse_address = True


class DaebusHttp:
    """
    HTTP endpoint support for Daebus applications.

    This class allows Daebus applications to expose HTTP endpoints using Python's
    built-in http.server, without requiring Flask or other web frameworks.
    """

    def __init__(self, port: int = 8080, host: str = '0.0.0.0', cors_config: Optional[Dict[str, Any]] = None):
        """
        Initialize the HTTP server component.

        Args:
            port: Port number to bind the HTTP server to (default: 8080)
            host: Host address to bind to (default: '0.0.0.0', all interfaces)
            cors_config: CORS configuration dictionary with the following optional keys:
                - allowed_origins: List of allowed origins (e.g. ["http://example.com"]) or ["*"] for any
                - allowed_methods: List of allowed HTTP methods (e.g. ["GET", "POST"]) or ["*"] for any
                - allowed_headers: List of allowed headers or ["*"] for any
                - expose_headers: List of headers to expose to the client
                - allow_credentials: Boolean indicating whether to allow credentials
                - max_age: Maximum cache time in seconds for preflight requests
        """
        self.port = port
        self.host = host
        self.server: Optional[ThreadedHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.logger = _default_logger.getChild("http")
        self.daemon = None
        self.routes: Dict[str, Dict[str, Any]] = {}

        # Process CORS configuration
        self.cors_config = None
        if cors_config:
            self.cors_config = self._process_cors_config(cors_config)

    def _process_cors_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process and validate CORS configuration.

        Args:
            config: Raw CORS configuration dictionary

        Returns:
            Dict: Processed CORS configuration
        """
        processed = {}

        # Process allowed origins
        if 'allowed_origins' in config:
            if config['allowed_origins'] == '*' or '*' in config['allowed_origins']:
                processed['allowed_origins'] = ['*']
            else:
                # Ensure it's a list of strings
                origins = config['allowed_origins']
                if isinstance(origins, str):
                    origins = [origins]
                processed['allowed_origins'] = list(origins)

        # Process allowed methods
        if 'allowed_methods' in config:
            if config['allowed_methods'] == '*' or '*' in config['allowed_methods']:
                processed['allowed_methods'] = ['*']
            else:
                methods = config['allowed_methods']
                if isinstance(methods, str):
                    methods = [methods]
                processed['allowed_methods'] = [m.upper() for m in methods]

        # Process allowed headers
        if 'allowed_headers' in config:
            if config['allowed_headers'] == '*' or '*' in config['allowed_headers']:
                processed['allowed_headers'] = ['*']
            else:
                headers = config['allowed_headers']
                if isinstance(headers, str):
                    headers = [headers]
                processed['allowed_headers'] = list(headers)

        # Process exposed headers
        if 'expose_headers' in config:
            headers = config['expose_headers']
            if isinstance(headers, str):
                headers = [headers]
            processed['expose_headers'] = list(headers)

        # Process boolean flags
        if 'allow_credentials' in config:
            processed['allow_credentials'] = bool(config['allow_credentials'])

        # Process numeric values
        if 'max_age' in config:
            processed['max_age'] = int(config['max_age'])

        return processed

    def configure_cors(self, config: Dict[str, Any]) -> None:
        """
        Configure CORS settings after initialization.

        Args:
            config: CORS configuration dictionary (see __init__ for details)
        """
        self.cors_config = self._process_cors_config(config)
        self.logger.info("CORS configuration updated")

    def attach(self, daemon: Any) -> None:
        """
        Attach this HTTP component to a Daebus daemon.

        Args:
            daemon: The Daebus instance to attach to
        """
        self.daemon = daemon
        self.logger = _default_logger.getChild(f"{daemon.name}.http")
        daemon.http = self

        # Register the HTTP component's shutdown with the daemon
        original_run = daemon.run

        def wrapped_run(*args: Any, **kwargs: Any) -> Any:
            result = original_run(*args, **kwargs)
            self.stop()  # Ensure server is stopped when daemon stops
            return result

        daemon.run = wrapped_run

    def route(self, path: str, methods: Optional[List[str]] = None):
        """
        Register a function to handle requests at the given path.

        Args:
            path: URL path to handle
            methods: List of HTTP methods to accept (default: ['GET'])

        Returns:
            A decorator to wrap the handler function
        """
        if methods is None:
            methods = ['GET']

        if not self.daemon:
            raise RuntimeError("DaebusHttp not attached to a Daebus instance. "
                               "Use app.attach(endpoint) before defining routes.")

        def decorator(func: Callable) -> Callable:
            # Store the route information
            self.routes[path] = {
                'function': func,
                'methods': methods
            }
            return func

        return decorator

    def start(self) -> None:
        """Start the HTTP server in a background thread."""
        if self.server:
            self.logger.warning("HTTP server already running")
            return

        # Create a custom handler with access to our routes
        handler_class = type('CustomDaebusHttpHandler', (DaebusHttpHandler,), {
            'routes': self.routes,
            'logger': self.logger,
            'daemon': self.daemon,
            'cors_config': self.cors_config
        })

        try:
            # Create the server
            self.server = ThreadedHTTPServer(
                (self.host, self.port), handler_class)
            self.logger.info(
                f"Starting HTTP server on {self.host}:{self.port}")

            # Run the server in a background thread
            self.server_thread = threading.Thread(
                target=self.server.serve_forever,
                name="daebus_http_server",
                daemon=True
            )
            self.server_thread.start()
        except OSError as e:
            self.logger.error(
                f"Failed to start HTTP server on {self.host}:{self.port}: {e}")
            self.server = None
            self.server_thread = None
        except Exception as e:
            self.logger.error(f"Error starting HTTP server: {e}")
            self.server = None
            self.server_thread = None

    def stop(self) -> None:
        """Stop the HTTP server if it's running."""
        if self.server:
            self.logger.info("Shutting down HTTP server...")
            try:
                self.server.shutdown()
                if self.server_thread and self.server_thread.is_alive():
                    self.server_thread.join(timeout=5.0)
                self.server.server_close()  # Ensure socket is closed
            except Exception as e:
                self.logger.error(f"Error stopping HTTP server: {e}")
            finally:
                self.server = None
                self.server_thread = None
