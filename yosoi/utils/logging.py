"""Logging configuration for Yosoi."""

import logging
from datetime import datetime
from pathlib import Path

from yosoi.utils.files import get_logs_path


def setup_local_logging(level: str = 'DEBUG') -> Path:
    """Set up local file-based logging.

    Creates a log file in .yosoi/logs/ and configures the root logger
    to write to it. Consoles output is kept minimal.

    Args:
        level: Logging level (e.g., 'DEBUG', 'INFO'). Defaults to 'DEBUG'.

    Returns:
        Path: The path to the created log file.

    """
    logs_dir = get_logs_path()
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = logs_dir / f'run_{timestamp}.log'

    # Map string level to numeric logging level
    if level.upper() == 'ALL':
        numeric_level = logging.NOTSET
    else:
        numeric_level = getattr(logging, level.upper(), logging.DEBUG)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # File handler for detailed logs
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(numeric_level)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # We don't add a console handler here because the CLI handles console output
    # via rich. If we wanted to redirect all logs to console via rich, we would
    # add a RichHandler here, but the user requested minimal console output.

    return log_file
