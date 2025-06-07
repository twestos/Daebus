---
title: Blueprints
description: Organize and modularize your Daebus applications with Blueprints
---
Blueprints in Daebus provide a way to organize your application into modular, reusable components. Similar to Flask's Blueprint system, they allow you to define routes, action handlers, background tasks, and other components in separate modules, then register them with your main application.

## Introduction

As your Daebus applications grow, keeping all your route handlers, action handlers, and other components in a single file can become unwieldy. Blueprints solve this problem by allowing you to:

- Split your application into logical modules
- Organize related functionality together
- Reuse components across multiple applications
- Develop and test components independently

## Basic Usage

### Creating a Blueprint

To create a blueprint, import the `Blueprint` class from Daebus and instantiate it with a name:

```python
from daebus import Blueprint

# Create a blueprint for user-related functionality
users_bp = Blueprint("users")
```

### Defining Handlers

You can register various types of handlers with your blueprint:

```python
@users_bp.action("get_user")
def get_user():
    user_id = request.payload.get("id")
    
    # Fetch user data
    user = fetch_user(user_id)
    
    return response.send(user)

@users_bp.route("/api/users/<user_id>")
def http_get_user(req, user_id):
    # Fetch user data
    user = fetch_user(user_id)
    
    return response.send(user, 200)
```

### Registering the Blueprint

After defining your blueprint, register it with your main Daebus application:

```python
from daebus import Daebus, DaebusHttp
from .blueprints.users import users_bp
from .blueprints.products import products_bp

app = Daebus(__name__)

# Set up HTTP support
http = DaebusHttp(port=8080)
app.attach(http)

# Register blueprints
app.register_blueprint(users_bp)
app.register_blueprint(products_bp)

# Run the application
app.run(service="api_service")
```

## Supported Features

Blueprints support all the main features of Daebus:

### Action Handlers

Register action handlers for pub/sub messages:

```python
@blueprint.action("create_user")
def create_user():
    # Handler implementation
    return response.send({"created": True})
```

### HTTP Routes

Register HTTP route handlers:

```python
@blueprint.route("/api/users", methods=["GET"])
def list_users(req):
    users = get_all_users()
    return response.send({"users": users}, 200)

@blueprint.route("/api/users", methods=["POST"])
def create_user(req):
    user_data = req.payload
    new_user = create_new_user(user_data)
    return response.send(new_user, 201)
```

### Channel Listeners

Register handlers for pub/sub channels:

```python
@blueprint.listen("user_events")
def handle_user_event(data):
    event_type = data.get("type")
    
    if event_type == "user_created":
        # Handle user creation event
        pass
    elif event_type == "user_updated":
        # Handle user update event
        pass
```

### WebSocket Handlers

Register WebSocket message handlers:

```python
@blueprint.socket("user_update")
def handle_user_update(data, client_id):
    # Handle WebSocket message
    return {"status": "processed"}

@blueprint.socket_connect()
def on_connect(data, client_id):
    return {"status": "connected"}

@blueprint.socket_disconnect()
def on_disconnect(data, client_id):
    # Clean up resources
    pass
```

### Background Tasks

Register periodic background tasks:

```python
@blueprint.background("cleanup_expired_users", 3600)  # Run hourly
def cleanup_expired_users():
    # Delete expired user accounts
    direct_logger.info("Expired users cleanup completed")
```

### Background Threads

Register long-running background threads:

```python
@blueprint.thread("user_activity_monitor")
def monitor_user_activity(running):
    while running():
        # Check user activity
        time.sleep(60)  # Check every minute
```

### Startup Handlers

Register handlers that run when the service starts:

```python
@blueprint.on_start()
def initialize_user_cache():
    # Initialize user cache
    direct_logger.info("User cache initialized")
```

## Organization Patterns

Here are some common ways to organize your application using blueprints:

### By Feature

Organize blueprints around specific features:

```
my_app/
├── app.py                  # Main application
├── blueprints/
│   ├── __init__.py
│   ├── users.py            # User-related functionality
│   ├── products.py         # Product-related functionality
│   ├── orders.py           # Order-related functionality
│   └── notifications.py    # Notification-related functionality
└── utils/
    └── db.py
```

```python
# app.py
from daebus import Daebus
from blueprints.users import users_bp
from blueprints.products import products_bp
from blueprints.orders import orders_bp
from blueprints.notifications import notifications_bp

app = Daebus(__name__)
app.register_blueprint(users_bp)
app.register_blueprint(products_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(notifications_bp)

app.run(service="my_service")
```

### By Protocol

Organize blueprints by communication protocol:

