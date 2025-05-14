---
title: Background Threads
description: Run long-lived background processes in your Daebus applications
---

Daebus provides a built-in mechanism for running long-lived background threads that operate continuously throughout the life of your service. Unlike scheduled tasks that run periodically, background threads run continuously and are ideal for operations like continuous monitoring, processing work queues, or maintaining persistent connections.

## Basic Usage

### Creating a Background Thread

Use the `@app.thread` decorator to define a background thread:

```python
from daebus import Daebus, direct_logger
import time

app = Daebus(__name__)

@app.thread("worker_thread")
def continuous_worker(running):
    # The 'running' parameter is a callable that returns False when the app is stopping
    direct_logger.info("Worker thread started")
    
    while running():  # This loops until the application exits
        try:
            # Do some work
            process_work_items()
            
            # Sleep briefly to prevent CPU hogging
            time.sleep(0.1)
        except Exception as e:
            direct_logger.error(f"Error in worker thread: {e}")
    
    direct_logger.info("Worker thread stopping")

if __name__ == "__main__":
    app.run(service="my_service")
```

The background thread will:
1. Start automatically when your service starts
2. Run continuously until your service stops
3. Be properly shut down when your service exits

## Thread Control

### The Running Function

Each thread function receives a `running` parameter, which is a callable that returns:
- `True` while the application is running normally
- `False` when the application is shutting down

This allows your thread to gracefully exit when the service is stopping:

```python
@app.thread("processor")
def data_processor(running):
    setup_resources()
    
    try:
        while running():
            # Process items as long as the service is running
            process_next_item()
    finally:
        # Clean up resources when the thread is stopping
        cleanup_resources()
```

### Using Thread State

You can maintain state within your thread function:

```python
@app.thread("connection_manager")
def manage_connections(running):
    # Initialize thread-local state
    connections = {}
    retry_count = 0
    
    while running():
        try:
            # Monitor and manage connections
            for host, conn in list(connections.items()):
                if not conn.is_active():
                    # Reconnect if needed
                    connections[host] = establish_connection(host)
                    direct_logger.info(f"Reconnected to {host}")
            
            # Check for new hosts to connect
            new_hosts = discover_hosts()
            for host in new_hosts:
                if host not in connections:
                    connections[host] = establish_connection(host)
                    direct_logger.info(f"Connected to new host: {host}")
            
            # Reset retry counter on successful iteration
            retry_count = 0
            
            time.sleep(5)  # Check every 5 seconds
            
        except Exception as e:
            retry_count += 1
            direct_logger.error(f"Connection error (retry {retry_count}): {e}")
            time.sleep(min(30, retry_count * 5))  # Exponential backoff
```

## Thread Safety

### Accessing Shared Resources

When accessing resources shared with other threads, always use proper synchronization:

```python
import threading

app = Daebus(__name__)

# Shared resources
shared_data = {}
data_lock = threading.Lock()

@app.thread("data_collector")
def collect_data(running):
    while running():
        try:
            # Collect new data
            new_data = fetch_external_data()
            
            # Update shared data with thread safety
            with data_lock:
                for key, value in new_data.items():
                    shared_data[key] = value
            
            time.sleep(10)  # Collect every 10 seconds
        except Exception as e:
            direct_logger.error(f"Data collection error: {e}")
            time.sleep(30)  # Longer sleep on error

@app.action("get_current_data")
def get_data():
    # Thread-safe access to the shared data
    with data_lock:
        current_data = shared_data.copy()
    
    return response.send(current_data)
```

### Logging Considerations

Always use `direct_logger` instead of the context-based `logger` in background threads:

```python
@app.thread("monitoring")
def monitor_system(running):
    while running():
        try:
            # This is correct
            direct_logger.info("System monitoring active")
            
            # This might not work correctly in a background thread
            # logger.info("System monitoring active")
            
            time.sleep(60)
        except Exception as e:
            direct_logger.error(f"Monitoring error: {e}")
```

## Practical Examples

### Work Queue Processor

Process items from a queue continuously:

```python
import queue
import threading

app = Daebus(__name__)

# Create a thread-safe work queue
work_queue = queue.Queue()
results = {}
results_lock = threading.Lock()

@app.thread("queue_processor")
def process_queue(running):
    direct_logger.info("Queue processor started")
    
    while running():
        try:
            # Try to get an item from the queue with a timeout
            # This allows the thread to check the running() condition regularly
            try:
                item = work_queue.get(timeout=1.0)
            except queue.Empty:
                continue
                
            # Process the item
            item_id = item.get("id")
            result = process_item(item)
            
            # Store the result
            with results_lock:
                results[item_id] = result
                
            # Mark the task as done
            work_queue.task_done()
            direct_logger.info(f"Processed item {item_id}")
            
        except Exception as e:
            direct_logger.error(f"Error processing queue item: {e}")

# Action to add items to the queue
@app.action("submit_job")
def submit_job():
    job_data = request.payload
    job_id = generate_unique_id()
    
    # Add metadata to the job
    job_data["id"] = job_id
    job_data["submitted_at"] = time.time()
    
    # Add to the queue
    work_queue.put(job_data)
    
    return response.send({
        "job_id": job_id,
        "status": "queued"
    })

# Action to check job results
@app.action("check_job")
def check_job():
    job_id = request.payload.get("job_id")
    
    if not job_id:
        return response.error("Missing job_id parameter")
    
    with results_lock:
        result = results.get(job_id)
    
    if result:
        return response.send({
            "job_id": job_id,
            "status": "completed",
            "result": result
        })
    else:
        # Check if job is in queue
        queue_position = check_queue_position(job_id)
        if queue_position >= 0:
            return response.send({
                "job_id": job_id,
                "status": "queued",
                "position": queue_position
            })
        else:
            return response.send({
                "job_id": job_id,
                "status": "not_found"
            })
```

### External API Monitor

Monitor external APIs and report status:

```python
import requests
import time

app = Daebus(__name__)

# API endpoints to monitor
endpoints = {
    "users_api": "https://api.example.com/users/health",
    "orders_api": "https://api.example.com/orders/health",
    "inventory_api": "https://api.example.com/inventory/health"
}

# Status storage
api_status = {}
status_lock = threading.Lock()

@app.thread("api_monitor")
def monitor_apis(running):
    while running():
        for api_name, url in endpoints.items():
            try:
                start_time = time.time()
                response = requests.get(url, timeout=5)
                latency = time.time() - start_time
                
                status = {
                    "status": "up" if response.status_code == 200 else "degraded",
                    "status_code": response.status_code,
                    "latency_ms": round(latency * 1000, 2),
                    "checked_at": time.time()
                }
                
                with status_lock:
                    api_status[api_name] = status
                
                if response.status_code != 200:
                    direct_logger.warning(
                        f"API {api_name} returned {response.status_code}"
                    )
            except Exception as e:
                with status_lock:
                    api_status[api_name] = {
                        "status": "down",
                        "error": str(e),
                        "checked_at": time.time()
                    }
                direct_logger.error(f"Error monitoring {api_name}: {e}")
        
        # Wait before next check cycle
        time.sleep(30)

@app.action("get_api_status")
def get_api_status():
    with status_lock:
        current_status = api_status.copy()
    
    return response.send(current_status)
```

### Websocket Client

Maintain a persistent WebSocket connection:

```python
import websocket
import json
import threading

app = Daebus(__name__)

# Shared message storage
received_messages = []
messages_lock = threading.Lock()
websocket_client = None

@app.thread("websocket_client")
def run_websocket_client(running):
    global websocket_client
    
    # WebSocket event callbacks
    def on_message(ws, message):
        try:
            data = json.loads(message)
            with messages_lock:
                received_messages.append(data)
                # Keep only the last 100 messages
                if len(received_messages) > 100:
                    received_messages.pop(0)
            
            # Process specific message types
            if data.get("type") == "alert":
                direct_logger.warning(f"Alert received: {data.get('message')}")
        except Exception as e:
            direct_logger.error(f"Error processing message: {e}")
    
    def on_error(ws, error):
        direct_logger.error(f"WebSocket error: {error}")
    
    def on_close(ws, close_status_code, close_msg):
        direct_logger.info("WebSocket connection closed")
    
    def on_open(ws):
        direct_logger.info("WebSocket connection established")
        # Send authentication message
        ws.send(json.dumps({
            "type": "auth",
            "api_key": get_api_key()
        }))
    
    # Connection loop - keeps trying to connect while the service is running
    while running():
        try:
            # Create a new WebSocket client
            url = "wss://api.example.com/stream"
            ws = websocket.WebSocketApp(url,
                                        on_open=on_open,
                                        on_message=on_message,
                                        on_error=on_error,
                                        on_close=on_close)
            
            # Store reference to client
            websocket_client = ws
            
            # Start the WebSocket connection (this will block until connection closes)
            ws.run_forever()
            
            # If we get here, the connection was closed - wait before reconnecting
            if running():
                direct_logger.info("WebSocket disconnected, reconnecting in 5 seconds...")
                time.sleep(5)
        except Exception as e:
            direct_logger.error(f"WebSocket connection error: {e}")
            time.sleep(10)  # Wait before retrying
    
    # Clean shutdown
    if websocket_client:
        try:
            websocket_client.close()
        except:
            pass
        websocket_client = None

@app.action("get_recent_messages")
def get_recent_messages():
    with messages_lock:
        messages = received_messages.copy()
    
    return response.send({
        "count": len(messages),
        "messages": messages
    })

@app.action("send_websocket_message")
def send_websocket_message():
    global websocket_client
    
    if not websocket_client:
        return response.error("WebSocket not connected")
    
    message = request.payload.get("message")
    if not message:
        return response.error("No message provided")
    
    try:
        websocket_client.send(json.dumps(message))
        return response.send({"sent": True})
    except Exception as e:
        return response.error(f"Failed to send message: {e}")
```

## Best Practices

1. **Graceful Shutdown**: Always check the `running()` condition and exit cleanly
2. **Error Handling**: Catch and handle exceptions within the thread
3. **Resource Management**: Clean up resources when the thread exits
4. **Thread Safety**: Use locks or thread-safe data structures for shared resources
5. **Avoid CPU Hogging**: Include sleep intervals in continuous processing loops
6. **Use Direct Logger**: Always use `direct_logger` instead of `logger`
7. **Implement Backoff**: Use exponential backoff for retries on failure

## Troubleshooting

### Thread Not Running

If your background thread doesn't seem to be running:

1. Check for exceptions during thread startup in the logs
2. Ensure your thread function accepts the `running` parameter
3. Verify your thread function doesn't exit prematurely

### High CPU Usage

If your thread is causing high CPU usage:

1. Make sure you have sleep intervals in your processing loops
2. Check for tight loops without proper delay
3. Consider using more efficient algorithms or batched processing

### Thread Deadlocks

If your application seems to freeze or deadlock:

1. Review your lock usage to ensure you're not causing deadlocks
2. Set timeouts on resource acquisition when possible
3. Avoid complex lock hierarchies

### Memory Leaks

If you see memory growth over time:

1. Look for data accumulation in global variables or thread-local storage
2. Ensure resources like file handles or network connections are being closed
3. Check that you're limiting cached data to reasonable sizes

## Further reading

- Read [about how-to guides](https://diataxis.fr/how-to-guides/) in the Diátaxis framework
