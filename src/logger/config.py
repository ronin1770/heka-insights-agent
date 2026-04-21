"""Logger configuration for file-only logging."""

from __future__ import annotations

import logging
import sys

from config import get_log_location

LOG_FORMAT = "%(filename)s - %(asctime)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d-%H-%M-%S"
RESET = "\x1b[0m"
LEVEL_COLORS = {
    logging.DEBUG: "\x1b[36m",      # cyan
    logging.INFO: "\x1b[32m",       # green
    logging.WARNING: "\x1b[33m",    # yellow
    logging.ERROR: "\x1b[31m",      # red
    logging.CRITICAL: "\x1b[1;37;41m",  # bold white on red background
}


class ColorFormatter(logging.Formatter):
    """Formatter that adds ANSI colors by log level."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        color = LEVEL_COLORS.get(record.levelno)
        if not color:
            return message
        return f"{color}{message}{RESET}"


def get_logger(name: str = "heka_insights_agent") -> logging.Logger:
    """Create and return a configured file logger."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    log_path = get_log_location()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Create file on startup and verify write permission.
        with log_path.open("a", encoding="utf-8"):
            pass
    except OSError as exc:
        raise RuntimeError(f"Unable to initialize log file at '{log_path}': {exc}") from exc

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(ColorFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger
