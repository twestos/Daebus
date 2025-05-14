---
title: Task Scheduler
description: Schedule recurring background tasks in Daebus applications
---

Daebus includes a built-in task scheduler that allows you to run recurring background tasks at specified intervals. This feature is useful for periodic operations like health checks, cleanup jobs, data synchronization, or any task that needs to run on a regular schedule.

## Basic Usage

### Scheduling a Task

Use the `@app.background` decorator to schedule a recurring task:

```python
from daebus import Daebus, direct_logger

app = Daebus(__name__)

@app.background("health_check", 60)  # Name "health_check", run every 60 seconds
def health_check():
    try:
        # Perform health check operations
        status = check_system_health()
        direct_logger.info(f"Health check completed: {status}")
    except Exception as e:
        direct_logger.error(f"Health check failed: {e}")

if __name__ == "__main__":
    app.run(service="monitor_service")
```

The `@app.background` decorator takes two required parameters:
- `name`: A unique identifier for the task
- `interval`: How often to run the task, in seconds

## Important Considerations

### Thread Safety

Background tasks run in separate threads from the main service and other tasks. This means you should:

1. Use `direct_logger` instead of `logger` for logging
2. Be careful with shared resources
3. Implement proper synchronization for shared state

```python
import threading

app = Daebus(__name__)

# Shared counter with lock for thread safety
request_counter = 0
counter_lock = threading.Lock()

@app.background("metrics_reporter", 300)  # Run every 5 minutes
def report_metrics():
    global request_counter
    
    # Thread-safe access to shared state
    with counter_lock:
        current_count = request_counter
        # Optionally reset counter
        request_counter = 0
    
    # Report metrics
    direct_logger.info(f"Processed {current_count} requests in the last 5 minutes")
```

### Error Handling

Always include error handling in background tasks:

```python
@app.background("cleanup", 3600)  # Run hourly
def cleanup_old_data():
    try:
        # Perform cleanup operations
        deleted = delete_old_records()
        direct_logger.info(f"Cleanup completed: {deleted} records removed")
    except Exception as e:
        direct_logger.error(f"Cleanup failed: {e}")
        # Prevent the error from stopping the task scheduler
```

If exceptions are not caught, they will be logged by Daebus, but it's better to handle them explicitly within your task function.

## Advanced Usage

### Dynamic Intervals

If you need to change the task interval dynamically, you can use the scheduler's API:

```python
app = Daebus(__name__)

# Store reference to the task for later modification
cleanup_task = None

@app.background("adaptive_cleanup", 3600)  # Start with hourly
def cleanup_job():
    # Task implementation...
    pass

# Store the task reference
cleanup_task = app.background_tasks["adaptive_cleanup"]

@app.action("adjust_schedule")
def adjust_cleanup_interval():
    global cleanup_task
    
    # Get requested interval from the payload
    new_interval = request.payload.get("interval", 3600)
    
    # Update the task interval
    if cleanup_task:
        cleanup_task.interval = new_interval
        return response.send({"updated": True, "new_interval": new_interval})
    else:
        return response.error("Task not found")
```

### One-time Tasks

For one-time delayed execution, you can use Python's `threading.Timer`:

```python
import threading

@app.action("schedule_one_time")
def schedule_one_time_task():
    delay = request.payload.get("delay", 60)  # Default 60 seconds
    
    # Create a one-time delayed task
    def delayed_task():
        try:
            # Task implementation
            direct_logger.info("One-time task executed")
        except Exception as e:
            direct_logger.error(f"One-time task failed: {e}")
    
    # Schedule the task
    timer = threading.Timer(delay, delayed_task)
    timer.daemon = True  # Allow app to exit even if task is pending
    timer.start()
    
    return response.send({"scheduled": True, "delay": delay})
```

## Practical Examples

### Periodic Data Refresh

```python
from daebus import Daebus, broadcast, direct_logger
import time

app = Daebus(__name__)

# Cache for data
cached_data = {}
last_update = 0

@app.background("data_refresh", 300)  # Refresh every 5 minutes
def refresh_data():
    global cached_data, last_update
    
    try:
        # Fetch fresh data from source
        fresh_data = fetch_data_from_source()
        
        # Update cache
        cached_data = fresh_data
        last_update = time.time()
        
        # Broadcast data update event
        broadcast.send("data_events", {
            "type": "data_refreshed",
            "timestamp": last_update
        })
        
        direct_logger.info("Data cache refreshed successfully")
    except Exception as e:
        direct_logger.error(f"Failed to refresh data: {e}")

# Action to access cached data
@app.action("get_data")
def get_data():
    return response.send({
        "data": cached_data,
        "last_updated": last_update
    })
```

### Resource Monitoring

```python
import psutil
import time

app = Daebus(__name__)

@app.background("system_monitor", 30)  # Check every 30 seconds
def monitor_system():
    try:
        # Collect system metrics
        metrics = {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent,
            "timestamp": time.time()
        }
        
        # Log high usage alerts
        if metrics["cpu_percent"] > 90:
            direct_logger.warning(f"High CPU usage: {metrics['cpu_percent']}%")
        
        if metrics["memory_percent"] > 85:
            direct_logger.warning(f"High memory usage: {metrics['memory_percent']}%")
        
        # Store metrics or broadcast to monitoring channel
        broadcast.send("monitoring", metrics)
        
    except Exception as e:
        direct_logger.error(f"Monitoring error: {e}")
```

### Cleanup Jobs

```python
import datetime

app = Daebus(__name__)

@app.background("db_cleanup", 86400)  # Run daily (24 hours)
def database_cleanup():
    try:
        # Calculate cutoff date (e.g., 30 days ago)
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=30)
        
        # Delete old logs
        deleted_logs = delete_old_logs(cutoff_date)
        direct_logger.info(f"Deleted {deleted_logs} old log entries")
        
        # Delete old temporary files
        deleted_files = cleanup_temp_files(cutoff_date)
        direct_logger.info(f"Deleted {deleted_files} temporary files")
        
        # Optimize database
        optimize_database()
        direct_logger.info("Database optimization completed")
        
    except Exception as e:
        direct_logger.error(f"Database cleanup failed: {e}")
```

## Best Practices

1. **Keep Tasks Light**: Avoid long-running operations that could block other tasks
2. **Use Thread-Safe Logging**: Always use `direct_logger` instead of `logger`
3. **Handle Exceptions**: Catch and handle exceptions to prevent task termination
4. **Consider Resource Usage**: Be mindful of CPU and memory usage, especially for frequent tasks
5. **Add Monitoring**: Log task execution times and results to monitor performance
6. **Use Appropriate Intervals**: Balance freshness requirements with system load

## Troubleshooting

### Task Not Running

If a scheduled task doesn't seem to be running:

1. Check logs for any errors in the task function
2. Verify the interval is what you expect (in seconds)
3. Ensure the task doesn't exit prematurely due to an uncaught exception

### High CPU Usage

If scheduled tasks are causing high CPU usage:

1. Increase the interval between task runs
2. Optimize the task implementation
3. Consider using fewer background tasks

### Memory Leaks

If you notice memory growth over time:

1. Check for resources not being properly cleaned up in your tasks
2. Ensure you're not accumulating data in global variables
3. Profile your application to identify memory leaks

## Further reading

- Read [about how-to guides](https://diataxis.fr/how-to-guides/) in the Diátaxis framework
