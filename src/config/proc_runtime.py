"""Runtime configuration for targeted procfs telemetry collection."""

from __future__ import annotations

import logging
import os

PROC_POLL_INTERVAL_ENV_KEY = "PROC_POLL_INTERVAL_SECONDS"
DEFAULT_PROC_POLL_INTERVAL_SECONDS = 30.0


def get_proc_poll_interval_seconds(
    *,
    logger: logging.Logger | None = None,
) -> float:
    """Return the validated procfs polling interval in seconds."""
    raw_value = os.getenv(PROC_POLL_INTERVAL_ENV_KEY, "").strip()
    if not raw_value:
        return DEFAULT_PROC_POLL_INTERVAL_SECONDS

    try:
        interval = float(raw_value)
        if interval > 0:
            return interval
    except ValueError:
        pass

    if logger is not None:
        logger.warning(
            "Invalid %s value '%s'; using default %.1f",
            PROC_POLL_INTERVAL_ENV_KEY,
            raw_value,
            DEFAULT_PROC_POLL_INTERVAL_SECONDS,
        )
    return DEFAULT_PROC_POLL_INTERVAL_SECONDS
