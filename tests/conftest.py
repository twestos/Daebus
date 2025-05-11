import pytest
import os
from unittest.mock import MagicMock, patch
from redis import Redis
from daebus import Daebus


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


@pytest.fixture
def daebus_app():
    """
    Create a Daebus app instance for testing.
    
    If CI_TESTING environment variable is set, it will use actual Redis,
    otherwise it mocks the Redis client for local testing.
    """
    # Check if we're running in CI with actual Redis
    use_actual_redis = os.environ.get('CI_TESTING') == 'true'
    
    if use_actual_redis:
        # For CI with actual Redis service
        redis_host = os.environ.get('REDIS_HOST', 'localhost')
        redis_port = int(os.environ.get('REDIS_PORT', '6379'))
        
        # Override the redis_client to use the CI Redis
        with patch('daebus.modules.redis_client.get_redis_client') as mock_get_redis:
            # Create a real Redis client with the CI settings
            redis_client = Redis(host=redis_host, port=redis_port, decode_responses=True)
            mock_get_redis.return_value = redis_client
            
            # Create the app
            app = Daebus("test_app")
            yield app
            
            # Clean up
            redis_client.flushall()
    else:
        # For local testing with mocks
        # Mock redis_client module first
        with patch('daebus.modules.redis_client.redis_client') as mock_redis:
            # Then mock Broadcast to use our redis client
            with patch('daebus.modules.daemon.Broadcast') as mock_broadcast_class:
                # Create mock broadcast instance
                mock_broadcast = MagicMock()
                mock_broadcast_class.return_value = mock_broadcast
                
                # And finally create the Daebus instance
                with patch('daebus.modules.daemon._default_logger') as mock_logger:
                    app = Daebus("test_app")
                    mock_logger.getChild.return_value = MagicMock()
                    yield app 