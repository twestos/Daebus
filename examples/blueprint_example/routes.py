from daebus import Blueprint, request, response, logger

# Create a blueprint for API routes
api = Blueprint('api')

@api.route('/api/hello')
def hello_route(req):
    name = req.payload.get('name', 'World')
    return {"message": f"Hello, {name}!"}

@api.route('/api/users', methods=['GET', 'POST'])
def users_route(req):
    if req.method == 'GET':
        # Example: get users from database
        return {"users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}
    elif req.method == 'POST':
        # Example: create a new user
        user_data = req.payload
        logger.info(f"Creating user: {user_data}")
        return {"status": "created", "user": user_data}, 201

# Create a blueprint for PubSub actions
pubsub = Blueprint('pubsub')

@pubsub.action('greet')
def greet_action():
    name = request.payload.get('name', 'World')
    response.success({"greeting": f"Hello, {name}!"})

@pubsub.action('calculate')
def calculate_action():
    a = request.payload.get('a', 0)
    b = request.payload.get('b', 0)
    operation = request.payload.get('operation', 'add')
    
    result = None
    if operation == 'add':
        result = a + b
    elif operation == 'subtract':
        result = a - b
    elif operation == 'multiply':
        result = a * b
    elif operation == 'divide':
        if b == 0:
            response.error(Exception("Cannot divide by zero"))
            return
        result = a / b
    
    response.success({"result": result})

# Create a blueprint for background tasks
tasks = Blueprint('tasks')

@tasks.background('cleanup', 3600)  # Run every hour
def cleanup_task():
    logger.info("Running cleanup task...")
    # Perform cleanup operations
    
@tasks.on_start()
def initialize():
    logger.info("Initializing tasks blueprint...")
    # Perform initialization 