---
title: Concurrency & Performance
description: Handle high volumes of messages between your services with ease.
---

Daebus provides a robust concurrency model that allows services to efficiently process multiple messages simultaneously. This document explains how Daebus implements concurrent message processing, ensuring reliable message delivery and avoiding common concurrency pitfalls.

## Overview

Daebus services need to handle multiple concurrent messages for several reasons:

1. **High throughput** - Processing messages one at a time would create a bottleneck
2. **Responsiveness** - Long-running operations shouldn't block other messages
3. **Resource utilization** - Modern servers have multiple CPU cores that can be utilized
4. **Fairness** - Messages should be processed in a timely manner regardless of other traffic

## Thread Pool Architecture

At the core of Daebus' concurrency model is a configurable thread pool:

```python
app = Daebus("my_service", max_workers=20)  # Configure with 20 worker threads
```

### How it works:

1. When a Daebus service starts, it initializes a thread pool using Python's `concurrent.futures.ThreadPoolExecutor`
2. All incoming Redis pub/sub messages are submitted to this thread pool for processing
3. The thread pool manages a limited number of worker threads to prevent resource exhaustion
4. Each message is processed in its own thread, allowing concurrent execution

### Configuration:

The `max_workers` parameter controls the number of concurrent messages that can be processed:

- **Default**: 10 worker threads
- **CPU-bound workloads**: Set to match available CPU cores (e.g., 4-8)
- **I/O-bound workloads**: Can use more workers (e.g., 20-50) since threads spend time waiting

## Thread-Local Context

One of the key challenges in concurrent programming is maintaining per-request context safely. Daebus solves this using thread-local storage:

### Request and Response Objects

Each message handler gets its own isolated `request` and `response` objects:

```python
@app.action("process_data")
def handle_process_data():
    # These objects are thread-local and specific to this message
    request_id = app.request.request_id
    data = app.request.payload
    
    # Process data...
    
    # Each response is isolated to this specific request
    return app.response.success({"result": "processed"})
```

### How Thread-Local Storage Works

Behind the scenes, Daebus:

1. Creates new `request` and `response` objects for each message
2. Stores these objects in Python's thread-local storage
3. Uses a proxy pattern to transparently access the correct objects for the current thread
4. Cleans up thread-local storage after each message is processed

This ensures that:
- Concurrent handlers cannot accidentally access each other's data
- Long-running handlers do not block other messages
- Thread safety is maintained without explicit locks in most cases

## Resilience Features

Daebus includes several features to make concurrent processing robust:

### Error Isolation

An error in one message handler won't affect other messages. Each thread has its own try/except block:

```python
try:
    # Message processing logic
except Exception as e:
    self.logger.error(f"Error processing message: {e}")
finally:
    # Clean up thread-local storage
    _clear_thread_local_storage()
```

### Thread Pool Protection

The thread pool is protected against exhaustion:

1. Task submission uses retry logic with exponential backoff
2. If the thread pool breaks, it's automatically recreated
3. Graceful shutdown waits for in-progress tasks to complete

## Performance Characteristics

Based on stress testing (see `tests/test_concurrency.py`), Daebus can handle:

- **High volume**: Thousands of messages per second on modest hardware
- **Burst patterns**: Quickly processes sudden spikes in traffic
- **Consistent latency**: Even under load, message processing remains responsive

### Performance Testing Results

The test suite includes extreme load tests that demonstrate:

- No message loss even under high concurrent load (1000+ simultaneous messages)
- Linear scaling with increased thread pool size for I/O-bound workloads
- Optimal configuration depends on your workload type (CPU vs I/O bound)

## Thread Safety Considerations

While Daebus handles most concurrency concerns automatically, you should be aware of:

### Thread-Safe Resources

When accessing shared resources from action handlers, use appropriate synchronization:

```python
# Example: Thread-safe counter
counter_lock = threading.Lock()
counter = 0

@app.action("increment")
def handle_increment():
    global counter
    with counter_lock:
        counter += 1
    return app.response.success({"new_value": counter})
```

### Redis Operations

Redis operations from Daebus are automatically thread-safe, as the Redis client handles its own connection pooling.

### Long-Running Operations

For very long-running operations, consider using background threads:

```python
@app.thread("data_processor")
def process_data_continuously():
    while app.is_running():
        # Process data in background
        # This won't block message handling
        time.sleep(1)
```

## Concurrency vs. Parallelism

It's important to understand the difference in the context of Daebus:

- **Concurrency**: Daebus provides concurrency through threading, allowing multiple messages to make progress simultaneously.
- **Parallelism**: Python's Global Interpreter Lock (GIL) may limit true parallelism for CPU-bound tasks. For heavy computational workloads, consider using separate processes or Python implementations without a GIL.

## Example: Concurrent Message Processing

Here's a complete example demonstrating concurrent message processing:

```python
from daebus import Daebus
import time
import threading

app = Daebus("concurrent_service", max_workers=20)

# Track processed messages with thread safety
processed = []
process_lock = threading.Lock()

@app.action("process")
def handle_process():
    # Get message details
    message_id = app.request.payload.get("id")
    process_time = app.request.payload.get("process_time", 0.5)
    
    # Simulate work with a delay
    time.sleep(process_time)
    
    # Update shared state in thread-safe way
    with process_lock:
        processed.append(message_id)
    
    # Respond with success
    return app.response.success({
        "id": message_id,
        "processed_at": time.time()
    })

if __name__ == "__main__":
    app.run("concurrent_service")
```

## Best Practices

1. **Configure thread pool size** based on your workload characteristics
2. **Use thread-safe operations** when accessing shared resources
3. **Keep handlers efficient** to improve overall throughput
4. **Monitor performance** in production to adjust thread pool size
5. **Use background threads** for long-running operations instead of blocking handlers 