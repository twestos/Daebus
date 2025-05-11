import logging
from typing import Optional

# default logger config
logging.basicConfig(
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    level=logging.INFO
)

# Create a package-wide logger
logger = logging.getLogger('daebus')


def set_log_level(level: int) -> None:
    """
    Set the log level for the Daebus logger.

    Args:
        level: Log level (e.g., logging.DEBUG, logging.INFO)
    """
    logger.setLevel(level)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger for a specific component.

    Args:
        name: Name of the component (will be prefixed with 'daebus.')

    Returns:
        A configured logger instance
    """
    if name:
        return logger.getChild(name)
    return logger
