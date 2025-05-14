---
title: WebSockets
description: Real-time bidirectional communication with WebSockets in Daebus
---

Daebus includes a WebSocket server that enables real-time, bidirectional communication between your services and clients. WebSockets are ideal for applications requiring live updates, chat functionality, notifications, or any feature needing continuous data exchange.

## Getting Started

### Setting Up WebSockets

To add WebSocket support to your Daebus application:

```python
from daebus import Daebus, DaebusHttp, DaebusWebSocket

app = Daebus(__name__)

# First, set up HTTP (required for WebSockets)
http = DaebusHttp(port=8080)
app.attach(http)

# Then, add WebSocket support
websocket = DaebusWebSocket()  # Uses the same port as HTTP by default
app.attach(websocket)

# Define message handlers and start the application
app.run(service="realtime_service")
```

> **Note**: WebSockets require HTTP to be attached first, as they share the same server infrastructure.

## Message Handlers

### Handling Message Types

Use the `@app.socket()` decorator to handle specific message types:

```python
@app.socket("chat_message")
def handle_chat(req, sid):
    """Handle incoming chat messages"""
    message = req.data.get("message", "")
    sender = req.data.get("sender", "Anonymous")
    
    # Log the message
    logger.info(f"Received chat message from {sender} (client {sid}): {message}")
    
    # Broadcast to all clients
    app.websocket.broadcast_to_all({
        "sender": sender,
        "message": message,
        "timestamp": time.time()
    }, message_type="chat_update")
    
    # Return acknowledgment to the sender
    return {
        "status": "delivered",
        "timestamp": time.time()
    }
```

The handler function receives two parameters:
- `req`: The WebSocketRequest object containing message data
- `sid`: The client's session ID (a unique identifier for the connection)

### Connection Events

Handle client connections and disconnections:

```python
@app.socket_connect()
def on_connect(req, sid):
    """Handle new client connection"""
    logger.info(f"Client {sid} connected")
    
    # You can return data that will be sent to the client
    return {
        "status": "connected",
        "client_id": sid,
        "server_time": time.time()
    }

@app.socket_disconnect()
def on_disconnect(req, sid):
    """Handle client disconnection"""
    logger.info(f"Client {sid} disconnected")
    
    # Clean up any client-specific resources
    if sid in user_sessions:
        del user_sessions[sid]
```

### Client Registration

Handle client registration with custom data:

```python
@app.socket_register()
def on_register(req, sid):
    """Handle client registration"""
    user_data = req.data.get("user", {})
    username = user_data.get("username", f"Guest-{sid[:8]}")
    
    # Store the user information
    user_sessions[sid] = {
        "username": username,
        "registered_at": time.time(),
        "is_active": True
    }
    
    logger.info(f"Client {sid} registered as {username}")
    
    # Notify others about the new user
    app.websocket.broadcast_to_all({
        "user": username,
        "action": "joined"
    }, message_type="user_update")
    
    return {
        "status": "registered",
        "username": username
    }
```

## Sending Messages

### Response to Current Client

Send a response to the client who sent the message:

```python
@app.socket("get_data")
def handle_data_request(req, sid):
    data_id = req.data.get("id")
    
    try:
        # Fetch the requested data
        result = fetch_data(data_id)
        
        # Return the data directly - this will be sent to the client
        return {
            "data": result,
            "timestamp": time.time()
        }
    except Exception as e:
        # Return an error response
        return {
            "error": str(e),
            "status": "error"
        }
```

### Send to a Specific Client

Send a message to any connected client:

```python
@app.action("notify_user")
def send_notification():
    user_id = request.payload.get("user_id")
    message = request.payload.get("message")
    
    # Find the client ID for this user
    client_id = find_client_for_user(user_id)
    
    if not client_id:
        return response.error(f"User {user_id} not connected")
    
    # Send a message to the specific client
    success = app.websocket.send_to_client(
        client_id,
        {
            "message": message,
            "timestamp": time.time()
        },
        message_type="notification"
    )
    
    return response.send({
        "delivered": success,
        "client_id": client_id
    })
```

### Broadcasting to All Clients

Send a message to all connected clients:

```python
@app.background("system_status", 60)  # Every minute
def broadcast_status():
    try:
        # Collect system metrics
        metrics = {
            "cpu": get_cpu_usage(),
            "memory": get_memory_usage(),
            "active_users": len(user_sessions),
            "timestamp": time.time()
        }
        
        # Broadcast to all connected clients
        recipients = app.websocket.broadcast_to_all(
            metrics,
            message_type="system_status"
        )
        
        direct_logger.info(f"Status broadcast sent to {recipients} clients")
    except Exception as e:
        direct_logger.error(f"Error broadcasting status: {e}")
```

