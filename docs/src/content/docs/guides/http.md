---
title: HTTP Endpoints
description: Adding HTTP API support to your Daebus applications
---

Daebus includes a lightweight HTTP server that allows you to expose RESTful APIs from your services without requiring external web frameworks like Flask or FastAPI.

## Getting Started

### Adding HTTP Support

To add HTTP support to your Daebus application, create and attach a `DaebusHttp` instance:

```python
from daebus import Daebus, DaebusHttp, response

# Create your application
app = Daebus(__name__)

# Create an HTTP endpoint
http = DaebusHttp(port=8080, host='0.0.0.0')

# Attach the HTTP endpoint to your app
app.attach(http)

# Define routes and start your application
app.run(service="my_service")
```

### Basic Routes

Define routes using the `@app.route()` decorator:

```python
@app.route("/status")
def get_status(req):
    return response.send({
        "status": "healthy",
        "uptime": 3600,
        "version": "1.0.0"
    }, 200)
```

### Request Methods

By default, routes handle GET requests. To support other HTTP methods, specify them in the `methods` parameter:

```python
@app.route("/users", methods=["POST"])
def create_user(req):
    # Access JSON data from the request
    user_data = req.payload
    
    # Process the data
    new_user = {
        "id": "user123",
        "name": user_data.get("name"),
        "email": user_data.get("email")
    }
    
    # Return with a 201 Created status
    return response.send(new_user, 201)
```

Supported HTTP methods are:
- `GET`
- `POST`
- `PUT`
- `DELETE`
- `OPTIONS` (handled automatically for CORS)

## Working with Requests

### The Request Object

In route handlers, you receive a `req` (or `request`) parameter that provides access to the HTTP request data:

```python
@app.route("/api/data")
def handle_data(req):
    # Access various properties of the request
    method = req.method       # HTTP method (GET, POST, etc.)
    path = req.path           # URL path
    headers = req.headers     # Dictionary of HTTP headers
    payload = req.payload     # Request data (combined from JSON, form, or query params)
    
    # Log information about the request
    logger.info(f"Received {method} request to {path}")
    
    return response.send({"received": True}, 200)
```

### Request Data Types

Daebus automatically parses request data and makes it available through `req.payload`:

- For `GET` requests: Query parameters 
- For `POST`/`PUT` requests: JSON body or form data
- For all requests: URL parameters (from route patterns)

### URL Parameters

Define route patterns with URL parameters using angle brackets:

```python
@app.route("/users/<user_id>")
def get_user(req, user_id):
    # user_id is automatically extracted from the URL
    
    # Example implementation
    if user_id == "123":
        return response.send({
            "id": user_id,
            "name": "John Doe",
            "email": "john@example.com"
        }, 200)
    else:
        return response.send({
            "error": "User not found"
        }, 404)
```

### Query Parameters

For GET requests, access query parameters through `req.payload`:

```python
@app.route("/search")
def search_items(req):
    # Access query parameters
    query = req.payload.get("q", "")
    limit = int(req.payload.get("limit", "10"))
    offset = int(req.payload.get("offset", "0"))
    
    # Process the search
    results = [
        {"id": 1, "name": "Example item"}
        # ... more items
    ]
    
    return response.send({
        "query": query,
        "results": results,
        "count": len(results),
        "limit": limit,
        "offset": offset
    }, 200)
```

## Working with Responses

### Basic Responses

Use `response.send()` to send data with a status code:

```python
@app.route("/data")
def get_data(req):
    data = {"message": "Hello, world!"}
    return response.send(data, 200)
```

### Error Responses

For error responses, use appropriate HTTP status codes:

```python
@app.route("/protected")
def protected_resource(req):
    # Check for Authorization header
    auth_header = req.headers.get("Authorization")
    
    if not auth_header:
        return response.send({
            "error": "Unauthorized",
            "message": "Authentication required"
        }, 401)
    
    if not is_valid_token(auth_header):
        return response.send({
            "error": "Forbidden",
            "message": "Invalid or expired token"
        }, 403)
    
    # Process authorized request
    return response.send({
        "message": "Protected data",
        "secret": "12345"
    }, 200)
```

### Response Methods

Daebus provides several ways to send responses:

```python
# Standard response with data and status code
return response.send(data, 200)

# Error response with custom message
return response.send({"error": "Not found"}, 404)

# You can also directly return a tuple of (data, status_code)
return {"data": "example"}, 200
```

## Advanced Features

### CORS Configuration

To enable Cross-Origin Resource Sharing (CORS) for browser clients:

```python
from daebus import Daebus, DaebusHttp

app = Daebus(__name__)

# Configure CORS with options
cors_config = {
    'allowed_origins': ['http://localhost:3000', 'https://example.com'],
    'allowed_methods': ['GET', 'POST', 'PUT', 'DELETE'],
    'allowed_headers': ['Content-Type', 'Authorization'],
    'expose_headers': ['X-Custom-Header'],
    'allow_credentials': True,
    'max_age': 3600  # Cache preflight for 1 hour
}

# Create HTTP endpoint with CORS
http = DaebusHttp(port=8080, cors_config=cors_config)
app.attach(http)
```

Available CORS configuration options:

