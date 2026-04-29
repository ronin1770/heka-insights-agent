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
OTLP_HTTP_ENDPOINT_ENV_KEY = "OTLP_HTTP_ENDPOINT"
OTLP_HTTP_HEADERS_ENV_KEY = "OTLP_HTTP_HEADERS"
OTLP_RESOURCE_ATTRIBUTES_ENV_KEY = "OTLP_RESOURCE_ATTRIBUTES"
OTLP_HTTP_TIMEOUT_SECONDS_ENV_KEY = "OTLP_HTTP_TIMEOUT_SECONDS"
OTLP_HTTP_RETRY_MAX_ATTEMPTS_ENV_KEY = "OTLP_HTTP_RETRY_MAX_ATTEMPTS"
OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS_ENV_KEY = (
    "OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS"
)
OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS_ENV_KEY = "OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS"

DEFAULT_CPU_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_OTLP_HTTP_TIMEOUT_SECONDS = 10
DEFAULT_OTLP_HTTP_RETRY_MAX_ATTEMPTS = 5
DEFAULT_OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS = 1.0
DEFAULT_OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS = 5.0

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


def get_otlp_http_endpoint(*, logger: logging.Logger | None = None) -> str:
    """Return OTLP HTTP endpoint and fail fast when missing."""
    endpoint = os.getenv(OTLP_HTTP_ENDPOINT_ENV_KEY, "").strip()
    if endpoint:
        return endpoint

    message = (
        f"{OTLP_HTTP_ENDPOINT_ENV_KEY} is required when "
        f"{EXPORTER_TYPE_ENV_KEY}=otlp_http."
    )
    if logger is not None:
        logger.error(message)
    raise RuntimeError(message)


def get_otlp_http_headers(*, logger: logging.Logger | None = None) -> dict[str, str]:
    """Return optional OTLP HTTP headers mapping from environment."""
    return _parse_key_value_mapping(
        env_key=OTLP_HTTP_HEADERS_ENV_KEY,
        logger=logger,
    )


def get_otlp_resource_attributes(
    *,
    logger: logging.Logger | None = None,
) -> dict[str, str]:
    """Return optional OTLP resource attributes mapping from environment."""
    return _parse_key_value_mapping(
        env_key=OTLP_RESOURCE_ATTRIBUTES_ENV_KEY,
        logger=logger,
    )


def get_otlp_http_timeout_seconds(*, logger: logging.Logger | None = None) -> int:
    """Return OTLP HTTP timeout seconds with validated default fallback."""
    return _get_positive_int_with_default(
        env_key=OTLP_HTTP_TIMEOUT_SECONDS_ENV_KEY,
        default_value=DEFAULT_OTLP_HTTP_TIMEOUT_SECONDS,
        logger=logger,
    )


def get_otlp_http_retry_max_attempts(*, logger: logging.Logger | None = None) -> int:
    """Return OTLP HTTP maximum retry attempts with validated default fallback."""
    return _get_positive_int_with_default(
        env_key=OTLP_HTTP_RETRY_MAX_ATTEMPTS_ENV_KEY,
        default_value=DEFAULT_OTLP_HTTP_RETRY_MAX_ATTEMPTS,
        logger=logger,
    )


def get_otlp_http_retry_initial_backoff_seconds(
    *,
    logger: logging.Logger | None = None,
) -> float:
    """Return OTLP HTTP initial retry backoff seconds."""
    return _get_positive_float_with_default(
        env_key=OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS_ENV_KEY,
        default_value=DEFAULT_OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS,
        logger=logger,
    )


def get_otlp_http_retry_max_backoff_seconds(
    *,
    logger: logging.Logger | None = None,
) -> float:
    """Return OTLP HTTP maximum retry backoff seconds."""
    return _get_positive_float_with_default(
        env_key=OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS_ENV_KEY,
        default_value=DEFAULT_OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS,
        logger=logger,
    )


def _parse_key_value_mapping(
    *,
    env_key: str,
    logger: logging.Logger | None = None,
) -> dict[str, str]:
    """Parse `key=value,key2=value2` strings into a mapping."""
    raw_value = os.getenv(env_key, "").strip()
    if not raw_value:
        return {}

    parsed: dict[str, str] = {}
    for index, entry in enumerate(raw_value.split(",")):
        item = entry.strip()
        if not item:
            _raise_config_error(
                env_key=env_key,
                detail=f"contains an empty entry at position {index + 1}.",
                logger=logger,
            )
        if "=" not in item:
            _raise_config_error(
                env_key=env_key,
                detail=f"entry '{item}' is invalid; expected key=value.",
                logger=logger,
            )
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            _raise_config_error(
                env_key=env_key,
                detail=f"entry '{item}' has an empty key.",
                logger=logger,
            )
        if not value:
            _raise_config_error(
                env_key=env_key,
                detail=f"entry '{item}' has an empty value.",
                logger=logger,
            )
        parsed[key] = value
    return parsed


def _get_positive_int_with_default(
    *,
    env_key: str,
    default_value: int,
    logger: logging.Logger | None = None,
) -> int:
    raw_value = os.getenv(env_key, "").strip()
    if not raw_value:
        return default_value

    try:
        parsed = int(raw_value)
        if parsed > 0:
            return parsed
    except ValueError:
        pass

    _warn_invalid_config_with_default(
        env_key=env_key,
        raw_value=raw_value,
        default_value=default_value,
        logger=logger,
    )
    return default_value


def _get_positive_float_with_default(
    *,
    env_key: str,
    default_value: float,
    logger: logging.Logger | None = None,
) -> float:
    raw_value = os.getenv(env_key, "").strip()
    if not raw_value:
        return default_value

    try:
        parsed = float(raw_value)
        if parsed > 0:
            return parsed
    except ValueError:
        pass

    _warn_invalid_config_with_default(
        env_key=env_key,
        raw_value=raw_value,
        default_value=default_value,
        logger=logger,
    )
    return default_value


def _warn_invalid_config_with_default(
    *,
    env_key: str,
    raw_value: str,
    default_value: int | float,
    logger: logging.Logger | None,
) -> None:
    if logger is not None:
        logger.warning(
            "Invalid %s value '%s'; using default %s",
            env_key,
            raw_value,
            default_value,
        )


def _raise_config_error(
    *,
    env_key: str,
    detail: str,
    logger: logging.Logger | None,
) -> None:
    message = f"Invalid {env_key}: {detail}"
    if logger is not None:
        logger.error(message)
    raise RuntimeError(message)
