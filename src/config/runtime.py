"""Unified runtime configuration loading and accessors."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlparse

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
NEWRELIC_OTLP_ENDPOINT_ENV_KEY = "NEWRELIC_OTLP_ENDPOINT"
NEWRELIC_API_KEY_ENV_KEY = "NEWRELIC_API_KEY"
NEWRELIC_SERVICE_NAME_ENV_KEY = "NEWRELIC_SERVICE_NAME"
NEWRELIC_ENVIRONMENT_ENV_KEY = "NEWRELIC_ENVIRONMENT"
NEWRELIC_HOST_NAME_ENV_KEY = "NEWRELIC_HOST_NAME"
DATADOG_ENABLED_ENV_KEY = "DATADOG_ENABLED"
DATADOG_SITE_ENV_KEY = "DATADOG_SITE"
DATADOG_API_KEY_ENV_KEY = "DATADOG_API_KEY"
DATADOG_HOSTNAME_ENV_KEY = "DATADOG_HOSTNAME"
DATADOG_TAGS_ENV_KEY = "DATADOG_TAGS"
DATADOG_METRIC_PREFIX_ENV_KEY = "DATADOG_METRIC_PREFIX"

DEFAULT_CPU_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_OTLP_HTTP_TIMEOUT_SECONDS = 10
DEFAULT_OTLP_HTTP_RETRY_MAX_ATTEMPTS = 5
DEFAULT_OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS = 1.0
DEFAULT_OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS = 5.0

ExporterType = Literal[
    "console",
    "otlp_http",
    "datadog_otlp",
    "datadog_native",
    "newrelic_otlp",
]
DEFAULT_EXPORTER_TYPE: ExporterType = "console"

SUPPORTED_EXPORTER_TYPES: tuple[ExporterType, ...] = (
    "console",
    "otlp_http",
    "datadog_otlp",
    "datadog_native",
    "newrelic_otlp",
)

_DATADOG_SITE_TO_DOMAIN: dict[str, str] = {
    "datadoghq.com": "datadoghq.com",
    "datadoghq.eu": "datadoghq.eu",
    "us3": "us3.datadoghq.com",
    "us5": "us5.datadoghq.com",
    "ap1": "ap1.datadoghq.com",
    "ap2": "ap2.datadoghq.com",
    "ddog-gov.com": "ddog-gov.com",
}

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
        _validate_http_endpoint_value(
            endpoint=endpoint,
            env_key=OTLP_HTTP_ENDPOINT_ENV_KEY,
            logger=logger,
        )
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


def get_newrelic_otlp_preset(
    *,
    logger: logging.Logger | None = None,
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Resolve New Relic preset into OTLP endpoint, headers, and resource attributes."""
    endpoint = _get_required_newrelic_value(
        env_key=NEWRELIC_OTLP_ENDPOINT_ENV_KEY,
        logger=logger,
    )
    _validate_http_endpoint_value(
        endpoint=endpoint,
        env_key=NEWRELIC_OTLP_ENDPOINT_ENV_KEY,
        logger=logger,
    )
    api_key = _get_required_newrelic_value(
        env_key=NEWRELIC_API_KEY_ENV_KEY,
        logger=logger,
    )
    service_name = _get_required_newrelic_value(
        env_key=NEWRELIC_SERVICE_NAME_ENV_KEY,
        logger=logger,
    )

    headers = {
        key.lower(): value
        for key, value in get_otlp_http_headers(logger=logger).items()
    }
    headers["api-key"] = api_key

    resource_attributes = get_otlp_resource_attributes(logger=logger)
    resource_attributes["service.name"] = service_name

    environment = _get_optional_env_value(NEWRELIC_ENVIRONMENT_ENV_KEY)
    if environment is not None:
        resource_attributes["deployment.environment"] = environment

    host_name = _get_optional_env_value(NEWRELIC_HOST_NAME_ENV_KEY)
    if host_name is not None:
        resource_attributes["host.name"] = host_name

    return endpoint, headers, resource_attributes


def get_datadog_enabled(*, logger: logging.Logger | None = None) -> bool:
    """Return optional Datadog enablement toggle from environment."""
    raw_value = os.getenv(DATADOG_ENABLED_ENV_KEY, "").strip()
    if not raw_value:
        return False

    normalized = raw_value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    _raise_config_error(
        env_key=DATADOG_ENABLED_ENV_KEY,
        detail=(
            f"value '{raw_value}' is invalid; expected one of: "
            "1,true,yes,on,0,false,no,off."
        ),
        logger=logger,
    )


def get_datadog_otlp_preset(
    *,
    logger: logging.Logger | None = None,
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Resolve Datadog OTLP preset into OTLP endpoint, headers, and resource attrs."""
    domain = _get_datadog_site_domain(logger=logger)
    api_key = _get_required_datadog_value(
        env_key=DATADOG_API_KEY_ENV_KEY,
        logger=logger,
    )

    endpoint = f"https://otlp.{domain}/v1/metrics"
    headers = {
        key.lower(): value
        for key, value in get_otlp_http_headers(logger=logger).items()
    }
    headers["dd-api-key"] = api_key

    resource_attributes = get_otlp_resource_attributes(logger=logger)
    host_name = _get_optional_env_value(DATADOG_HOSTNAME_ENV_KEY)
    if host_name is not None:
        resource_attributes["host.name"] = host_name

    for key, value in _get_datadog_tags_as_resource_attributes(logger=logger).items():
        resource_attributes[key] = value

    return endpoint, headers, resource_attributes


def get_datadog_native_config(
    *,
    logger: logging.Logger | None = None,
) -> tuple[str, str, str | None, list[str], str | None]:
    """Resolve Datadog native exporter settings."""
    domain = _get_datadog_site_domain(logger=logger)
    endpoint = f"https://api.{domain}/api/v1/series"
    api_key = _get_required_datadog_value(
        env_key=DATADOG_API_KEY_ENV_KEY,
        logger=logger,
    )
    host_name = _get_optional_env_value(DATADOG_HOSTNAME_ENV_KEY)
    default_tags = _parse_datadog_tags(logger=logger)
    metric_prefix = _get_optional_env_value(DATADOG_METRIC_PREFIX_ENV_KEY)
    if metric_prefix is not None:
        metric_prefix = metric_prefix.strip(".")
        if not metric_prefix:
            _raise_config_error(
                env_key=DATADOG_METRIC_PREFIX_ENV_KEY,
                detail="value is empty after trimming dots.",
                logger=logger,
            )
    return endpoint, api_key, host_name, default_tags, metric_prefix


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


def _parse_datadog_tags(*, logger: logging.Logger | None = None) -> list[str]:
    """Parse DATADOG_TAGS as a comma-delimited tag list."""
    raw_value = os.getenv(DATADOG_TAGS_ENV_KEY, "").strip()
    if not raw_value:
        return []

    tags: list[str] = []
    for index, entry in enumerate(raw_value.split(",")):
        tag = entry.strip()
        if not tag:
            _raise_config_error(
                env_key=DATADOG_TAGS_ENV_KEY,
                detail=f"contains an empty entry at position {index + 1}.",
                logger=logger,
            )
        tags.append(tag)
    return tags


def _get_datadog_tags_as_resource_attributes(
    *,
    logger: logging.Logger | None,
) -> dict[str, str]:
    """Map Datadog tags to OTLP resource attributes for preset mode."""
    attributes: dict[str, str] = {}
    for tag in _parse_datadog_tags(logger=logger):
        if ":" in tag:
            key, value = tag.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key or not value:
                _raise_config_error(
                    env_key=DATADOG_TAGS_ENV_KEY,
                    detail=f"tag '{tag}' is invalid; expected key:value.",
                    logger=logger,
                )
            attributes[key] = value
            continue
        attributes[tag] = "true"
    return attributes


def _get_required_newrelic_value(
    *,
    env_key: str,
    logger: logging.Logger | None,
) -> str:
    value = _get_optional_env_value(env_key)
    if value is not None:
        return value

    message = (
        f"{env_key} is required when {EXPORTER_TYPE_ENV_KEY}=newrelic_otlp."
    )
    if logger is not None:
        logger.error(message)
    raise RuntimeError(message)


def _get_required_datadog_value(
    *,
    env_key: str,
    logger: logging.Logger | None,
) -> str:
    value = _get_optional_env_value(env_key)
    if value is not None:
        return value

    message = (
        f"{env_key} is required when {EXPORTER_TYPE_ENV_KEY} is "
        "datadog_otlp or datadog_native."
    )
    if logger is not None:
        logger.error(message)
    raise RuntimeError(message)


def _get_datadog_site_domain(*, logger: logging.Logger | None) -> str:
    site = _get_required_datadog_value(
        env_key=DATADOG_SITE_ENV_KEY,
        logger=logger,
    ).lower()
    domain = _DATADOG_SITE_TO_DOMAIN.get(site)
    if domain is not None:
        return domain

    supported_sites = ", ".join(sorted(_DATADOG_SITE_TO_DOMAIN))
    _raise_config_error(
        env_key=DATADOG_SITE_ENV_KEY,
        detail=(
            f"value '{site}' is unsupported; "
            f"supported values: {supported_sites}."
        ),
        logger=logger,
    )


def _get_optional_env_value(env_key: str) -> str | None:
    raw_value = os.getenv(env_key, "").strip()
    if not raw_value:
        return None
    return raw_value


def _validate_http_endpoint_value(
    *,
    endpoint: str,
    env_key: str,
    logger: logging.Logger | None,
) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return

    _raise_config_error(
        env_key=env_key,
        detail=(
            f"value '{endpoint}' is invalid; "
            "expected absolute http/https URL."
        ),
        logger=logger,
    )


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
