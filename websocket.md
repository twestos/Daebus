# WebSocket Support in Daebus

Daebus provides a WebSocket server that integrates seamlessly with the HTTP server, enabling real-time bidirectional communication between clients and your application.

## Setup

### 1. Import and attach components

To use WebSockets in your Daebus application:

```python
from daebus import Daebus, DaebusHttp, DaebusWebSocket

# Create Daebus application
app = Daebus("my_app")

# First attach HTTP server (required)
http = app.attach(DaebusHttp(port=8080))

# Then attach WebSocket server
websocket = app.attach(DaebusWebSocket())
# Note: If no port is specified, WebSocket uses the same port as the HTTP server
```

> **Important**: The HTTP component must be attached before the WebSocket component.

### 2. Register message handlers

Register handlers for specific message types using the `socket` decorator:

```python
@app.socket("chat_message")
def handle_chat_message(req):
    # Process the message
    username = req.data.get("username", "Anonymous")
    message = req.data.get("message", "")
    
    print(f"Received '{message}' from {username}")
    
    # Return a response (automatically sent to the client)
    return {"status": "received"}
```

## Message Handling

### Request Object

Each WebSocket handler receives a `WebSocketRequest` object with these properties:

| Property | Description |
|----------|-------------|
| `client_id` | Unique identifier for this connection |
| `message_type` | Type of the received message (same as in `@app.socket()`) |
| `data` | Data portion of the message |
| `payload` | The complete message object |
| `websocket` | Raw WebSocket connection (for advanced usage) |

### Sending Responses

#### Method 1: Return a value (Recommended)

The simplest way to respond is to return a value from your handler:

```python
@app.socket("ping")
def handle_ping(req):
    # Any returned dict or value will be sent as a response
    return {
        "pong": True,
        "timestamp": time.time()
    }
```

The returned value will be automatically sent with message type "response".

#### Method 2: Use app.websocket.send

For more control or to send multiple messages:

```python
@app.socket("long_operation")
def handle_long_operation(req):
    # Send an initial response
    app.websocket.send({"status": "processing"})
    
    # Perform operation...
    result = do_some_work()
    
    # Send final response
    app.websocket.send({"status": "complete", "result": result})
```

## Broadcasting Messages

To send a message to all connected clients:

```python
app.websocket.broadcast_to_all(
    {
        "message": "System maintenance in 5 minutes", 
        "timestamp": time.time()
    },
    message_type="announcement"  # Optional, defaults to "broadcast"
)
```

## Connection Events

### Connection Handlers

Register handlers for client connections:

```python
@app.websocket.on_connect
def handle_new_connection(client_id):
    print(f"Client connected: {client_id}")
    
    # Update user count for all clients
    app.websocket.broadcast_to_all({
        "user_count": app.websocket.get_client_count()
    })
```

### Disconnection Handlers

Register handlers for client disconnections:

```python
@app.websocket.on_disconnect
def handle_disconnection(client_id):
    print(f"Client disconnected: {client_id}")
    
    # Update user count for all clients
    app.websocket.broadcast_to_all({
        "user_count": app.websocket.get_client_count()
    })
```

## Client Management

The WebSocket server provides methods to track and manage connected clients:

```python
# Get list of all connected client IDs
client_ids = app.websocket.get_clients()

# Get number of connected clients
client_count = app.websocket.get_client_count()

# Check if a specific client is connected
if app.websocket.is_client_connected(client_id):
    print(f"Client {client_id} is still connected")
```

## Message Format

### Client to Server

Messages sent from clients to the server should follow this format:

```json
{
    "type": "message_type",
    "data": {
        // Any data relevant to this message
    }
}
```

The `"type"` field must match a registered message type (used in `@app.socket()`).

### Server to Client

Messages sent from the server to clients follow this format:

```json
{
    "type": "message_type",
    "data": {
        // Response data
    }
}
```

The `"type"` field will be:
- The value provided to `app.websocket.send()` (defaults to "response")
- The value provided to `app.websocket.broadcast_to_all()` (defaults to "broadcast")
- "error" for error messages

## JavaScript Client Example

```javascript
// Connect to the WebSocket server
const ws = new WebSocket(`ws://${window.location.host}`);

// Connection opened
ws.addEventListener('open', (event) => {
    console.log('Connected to WebSocket server');
});

// Listen for messages
ws.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    console.log(`Received ${message.type} message:`, message.data);
    
    // Handle different message types
    switch (message.type) {
        case 'response':
            handleResponse(message.data);
            break;
        case 'broadcast':
            handleBroadcast(message.data);
            break;
        case 'error':
            handleError(message.data);
            break;
    }
});

// Send a message
function sendMessage(messageType, data) {
    ws.send(JSON.stringify({
        type: messageType,
        data: data
    }));
}

// Example usage
sendMessage('chat_message', {
    username: 'John',
    message: 'Hello, world!'
});
```

## Requirements and Limitations

- The WebSocket server requires the `websockets` Python package
- WebSockets share the same port as the HTTP server
- The WebSocket component must be attached after the HTTP component
- Handlers can be synchronous or asynchronous functions 