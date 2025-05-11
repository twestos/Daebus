# Daebus

A lightweight framework for building Python background services with a Flask-like API, enabling seamless inter-service communication via Redis pub/sub.

## Overview

Daebus provides a simple way to create and connect distributed background services. It offers a Flask-inspired API that makes it easy to:

- Create systemd daemons that communicate with each other
- Expose HTTP endpoints for frontend applications (e.g., kiosk browsers)
- Enable quick bootstrapping of new services with minimal boilerplate

Services communicate via Redis pub/sub channels, providing a lightweight and reliable messaging system ideal for local service orchestration.

> **Note**: Daebus requires a Redis instance running on the system.

## Features

- **Flask-inspired API**: Simple, decorator-based API for defining service functionality
- **Redis Pub/Sub**: Direct channel-based communication between services
- **Action Routing**: Route messages to specific handlers based on action field
- **Background tasks**: Easy scheduling of periodic background tasks
- **Client library**: `DaebusCaller` allows for easy communication with Daebus services
- **HTTP endpoints**: Expose lightweight HTTP APIs from your daemon without additional dependencies
- **Specialized APIs**: Distinct and purpose-built APIs for HTTP and pub/sub contexts

## Installation
```bash
pip install daebus
```

## Quick Start

### Creating a Service

```python
from Daebus import Daebus, request, response, broadcast, cache, logger

app = Daebus(__name__)

# Define an action handler (like a Flask route)
@app.action("get_status")
def handle_status_request():
    try:
        payload = request.payload
        logger.info(f"Received status request: {payload}")

        # Process the request
        result = {"status": "healthy", "uptime": 3600}

        # Send response back to the requester
        return response.success(result)
    except Exception as e:
        return response.error(e)

# Define another action handler
@app.action("restart")
def handle_restart():
    try:
        logger.info("Handling restart request")
        # Restart logic here
        return response.success({"restarted": True})
    except Exception as e:
        return response.error(e)

# Define a channel listener for broadcasts
@app.listen("notifications")
def handle_notification(payload):
    logger.info(f"Received notification: {payload}")
    # Process the notification

# Define a background task that runs every 30 seconds
@app.background("health_check", 30)
def health_check():
    logger.info("Running health check")
    # Perform health check

    # Broadcast status to any interested services
    broadcast.send("system_status", {"status": "healthy"})

# Run the service
if __name__ == "__main__":
    app.run(service="my_service", debug=True)
```

### Communicating with Services using DaebusCaller

```python
from Daebus import DaebusCaller

# Create a caller for the target service
caller = DaebusCaller("my_service")

try:
    # Send a request to a specific action and wait for a response
    response = caller.send_request("get_status", {
        "detail_level": "full"
    })
    print(f"Service status: {response}")

    # Send a restart request
    restart_response = caller.send_request("restart", {
        "mode": "graceful"
    })
    print(f"Restart result: {restart_response}")

    # Send a message to a broadcast channel
    caller.send_message("notifications", {
        "type": "alert",
        "message": "System temperature high"
    })

    # Send a message directly to the service with a specific action
    caller.send_to_service({
        "timestamp": 1625176230,
        "info": "Direct message with action"
    }, action="log_info")
finally:
    # Clean up resources when done
    caller.close()
```

### Adding HTTP Endpoints to Your Service

You can easily add HTTP endpoints to your daemon using the built-in HTTP server:

```python
from Daebus import Daebus, DaebusHttp

app = Daebus(__name__)

# Create and attach an HTTP endpoint
http = DaebusHttp(port=8080)
app.attach(http)

# Define HTTP routes (similar to Flask)
@app.route("/status")
def get_status(req):
    # Use the request object to access request data
    # req.payload contains JSON, form data, or query params

    # For HTTP responses, use response.send with data and status code
    return response.send({
        "service": "my_service",
        "status": "running",
        "timestamp": time.time()
    }, 200)  # 200 OK status code

# Routes with parameters
@app.route("/devices/<device_id>")
def get_device(req, device_id):
    # The device_id parameter is extracted from the URL
    if device_id == "123":
        return response.send({
            "device_id": device_id,
            "status": "online"
        }, 200)
    else:
        # Error responses with appropriate status codes
        return response.send({
            "error": "Device not found"
        }, 404)  # 404 Not Found

# POST requests
@app.route("/control", methods=["POST"])
def control_action(req):
    # Access JSON data from the request payload
    data = req.payload

    # Process the request
    return response.send({
        "success": True,
        "message": "Command received"
    }, 201)  # 201 Created

# Run the service with HTTP enabled
app.run(service="my_service")
```

