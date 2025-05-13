# Daebus Blueprint Example

This example demonstrates how to use the blueprint system in Daebus to organize your code into modular components.

## What is a Blueprint?

A Blueprint is a way to organize a group of related routes and other functionality that can be registered on a Daebus app. This is similar to Flask's Blueprint system, allowing you to build your application in a modular way.

Blueprints help you:
- Organize related functionality into separate modules
- Avoid circular imports
- Create reusable components across different applications
- Maintain clean code structure as your application grows

## Project Structure

```
blueprint_example/
├── app.py           # Main application entry point
├── routes.py        # Blueprint definitions
└── README.md        # This file
```

## How to Use Blueprints

### 1. Create a Blueprint

```python
from daebus import Blueprint

# Create a blueprint with a name
api = Blueprint('api')

# Define routes on the blueprint
@api.route('/api/users')
def get_users(req):
    return {"users": ["user1", "user2"]}

# Define PubSub actions on the blueprint
@api.action('get_data')
def get_data():
    # Handle the action
    pass
```

### 2. Register the Blueprint

```python
from daebus import Daebus
from .routes import api

app = Daebus('my_app')
app.register_blueprint(api)
```

## Features Supported by Blueprints

Blueprints support registering all the same types of handlers that you can register directly on a Daebus app:

- **HTTP Routes**: `@blueprint.route('/path')`
- **Action Handlers**: `@blueprint.action('action_name')`
- **Channel Listeners**: `@blueprint.listen('channel')`
- **WebSocket Handlers**: `@blueprint.socket('message_type')`
- **Background Tasks**: `@blueprint.background('task_name', interval)`
- **Thread Tasks**: `@blueprint.thread('thread_name')`
- **On-Start Handlers**: `@blueprint.on_start()`

## Running the Example

1. Make sure you have Redis running
2. Run the application:
```
python -m examples.blueprint_example.app
```

## Testing the API Endpoints

```bash
# Test the hello endpoint
curl http://localhost:8080/api/hello

# Test the users endpoint (GET)
curl http://localhost:8080/api/users

# Test the users endpoint (POST)
curl -X POST -H "Content-Type: application/json" -d '{"name":"Charlie"}' http://localhost:8080/api/users
```

## Testing the PubSub Actions

You can use the `redis-cli` to publish messages to the service channel:

```bash
# Test the greet action
redis-cli publish blueprint_example_service '{"action":"greet","name":"Alice"}'

# Test the calculate action
redis-cli publish blueprint_example_service '{"action":"calculate","a":5,"b":3,"operation":"add"}'
``` 