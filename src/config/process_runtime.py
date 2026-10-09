"""Runtime configuration for process telemetry collection."""

from __future__ import annotations

import logging
import os

PROCESS_POLL_INTERVAL_ENV_KEY = "PROCESS_POLL_INTERVAL_SECONDS"
DEFAULT_PROCESS_POLL_INTERVAL_SECONDS = 30.0


def get_process_poll_interval_seconds(
    *,
    logger: logging.Logger | None = None,
) -> float:
    """Return the validated process polling interval in seconds."""
    raw_value = os.getenv(PROCESS_POLL_INTERVAL_ENV_KEY, "").strip()
    if not raw_value:
        return DEFAULT_PROCESS_POLL_INTERVAL_SECONDS

    try:
        interval = float(raw_value)
        if interval > 0:
            return interval
    except ValueError:
        pass

    if logger is not None:
        logger.warning(
            "Invalid %s value '%s'; using default %.1f",
            PROCESS_POLL_INTERVAL_ENV_KEY,
            raw_value,
            DEFAULT_PROCESS_POLL_INTERVAL_SECONDS,
        )
    return DEFAULT_PROCESS_POLL_INTERVAL_SECONDS