```
my_app/
├── app.py                  # Main application
├── blueprints/
│   ├── __init__.py
│   ├── api.py              # HTTP API routes
│   ├── websocket.py        # WebSocket handlers
│   ├── actions.py          # Pub/Sub action handlers
│   └── tasks.py            # Background tasks and threads
└── utils/
    └── db.py
```

```python
# app.py
from daebus import Daebus, DaebusHttp, DaebusWebSocket
from blueprints.api import api_bp
from blueprints.websocket import ws_bp
from blueprints.actions import actions_bp
from blueprints.tasks import tasks_bp

app = Daebus(__name__)

# Set up HTTP and WebSocket
http = DaebusHttp(port=8080)
websocket = DaebusWebSocket()
app.attach(http)
app.attach(websocket)

# Register blueprints
app.register_blueprint(api_bp)
app.register_blueprint(ws_bp)
app.register_blueprint(actions_bp)
app.register_blueprint(tasks_bp)

app.run(service="my_service")
```

## Complete Example

Here's a complete example of a Daebus application using blueprints:

### Main Application

```python
# app.py
from daebus import Daebus, DaebusHttp, DaebusWebSocket, direct_logger

from blueprints.users import users_bp
from blueprints.auth import auth_bp

def main():
    # Create the application
    app = Daebus(__name__)
    
    # Set up HTTP and WebSocket
    http = DaebusHttp(port=8080)
    websocket = DaebusWebSocket()
    
    app.attach(http)
    app.attach(websocket)
    
    # Register blueprints
    app.register_blueprint(users_bp)
    app.register_blueprint(auth_bp)
    
    # Add application-wide handlers
    @app.on_start()
    def initialize():
        direct_logger.info("Application starting...")
    
    # Run the service
    direct_logger.info("Starting service...")
    app.run(service="user_service")

if __name__ == "__main__":
    main()
```

### User Blueprint

```python
# blueprints/users.py
from daebus import Blueprint, request, response, direct_logger, broadcast
import time

users_bp = Blueprint("users")

# In-memory user storage for example
users = {}

# Action handlers
@users_bp.action("get_user")
def get_user():
    user_id = request.payload.get("id")
    
    if user_id not in users:
        return response.error(f"User {user_id} not found")
    
    return response.send(users[user_id])

@users_bp.action("create_user")
def create_user():
    user_data = request.payload
    
    if not user_data.get("email"):
        return response.error("Email is required")
    
    user_id = f"user_{int(time.time())}"
    users[user_id] = {
        "id": user_id,
        "email": user_data["email"],
        "name": user_data.get("name", ""),
        "created_at": time.time()
    }
    
    # Broadcast user creation event
    broadcast.send("user_events", {
        "type": "user_created",
        "user_id": user_id
    })
    
    return response.send(users[user_id])

# HTTP routes
@users_bp.route("/api/users", methods=["GET"])
def list_users(req):
    return response.send({
        "users": list(users.values())
    }, 200)

@users_bp.route("/api/users/<user_id>", methods=["GET"])
def http_get_user(req, user_id):
    if user_id not in users:
        return response.send({"error": "User not found"}, 404)
    
    return response.send(users[user_id], 200)

@users_bp.route("/api/users", methods=["POST"])
def http_create_user(req):
    user_data = req.payload
    
    if not user_data.get("email"):
        return response.send({"error": "Email is required"}, 400)
    
    user_id = f"user_{int(time.time())}"
    users[user_id] = {
        "id": user_id,
        "email": user_data["email"],
        "name": user_data.get("name", ""),
        "created_at": time.time()
    }
    
    # Broadcast user creation event
    broadcast.send("user_events", {
        "type": "user_created",
        "user_id": user_id
    })
    
    return response.send(users[user_id], 201)

# WebSocket handlers
@users_bp.socket("get_users")
def ws_get_users(data, client_id):
    return {
        "users": list(users.values())
    }

# Channel listeners
@users_bp.listen("user_events")
def handle_user_event(data):
    event_type = data.get("type")
    user_id = data.get("user_id")
    
    direct_logger.info(f"Received user event: {event_type} for user {user_id}")

# Background tasks
@users_bp.background("user_cleanup", 3600)  # Run hourly
def cleanup_inactive_users():
    try:
        now = time.time()
        deleted_count = 0
        
        for user_id, user in list(users.items()):
            # Example: Delete users inactive for more than 30 days
            if user.get("last_active", 0) < now - (30 * 24 * 3600):
                del users[user_id]
                deleted_count += 1
        
        direct_logger.info(f"Cleaned up {deleted_count} inactive users")
    except Exception as e:
        direct_logger.error(f"Error in user cleanup: {e}")
```

### Authentication Blueprint

