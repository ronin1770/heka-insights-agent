"""Logger configuration for file-only logging."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

LOG_ENV_KEY = "LOG_LOCATION"
LOG_FORMAT = "%(filename)s - %(asctime)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d-%H-%M-%S"
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
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


def _read_log_location() -> Path:
    """Return log path from env var or repo-root .env, fail if missing."""
    env_value = os.getenv(LOG_ENV_KEY)
    if env_value:
        env_path = Path(env_value).expanduser()
        return env_path if env_path.is_absolute() else (REPO_ROOT / env_path)

    if not ENV_FILE.exists():
        raise RuntimeError("LOG_LOCATION is not set and .env file was not found.")

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(f"{LOG_ENV_KEY}="):
            continue
        value = line.split("=", 1)[1].strip().strip('"').strip("'")
        if not value:
            break
        env_path = Path(value).expanduser()
        return env_path if env_path.is_absolute() else (REPO_ROOT / env_path)

    raise RuntimeError("LOG_LOCATION is missing or empty in environment and .env.")


def get_logger(name: str = "heka_insights_agent") -> logging.Logger:
    """Create and return a configured file logger."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    log_path = _read_log_location()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Create file on startup and verify write permission.
        with log_path.open("a", encoding="utf-8"):
            pass
    except OSError as exc:
        raise RuntimeError(f"Unable to initialize log file at '{log_path}': {exc}") from exc

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColorFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger
