# Daebus Tests

This directory contains tests for the Daebus package.

## Setup

Install the test dependencies:

```bash
pip install -r requirements.txt
```

## Running Tests

Run all tests:

```bash
pytest
```

Run tests for specific modules:

```bash
pytest test_websocket.py
```

## Test Types

### Unit Tests

- `test_websocket.py` - Unit tests for the WebSocket functionality

### End-to-End Tests

- `test_websocket_e2e.py` - End-to-end tests that actually start a server and connect to it

## Writing Tests

When writing tests for WebSocket functionality:

1. Use `pytest.mark.asyncio` for tests that involve async operations
2. Mock the Redis connection and scheduler to avoid external dependencies
3. For WebSocket handlers, remember to setup the proper context
4. Clean up contexts and connections properly after tests 