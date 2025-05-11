"""
Daebus Example

This example demonstrates:
1. Creating a Daebus service that uses Redis pub/sub
2. Using DaebusCaller to communicate with Daebus services
3. Multi-step responses for long-running operations
4. Long-running background threads with app.thread
5. Lifecycle hooks with app.on_start()

To run this example:
1. Start the service: python example.py
2. In another terminal, run the client code (uncomment client_example())
"""

from Daebus import Daebus, DaebusCaller, request, response, logger, broadcast, cache
import json
import time
import threading
import random

# Daebus Service Example
app = Daebus(__name__)


@app.on_start()
def on_startup():
    """
    This function runs once when the service starts up.
    Use it for initialization tasks, broadcasting startup notifications,
    or setting up initial cache values.
    """
    logger.info("🚀 Service is starting up!")

    # Set some initial values in cache
    try:
        cache.set("service.start_time", str(time.time()))
        cache.set("service.status", "running")

        # Broadcast a startup message
        broadcast.send("system.events", {
            "event": "startup",
            "service": app.name,
            "timestamp": time.time()
        })

        logger.info("✅ Startup tasks completed successfully")
    except Exception as e:
        logger.error(f"❌ Error during startup: {e}")


@app.action("handle_request")
def handle_response():
    """
    Handle the 'handle_request' action.
    This receives messages sent to the service's main channel with action='handle_request'.
    """
    try:
        payload = request.payload

        # Log the received request
        logger.info(
            f"Received 'handle_request' action with payload: {payload}")

        # Process the request (this is where your business logic goes)
        response_payload = {
            "message": "Hello, world!",
            "received_data": payload
        }

        # Response will send a message back to the sender of the request
        return response.success(response_payload)
    except Exception as e:
        # If an error occurs, we can send an error message back to the sender
        return response.error(e)


@app.action("ping")
def handle_ping():
    """
    Handle the 'ping' action.
    This receives messages sent to the service's main channel with action='ping'.
    """
    try:
        payload = request.payload
        logger.info(f"Received ping with payload: {payload}")

        # Return a pong response
        return response.success({
            "pong": True,
            "timestamp": time.time(),
            "received_at": payload.get("timestamp", 0)
        })
    except Exception as e:
        return response.error(e)


@app.action("long_task")
def handle_long_task():
    """
    A long-running task that demonstrates multi-step responses.
    """
    try:
        payload = request.payload
        steps = payload.get("steps", 5)
        delay = payload.get("delay", 1.0)

        logger.info(f"Starting long task with {steps} steps, {delay}s delay")

        # First, send an immediate response that we've started the task
        response.progress({
            "message": f"Starting task with {steps} steps",
            "step": 0,
            "total_steps": steps
        }, progress_percentage=0)

        # Run the long task in a background thread to avoid blocking
        def run_task():
            try:
                for i in range(1, steps + 1):
                    # Simulate work
                    time.sleep(delay)

                    # Send progress update
                    progress_pct = (i / steps) * 100
                    response.progress({
                        "message": f"Completed step {i} of {steps}",
                        "step": i,
                        "total_steps": steps
                    }, progress_percentage=progress_pct)

                    logger.info(
                        f"Long task progress: {i}/{steps} ({progress_pct:.1f}%)")

                # Send final result
                response.success({
                    "message": "Task completed successfully",
                    "steps_completed": steps,
                    "timestamp": time.time()
                })
            except Exception as e:
                logger.error(f"Error in long task: {e}")
                response.error(Exception(f"Task failed at step {i}: {e}"))

        # Start the background task
        thread = threading.Thread(target=run_task)
        thread.daemon = True
        thread.start()

        # Return None since we're handling the responses in the background thread
        return None
    except Exception as e:
        logger.error(f"Error setting up long task: {e}")
        return response.error(e)


# Define a mock data source that simulates external data
class MockDataSource:
    def __init__(self):
        self.connected = False
        self.data = ["sensor1", "sensor2", "sensor3", "sensor4"]

    def connect(self):
        # Simulate connection delay
        time.sleep(1)
        self.connected = True
        return True

    def disconnect(self):
        self.connected = False

    def read_data(self):
        if not self.connected:
            raise ConnectionError("Not connected to data source")

        # Simulate some varying data
        value = random.randint(0, 100)
        sensor = random.choice(self.data)
        return {"sensor": sensor, "value": value, "timestamp": time.time()}