| Option | Description | Example |
|--------|-------------|---------|
| `allowed_origins` | List of allowed origins or `["*"]` for any | `["http://localhost:3000"]` |
| `allowed_methods` | List of allowed HTTP methods | `["GET", "POST"]` |
| `allowed_headers` | List of allowed headers or `["*"]` for any | `["Content-Type"]` |
| `expose_headers` | Headers to expose to the client | `["X-Custom-Header"]` |
| `allow_credentials` | Allow cookies and authentication | `True` or `False` |
| `max_age` | Cache time for preflight requests (seconds) | `3600` |

### Blueprints

For larger applications, organize routes using blueprints:

```python
from daebus import Daebus, DaebusHttp, Blueprint

# Create a blueprint for user-related routes
users_bp = Blueprint("users")

@users_bp.route("/users")
def list_users(req):
    return response.send({"users": [...]}, 200)

@users_bp.route("/users/<user_id>")
def get_user(req, user_id):
    return response.send({"id": user_id, "name": "..."}, 200)

# Create your application
app = Daebus(__name__)
http = DaebusHttp(port=8080)
app.attach(http)

# Register the blueprint
app.register_blueprint(users_bp)

# Start your application
app.run(service="my_service")
```

### Direct Access to Classes

For advanced customization, access the HTTP-specific classes directly:

```python
from daebus import Daebus, DaebusHttp, HttpRequest, HttpResponse

app = Daebus(__name__)
http = DaebusHttp(port=8080)
app.attach(http)

@app.route("/advanced")
def advanced_route(req):
    # Ensure we have the right request type
    if not isinstance(req, HttpRequest):
        raise TypeError("Expected HttpRequest")
    
    # Create a custom response
    custom_response = HttpResponse(None)
    return custom_response.send({
        "custom": True,
        "path": req.path
    }, 200)
```

## Security Considerations

### Secure Headers

For production deployments, consider adding security headers:

```python
@app.route("/secure")
def secure_endpoint(req):
    data = {"message": "Secure content"}
    
    # Create a response with security headers
    resp, status = response.send(data, 200)
    
    # Add custom security headers here if needed
    # This would need custom middleware in a production environment
    
    return resp, status
```

### Authentication

Implement authentication for your endpoints:

```python
def require_auth(handler):
    """Authentication middleware for routes"""
    def wrapper(req, *args, **kwargs):
        auth_header = req.headers.get("Authorization")
        
        if not auth_header or not auth_header.startswith("Bearer "):
            return response.send({"error": "Unauthorized"}, 401)
        
        token = auth_header.split("Bearer ")[1]
        if not validate_token(token):
            return response.send({"error": "Invalid token"}, 403)
        
        # Token is valid, continue to handler
        return handler(req, *args, **kwargs)
    
    return wrapper

# Use the middleware
@app.route("/protected")
@require_auth
def protected_endpoint(req):
    return response.send({"message": "Protected data"}, 200)
```

## Performance

The Daebus HTTP server is designed for:

- Internal APIs between services
- Admin interfaces and debugging endpoints
- Lightweight frontend APIs

For high-traffic production APIs, consider using dedicated web frameworks like FastAPI or Flask with WSGI/ASGI servers.

## Complete Example

Here's a complete example of an HTTP-enabled Daebus application:

```python
from daebus import Daebus, DaebusHttp, response, logger

# Create application
app = Daebus(__name__)

# Configure and attach HTTP
http = DaebusHttp(
    port=8080, 
    host="0.0.0.0",
    cors_config={
        'allowed_origins': ['*'],
        'allowed_methods': ['GET', 'POST']
    }
)
app.attach(http)

# Define routes
@app.route("/")
def index(req):
    return response.send({
        "service": "example_service",
        "version": "1.0.0",
        "endpoints": ["/", "/users", "/users/<id>"]
    }, 200)

@app.route("/users")
def list_users(req):
    users = [
        {"id": "1", "name": "User One"},
        {"id": "2", "name": "User Two"}
    ]
    return response.send({"users": users}, 200)

@app.route("/users/<user_id>")
def get_user(req, user_id):
    # Example user lookup
    if user_id in ["1", "2"]:
        return response.send({
            "id": user_id,
            "name": f"User {user_id}"
        }, 200)
    else:
        return response.send({
            "error": "User not found"
        }, 404)

@app.route("/users", methods=["POST"])
def create_user(req):
    user_data = req.payload
    
    # Validate required fields
    if not user_data.get("name"):
        return response.send({
            "error": "Name is required"
        }, 400)
    
    # Create user (example implementation)
    new_user = {
        "id": "3",  # In a real app, generate a unique ID
        "name": user_data["name"]
    }
    
    return response.send(new_user, 201)

# Start the application
if __name__ == "__main__":
    logger.info(f"Starting HTTP server on port {http.port}")
    app.run(service="example_service")
```

## Troubleshooting

### Common Issues

1. **Port already in use**:
   - Error: `OSError: [Errno 48] Address already in use`
   - Solution: Change the port number or stop the process using the port

2. **Permission denied**:
   - Error: `Permission denied` when binding to port 80/443
   - Solution: Use ports above 1024 or run with elevated privileges

3. **Headers already sent**:
   - Error: Cannot send response after headers are sent
   - Solution: Ensure only one response is sent per request

## Further reading

- Read [about how-to guides](https://diataxis.fr/how-to-guides/) in the Diátaxis framework
