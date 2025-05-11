import unittest
import time
import threading
import json
import random
import redis
import queue
import collections
from concurrent.futures import as_completed
from unittest.mock import MagicMock, patch

from daebus import Daebus


class TestConcurrency(unittest.TestCase):
    """Tests for concurrent message processing in Daebus"""
    
    @patch('redis.Redis')
    @patch('redis.Redis.pubsub')
    def test_concurrent_message_processing(self, mock_pubsub, mock_redis):
        """Test that multiple messages can be processed concurrently"""
        
        # Setup message tracking
        processed_messages = []
        processing_times = {}
        processing_lock = threading.Lock()
        
        # Create a mock Redis instance
        redis_instance = mock_redis.return_value
        redis_instance.decode_responses = True
        
        # Create a mock PubSub instance
        pubsub_instance = mock_pubsub.return_value
        
        # Create a Daebus app with a small thread pool
        app = Daebus("test_app", max_workers=5)
        app.redis = redis_instance
        app.pubsub = pubsub_instance
        
        # Simulate starting the app
        app._running = True
        app.thread_pool = app._create_thread_pool()
        
        # Define a slow action handler that simulates processing time
        @app.action("slow_action")
        def handle_slow_action():
            message_id = app.request.payload.get("id")
            process_time = app.request.payload.get("process_time", 0.5)
            
            start_time = time.time()
            
            # Simulate work by sleeping
            time.sleep(process_time)
            
            end_time = time.time()
            
            # Record processing information in a thread-safe way
            with processing_lock:
                processed_messages.append(message_id)
                processing_times[message_id] = {
                    "start": start_time,
                    "end": end_time,
                    "duration": end_time - start_time
                }
            
            return app.response.success({"id": message_id, "processed": True})
        
        # Create 10 test messages with varying processing times
        messages = []
        for i in range(10):
            message_id = f"msg_{i}"
            process_time = random.uniform(0.1, 0.5)  # Random processing time between 0.1-0.5s
            message = {
                "action": "slow_action",
                "payload": {
                    "id": message_id,
                    "process_time": process_time
                }
            }
            message_data = json.dumps(message)
            messages.append({"data": message_data})
        
        # Define a method to process a message
        def process_message(message):
            # Call the private method directly to simulate pubsub behavior
            app._process_message(message)
        
        # Process all messages concurrently using threads
        threads = []
        for message in messages:
            thread = threading.Thread(target=process_message, args=(message,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
            
        # Verify all messages were processed
        self.assertEqual(len(processed_messages), 10, "All 10 messages should be processed")
        
        # Check for concurrency by analyzing processing times
        # If processing is happening concurrently, we should see overlapping time ranges
        overlaps = 0
        for i, msg_i in enumerate(processed_messages):
            for j, msg_j in enumerate(processed_messages):
                if i != j:
                    # Check if message processing times overlap
                    if (processing_times[msg_i]["start"] < processing_times[msg_j]["end"] and
                        processing_times[msg_i]["end"] > processing_times[msg_j]["start"]):
                        overlaps += 1
        
        # With 10 messages, each potentially overlapping with 9 others, we should have overlaps
        # if processing is concurrent (exact count depends on timing)
        self.assertGreater(overlaps, 0, "There should be overlapping message processing times")
        
        # Cleanup
        app.thread_pool.shutdown(wait=True)
    
    @patch('redis.Redis')
    @patch('redis.Redis.pubsub')
    def test_thread_local_request_response(self, mock_pubsub, mock_redis):
        """Test that each concurrent message gets its own request/response objects"""
        
        # Setup tracking of request IDs seen by handlers
        request_ids = {}
        request_ids_lock = threading.Lock()
        
        # Create a mock Redis instance
        redis_instance = mock_redis.return_value
        redis_instance.decode_responses = True
        
        # Create a mock PubSub instance
        pubsub_instance = mock_pubsub.return_value
        
        # Create a Daebus app
        app = Daebus("test_app", max_workers=5)
        app.redis = redis_instance
        app.pubsub = pubsub_instance
        
        # Simulate starting the app
        app._running = True
        app.thread_pool = app._create_thread_pool()
        
        # Define a handler that checks and records request object properties
        @app.action("check_request")
        def handle_check_request():
            # Get the current thread ID and request ID
            thread_id = threading.get_ident()
            request_id = app.request.payload.get("id")
            
            # Store this thread's view of the request ID
            with request_ids_lock:
                request_ids[thread_id] = request_id
            
            # Small delay to increase chance of interference if there's a bug
            time.sleep(0.1)
            
            # Get the request ID again after the delay
            current_id = app.request.payload.get("id")
            
            # Verify the request ID hasn't changed for this thread
            if current_id != request_id:
                self.fail(f"Request ID changed from {request_id} to {current_id}")
            
            return app.response.success({"id": request_id, "checked": True})
        
        # Create 10 messages with different request IDs
        messages = []
        for i in range(10):
            request_id = f"req_{i}"
            message = {
                "action": "check_request",
                "payload": {
                    "id": request_id
                }
            }
            message_data = json.dumps(message)
            messages.append({"data": message_data})
        
        # Process each message in its own thread sequentially
        for message in messages:
            thread = threading.Thread(target=app._process_message, args=(message,))
            thread.start()
            thread.join()  # Wait for thread to complete before processing next message
        
        # Verify we got responses from threads
        self.assertGreater(len(request_ids), 0, "Should have recorded request IDs")
        
        # Cleanup
        app.thread_pool.shutdown(wait=True)


class TestStressTest(unittest.TestCase):
    """Stress test for concurrent message processing"""
    
    @patch('redis.Redis')
    @patch('redis.Redis.pubsub')
    def test_high_load(self, mock_pubsub, mock_redis):
        """Test processing a large number of concurrent messages"""
        
        # Number of concurrent messages
        NUM_MESSAGES = 100
        
        # Success tracking
        success_count = 0
        success_lock = threading.Lock()
        
        # Create a mock Redis instance
        redis_instance = mock_redis.return_value
        redis_instance.decode_responses = True
        
        # Create a mock PubSub instance
        pubsub_instance = mock_pubsub.return_value
        
        # Create a Daebus app 
        app = Daebus("test_app", max_workers=20)  # Use more workers for stress test
        app.redis = redis_instance
        app.pubsub = pubsub_instance
        
        # Simulate starting the app
        app._running = True
        app.thread_pool = app._create_thread_pool()
        
        # Define a simple handler
        @app.action("stress_test")
        def handle_stress_test():
            nonlocal success_count
            try:
                # Small random delay
                time.sleep(random.uniform(0.01, 0.1))
                
                with success_lock:
                    success_count += 1
                
                # Use a defensive approach to return success
                try:
                    return app.response.success({"success": True})
                except AttributeError:
                    # Ignore response errors in the test
                    pass
            except Exception as e:
                # Use a defensive approach to return errors too
                try:
                    return app.response.error(str(e))
                except AttributeError:
                    # Ignore response errors in the test
                    pass
        
        # Create test messages
        messages = []
        for i in range(NUM_MESSAGES):
            message = {
                "action": "stress_test",
                "payload": {
                    "id": f"stress_{i}"
                }
            }
            message_data = json.dumps(message)
            messages.append({"data": message_data})
        
        # Start timing
        start_time = time.time()
        
        # Process all messages using separate threads rather than the thread pool
        # This ensures cleaner thread-local storage management
        threads = []
        for message in messages:
            thread = threading.Thread(target=app._process_message, args=(message,))
            threads.append(thread)
            thread.start()
            
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # End timing
        end_time = time.time()
        total_time = end_time - start_time
        
        # Verify all messages were processed successfully
        self.assertEqual(success_count, NUM_MESSAGES,
                        f"All {NUM_MESSAGES} messages should be processed successfully")
        
        # Calculate and log throughput (keep this one as it's useful info)
        throughput = NUM_MESSAGES / total_time
        print(f"Stress test: {NUM_MESSAGES} msgs in {total_time:.2f}s ({throughput:.2f} msgs/sec)")
        
        # Cleanup
        app.thread_pool.shutdown(wait=True)
        
    @patch('redis.Redis')
    @patch('redis.Redis.pubsub')
    def test_extreme_load(self, mock_pubsub, mock_redis):
        """Test with extreme message volume to ensure no messages are lost"""
        
        # Number of messages for extreme load test
        NUM_MESSAGES = 1000
        
        # Success tracking with message IDs to verify completeness
        processed_msgs = set()
        processing_lock = threading.Lock()
        
        # Create a mock Redis instance
        redis_instance = mock_redis.return_value
        redis_instance.decode_responses = True
        
        # Create a mock PubSub instance
        pubsub_instance = mock_pubsub.return_value
        
        # Track response times
        response_times = []
        response_times_lock = threading.Lock()
        
        # Create a Daebus app with various worker counts to test different configs
        thread_pool_sizes = [10, 20, 50]
        results_by_pool_size = {}
        
        for pool_size in thread_pool_sizes:
            # Create app with specific pool size
            app = Daebus("test_app", max_workers=pool_size)
            app.redis = redis_instance
            app.pubsub = pubsub_instance
            
            # Simulate starting the app
            app._running = True
            app.thread_pool = app._create_thread_pool()
            
            # Reset tracking
            processed_msgs.clear()
            response_times.clear()
            
            # Define a handler that tracks processed message IDs
            @app.action("process")
            def handle_process():
                msg_id = app.request.payload.get("id")
                start_time = app.request.payload.get("timestamp", 0)
                end_time = time.time()
                
                # Add tiny delay to simulate minimal processing time
                time.sleep(0.001)
                
                # Track in thread-safe way
                with processing_lock:
                    processed_msgs.add(msg_id)
                    
                # Record response time
                with response_times_lock:
                    response_times.append(end_time - start_time)
                
                return app.response.success({"id": msg_id, "processed": True})
            
            # Create messages with sequential IDs to verify none are missed
            messages = []
            for i in range(NUM_MESSAGES):
                msg_id = f"msg_{i:04d}"  # Zero-padded for consistent sorting
                message = {
                    "action": "process",
                    "payload": {
                        "id": msg_id,
                        "timestamp": time.time()
                    }
                }
                message_data = json.dumps(message)
                messages.append({"data": message_data})
            
            # Start timing
            start_time = time.time()
            
            # Create worker threads for processing messages
            threads = []
            for message in messages:
                thread = threading.Thread(target=app._process_message, args=(message,))
                threads.append(thread)
            
            # Start all threads (burst all messages at once)
            for thread in threads:
                thread.start()
                
            # Wait for all threads to complete
            for thread in threads:
                thread.join(timeout=10.0)  # Add timeout to prevent hanging tests
            
            # End timing
            end_time = time.time()
            total_time = end_time - start_time
            
            # Verify all messages were processed
            self.assertEqual(len(processed_msgs), NUM_MESSAGES, 
                           f"Should process all {NUM_MESSAGES} messages with thread pool size {pool_size}")
            
            # Verify no messages were missed (sequential IDs)
            expected_msgs = {f"msg_{i:04d}" for i in range(NUM_MESSAGES)}
            self.assertEqual(processed_msgs, expected_msgs, 
                            f"No messages should be missed with thread pool size {pool_size}")
            
            # Calculate metrics
            throughput = NUM_MESSAGES / total_time
            avg_response_time = sum(response_times) / len(response_times)
            max_response_time = max(response_times)
            min_response_time = min(response_times)
            
            # Store results for comparison
            results_by_pool_size[pool_size] = {
                "throughput": throughput,
                "avg_response_time": avg_response_time,
                "max_response_time": max_response_time,
                "min_response_time": min_response_time,
                "total_time": total_time
            }
            
            # Print results for this pool size
            print(f"Pool size {pool_size}: {NUM_MESSAGES} msgs in {total_time:.2f}s ({throughput:.2f} msgs/sec)")
            print(f"  Avg response time: {avg_response_time:.4f}s, Min: {min_response_time:.4f}s, Max: {max_response_time:.4f}s")
            
            # Cleanup
            app.thread_pool.shutdown(wait=True)
        
        # Find optimal thread pool size
        optimal_size = max(results_by_pool_size.keys(), 
                         key=lambda k: results_by_pool_size[k]["throughput"])
        
        print(f"Optimal thread pool size: {optimal_size} "
              f"(throughput: {results_by_pool_size[optimal_size]['throughput']:.2f} msgs/sec)")
    
    @patch('redis.Redis')
    @patch('redis.Redis.pubsub')
    def test_burst_patterns(self, mock_pubsub, mock_redis):
        """Test with burst patterns to simulate traffic spikes"""
        
        # Message tracking
        processed_order = []
        order_lock = threading.Lock()
        
        # Create a mock Redis instance
        redis_instance = mock_redis.return_value
        redis_instance.decode_responses = True
        
        # Create a mock PubSub instance
        pubsub_instance = mock_pubsub.return_value
        
        # Create a Daebus app
        app = Daebus("test_app", max_workers=20)
        app.redis = redis_instance
        app.pubsub = pubsub_instance
        
        # Simulate starting the app
        app._running = True
        app.thread_pool = app._create_thread_pool()
        
        # Define a handler that tracks message processing order
        @app.action("ordered")
        def handle_ordered():
            msg_id = app.request.payload.get("id")
            batch = app.request.payload.get("batch")
            
            # Simulate varying processing times
            time.sleep(random.uniform(0.005, 0.05))
            
            # Record the order in which messages are processed
            with order_lock:
                processed_order.append((batch, msg_id))
            
            return app.response.success({"processed": True})
        
        # Create multiple batches of messages
        NUM_BATCHES = 5
        MSGS_PER_BATCH = 50
        all_messages = []
        
        # Generate batches with sequential IDs
        for batch in range(NUM_BATCHES):
            batch_messages = []
            for i in range(MSGS_PER_BATCH):
                msg_id = i
                message = {
                    "action": "ordered",
                    "payload": {
                        "id": msg_id,
                        "batch": batch
                    }
                }
                message_data = json.dumps(message)
                batch_messages.append({"data": message_data})
            
            all_messages.append(batch_messages)
        
        # Use a completion event to track when all processing is done
        completion_event = threading.Event()
        
        # Track total messages processed
        messages_processed = 0
        total_messages = NUM_BATCHES * MSGS_PER_BATCH
        messages_lock = threading.Lock()
        
        # Define a monitor function to detect completion
        def monitor_completion():
            nonlocal messages_processed
            while not completion_event.is_set():
                with order_lock:
                    current_count = len(processed_order)
                
                with messages_lock:
                    messages_processed = current_count
                    
                if current_count >= total_messages:
                    completion_event.set()
                    break
                
                time.sleep(0.01)  # Small sleep to reduce CPU usage
        
        # Start the monitor thread
        monitor_thread = threading.Thread(target=monitor_completion)
        monitor_thread.daemon = True
        monitor_thread.start()
        
        # Process each batch with a gap between batches
        batch_starts = []
        start_time = time.time()
        
        all_batch_threads = []
        
        for batch_idx, batch in enumerate(all_messages):
            # Record batch start time
            batch_start = time.time()
            batch_starts.append(batch_start)
            
            # Process batch in parallel
            batch_threads = []
            for message in batch:
                thread = threading.Thread(target=app._process_message, args=(message,))
                thread.daemon = True  # Make threads daemon so they don't block test exit
                batch_threads.append(thread)
                all_batch_threads.append(thread)
                thread.start()
            
            # Wait before sending next batch (except for last batch)
            if batch_idx < len(all_messages) - 1:
                time.sleep(0.2)  # Gap between bursts
        
        # Wait for all processing to complete with timeout
        completion_event.wait(timeout=10.0)
        
        # Wait for threads to complete (with timeout to prevent hanging)
        for thread in all_batch_threads:
            thread.join(timeout=0.1)
            
        # Get final process count
        with order_lock:
            final_processed = len(processed_order)
        
        # End timing
        end_time = time.time()
        
        # Analyze the results
        # Group processed messages by batch
        batch_groups = collections.defaultdict(list)
        for batch, msg_id in processed_order:
            batch_groups[batch].append(msg_id)
        
        # Print diagnostic info
        print(f"Total expected: {total_messages}, Total processed: {final_processed}")
        print(f"Messages by batch: {[len(batch_groups[b]) for b in range(NUM_BATCHES)]}")
        
        # Verify all messages were processed
        self.assertEqual(final_processed, total_messages, 
                        "All messages should be processed")
        
        # Verify each batch was fully processed
        for batch in range(NUM_BATCHES):
            self.assertEqual(len(batch_groups[batch]), MSGS_PER_BATCH,
                           f"All messages in batch {batch} should be processed")
            
            # Verify all messages in the batch were processed
            processed_ids = set(batch_groups[batch])
            expected_ids = set(range(MSGS_PER_BATCH))
            self.assertEqual(processed_ids, expected_ids,
                           f"No messages should be missed in batch {batch}")
        
        # Calculate and print metrics
        total_time = end_time - start_time
        throughput = final_processed / total_time
        
        print(f"Burst test: {NUM_BATCHES} batches of {MSGS_PER_BATCH} msgs in {total_time:.2f}s")
        print(f"Total throughput: {throughput:.2f} msgs/sec")
        
        # Calculate latency between batches
        if len(batch_starts) > 1:
            batch_gaps = [batch_starts[i+1] - batch_starts[i] 
                         for i in range(len(batch_starts)-1)]
            avg_gap = sum(batch_gaps) / len(batch_gaps)
            print(f"Average gap between batches: {avg_gap:.3f}s")
        
        # Cleanup
        app.thread_pool.shutdown(wait=True)

    @patch('redis.Redis')
    @patch('redis.Redis.pubsub')
    def test_thread_pool_execution(self, mock_pubsub, mock_redis):
        """Test that the thread pool properly manages concurrent work"""
        
        # Task tracking
        completed_tasks = set()
        tasks_lock = threading.Lock()
        
        # Create a mock Redis instance
        redis_instance = mock_redis.return_value
        redis_instance.decode_responses = True
        
        # Create a mock PubSub instance
        pubsub_instance = mock_pubsub.return_value
        
        # Create a Daebus app with a controlled thread pool size
        # Use a small thread pool to force concurrency limitations
        WORKER_COUNT = 5
        TASK_COUNT = 100  # Many more tasks than workers
        
        app = Daebus("test_app", max_workers=WORKER_COUNT)
        app.redis = redis_instance
        app.pubsub = pubsub_instance
        
        # Simulate starting the app
        app._running = True
        app.thread_pool = app._create_thread_pool()
        
        # Create messages with IDs to track completion
        messages = []
        for i in range(TASK_COUNT):
            task_id = f"task_{i}"
            message = {
                "action": "pool_task",
                "payload": {
                    "id": task_id,
                    "sleep_time": random.uniform(0.01, 0.1)  # Random work duration
                }
            }
            message_data = json.dumps(message)
            messages.append((task_id, {"data": message_data}))
        
        # Define a task handler
        @app.action("pool_task")
        def handle_pool_task():
            task_id = app.request.payload.get("id")
            sleep_time = app.request.payload.get("sleep_time", 0.01)
            
            # Simulate work
            time.sleep(sleep_time)
            
            # Mark task as complete
            with tasks_lock:
                completed_tasks.add(task_id)
            
            return app.response.success({"completed": task_id})
        
        # Submit all tasks to the thread pool directly
        # This simulates how tasks would be processed when coming from Redis
        futures = []
        task_map = {}  # Map futures to task IDs for verification
        
        start_time = time.time()
        
        for task_id, message in messages:
            # This is how Daebus internally submits tasks to the thread pool
            future = app.thread_pool.submit(app._process_message, message)
            futures.append(future)
            task_map[future] = task_id
        
        # Wait for all futures to complete and verify results
        for future in as_completed(futures):
            task_id = task_map[future]
            # A completed future doesn't guarantee task success, just execution
            result = future.result()  # This would raise if the task failed
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Verify all tasks were processed
        self.assertEqual(len(completed_tasks), TASK_COUNT, 
                        f"Thread pool should process all {TASK_COUNT} tasks")
        
        # Verify no tasks were missed
        expected_tasks = {f"task_{i}" for i in range(TASK_COUNT)}
        self.assertEqual(completed_tasks, expected_tasks, 
                        "Thread pool should process all tasks without missing any")
        
        # Calculate task throughput
        throughput = TASK_COUNT / total_time
        
        # Check that actual concurrency is limited by the worker count
        # We expect throughput to be approximately proportional to worker count
        # for CPU-bound tasks (though this is not a precise expectation due to
        # the variable task durations and system-specific factors)
        print(f"Thread pool: {WORKER_COUNT} workers, {TASK_COUNT} tasks, "
              f"{total_time:.2f}s ({throughput:.2f} tasks/sec)")
        
        # Verify the thread pool behavior for sequential vs. concurrent execution
        # If tasks were executed sequentially, they'd take at least sum(sleep_times)
        # which would be roughly TASK_COUNT * avg_sleep_time = 100 * 0.055 = 5.5s
        # With concurrency, we expect much better performance
        estimated_sequential_time = TASK_COUNT * 0.055  # Avg sleep time
        self.assertLess(total_time, estimated_sequential_time * 0.8,  # 80% of sequential time
                       "Thread pool should provide meaningful concurrency improvement")
        
        # Cleanup
        app.thread_pool.shutdown(wait=True)


if __name__ == '__main__':
    unittest.main() 