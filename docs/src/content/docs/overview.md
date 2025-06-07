---
title: Overview
description: Understanding Daebus - a lightweight framework for building distributed Python services
---
## What is Daebus?

Daebus is a lightweight framework for building Python background services with a Flask-inspired API. It enables seamless inter-service communication via Redis pub/sub, making it easy to create distributed applications with minimal boilerplate.

## Key Concepts

Daebus was built with the following design principles:

1. **Simplicity**: Provide a clean, intuitive API that developers can learn quickly
2. **Modularity**: Allow components to be used independently or together
3. **Interoperability**: Enable easy communication between services
4. **Minimal Dependencies**: Rely only on essential libraries for core functionality

## Core Features

### Service-Based Architecture

Daebus encourages a service-oriented architecture where each service:

- Has a unique name (used as its main communication channel)
- Runs as a standalone Python process
- Provides specific functionality through message handlers
- Can communicate with other services seamlessly

### Messaging System

The heart of Daebus is its Redis-based messaging system that enables:

- **Request/Response**: Send a message to a service and receive a response
- **Broadcasts**: Publish messages to channels that multiple services can subscribe to
- **Action Routing**: Automatically route messages to the appropriate handler based on an action field

### Component Extensions

Daebus can be extended with additional components:

- **HTTP Endpoints**: Expose REST APIs without additional web frameworks
- **WebSockets**: Enable real-time bidirectional communication
- **Scheduled Tasks**: Run background jobs at specified intervals
- **Background Threads**: Execute long-running processes

## Architecture

### Component Structure

A typical Daebus application consists of:

```
┌─────────────────────────────────────────┐
│ Daebus Application                      │
│                                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
│  │  Action │  │ Channel │  │  Task   │  │
│  │ Handlers│  │Listeners│  │Scheduler│  │
│  └─────────┘  └─────────┘  └─────────┘  │
│                                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
│  │  HTTP   │  │WebSocket│  │Background│  │
│  │Endpoints│  │ Server  │  │ Threads │  │
│  └─────────┘  └─────────┘  └─────────┘  │
│                                         │
└─────────────────────────────────────────┘
           │          │          │
           ▼          ▼          ▼
    ┌─────────────────────────────────┐
    │          Redis Server           │
    └─────────────────────────────────┘
           ▲          ▲          ▲
           │          │          │
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│  Service A  │ │  Service B  │ │  Service C  │
└─────────────┘ └─────────────┘ └─────────────┘
```

### Communication Patterns

Daebus supports several communication patterns:

1. **Direct Service Communication**:
   - Service A sends a message directly to Service B
   - Service B processes the message and sends a response back

2. **Broadcast Notifications**:
   - Service A broadcasts a message to a channel
   - Multiple services subscribed to that channel receive the message

3. **HTTP API Requests**:
   - External clients send HTTP requests to a service
   - The service processes the request and returns an HTTP response

4. **WebSocket Real-time Communication**:
   - Clients establish WebSocket connections to a service
   - Bidirectional real-time communication occurs between clients and the service

## Key Components

### Action Handlers

Action handlers respond to messages sent to a service's main channel:

```python
@app.action("get_status")
def handle_status_request():
    # Access the request payload
    data = request.payload
    
    # Process the request
    result = {
        "status": "healthy",
        "uptime": 3600
    }
    
    # Return a response
    return response.send(result)
```

### Channel Listeners

Channel listeners subscribe to broadcast channels:

```python
@app.listen("system_events")
def handle_system_event(data):
    event_type = data.get("type")
    
    if event_type == "shutdown":
        # Handle shutdown event
        pass
```

### HTTP Endpoints

HTTP endpoints expose REST APIs:

```python
@app.route("/api/status")
def get_status(req):
    return response.send({
        "status": "operational",
        "version": "1.0.0"
    }, 200)
```

### Background Tasks

Background tasks run at specified intervals:

```python
@app.background("cleanup", 3600)  # Run hourly
def cleanup_old_data():
    # Delete old records
    direct_logger.info("Cleanup completed")
```

### WebSocket Handlers

WebSocket handlers process real-time messages:

```python
@app.socket("chat_message")
def handle_chat(data, client_id):
    message = data.get("message", "")
    
    # Process the message
    return {
        "status": "received",
        "timestamp": time.time()
    }
```

## Thread Safety and Concurrency

Daebus is designed to handle concurrent processing:

- Each message is processed in its own thread
- Thread-local storage isolates request and response objects
- The framework manages context lifecycle automatically

This ensures that your service can handle multiple concurrent messages without interference.

## Use Cases

Daebus is ideal for:

1. **Microservices**: Create a network of small, focused services that communicate with each other
2. **IoT Applications**: Build lightweight services for sensors and devices
3. **Background Processing**: Implement task processing systems with easy communication
4. **Admin/Monitoring Tools**: Create services that monitor and manage other services
5. **Kiosk Applications**: Build backend services for kiosk UIs with HTTP and WebSocket interfaces

## Getting Started

To start building with Daebus, check out these guides:

- [Installation](/installation) - Install and set up Daebus
- [PubSub Messaging](/guides/messaging) - Learn how to use the messaging system
- [HTTP Endpoints](/guides/http) - Add HTTP APIs to your services
- [WebSockets](/guides/websockets) - Enable real-time communication
- [Task Scheduler](/guides/task-scheduler) - Schedule recurring tasks
- [Background Threads](/guides/threads) - Run continuous background processes

## Example: Complete Service

Here's a complete example of a Daebus service that combines multiple features:

```python
from daebus import Daebus, DaebusHttp, DaebusWebSocket, response, request, broadcast, direct_logger
import time

# Create our application
app = Daebus(__name__)

# Add HTTP and WebSocket support
http = DaebusHttp(port=8080)
websocket = DaebusWebSocket()
app.attach(http)
app.attach(websocket)

# Track service metrics
metrics = {
    "start_time": time.time(),
    "requests": 0,
    "broadcasts": 0
}

# Action handler for direct service communication
@app.action("get_metrics")
def handle_get_metrics():
    uptime = time.time() - metrics["start_time"]
    
    # Increment request counter
    metrics["requests"] += 1
    
    return response.send({
        "uptime": uptime,
        "requests": metrics["requests"],
        "broadcasts": metrics["broadcasts"]
    })

# Listen to broadcast messages
@app.listen("system_events")
def handle_system_event(data):
    event_type = data.get("type")
    logger.info(f"Received system event: {event_type}")
    
    # Process different event types
    if event_type == "maintenance_mode":
        # Update our status
        pass

# HTTP endpoint
@app.route("/api/metrics")
def http_get_metrics(req):
    uptime = time.time() - metrics["start_time"]
    
    return response.send({
        "uptime": uptime,
        "requests": metrics["requests"],
        "broadcasts": metrics["broadcasts"]
    }, 200)

# WebSocket message handler
@app.socket("subscribe_metrics")
def socket_subscribe_metrics(data, client_id):
    # Register this client for metric updates
    # (implementation details omitted)
    
    return {
        "status": "subscribed",
        "update_interval": 10
    }

# Background task for metrics broadcast
@app.background("metrics_broadcast", 10)  # Every 10 seconds
def broadcast_metrics():
    try:
        # Prepare current metrics
        current_metrics = {
            "uptime": time.time() - metrics["start_time"],
            "requests": metrics["requests"],
            "broadcasts": metrics["broadcasts"] + 1,
            "timestamp": time.time()
        }
        
        # Update counter
        metrics["broadcasts"] += 1
        
        # Broadcast to interested services
        broadcast.send("metrics_updates", current_metrics)
        
        # Also send to WebSocket clients
        websocket.broadcast_to_all(current_metrics, message_type="metrics_update")
        
        direct_logger.info("Metrics broadcast completed")
    except Exception as e:
        direct_logger.error(f"Error broadcasting metrics: {e}")

# Run the application
if __name__ == "__main__":
    app.run(service="metrics_service")
```

This service demonstrates:
- Action handlers for direct communication
- Channel listeners for broadcast messages
- HTTP endpoints for REST API access
- WebSocket handlers for real-time communication
- Background tasks for periodic operations

## Further reading

- Read [about how-to guides](https://diataxis.fr/how-to-guides/) in the Diátaxis framework