# Create a global data source that our thread will use
data_source = MockDataSource()


# Example of a long-running thread that processes external data
@app.thread("data_collector")
def run_data_collector(running):
    """
    A long-running thread that collects data from an external source.

    Args:
        running: A function that returns True while the app is running, 
                 False when the app is shutting down
    """
    logger.info("Starting data collector thread")

    # Try to connect to the data source
    connected = False
    while running() and not connected:
        try:
            logger.info("Connecting to data source...")
            connected = data_source.connect()
            logger.info("Connected to data source successfully")
        except Exception as e:
            logger.error(f"Failed to connect to data source: {e}")
            logger.info("Retrying in 5 seconds...")
            time.sleep(5)

    # Main processing loop
    while running() and connected:
        try:
            # Read data from the source
            data = data_source.read_data()

            # Process and broadcast the data
            broadcast.send("data.update", {
                "source": "data_collector",
                "data": data,
                "timestamp": time.time()
            })

            logger.debug(f"Collected and broadcast data: {data}")

            # Wait a bit before next collection
            time.sleep(2)

        except Exception as e:
            logger.error(f"Error collecting data: {e}")

            # If connection was lost, try to reconnect
            if isinstance(e, ConnectionError):
                logger.info("Attempting to reconnect...")
                connected = False
                try:
                    connected = data_source.connect()
                    logger.info("Reconnected successfully")
                except Exception as reconnect_error:
                    logger.error(f"Failed to reconnect: {reconnect_error}")
                    # Back off before retry
                    time.sleep(5)
            else:
                # For other errors, wait a bit before retrying
                time.sleep(1)

    # Clean up when the thread is stopping
    if data_source.connected:
        logger.info("Disconnecting from data source...")
        data_source.disconnect()

    logger.info("Data collector thread stopped")


# Another example using a WebSocket-like interface
# auto_start=False means we'll start it manually
@app.thread("socket_client", auto_start=False)
def run_socket_client(running):
    """
    A simulated WebSocket client that connects to a server and processes messages.
    This example shows how to use the thread decorator with auto_start=False
    for threads that need explicit starting.

    Args:
        running: A function that returns True while the app is running, 
                 False when the app is shutting down
    """
    logger.info("Socket client thread starting")

    # Simulate a socket connection
    class MockSocket:
        def __init__(self):
            self.connected = False

        def connect(self, url):
            logger.info(f"Connecting to {url}...")
            time.sleep(1)  # Simulate connection delay
            self.connected = True
            logger.info(f"Connected to {url}")
            return True

        def disconnect(self):
            logger.info("Disconnecting socket...")
            self.connected = False

        def receive_message(self):
            # Simulate receiving a message
            time.sleep(0.5)
            if random.random() < 0.1:  # 10% chance of error
                raise ConnectionError("Connection lost")

            return {"type": "update", "data": random.randint(0, 100)}

    # Create a mock socket
    socket = MockSocket()

    # Connect to the server
    try:
        socket.connect("wss://example.com/socket")
    except Exception as e:
        logger.error(f"Failed to connect socket: {e}")
        return

    # Process messages
    while running() and socket.connected:
        try:
            message = socket.receive_message()

            # Process the message
            broadcast.send("socket.message", {
                "source": "socket_client",
                "message": message,
                "timestamp": time.time()
            })

        except ConnectionError as e:
            logger.error(f"Socket error: {e}")

            # Try to reconnect
            logger.info("Attempting to reconnect socket...")
            socket.connected = False
            try:
                socket.connect("wss://example.com/socket")
            except Exception as reconnect_error:
                logger.error(f"Failed to reconnect socket: {reconnect_error}")
                break

        except Exception as e:
            logger.error(f"Error processing socket message: {e}")
            time.sleep(1)

    # Clean up
    if socket.connected:
        socket.disconnect()

    logger.info("Socket client thread stopped")