### Configuring CORS for HTTP Endpoints

If your HTTP API needs to be accessed from web browsers, you can configure Cross-Origin Resource Sharing (CORS):

```python
from Daebus import Daebus, DaebusHttp

app = Daebus(__name__)

# Configure CORS when creating the HTTP endpoint
cors_config = {
    'allowed_origins': ['http://localhost:3000', 'https://example.com'],  # Specific origins
    'allowed_methods': ['GET', 'POST', 'OPTIONS'],                        # Allowed HTTP methods
    'allowed_headers': ['Content-Type', 'Authorization'],                 # Allowed headers
    'expose_headers': ['X-Custom-Header'],                                # Headers exposed to client
    'allow_credentials': True,                                            # Allow cookies
    'max_age': 3600                                                       # Cache preflight for 1 hour
}

# Create HTTP endpoint with CORS support
http = DaebusHttp(port=8080, cors_config=cors_config)
app.attach(http)

# Alternatively, configure CORS after initialization
# http = DaebusHttp(port=8080)
# http.configure_cors({
#     'allowed_origins': '*',  # Allow all origins
#     'allowed_methods': ['GET', 'POST'],
#     'allowed_headers': '*',  # Allow all headers
# })

@app.route("/api/data")
def get_data(req):
    # This endpoint will now include CORS headers in the response
    return response.send({"data": "example"}, 200)
```

You can use these CORS configuration options:

- `allowed_origins`: List of allowed origins or `'*'` for any origin
- `allowed_methods`: List of allowed HTTP methods or `'*'` for any method
- `allowed_headers`: List of allowed headers or `'*'` for any header
- `expose_headers`: List of headers to expose to the client
- `allow_credentials`: Boolean for allowing credentials (cookies)
- `max_age`: Cache time (seconds) for preflight requests

### Protocol-Specific Response Methods

Daebus provides distinct response methods optimized for each protocol:

```python
from Daebus import Daebus, DaebusHttp, request, response

app = Daebus(__name__)
http = DaebusHttp(port=8080)
app.attach(http)

# Shared function for business logic
def get_status_data():
    return {
        "service": "my_service",
        "status": "healthy",
        "uptime": 3600
    }

# HTTP route with HTTP-specific response using response.send
@app.route("/status")
def http_status_handler(req):
    try:
        data = get_status_data()

        # Use response.send() for HTTP responses, with status code
        return response.send(data, 200)
    except Exception as e:
        # HTTP errors with appropriate status codes
        return response.send({"error": str(e)}, 500)

# Redis action handler with pub/sub specific response methods
@app.action("get_status")
def redis_status_handler():
    try:
        data = get_status_data()

        # Use response.success() for Redis responses
        return response.success(data)
    except Exception as e:
        # Redis-specific error handling
        return response.error(e)
```

### Advanced: Direct Access to Protocol-Specific Classes

For advanced usage, you can access the protocol-specific classes directly:

```python
from Daebus import (
    Daebus, DaebusHttp,
    HttpRequest, HttpResponse,  # HTTP-specific classes
    PubSubRequest, PubSubResponse  # Pub/Sub-specific classes
)

app = Daebus(__name__)
http = DaebusHttp(port=8080)
app.attach(http)

# Use HTTP-specific classes directly for advanced customization
@app.route("/advanced")
def advanced_handler(req):
    # Check if we have the right request type
    if not isinstance(req, HttpRequest):
        raise TypeError("Expected an HttpRequest object")

    # Create a custom HTTP response
    custom_response = HttpResponse(None)
    return custom_response.send({
        "message": "Custom HTTP response",
        "path": req.path
    }, 200)
```

Benefits of protocol-specific methods:

- `response.send(data, status_code)` - HTTP focused, with explicit status codes
- `response.success(data)` - Pub/sub focused, adds necessary pub/sub metadata
- `response.error(exception)` - Pub/sub focused, formats exceptions for pub/sub
- Clear distinction between HTTP and pub/sub handling
- Direct access to protocol-specific classes for advanced customization

## How It Works

### Action Routing

Daebus uses a simple action routing system:

1. Each service automatically listens on its main channel (named after the service)
2. Messages sent to this channel can include an `action` field to route to specific handlers
3. Handlers are registered using `@app.action("action_name")`

For example:

- When a message with `action: "get_status"` is received, it's routed to the function decorated with `@app.action("get_status")`
- When a message with `action: "restart"` is received, it's routed to the function decorated with `@app.action("restart")`

### Channel Types

Daebus uses two types of Redis pub/sub channels:

1. **Service Channels**: Named after the service (e.g., `my_service`) and used for direct communication with action routing
2. **Custom Channels**: Any additional channels that services can publish to or subscribe to (e.g., `notifications`, `system_status`)

### Message Flow

1. **Request/Response**:

    - Client calls `send_request("action_name", payload)`
    - DaebusCaller sends message to service's main channel with the action field
    - Service routes to appropriate handler based on action
    - Handler processes request and sends response back to caller's response channel

2. **Broadcasts**:
    - Any service can broadcast to any channel with `broadcast.send(channel, payload)`
    - Interested services subscribe to those channels with `@app.listen(channel)`

### HTTP Endpoints

Daebus provides a lightweight HTTP server that:

1. Uses Python's built-in `http.server` module (no external dependencies)
2. Automatically converts Python dictionaries to JSON responses
3. Parses JSON and form data from requests
4. Supports URL parameters with the same syntax as Flask (`/path/<param>`)
5. Runs in a background thread, allowing your service to handle both Redis and HTTP requests

### Protocol-Specific Classes

Daebus provides specialized classes for each protocol:

1. **For Pub/Sub (Redis)**:

    - `PubSubRequest`: Handles pub/sub message payloads, reply channels, and request IDs
    - `PubSubResponse`: Handles pub/sub responses and error handling

## Usage

### Basic Usage

```python
from daebus import Daebus, response, request, logger

app = Daebus(__name__)

@app.action("hello_world")
def hello_world():
    name = request.payload.get("name", "World")
    logger.info(f"Received request from {name}")
    return response.success({"message": f"Hello, {name}!"})

if __name__ == "__main__":
    app.run(service='hello-service')
```

### Logging

Daebus provides two logger options:
- `logger`: A proxy that references the service's logger. This works within main handlers.
- `direct_logger`: A direct reference to the base logger. This works in all contexts.

For background tasks, scheduled jobs, and other situations where the thread context might differ, use `direct_logger`:

```python
from daebus import Daebus, direct_logger

app = Daebus(__name__)

@app.background("periodic_task", interval=60)
def run_periodic_task():
    try:
        # Do some work
        direct_logger.info("Periodic task completed")
    except Exception as e:
        # Always use direct_logger in background tasks
        direct_logger.error(f"Error in periodic task: {e}")

if __name__ == "__main__":
    app.run(service='background-service')
```

### HTTP Endpoints

```python
from daebus import Daebus, DaebusHttp, response, logger

app = Daebus(__name__)
http = DaebusHttp(port=8080)

app.attach(http)

@app.route("/hello")
def hello(request):
    name = request.params.get("name", "World")
    logger.info(f"HTTP request from {name}")
    return response.send({"message": f"Hello, {name}!"}, 200)

if __name__ == "__main__":
    app.run(service='web-service')
```

### Cross-Service Communication

```python
from daebus import Daebus, DaebusCaller, direct_logger

app = Daebus(__name__)

# Create a caller for another service
other_service = DaebusCaller("other-service")

@app.on_start()
def initialize():
    direct_logger.info("Notifying other services that we've started")
    try:
        # Send a message to another service
        result = other_service.send_message("service_started", {
            "service_name": "my-service",
            "timestamp": time.time()
        })
        direct_logger.info(f"Notification sent, response: {result}")
    except Exception as e:
        direct_logger.error(f"Failed to send notification: {e}")

if __name__ == "__main__":
    app.run(service='my-service')
```

## Advanced Features

- **Background Tasks**: Run tasks periodically with `@app.background(name, interval)`
- **Threads**: Run long-running tasks in dedicated threads with `@app.thread(name)`
- **Lifecycle Hooks**: Register functions to run at service startup with `@app.on_start()`
- **HTTP**: Add HTTP endpoints with `@app.route(path, methods)`

## Thread Safety and Contexts

When working with Daebus in different contexts (HTTP handlers, background tasks, service initialization), 
follow these guidelines:

1. **Main Handlers**: In action handlers and HTTP route handlers, you can use `logger`, `request`, and `response`.
2. **Background Tasks**: Always use `direct_logger` for logging in background tasks and scheduled jobs.
3. **Initialization**: Use `direct_logger` before calling `app.run()`.
4. **On Start Handlers**: For consistency, use `direct_logger` in `on_start` handlers.

## Concurrent Message Processing

Daebus 0.0.16+ includes built-in concurrent message processing to handle multiple incoming messages simultaneously:

- Messages are processed in a thread pool (default: 10 worker threads)
- Each message gets its own dedicated thread-local context
- Multiple services can communicate with the same service without blocking each other
- Long-running message handlers won't block other messages from being processed

You can adjust the thread pool size when initializing Daebus:

```python
app = Daebus(__name__, max_workers=20)  # Use 20 worker threads instead of the default 10
```

This ensures that your service can handle multiple concurrent requests efficiently, especially in environments where multiple services might be sending messages at the same time.

### Thread Safety Implementation

Daebus achieves thread safety through several mechanisms:

1. **Thread-Local Storage**: 
   - Each message handler thread gets its own isolated thread-local `request` and `response` objects
   - Thread-local storage prevents data leakage between concurrent operations
   - The framework automatically manages the thread-local context lifecycle

2. **Proxy Pattern**:
   - The `request` and `response` global objects are actually proxies
   - These proxies automatically detect which thread is executing and retrieve the correct thread-local objects
   - This approach maintains backward compatibility while enabling concurrency

3. **Thread Pool Management**:
   - A configurable `ThreadPoolExecutor` manages concurrent message processing
   - The pool size can be tuned based on system resources and workload characteristics
   - Protection against thread pool exhaustion with retry mechanisms and exponential backoff

4. **Resource Cleanup**:
   - Thread-local storage is properly cleaned up after each message is processed
   - This prevents memory leaks and ensures resources are released

### Performance Considerations

Based on stress testing, the concurrent processing architecture can handle:

- Thousands of messages per second on modest hardware
- Burst patterns of traffic without message loss
- Long-running handlers without blocking other messages

For optimal performance:

- **Thread Pool Size**: For most applications, 10-20 workers is sufficient. CPU-bound workloads may benefit from fewer workers (matching CPU core count), while I/O-bound workloads may benefit from more workers.
- **Message Processing**: Keep message handlers efficient. While concurrency allows long-running handlers, it's still best practice to keep processing time minimal.
- **Redis Connection**: Ensure your Redis instance can handle the concurrent connections and throughput.

### Error Handling in Concurrent Context

When a handler encounters an exception:

- The error is contained within that specific thread
- Other message processing continues unaffected
- The framework logs the error and properly cleans up thread-local resources
- For background tasks, always use `direct_logger` instead of the proxy `logger`

```python
from daebus import Daebus, direct_logger

app = Daebus(__name__, max_workers=20)

@app.thread("long_running")
def background_processor(running):
    while running():
        try:
            # Process something
            pass
        except Exception as e:
            # Always use direct_logger for thread-safe logging
            direct_logger.error(f"Error in background processor: {e}")
```

### Advanced: Thread-Safe Shared State

If your service needs to share state between message handlers:

1. Use thread-safe data structures from `queue` or `collections.concurrent`
2. Protect shared resources with locks from the `threading` module
3. Consider using atomic operations where possible

Example:

```python
import threading
from daebus import Daebus, request, response

app = Daebus(__name__)

# Thread-safe counter using a lock
request_counter = 0
counter_lock = threading.Lock()

@app.action("increment")
def increment_counter():
    global request_counter
    
    # Use a lock to safely update shared state
    with counter_lock:
        request_counter += 1
        current_count = request_counter
    
    return response.success({"count": current_count})
```

## License

MIT