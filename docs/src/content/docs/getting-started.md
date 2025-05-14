---
title: Getting Started
description: Build your first Daebus application in minutes
---

Welcome to Daebus, a lightweight framework for building Python background services with seamless inter-service communication. This guide will take you through the essential steps to create your first Daebus application.

## Prerequisites

Before you begin, make sure you have:

- Python 3.9 or higher
- A running Redis server (required for pub/sub messaging)
- Basic Python knowledge

If you haven't installed Daebus yet, follow the [Installation](/installation) guide.

## Understanding Daebus Concepts

Before diving into code, let's understand the core concepts of Daebus:

- **Services**: Independent Python applications that can communicate with each other
- **Actions**: Functions that handle specific messages sent to a service
- **Channel Listeners**: Functions that process messages from broadcast channels
- **HTTP Endpoints**: REST API routes exposed by your service

## Creating Your First Service

Let's create a simple "hello world" service that responds to messages:

1. Create a new file called `hello_service.py`
2. Add the following code:

```python
from daebus import Daebus, request, response, logger

# Create a Daebus application
app = Daebus(__name__)

# Define an action handler
@app.action("hello")
def handle_hello():
    # Get the name from the request payload, or default to "World"
    name = request.payload.get("name", "World")
    
    # Log the request
    logger.info(f"Received hello request for {name}")
    
    # Return a response
    return response.success({
        "message": f"Hello, {name}!"
    })

# Run the service
if __name__ == "__main__":
    app.run(service="hello-service")
```

3. Run your service:

```bash
python hello_service.py
```

Your service is now running and listening for messages on the "hello-service" channel!

## Communicating with Your Service

Let's create a client to communicate with our service. Create a new file called `hello_client.py`:

```python
from daebus import DaebusCaller

# Create a caller for our hello-service
caller = DaebusCaller("hello-service")

try:
    # Send a request to the "hello" action
    result = caller.send_request("hello", {
        "name": "Daebus"
    })
    
    # Print the response
    print(result)
    
    # Send another request
    result = caller.send_request("hello", {})
    print(result)
    
finally:
    # Always close the caller when done
    caller.close()
```

Run the client:

```bash
python hello_client.py
```

You should see responses like:
```
{'message': 'Hello, Daebus!'}
{'message': 'Hello, World!'}
```

## Adding HTTP Support

Let's enhance our service with HTTP endpoints:

```python
from daebus import Daebus, DaebusHttp, request, response, logger

# Create a Daebus application
app = Daebus(__name__)

# Add HTTP support
http = DaebusHttp(port=8080)
app.attach(http)

# Define an action handler for direct service communication
@app.action("hello")
def handle_hello():
    name = request.payload.get("name", "World")
    logger.info(f"Received direct hello request for {name}")
    return response.success({
        "message": f"Hello, {name}!"
    })

# Define an HTTP endpoint
@app.route("/hello")
def http_hello(req):
    name = req.payload.get("name", "World")
    logger.info(f"Received HTTP hello request for {name}")
    return response.send({
        "message": f"Hello, {name}!"
    }, 200)

# Run the service
if __name__ == "__main__":
    app.run(service="hello-service")
```

Now you can access your service via HTTP:

```bash
# Using curl
curl "http://localhost:8080/hello?name=Web"

# Or in a browser
# http://localhost:8080/hello?name=Browser
```

## Scheduling Background Tasks

Let's add a periodic background task to our service:

```python
from daebus import Daebus, DaebusHttp, direct_logger, request, response
import time

app = Daebus(__name__)
http = DaebusHttp(port=8080)
app.attach(http)

# Keep track of uptime
start_time = time.time()

# Add a background task that runs every 30 seconds
@app.background("stats_reporter", 30)
def report_stats():
    uptime = time.time() - start_time
    direct_logger.info(f"Service uptime: {uptime:.2f} seconds")

# Define routes
@app.route("/status")
def get_status(req):
    uptime = time.time() - start_time
    return response.send({
        "service": "hello-service",
        "status": "running",
        "uptime": f"{uptime:.2f} seconds"
    }, 200)

# Run the service
if __name__ == "__main__":
    app.run(service="hello-service")
```

## A Complete Example

Here's a more complete example that combines multiple features:

```python
from daebus import Daebus, DaebusHttp, request, response, broadcast, direct_logger
import time

# Create our application
app = Daebus(__name__)

# Add HTTP support
http = DaebusHttp(port=8080)
app.attach(http)

# Track service metrics
metrics = {
    "start_time": time.time(),
    "requests": 0
}

# Action handler for direct service communication
@app.action("get_metrics")
def handle_get_metrics():
    uptime = time.time() - metrics["start_time"]
    
    # Increment request counter
    metrics["requests"] += 1
    
    return response.success({
        "uptime": f"{uptime:.2f} seconds",
        "requests": metrics["requests"]
    })

# Listen to broadcast messages on the "system" channel
@app.listen("system")
def handle_system_event(data):
    event_type = data.get("type")
    direct_logger.info(f"Received system event: {event_type}")

# HTTP endpoint
@app.route("/metrics")
def http_get_metrics(req):
    uptime = time.time() - metrics["start_time"]
    
    # Increment request counter
    metrics["requests"] += 1
    
    return response.send({
        "uptime": f"{uptime:.2f} seconds",
        "requests": metrics["requests"]
    }, 200)

# Background task for periodic reporting
@app.background("metrics_reporter", 60)  # Every 60 seconds
def broadcast_metrics():
    try:
        uptime = time.time() - metrics["start_time"]
        
        # Broadcast to the "system" channel
        broadcast.send("system", {
            "type": "metrics_update",
            "service": "example-service",
            "uptime": f"{uptime:.2f} seconds",
            "requests": metrics["requests"]
        })
        
        direct_logger.info("Metrics broadcast completed")
    except Exception as e:
        direct_logger.error(f"Error broadcasting metrics: {e}")

# Run the application
if __name__ == "__main__":
    app.run(service="example-service")
```

## Next Steps

Now that you've created your first Daebus application, you can:

1. Learn about the [PubSub Messaging](/guides/messaging) system for inter-service communication
2. Explore [HTTP Endpoints](/guides/http) for building REST APIs
3. Add [WebSockets](/guides/websockets) for real-time communication
4. Use [Task Scheduler](/guides/task-scheduler) for background processing
5. Implement [Background Threads](/guides/threads) for continuous processing
6. Organize your code with [Blueprints](/guides/blueprint)

## Common Patterns

### Service Registration

When building a system with multiple services, it's common to implement service discovery:

```python
@app.on_start()
def register_service():
    try:
        # Broadcast that our service is starting
        broadcast.send("service_registry", {
            "type": "service_started",
            "service": "my-service",
            "capabilities": ["data_processing", "api"],
            "timestamp": time.time()
        })
        direct_logger.info("Service registered")
    except Exception as e:
        direct_logger.error(f"Failed to register service: {e}")
```

### Service-to-Service Communication

```python
from daebus import Daebus, DaebusCaller

app = Daebus(__name__)

# Create a caller for another service
data_service = DaebusCaller("data-service")

@app.action("process_user")
def process_user():
    user_id = request.payload.get("user_id")
    
    # Call the data service to get user details
    user_data = data_service.send_request("get_user", {
        "user_id": user_id
    })
    
    # Process the user data
    result = {
        "user": user_data,
        "processed": True
    }
    
    return response.success(result)
```

## Troubleshooting

### Redis Connection Issues

If your service can't connect to Redis:

1. Make sure Redis is running: `redis-cli ping`
2. Check that your Redis host/port configuration is correct
3. Ensure your firewall allows connections to Redis

### Message Queue Backlog

If your service is processing messages slowly:

1. Increase the thread pool: `app = Daebus(__name__, max_workers=20)`
2. Optimize your message handlers
3. Consider splitting functionality into multiple services

### Logging

For debugging issues:

1. Use `logger` in main handlers: `logger.debug("Processing request")`
2. Use `direct_logger` in background tasks and threads: `direct_logger.debug("Background task running")`

## Further Learning

- Check the [Overview](/overview) for a high-level understanding of Daebus architecture
- Explore the other [Guides](/guides) for detailed features
- Refer to the [GitHub repository](https://github.com/twestos/daebus) for source code and examples
