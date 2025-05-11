import pytest
import os
from unittest.mock import MagicMock, patch
from redis import Redis
from daebus import Daebus
from daebus.modules.redis_client import get_redis_client


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing"""
    redis_mock = MagicMock(spec=Redis)
    # Mock PubSub
    pubsub_mock = MagicMock()
    redis_mock.pubsub.return_value = pubsub_mock
    return redis_mock


@pytest.fixture
def mock_logger():
    """Mock logger for testing"""
    logger_mock = MagicMock()
    return logger_mock


@pytest.fixture(scope="function")
def redis_for_tests():
    """
    Provide a Redis client for tests.
    This will either use a real Redis connection in CI or a mock in local testing.
    """
    use_actual_redis = os.environ.get('CI_TESTING') == 'true'
    
    if use_actual_redis:
        # For CI with actual Redis service
        redis_host = os.environ.get('REDIS_HOST', 'localhost')
        redis_port = int(os.environ.get('REDIS_PORT', '6379'))
        
        # Create a real Redis client with the CI settings
        redis_client = Redis(host=redis_host, port=redis_port, decode_responses=True)
        # Test connection
        try:
            redis_client.ping()
            yield redis_client
            # Clean up after test
            redis_client.flushall()
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")
    else:
        # For local testing with a mock
        mock_redis = MagicMock(spec=Redis)
        yield mock_redis


@pytest.fixture
def daebus_app(redis_for_tests):
    """
    Create a Daebus app instance for testing.
    """
    # Need to patch both the redis_client module and Broadcast
    with patch('daebus.modules.redis_client.redis_client', redis_for_tests):
        with patch('daebus.modules.redis_client.get_redis_client', return_value=redis_for_tests):
            # Also patch the Broadcast class to use our redis client directly
            original_broadcast_init = patch('daebus.modules.broadcast.Broadcast.__init__', 
                                          return_value=None)
            
            with original_broadcast_init:
                with patch('daebus.modules.daemon._default_logger') as mock_logger:
                    # Create the app
                    app = Daebus("test_app")
                    
                    # Explicitly set the redis client on broadcast
                    app.broadcast._redis = redis_for_tests
                    
                    # Set up logger mock
                    mock_logger.getChild.return_value = MagicMock()
                    
                    yield app 