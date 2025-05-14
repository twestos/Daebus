---
title: PubSub Messaging
description: Using Redis Pub/Sub for inter-service communication in Daebus
---

Daebus uses Redis Pub/Sub as its primary mechanism for inter-service communication. This lightweight messaging system allows your services to communicate with each other in real-time through a variety of patterns.

## Core Concepts

### Channel Types

Daebus uses two main types of Redis Pub/Sub channels:

1. **Service Channels**: Each service has its own dedicated channel (named after the service) for direct communication.
2. **Custom Channels**: Generic channels that any service can publish to or subscribe to (e.g., `notifications`, `events`, `system_status`).

### Message Flow Patterns

Daebus supports several messaging patterns:

1. **Request/Response**: Send a message to a service and receive a direct response
2. **Broadcast**: Send messages to any channel for one-to-many communication
3. **Action Routing**: Route messages to specific handlers within a service based on an `action` field

## Getting Started

### Defining Action Handlers

Action handlers respond to messages sent directly to your service channel:

```python
from daebus import Daebus, request, response, logger

app = Daebus(__name__)

@app.action("get_status")
def handle_status_request():
    # Access the request payload
    payload = request.payload
    logger.info(f"Received status request: {payload}")

    # Process the request
    result = {
        "status": "healthy",
        "uptime": 3600,
        "memory_usage": "128MB"
    }

    # Return a response (automatically sent back to requester)
    return response.send(result)

# Run the service
if __name__ == "__main__":
    app.run(service="system_monitor")
```

### Listening to Channels

To subscribe to custom channels for broadcast messages:

```python
from daebus import Daebus, logger

app = Daebus(__name__)

@app.listen("system_events")
def handle_system_event(data):
    event_type = data.get("type")
    event_data = data.get("data", {})
    
    logger.info(f"Received system event: {event_type}")
    
    # Process different event types
    if event_type == "shutdown":
        # Handle shutdown notification
        pass
    elif event_type == "config_changed":
        # Reload configuration
        pass

# Run the service
if __name__ == "__main__":
    app.run(service="event_listener")
```

### Broadcasting Messages

Send messages to any channel using the broadcast module:

```python
from daebus import Daebus, broadcast, logger
import time

app = Daebus(__name__)

@app.background("heartbeat", 60)  # Run every 60 seconds
def send_heartbeat():
    try:
        # Prepare heartbeat data
        heartbeat_data = {
            "type": "heartbeat",
            "service": "web_service",
            "timestamp": time.time(),
            "status": "operational"
        }
        
        # Broadcast to the monitoring channel
        recipients = broadcast.send("monitoring", heartbeat_data)
        logger.info(f"Heartbeat sent to {recipients} listeners")
    except Exception as e:
        logger.error(f"Failed to send heartbeat: {e}")

# Run the service
if __name__ == "__main__":
    app.run(service="web_service")
```

## Working with Requests

### The Request Object

In action handlers, the `request` object provides access to:

```python
@app.action("process_data")
def process_data():
    # The full payload sent with the request
    payload = request.payload
    
    # Metadata about the request
    reply_to = request.reply_to       # Channel to send response to
    request_id = request.request_id   # Unique ID for this request
    service = request.service         # Source service name
    
    # Access specific fields from the payload
    user_id = payload.get("user_id")
    data_type = payload.get("type")
    
    # Process based on payload content
    return response.send({"processed": True})
```

## Working with Responses

### Basic Responses

Send successful responses with the `response.send()` method:

```python
@app.action("create_user")
def create_user():
    user_data = request.payload
    
    # Process user creation
    new_user = {
        "id": "user123",
        "name": user_data.get("name"),
        "created_at": time.time()
    }
    
    # Return success response with the created user
    return response.send(new_user)
```

### Error Responses

For error conditions, use `response.error()`:

```python
@app.action("fetch_record")
def fetch_record():
    record_id = request.payload.get("id")
    
    if not record_id:
        # Return error for missing ID
        return response.error("Missing record ID")
    
    try:
        # Attempt to fetch the record
        record = database.get_record(record_id)
        
        if not record:
            return response.error(f"Record not found: {record_id}")
        
        # Return success with the record data
        return response.send(record)
    except Exception as e:
        # Handle and return any exceptions
        return response.error(e)
```

