import pytest
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
    """Create a Daebus app instance for testing"""
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