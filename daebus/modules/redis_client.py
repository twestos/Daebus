from redis import Redis
from typing import Optional

# Use a function to create the Redis client only when needed
_redis_instance: Optional[Redis] = None


def get_redis_client() -> Redis:
    """
    Get the global Redis client instance.

    Returns:
        Redis: The Redis client instance
    """
    global _redis_instance
    if _redis_instance is None:
        _redis_instance = Redis(decode_responses=True)
    return _redis_instance


# For backwards compatibility, maintain the redis_client name
redis_client = get_redis_client()