### Streaming Responses

For long-running operations, send multiple responses:

```python
@app.action("process_large_dataset")
def process_large_dataset():
    dataset = request.payload.get("dataset", [])
    
    # Send initial response
    response.send({"status": "processing", "progress": 0}, final=False)
    
    # Process in chunks
    total_items = len(dataset)
    processed = 0
    
    for chunk in chunks(dataset, 100):
        # Process this chunk
        process_chunk(chunk)
        
        # Update progress
        processed += len(chunk)
        progress = (processed / total_items) * 100
        
        # Send progress update (non-final response)
        if processed < total_items:
            response.send({
                "status": "processing", 
                "progress": progress
            }, final=False)
    
    # Send final response
    return response.send({
        "status": "complete",
        "progress": 100,
        "total_processed": processed
    })
```

## Communicating Between Services

### Using DaebusCaller

To call other services from your code:

```python
from daebus import Daebus, DaebusCaller, logger

app = Daebus(__name__)

# Create a caller for the target service
user_service = DaebusCaller("user_service")
notification_service = DaebusCaller("notification_service")

@app.action("register_user")
def register_user():
    user_data = request.payload
    
    try:
        # Call the user service to create the user
        user_result = user_service.send_request("create_user", user_data)
        
        if user_result.get("status") == "error":
            return response.error(f"User creation failed: {user_result.get('error')}")
        
        # Send a welcome notification
        notification_result = notification_service.send_request("send_email", {
            "user_id": user_result["id"],
            "template": "welcome",
            "email": user_data.get("email")
        })
        
        # Return the combined result
        return response.send({
            "user": user_result,
            "notification": notification_result
        })
    except Exception as e:
        return response.error(f"Registration failed: {e}")
    finally:
        # Clean up resources
        user_service.close()
        notification_service.close()
```

### Direct Service Communication

For simple one-way communication:

```python
from daebus import DaebusCaller

# Create a caller
logger_service = DaebusCaller("logger_service")

# Send a direct message to an action
logger_service.send_to_service({
    "level": "info",
    "message": "System started successfully",
    "timestamp": time.time()
}, action="log_event")

# Clean up
logger_service.close()
```

## Advanced Patterns

### Fire-and-Forget Messages

Send messages without waiting for a response:

```python
from daebus import DaebusCaller

metrics = DaebusCaller("metrics_service")

# Send a metric without waiting for a response
metrics.send_message("record_metric", {
    "name": "api_request",
    "value": 1,
    "tags": {"endpoint": "/users", "method": "GET"}
})

metrics.close()
```

### Broadcasting Events

Broadcast events to any interested services:

```python
from daebus import broadcast

# Broadcast to a topic channel
broadcast.send("user_events", {
    "type": "user_registered",
    "user_id": "user123",
    "timestamp": time.time()
})
```

### Using Blueprints for Organization

Organize your handlers with blueprints:

```python
from daebus import Daebus, Blueprint, response

# Create a blueprint for user-related functionality
user_bp = Blueprint("users")

@user_bp.action("get_user")
def get_user():
    user_id = request.payload.get("id")
    # Fetch and return user
    return response.send({"id": user_id, "name": "Example User"})

@user_bp.listen("user_events")
def on_user_event(data):
    # Handle user events
    pass

# Create the app and register the blueprint
app = Daebus(__name__)
app.register_blueprint(user_bp)

# Run the service
app.run(service="user_service")
```

## Message Structure

### Standard Request Format

```json
{
  "action": "get_user",
  "payload": {
    "id": "user123"
  },
  "reply_to": "caller_123456",
  "request_id": "req_789"
}
```

### Standard Response Format

```json
{
  "status": "success",
  "payload": {
    "id": "user123",
    "name": "John Doe",
    "email": "john@example.com"
  },
  "request_id": "req_789",
  "final": true
}
```

## Thread Safety

Daebus handles concurrent PubSub messages using thread-local storage:

- Each message is processed in its own thread
- Thread-local storage prevents data leakage between handlers
- The framework automatically manages context lifecycle

For background tasks or custom threads, use `direct_logger` instead of `logger` for thread safety:

```python
from daebus import Daebus, direct_logger

app = Daebus(__name__)

@app.background("cleanup", 3600)  # Run hourly
def cleanup_job():
    try:
        # Perform cleanup
        direct_logger.info("Cleanup job completed")
    except Exception as e:
        direct_logger.error(f"Cleanup job failed: {e}")
```

## Performance Considerations

For optimal performance with PubSub messaging:

1. **Message Size**: Keep messages small (< 1MB)
2. **Connection Pooling**: Redis connections are pooled automatically
3. **Worker Threads**: Adjust the thread pool size based on workload:
   ```python
   app = Daebus(__name__, max_workers=20)  # 20 worker threads
   ```
4. **Redis Configuration**: Ensure your Redis instance is properly configured for your expected throughput

## Complete Example

Here's a complete example of a service using PubSub messaging:

```python
from daebus import Daebus, request, response, broadcast, logger, direct_logger
import time
import random

app = Daebus(__name__)

# Service health status
service_status = {
    "status": "healthy",
    "start_time": time.time(),
    "request_count": 0
}

# Action handler for status request
@app.action("get_status")
def handle_status_request():
    service_status["request_count"] += 1
    
    uptime = time.time() - service_status["start_time"]
    
    return response.send({
        "status": service_status["status"],
        "uptime": uptime,
        "requests_handled": service_status["request_count"]
    })

# Action handler for data processing
@app.action("process_data")
def handle_process_data():
    data = request.payload.get("data", [])
    
    if not data:
        return response.error("No data provided")
    
    try:
        # Simple processing example
        result = sum(data)
        
        # Log the operation
        logger.info(f"Processed {len(data)} data points, result: {result}")
        
        # Return the result
        return response.send({
            "input_size": len(data),
            "result": result,
            "timestamp": time.time()
        })
    except Exception as e:
        logger.error(f"Data processing error: {e}")
        return response.error(f"Processing failed: {e}")

# Listener for system events
@app.listen("system_events")
def handle_system_event(data):
    event_type = data.get("type")
    logger.info(f"Received system event: {event_type}")
    
    if event_type == "shutdown_request":
        # Set status to shutting down
        service_status["status"] = "shutting_down"
        
        # Broadcast our new status
        broadcast.send("service_status", {
            "service": "data_processor",
            "status": "shutting_down",
            "timestamp": time.time()
        })

# Background task for regular status updates
@app.background("status_reporter", 60)  # Run every minute
def report_status():
    try:
        # Generate random load metrics for demonstration
        cpu_load = random.uniform(0.1, 0.9)
        memory_usage = random.uniform(100, 500)
        
        # Broadcast status to the monitoring channel
        broadcast.send("monitoring", {
            "service": "data_processor",
            "status": service_status["status"],
            "metrics": {
                "cpu": cpu_load,
                "memory_mb": memory_usage,
                "uptime": time.time() - service_status["start_time"],
                "requests": service_status["request_count"]
            },
            "timestamp": time.time()
        })
        
        direct_logger.info(f"Status report sent: CPU {cpu_load:.2f}, Memory {memory_usage:.2f}MB")
    except Exception as e:
        direct_logger.error(f"Failed to send status report: {e}")

# Run the service
if __name__ == "__main__":
    app.run(service="data_processor")
```

## Troubleshooting

### Common Issues

1. **Redis Connection Errors**:
   - Error: `ConnectionError: Error 111 connecting to localhost:6379. Connection refused`
   - Solution: Ensure Redis is running and accessible

2. **Message Size Limits**:
   - Error: `DataError: Protocol error, got '-' as reply type byte`
   - Solution: Keep message payloads under Redis limits (typically < 512MB)

3. **Thread Pool Exhaustion**:
   - Symptom: Slow response times or dropped messages
   - Solution: Increase thread pool size (`max_workers`) or optimize handlers

### Debugging Tips

1. **Enable Debug Mode**: Run with debug to see detailed message flow:
   ```python
   app.run(service="my_service", debug=True)
   ```

2. **Monitor Redis Channels**: Use Redis CLI to monitor channels:
   ```bash
   redis-cli psubscribe '*'
   ```

3. **Test Services Individually**: Use the DaebusCaller to test services in isolation:
   ```python
   from daebus import DaebusCaller
   
   caller = DaebusCaller("my_service")
   response = caller.send_request("get_status", {})
   print(f"Response: {response}")
   caller.close()
   ```