```python
# blueprints/auth.py
from daebus import Blueprint, request, response, direct_logger
import time
import hashlib
import secrets

auth_bp = Blueprint("auth")

# In-memory token storage
tokens = {}

# Helper functions
def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(8)
    
    hash_obj = hashlib.sha256((password + salt).encode())
    return hash_obj.hexdigest(), salt

def verify_token(token):
    if token not in tokens:
        return None
    
    token_data = tokens[token]
    
    # Check if token is expired
    if token_data["expires_at"] < time.time():
        del tokens[token]
        return None
    
    return token_data["user_id"]

# Action handlers
@auth_bp.action("login")
def login():
    payload = request.payload
    email = payload.get("email")
    password = payload.get("password")
    
    # In a real app, you would verify against a database
    # This is just a simple example
    if email == "user@example.com" and password == "password":
        token = secrets.token_hex(16)
        tokens[token] = {
            "user_id": "user_1",
            "created_at": time.time(),
            "expires_at": time.time() + 3600  # 1 hour
        }
        
        return response.send({
            "token": token,
            "expires_in": 3600
        })
    
    return response.error("Invalid email or password")

@auth_bp.action("verify_token")
def check_token():
    token = request.payload.get("token")
    
    user_id = verify_token(token)
    if not user_id:
        return response.error("Invalid or expired token")
    
    return response.send({
        "valid": True,
        "user_id": user_id
    })

# HTTP routes
@auth_bp.route("/api/auth/login", methods=["POST"])
def http_login(req):
    payload = req.payload
    email = payload.get("email")
    password = payload.get("password")
    
    # In a real app, you would verify against a database
    if email == "user@example.com" and password == "password":
        token = secrets.token_hex(16)
        tokens[token] = {
            "user_id": "user_1",
            "created_at": time.time(),
            "expires_at": time.time() + 3600  # 1 hour
        }
        
        return response.send({
            "token": token,
            "expires_in": 3600
        }, 200)
    
    return response.send({
        "error": "Invalid email or password"
    }, 401)

# WebSocket authentication
@auth_bp.socket_connect()
def ws_authenticate(data, client_id):
    # Extract token from connection data
    token = data.get("token")
    
    if not token:
        # No token provided, allow connection but mark as unauthenticated
        return {
            "authenticated": False,
            "message": "No authentication token provided"
        }
    
    user_id = verify_token(token)
    if not user_id:
        # Invalid token, still allow connection but mark as unauthenticated
        return {
            "authenticated": False,
            "message": "Invalid or expired token"
        }
    
    # Valid token, mark as authenticated
    return {
        "authenticated": True,
        "user_id": user_id
    }
```

## Best Practices

### Blueprint Naming

Choose descriptive names for your blueprints that reflect their functionality:

```python
users_bp = Blueprint("users")            # User management
auth_bp = Blueprint("auth")              # Authentication
products_bp = Blueprint("products")      # Product management
admin_bp = Blueprint("admin")            # Admin functionality
```

### Import Management

Keep your imports organized to avoid circular dependencies:

```python
# Good: Import Blueprint once in __init__.py
# blueprints/__init__.py
from daebus import Blueprint

# blueprints/users.py
from . import Blueprint
from some_module import SomeClass

users_bp = Blueprint("users")
```

### Blueprint Granularity

Find the right granularity for your blueprints:
- Too large: Blueprints become hard to maintain
- Too small: Excessive fragmentation and overhead

Aim for logically cohesive units that group related functionality.

### Handler Registration Order

Register all handlers in the blueprint before registering the blueprint with the application:

```python
# Define all handlers first
@blueprint.action("handler1")
def handler1():
    pass

@blueprint.route("/path")
def handler2(req):
    pass

# Then register with the app
app.register_blueprint(blueprint)
```

### Error Handling

Implement proper error handling within blueprint handlers:

```python
@blueprint.action("some_action")
def handle_action():
    try:
        # Action logic
        result = process_data()
        return response.send(result)
    except ValueError as e:
        # Handle specific errors
        return response.error(f"Invalid data: {e}")
    except Exception as e:
        # Catch-all for unexpected errors
        direct_logger.error(f"Unexpected error in some_action: {e}")
        return response.error("An unexpected error occurred")
```

## Troubleshooting

### Handler Not Registered

If your handler isn't being called:

1. Check that the blueprint is properly registered with `app.register_blueprint()`
2. Verify the blueprint is registered before the app is started
3. Ensure handler names/paths don't conflict with other handlers

### Circular Dependencies

If you encounter circular imports:

1. Restructure your imports to break the cycle
2. Import only what you need, when you need it
3. Consider using dependency injection patterns

### Namespace Conflicts

If multiple blueprints define the same routes or actions:

1. The last registered blueprint's handler will override previous ones
2. Use unique prefixes or namespaces for your handlers
3. Check logs for warnings about handler overrides 