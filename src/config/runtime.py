"""Unified runtime configuration loading and accessors."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal, cast

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"

LOG_LOCATION_ENV_KEY = "LOG_LOCATION"
CPU_POLL_INTERVAL_ENV_KEY = "CPU_POLL_INTERVAL_SECONDS"
EXPORTER_TYPE_ENV_KEY = "EXPORTER_TYPE"

DEFAULT_CPU_POLL_INTERVAL_SECONDS = 5.0

ExporterType = Literal[
    "console",
    "otlp_http",
    "datadog_native",
    "newrelic_otlp",
]
DEFAULT_EXPORTER_TYPE: ExporterType = "console"

SUPPORTED_EXPORTER_TYPES: tuple[ExporterType, ...] = (
    "console",
    "otlp_http",
    "datadog_native",
    "newrelic_otlp",
)

load_dotenv(ENV_FILE, override=False)


def get_log_location() -> Path:
    """Return the resolved log file path from unified configuration."""
    raw_value = os.getenv(LOG_LOCATION_ENV_KEY, "").strip()
    if not raw_value:
        raise RuntimeError(f"{LOG_LOCATION_ENV_KEY} is missing or empty.")

    env_path = Path(raw_value).expanduser()
    return env_path if env_path.is_absolute() else (REPO_ROOT / env_path)


def get_cpu_poll_interval_seconds(
    *,
    logger: logging.Logger | None = None,
) -> float:
    """Return validated CPU polling interval in seconds."""
    raw_value = os.getenv(CPU_POLL_INTERVAL_ENV_KEY, "").strip()
    if not raw_value:
        return DEFAULT_CPU_POLL_INTERVAL_SECONDS

    try:
        interval = float(raw_value)
        if interval > 0:
            return interval
    except ValueError:
        pass

    if logger is not None:
        logger.warning(
            "Invalid %s value '%s'; using default %.1f",
            CPU_POLL_INTERVAL_ENV_KEY,
            raw_value,
            DEFAULT_CPU_POLL_INTERVAL_SECONDS,
        )
    return DEFAULT_CPU_POLL_INTERVAL_SECONDS


def get_exporter_type(*, logger: logging.Logger | None = None) -> ExporterType:
    """Return normalized exporter selector and fail fast on invalid values."""
    raw_value = os.getenv(EXPORTER_TYPE_ENV_KEY, "").strip().lower()
    if not raw_value:
        return DEFAULT_EXPORTER_TYPE

    if raw_value in SUPPORTED_EXPORTER_TYPES:
        return cast(ExporterType, raw_value)

    supported_values = ", ".join(SUPPORTED_EXPORTER_TYPES)
    message = (
        f"Invalid {EXPORTER_TYPE_ENV_KEY} value '{raw_value}'. "
        f"Supported values: {supported_values}."
    )
    if logger is not None:
        logger.error(message)
    raise RuntimeError(message)