## Client Management

### Getting Connected Clients

Access information about connected clients:

```python
@app.action("get_connected_clients")
def get_clients():
    # Get a list of all connected client IDs
    client_ids = list(app.websocket.clients.keys())
    
    # Get more detailed information about each client
    client_info = {}
    for cid in client_ids:
        metadata = app.websocket.get_client_metadata(cid)
        client_info[cid] = {
            "connected_at": metadata.get("connected_at"),
            "remote_address": metadata.get("remote_address"),
            "messages_received": metadata.get("messages_received", 0),
            "is_authenticated": cid in user_sessions
        }
    
    return response.send({
        "count": len(client_ids),
        "clients": client_info
    })
```

### Filtering Clients

Find clients matching specific criteria:

```python
@app.action("find_inactive_clients")
def find_inactive_clients():
    # Get clients inactive for more than 30 minutes
    threshold = time.time() - (30 * 60)
    
    inactive_clients = app.websocket.get_clients_by_filter(
        lambda _, meta: meta.get("last_activity", 0) < threshold
    )
    
    return response.send({
        "count": len(inactive_clients),
        "clients": inactive_clients
    })
```

### Disconnecting Clients

Force disconnect a client:

```python
@app.action("kick_client")
def disconnect_client():
    client_id = request.payload.get("client_id")
    reason = request.payload.get("reason", "Disconnected by administrator")
    
    if not client_id:
        return response.error("No client_id provided")
    
    # Send a message to the client before disconnecting
    app.websocket.send_to_client(
        client_id,
        {
            "reason": reason,
            "timestamp": time.time()
        },
        message_type="disconnect_notice"
    )
    
    # Disconnect the client
    success = app.websocket.disconnect_client(client_id)
    
    return response.send({
        "success": success,
        "client_id": client_id
    })
```

## Working with Request Data

The `req` object in WebSocket handlers provides:

```python
@app.socket("example_message")
def handle_example(req, sid):
    # Message type (from the 'type' field in the client message)
    message_type = req.message_type
    
    # Full message payload
    full_payload = req.payload
    
    # Convenience access to the 'data' field of the message
    message_data = req.data
    
    # Access specific fields with defaults
    username = message_data.get("username", "Anonymous")
    action = message_data.get("action", "view")
    
    # You can also access the WebSocket connection directly
    websocket = req.websocket
    
    # Process the message...
    return {"status": "processed"}
```

## Client-Side Implementation

Here's a basic JavaScript client implementation:

```javascript
// Connect to the WebSocket server
const socket = new WebSocket('ws://localhost:8080');

// Handle connection open
socket.onopen = (event) => {
    console.log('Connected to server');
    
    // Register with the server
    socket.send(JSON.stringify({
        type: 'register',
        data: {
            user: {
                username: 'JohnDoe'
            }
        }
    }));
};

// Handle incoming messages
socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    console.log('Received:', message);
    
    // Handle different message types
    switch(message.type) {
        case 'chat_update':
            displayChatMessage(message.data);
            break;
        case 'notification':
            showNotification(message.data);
            break;
        case 'system_status':
            updateDashboard(message.data);
            break;
    }
};

// Send a chat message
function sendChatMessage(text) {
    socket.send(JSON.stringify({
        type: 'chat_message',
        data: {
            message: text,
            sender: 'JohnDoe'
        }
    }));
}

// Handle connection close
socket.onclose = (event) => {
    console.log('Disconnected from server:', event.reason);
};

// Handle errors
socket.onerror = (error) => {
    console.error('WebSocket error:', error);
};
```

## Advanced Features

### Rate Limiting

Enable rate limiting to prevent abuse:

```python
# Set up rate limiting when creating the WebSocket component
websocket = DaebusWebSocket()
websocket.enable_rate_limiting(
    messages_per_minute=60,  # Maximum messages per minute
    window_seconds=60        # Time window for counting messages
)
app.attach(websocket)
```

### Custom Client ID Generation

Customize how client IDs are generated:

```python
def custom_id_generator(websocket, path):
    """Generate custom client IDs based on IP and timestamp"""
    client_ip = websocket.remote_address[0] if hasattr(websocket, 'remote_address') else 'unknown'
    timestamp = int(time.time())
    return f"client_{client_ip}_{timestamp}"

# Set the custom ID generator
websocket.set_client_id_generator(custom_id_generator)
```

### Graceful Shutdown

Implement a graceful shutdown for the WebSocket server:

```python
@app.action("shutdown")
def graceful_shutdown():
    # Prepare a shutdown message
    shutdown_message = {
        "message": "Server is shutting down for maintenance",
        "expected_downtime": "10 minutes",
        "reconnect": False
    }
    
    # Perform graceful shutdown
    app.websocket.graceful_shutdown(
        timeout=5.0,  # Wait 5 seconds after sending the message
        message=shutdown_message
    )
    
    # Continue with other shutdown operations
    return response.send({"shutdown_initiated": True})
```

## Organizing with Blueprints

Use blueprints to organize WebSocket handlers:

```python
from daebus import Daebus, DaebusHttp, DaebusWebSocket, Blueprint

# Create a blueprint for chat functionality
chat_bp = Blueprint("chat")

@chat_bp.socket("send_message")
def handle_chat_message(req, sid):
    # Chat message handling logic
    return {"received": True}

@chat_bp.socket("join_room")
def handle_join_room(req, sid):
    # Room joining logic
    return {"joined": True}

# Create another blueprint for user management
user_bp = Blueprint("users")

@user_bp.socket_connect()
def handle_connect(req, sid):
    # Connection handling
    return {"welcome": True}

# Create the application and attach components
app = Daebus(__name__)
http = DaebusHttp(port=8080)
websocket = DaebusWebSocket()

app.attach(http)
app.attach(websocket)

# Register the blueprints
app.register_blueprint(chat_bp)
app.register_blueprint(user_bp)

# Run the application
app.run(service="chat_service")
```

## Security Considerations

### Authentication

Implement authentication for WebSocket connections:

```python
@app.socket_connect()
def on_connect(req, sid):
    # Extract authentication token from request path or headers
    token = extract_token_from_request(req)
    
    if not token or not validate_token(token):
        # Return False to reject the connection
        return False
    
    # Store authenticated user information
    user_id = get_user_id_from_token(token)
    app.websocket.set_client_data(sid, "user_id", user_id)
    
    logger.info(f"Authenticated connection from user {user_id}")
    return {"authenticated": True, "user_id": user_id}
```

### Input Validation

Always validate incoming messages:

```python
@app.socket("update_profile")
def handle_profile_update(req, sid):
    # Get user data
    profile_data = req.data.get("profile", {})
    
    # Validate required fields
    if not profile_data.get("name"):
        return {"error": "Name is required", "status": "error"}
    
    # Validate data types
    if "age" in profile_data and not isinstance(profile_data["age"], int):
        return {"error": "Age must be a number", "status": "error"}
    
    # Sanitize input (example)
    if "bio" in profile_data:
        profile_data["bio"] = sanitize_html(profile_data["bio"])
    
    # Process the valid data
    # ...
    
    return {"status": "updated"}
```

## Complete Example

Here's a complete example of a chat application using WebSockets:

```python
from daebus import Daebus, DaebusHttp, DaebusWebSocket, direct_logger
import time
import threading

app = Daebus(__name__)

# Set up HTTP and WebSocket
http = DaebusHttp(port=8080)
websocket = DaebusWebSocket()

app.attach(http)
app.attach(websocket)

# Thread-safe storage for chat rooms and users
rooms = {}
rooms_lock = threading.Lock()
users = {}
users_lock = threading.Lock()

# Connection handler
@app.socket_connect()
def on_connect(req, sid):
    direct_logger.info(f"Client connected: {sid}")
    return {"status": "connected", "client_id": sid}

# Disconnection handler
@app.socket_disconnect()
def on_disconnect(req, sid):
    # Remove user from rooms
    with rooms_lock:
        for room_name, room in list(rooms.items()):
            if sid in room["members"]:
                room["members"].remove(sid)
                
                # Notify others in the room
                if room["members"]:
                    app.websocket.broadcast_to_clients(
                        room["members"],
                        {
                            "user": users.get(sid, {}).get("username", "Anonymous"),
                            "action": "left",
                            "room": room_name
                        },
                        message_type="room_update"
                    )
    
    # Remove user
    with users_lock:
        if sid in users:
            del users[sid]
    
    direct_logger.info(f"Client disconnected: {sid}")

# User registration
@app.socket("register")
def register_user(req, sid):
    username = req.data.get("username")
    
    if not username:
        return {"error": "Username is required", "status": "error"}
    
    # Store user information
    with users_lock:
        users[sid] = {
            "username": username,
            "registered_at": time.time(),
            "rooms": []
        }
    
    direct_logger.info(f"User registered: {username} ({sid})")
    
    return {
        "status": "registered",
        "username": username,
        "available_rooms": list(rooms.keys())
    }

# Create or join room
@app.socket("join_room")
def join_room(req, sid):
    room_name = req.data.get("room")
    
    if not room_name:
        return {"error": "Room name is required", "status": "error"}
    
    # Get username
    username = users.get(sid, {}).get("username", "Anonymous")
    
    with rooms_lock:
        # Create room if it doesn't exist
        if room_name not in rooms:
            rooms[room_name] = {
                "created_at": time.time(),
                "created_by": sid,
                "members": set(),
                "messages": []
            }
            direct_logger.info(f"Room created: {room_name} by {username}")
        
        # Add user to room
        rooms[room_name]["members"].add(sid)
    
    # Add room to user's list
    with users_lock:
        if sid in users and "rooms" in users[sid]:
            if room_name not in users[sid]["rooms"]:
                users[sid]["rooms"].append(room_name)
    
    # Notify others in the room
    with rooms_lock:
        room = rooms[room_name]
        others = room["members"] - {sid}
        
        if others:
            app.websocket.broadcast_to_clients(
                list(others),
                {
                    "user": username,
                    "action": "joined",
                    "room": room_name
                },
                message_type="room_update"
            )
    
    direct_logger.info(f"User {username} joined room: {room_name}")
    
    # Return room information
    return {
        "status": "joined",
        "room": room_name,
        "members": len(rooms[room_name]["members"]),
        "history": rooms[room_name]["messages"][-20:]  # Last 20 messages
    }

# Send message to room
@app.socket("chat_message")
def send_message(req, sid):
    room_name = req.data.get("room")
    message = req.data.get("message", "").strip()
    
    if not room_name or not message:
        return {"error": "Room and message are required", "status": "error"}
    
    # Check if user is in the room
    with rooms_lock:
        if room_name not in rooms:
            return {"error": "Room does not exist", "status": "error"}
        
        if sid not in rooms[room_name]["members"]:
            return {"error": "Not a member of this room", "status": "error"}
    
    # Get username
    username = users.get(sid, {}).get("username", "Anonymous")
    
    # Create message object
    msg = {
        "id": f"msg_{time.time()}_{sid[:8]}",
        "room": room_name,
        "sender": username,
        "text": message,
        "timestamp": time.time()
    }
    
    # Add to room history
    with rooms_lock:
        rooms[room_name]["messages"].append(msg)
        # Keep only last 100 messages
        if len(rooms[room_name]["messages"]) > 100:
            rooms[room_name]["messages"] = rooms[room_name]["messages"][-100:]
            
        # Get all members except sender
        recipients = list(rooms[room_name]["members"] - {sid})
    
    # Broadcast to other room members
    if recipients:
        app.websocket.broadcast_to_clients(
            recipients,
            msg,
            message_type="new_message"
        )
    
    direct_logger.info(f"Message from {username} in {room_name}: {message[:30]}...")
    
    return {
        "status": "sent",
        "message_id": msg["id"],
        "timestamp": msg["timestamp"]
    }

# HTTP route to get active rooms
@app.route("/api/rooms")
def get_rooms(req):
    with rooms_lock:
        room_info = []
        for name, room in rooms.items():
            room_info.append({
                "name": name,
                "members": len(room["members"]),
                "message_count": len(room["messages"]),
                "created_at": room["created_at"]
            })
    
    return response.send({
        "count": len(room_info),
        "rooms": room_info
    }, 200)

if __name__ == "__main__":
    app.run(service="chat_service")
```

## Best Practices

1. **Message Structure**: Use a consistent message structure across your application
2. **Error Handling**: Always handle connection errors and retries on the client
3. **Authentication**: Implement proper authentication for WebSocket connections
4. **Validation**: Validate all incoming message data
5. **Performance**: Be mindful of broadcasting to large numbers of clients
6. **Reconnection**: Implement reconnection logic on the client side
7. **Testing**: Test with multiple simultaneous connections to ensure scalability

## Troubleshooting

### Connection Issues

If clients can't connect:

1. Verify the WebSocket server is running (check logs)
2. Ensure the client is using the correct WebSocket URL
3. Check for firewall or proxy issues blocking WebSocket traffic
4. Verify HTTP is properly set up before WebSockets

### Message Handling

If messages aren't being processed:

1. Verify the message type matches your handler registration
2. Check the message format on the client side
3. Look for errors in your handler functions
4. Ensure the `data` field contains the expected structure

### Performance Issues

If you experience performance problems:

1. Limit the number of messages sent per second
2. Reduce the size of messages
3. Use more targeted broadcasting instead of broadcasting to all clients
4. Consider splitting clients across multiple server instances
