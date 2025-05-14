---
title: Installation
description: How to install and set up Daebus in your environment
---
This guide will help you install and set up Daebus in your Python environment.

## Prerequisites

Before installing Daebus, make sure you have:

- Python 3.9 or higher
- pip (Python package installer)
- A running Redis server (required for pub/sub messaging)

## Installing with pip

The easiest way to install Daebus is using pip:

```bash
pip install daebus
```

This will install Daebus and its required dependencies.

## Installation from Source

If you want to install the latest development version or make modifications, you can install from source:

```bash
# Clone the repository
git clone https://github.com/twestos/daebus.git
cd daebus

# Install in development mode
pip install -e .
```

## Dependencies

Daebus has the following dependencies that will be automatically installed:

- **redis** (>=6.0.0): For Redis pub/sub messaging between services
- **apscheduler** (>=3.11.0): For scheduling background tasks
- **websockets** (>=15.0.1): For WebSocket support

## Optional Dependencies

For development and testing, you can install additional dependencies:

```bash
# Install with development dependencies
pip install daebus[dev]

# Or if installing from source
pip install -e ".[dev]"
```

This includes:
- pytest and pytest-related packages for testing
- flake8 for linting
- codecov for code coverage reporting

## Setting up Redis

Daebus requires a Redis server for pub/sub messaging functionality. Here's how to set it up:

### On Linux

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install redis-server

# Start Redis service
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

### On macOS

Using Homebrew:

```bash
brew install redis
brew services start redis
```

### On Windows

Download and install Redis for Windows from the [Microsoft Store](https://apps.microsoft.com/store/detail/redis/XPFKGVNGVRHR) or [Redis for Windows by tporadowski](https://github.com/tporadowski/redis/releases).

### Docker

You can also run Redis in a Docker container:

```bash
docker run -d -p 6379:6379 --name redis redis:latest
```

### Verifying Redis Installation

To verify that Redis is running correctly:

```bash
redis-cli ping
```

This should return `PONG` if Redis is running properly.

## Configuration

By default, Daebus will connect to Redis at `localhost:6379`. If your Redis server is running on a different host or port, you'll need to specify this when initializing your application:

```python
from daebus import Daebus

app = Daebus(__name__)

# Specify Redis connection details when running
if __name__ == "__main__":
    app.run(
        service="my_service",
        redis_host="custom.redis.host",
        redis_port=6380
    )
```

## Verifying Installation

To verify that Daebus is installed correctly, you can run the following in a Python interpreter:

```python
import daebus
print(daebus.__version__)
```

This should display the installed version of Daebus.

## Next Steps

After installation, check out these resources to start building with Daebus:

- [Overview](/docs/overview) - Learn about Daebus concepts and architecture
- [PubSub Messaging](/docs/guides/messaging) - Learn how to use the Redis pub/sub messaging
- [HTTP Endpoints](/docs/guides/http) - Add HTTP APIs to your Daebus services
- [WebSockets](/docs/guides/websockets) - Add real-time WebSocket capabilities

## Troubleshooting

### Could not find a version that satisfies the requirement

If you see an error like:

```
ERROR: Could not find a version that satisfies the requirement daebus
ERROR: No matching distribution found for daebus
```

Make sure you're using Python 3.9 or higher and that your pip is up to date:

```bash
python --version
pip --version
pip install --upgrade pip
```

### Connection errors with Redis

If your application fails to connect to Redis:

1. Check that Redis is running: `redis-cli ping`
2. Verify the host and port in your application
3. Check for firewall rules that might be blocking the connection
4. Ensure Redis is not configured to only accept local connections if you're connecting remotely

### Other Issues

If you encounter other installation issues:

1. Check that all dependencies are properly installed
2. Try installing in a fresh virtual environment
3. Check the project's GitHub page for any reported issues
4. Consult the community for help
