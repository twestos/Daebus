# Daebus Tests

This directory contains pytest tests for the Daebus package.

## Running Tests

To run the tests, make sure you have installed the test dependencies:

```bash
# Install the package with development dependencies
pip install -e ".[dev]"
```

Then, run pytest:

```bash
# Run all tests with coverage report
pytest

# Run specific test file
pytest tests/test_daemon.py

# Run specific test
pytest tests/test_daemon.py::test_daebus_initialization
```

## Test Structure

The tests are organized by module:

- `test_daemon.py`: Tests for the core Daebus class
- `test_context.py`: Tests for the context module
- `test_http.py`: Tests for the HTTP module
- `test_pubsub.py`: Tests for the PubSub request/response

## Mocking Strategy

The tests use extensive mocking to avoid relying on external services like Redis. The approach is:

1. In `conftest.py`, the `daebus_app` fixture sets up a properly mocked Daebus instance for most tests
2. Individual tests may add their own mocks for specific functionality
3. Redis-related functionality is mocked at the source, ensuring no actual Redis connections are attempted
4. The `test_run_initialization` test is currently skipped as it requires complex mocking of the Redis client module

### Known Limitations

Some tests are currently skipped or don't achieve 100% coverage because:

1. The `redis_client` module uses a global instance pattern that is challenging to mock consistently
2. The run loop in Daebus is an infinite loop with signal handling, making it difficult to test fully
3. Some HTTP functionality relies on threading that can be complex to mock completely

## Adding New Tests

When adding new tests, follow these guidelines:

1. Create test files named `test_*.py`
2. Use pytest fixtures from `conftest.py` when possible
3. Mock external dependencies like Redis
4. Keep tests isolated and focused on a single functionality
5. Use descriptive function names with the `test_` prefix 