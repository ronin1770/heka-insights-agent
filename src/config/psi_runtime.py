"""Runtime configuration for Linux PSI telemetry collection."""

from __future__ import annotations

import logging
import math
import os

PSI_POLL_INTERVAL_ENV_KEY = "PSI_POLL_INTERVAL_SECONDS"
DEFAULT_PSI_POLL_INTERVAL_SECONDS = 30.0


def get_psi_poll_interval_seconds(
    *,
    logger: logging.Logger | None = None,
) -> float:
    """Return the validated PSI polling interval in seconds."""
    raw_value = os.getenv(PSI_POLL_INTERVAL_ENV_KEY, "").strip()
    if not raw_value:
        return DEFAULT_PSI_POLL_INTERVAL_SECONDS

    try:
        interval = float(raw_value)
        if math.isfinite(interval) and interval > 0:
            return interval
    except ValueError:
        pass

    if logger is not None:
        logger.warning(
            "Invalid %s value '%s'; using default %.1f",
            PSI_POLL_INTERVAL_ENV_KEY,
            raw_value,
            DEFAULT_PSI_POLL_INTERVAL_SECONDS,
        )
    return DEFAULT_PSI_POLL_INTERVAL_SECONDS
