"""
Daebus HTTP Example

This example demonstrates how to use the HTTP endpoint functionality in Daebus.
It shows how request and response objects work across HTTP and Redis contexts.

To run this example:
1. Make sure Redis is running locally
2. Run: python example_http.py
3. Visit http://localhost:8080/status in your browser or use curl
"""

import time
import json
import threading
import random
from Daebus import (
    Daebus, DaebusHttp, request, response, logger, broadcast, cache,
    HttpRequest, HttpResponse, PubSubRequest, PubSubResponse
)


def main():
    """Run the demo application."""

    # Create and configure the application
    app = Daebus('http_example')

    # Configure HTTP endpoints
    # You can add CORS configuration when creating the HTTP endpoint
    cors_config = {
        'allowed_origins': ['http://localhost:3000', 'https://example.com'],
        'allowed_methods': ['GET', 'POST', 'OPTIONS'],
        'allowed_headers': ['Content-Type', 'Authorization'],
        'expose_headers': ['X-Custom-Header'],
        'allow_credentials': True,
        'max_age': 3600  # Cache preflight request for 1 hour
    }

    # Create HTTP endpoint with CORS support
    http = DaebusHttp(port=8080, cors_config=cors_config)

    # Alternatively, you can configure CORS after creation
    # http = DaebusHttp(port=8080)
    # http.configure_cors({
    #     'allowed_origins': '*',  # Allow all origins
    #     'allowed_methods': ['GET', 'POST'],
    #     'allowed_headers': '*',  # Allow all headers
    # })

    # Attach HTTP endpoint to the application
    app.attach(http)


# Some example data for our API
system_data = {
    "cpu_temp": 45.2,
    "memory_usage": 32.5,
    "uptime": 0,
    "started_at": time.time()
}

# Update system data every 5 seconds


@app.background("update_system_data", 5)
def update_system_data():
    """Simulate updating system metrics"""
    try:
        # Update system data with some random fluctuations
        system_data["cpu_temp"] = 40 + random.random() * 10
        system_data["memory_usage"] = 25 + random.random() * 20
        system_data["uptime"] = time.time() - system_data["started_at"]

        # Broadcast the system status
        broadcast.send("system.status", {
            "source": "http_example_service",
            "data": system_data,
            "timestamp": time.time()
        })

        logger.debug(f"Updated system data: {system_data}")
    except Exception as e:
        logger.error(f"Error updating system data: {e}")


# Example of a shared function that works with both HTTP and Redis
def get_system_status():
    """
    Get system status data.

    This function can be called from both HTTP routes and Redis action handlers.
    """
    return {
        "service": "http_example_service",
        "status": "running",
        "data": system_data,
        "timestamp": time.time()
    }


# Define an HTTP route for system status
@app.route("/status")
def http_status(req):
    """
    Return the current system status as JSON.

    This handler uses the new response.send method which is specific to HTTP.
    """
    try:
        # You can see what's in the request
        logger.debug(f"Got HTTP request with payload: {req.payload}")

        # Get the system status
        status_data = get_system_status()

        # Return using response.send - HTTP specific!
        return response.send(status_data, 200)
    except Exception as e:
        # Error handling with appropriate HTTP status code
        return response.send({"error": str(e)}, 500)


# Register a Redis action handler that uses pub/sub specific methods
@app.action("get_status")
def redis_status_handler():
    """
    Handle status requests via Redis.

    This handler uses response.success which is designed for pub/sub communication.
    """
    try:
        logger.info(
            f"Received status request via Redis with payload: {request.payload}")

        # Get the system status using the shared function
        status_data = get_system_status()

        # Return using response.success - pub/sub specific!
        return response.success(status_data)
    except Exception as e:
        return response.error(e)


# Example of direct use of HTTP classes (without proxies)
# This would be used in more advanced scenarios or for custom middleware
@app.route("/advanced")
def advanced_handler(req):
    """Example of working with the explicit HttpRequest and HttpResponse classes"""
    try:
        # You can choose to work directly with the HttpRequest class
        # This is useful if you need to create specialized request handlers

        # Check if the request has the expected type
        if not isinstance(req, HttpRequest):
            raise TypeError("Expected an HttpRequest object")

        # Process the request
        result = {
            "message": "Advanced handler example",
            "request_path": req.path,
            "request_method": req.method,
            "timestamp": time.time()
        }

        # You could also create an HttpResponse directly if needed
        # This is useful for custom middleware or response formatting
        http_response = HttpResponse(None)  # Would normally take the handler
        return http_response.send(result, 200)

        # But the proxy is usually more convenient
        # return response.send(result, 200)
    except Exception as e:
        logger.error(f"Error in advanced handler: {e}")
        return response.send({"error": str(e)}, 500)


# Define a route that accepts POST requests
@app.route("/trigger", methods=["POST"])
def trigger_action(req):
    """Example of handling POST requests with JSON data"""
    try:
        # Get JSON data from the request
        data = req.payload

        if not data:
            return response.send({"error": "No data provided"}, 400)

        # Log the received data
        logger.info(f"Received trigger request with data: {data}")

        # Broadcast the trigger event
        broadcast.send("api.trigger", {
            "source": "http_api",
            "data": data,
            "timestamp": time.time()
        })

        # Return a success response
        return response.send({
            "message": "Action triggered",
            "received_data": data
        }, 200)
    except Exception as e:
        logger.error(f"Error handling trigger request: {e}")
        return response.send({"error": str(e)}, 500)


# Define a parametrized route with long-running task
@app.route("/tasks/<task_id>/start")
def start_task(req, task_id):
    """
    Example of a long-running task with progress updates.

    This demonstrates how a task might use both HTTP and pub/sub mechanisms.
    """
    try:
        logger.info(f"Starting task {task_id}")

        # Start a background thread to simulate a long process
        def run_task():
            try:
                # Simulate steps of work
                for i in range(1, 6):
                    time.sleep(1)  # Simulate work

                    # Broadcast progress updates via Redis (would not go to HTTP client)
                    broadcast.send(f"task.{task_id}.progress", {
                        "message": f"Step {i} of 5 completed",
                        "status": "in_progress",
                        "task_id": task_id,
                        "step": i,
                        "progress_percentage": (i / 5) * 100
                    })

                # Send completion message via Redis broadcast
                broadcast.send(f"task.{task_id}.completed", {
                    "message": f"Task {task_id} completed successfully",
                    "status": "completed",
                    "task_id": task_id,
                    "result": "Task data here"
                })
            except Exception as e:
                logger.error(f"Error in task {task_id}: {e}")
                broadcast.send(f"task.{task_id}.error", {
                    "error": str(e),
                    "task_id": task_id
                })

        # Start the task in a background thread
        thread = threading.Thread(target=run_task)
        thread.daemon = True
        thread.start()

        # For HTTP, return an immediate response
        return response.send({
            "message": f"Task {task_id} started",
            "task_id": task_id,
            "status": "started",
            "stream_updates_channel": f"task.{task_id}.progress"
        }, 202)  # 202 Accepted
    except Exception as e:
        logger.error(f"Error starting task {task_id}: {e}")
        return response.send({"error": str(e)}, 500)


# Define a parametrized route
@app.route("/devices/<device_id>")
def get_device(req, device_id):
    """Example of a route with URL parameters"""
    # Simulate device data
    devices = {
        "1": {"name": "Thermostat", "temp": 22.5},
        "2": {"name": "Light Switch", "state": "on"},
        "3": {"name": "Camera", "recording": False}
    }

    if device_id in devices:
        return response.send({
            "id": device_id,
            "device": devices[device_id],
            "timestamp": time.time()
        }, 200)
    else:
        return response.send({
            "error": f"Device {device_id} not found"
        }, 404)


if __name__ == "__main__":
    print(f"""
    ===========================================
    Daebus HTTP Example Server
    ===========================================
    
    Server is running with the following endpoints:
    
    GET  http://localhost:8080/status           - Get system status
    GET  http://localhost:8080/advanced         - Example using explicit HttpRequest/Response
    POST http://localhost:8080/trigger          - Trigger an action
    GET  http://localhost:8080/tasks/<id>/start - Start a task with progress
    GET  http://localhost:8080/devices/<id>     - Get device info
    
    Try these commands:
    curl http://localhost:8080/status
    curl http://localhost:8080/devices/1
    curl -X POST -H "Content-Type: application/json" -d '{"command":"test"}' http://localhost:8080/trigger
    
    Press Ctrl+C to stop the server
    """)

    # Run the Daebus application
    app.run(service="http_example_service", debug=True,
            redis_host="localhost", redis_port=6379)