@app.action("start_socket")
def handle_start_socket():
    """
    Action handler to manually start the socket client thread.
    """
    try:
        # Start the socket client thread (which has auto_start=False)
        success = app.start_thread("socket_client")

        if success:
            return response.success({
                "message": "Socket client thread started",
                "timestamp": time.time()
            })
        else:
            return response.error(Exception("Failed to start socket client thread (already running?)"))
    except Exception as e:
        logger.error(f"Error starting socket client thread: {e}")
        return response.error(e)


@app.action("stop_socket")
def handle_stop_socket():
    """
    Action handler to manually stop the socket client thread.
    """
    try:
        # Stop the socket client thread
        success = app.stop_thread("socket_client")

        if success:
            return response.success({
                "message": "Socket client thread stopped",
                "timestamp": time.time()
            })
        else:
            return response.error(Exception("Failed to stop socket client thread (not running?)"))
    except Exception as e:
        logger.error(f"Error stopping socket client thread: {e}")
        return response.error(e)


# A custom handler for messages sent to a different channel
@app.listen("notifications")
def notification_handler(payload):
    """
    Handle messages sent to the 'notifications' channel.
    This is for broadcast-style messages that don't need responses.
    """
    logger.info(f"Received notification: {payload}")
    # Process the notification


# A named background function that will run on a specified interval
@app.background("some_background_function", 10)
def some_background_function():
    """Background task that runs every 10 seconds"""
    try:
        # Cache is just the exposed redis instance that the package uses behind the scenes
        cache.set("some_key", json.dumps({"message": "Hello, world!"}))
        logger.info("Background task executed")

        # Publish a status update
        broadcast.send("system_status", {
            "service": "example_service",
            "status": "healthy",
            "timestamp": time.time()
        })
    except Exception as e:
        logger.error(f"Error in some_background_function: {e}")


# Client code example - this would typically be in a separate file
def client_example():
    """Example of how to use DaebusCaller to communicate with a service"""
    # Create a caller to interact with our service
    caller = DaebusCaller("example_service")

    try:
        # Example 1: Send a request and get a response (uses the 'handle_request' action)
        print("Sending request to 'handle_request' action...")
        response = caller.send_request("handle_request", {
            "name": "Client",
            "data": "Some test data"
        })
        print(f"Received response: {response}")

        # Example 2: Send a ping request
        print("Sending ping request...")
        ping_response = caller.send_request("ping", {
            "timestamp": time.time()
        })
        print(f"Received ping response: {ping_response}")

        # Example 3: Send a long-running task request with progress callback
        print("\nStarting long-running task...")

        def progress_callback(data):
            """Handle progress updates from the long-running task"""
            message = data.get("message", "Working...")
            progress = data.get("progress_percentage", 0)
            print(f"Progress ({progress:.1f}%): {message}")

        # Start a task with 5 steps, 1 second each
        final_result = caller.send_request("long_task", {
            "steps": 5,
            "delay": 1.0
        }, on_progress=progress_callback)

        print(f"Long task complete! Result: {final_result}")

        # Example 4: Start the socket client thread
        print("\nStarting socket client thread...")
        start_result = caller.send_request("start_socket", {})
        print(f"Socket start result: {start_result}")

        # Wait a bit to let it run
        print("Waiting for 5 seconds while socket runs...")
        time.sleep(5)

        # Stop the socket client thread
        print("Stopping socket client thread...")
        stop_result = caller.send_request("stop_socket", {})
        print(f"Socket stop result: {stop_result}")

        # Example 5: Send a message to a different channel (broadcast)
        print("Broadcasting message to notifications channel...")
        caller.send_message("notifications", {
            "type": "alert",
            "message": "This is a broadcast message"
        })

        # Example 6: Send a message directly to the service with an action specified
        print("Sending message directly to service with 'ping' action...")
        caller.send_to_service({
            "timestamp": time.time(),
            "message": "Direct ping"
        }, action="ping")

        print("\nClient examples completed successfully")
    except Exception as e:
        print(f"Error in client: {e}")
    finally:
        # Clean up resources
        caller.close()


if __name__ == '__main__':
    # To run the client example, uncomment the line below and comment out the app.run() line
    # client_example()

    # Run the service
    app.run(service='example_service', debug=True,
            redis_host='localhost', redis_port=6379)
