"""Interactive setup flow for packaged installs."""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from dotenv import dotenv_values

from config import (
    CPU_POLL_INTERVAL_ENV_KEY,
    DATADOG_API_KEY_ENV_KEY,
    DATADOG_HOSTNAME_ENV_KEY,
    DATADOG_METRIC_PREFIX_ENV_KEY,
    DATADOG_SITE_ENV_KEY,
    DATADOG_TAGS_ENV_KEY,
    DEFAULT_CPU_POLL_INTERVAL_SECONDS,
    DEFAULT_EXPORTER_TYPE,
    DEFAULT_LOG_LOCATION,
    DEFAULT_OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS,
    DEFAULT_OTLP_HTTP_RETRY_MAX_ATTEMPTS,
    DEFAULT_OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS,
    DEFAULT_OTLP_HTTP_TIMEOUT_SECONDS,
    HEKA_AGENT_ID_ENV_KEY,
    HEKA_API_KEY_ENV_KEY,
    HEKA_INTELLIGENCE_ENABLED_ENV_KEY,
    ENV_DIRECTORY,
    ENV_FILE,
    EXPORTER_TYPE_ENV_KEY,
    INSTALLED_BINARY_PATH,
    LOG_LOCATION_ENV_KEY,
    NEWRELIC_API_KEY_ENV_KEY,
    NEWRELIC_ENVIRONMENT_ENV_KEY,
    NEWRELIC_HOST_NAME_ENV_KEY,
    NEWRELIC_OTLP_ENDPOINT_ENV_KEY,
    NEWRELIC_SERVICE_NAME_ENV_KEY,
    OTLP_HTTP_ENDPOINT_ENV_KEY,
    OTLP_HTTP_HEADERS_ENV_KEY,
    OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS_ENV_KEY,
    OTLP_HTTP_RETRY_MAX_ATTEMPTS_ENV_KEY,
    OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS_ENV_KEY,
    OTLP_HTTP_TIMEOUT_SECONDS_ENV_KEY,
    OTLP_RESOURCE_ATTRIBUTES_ENV_KEY,
    SERVICE_GROUP,
    SERVICE_NAME,
    SERVICE_USER,
    SUPPORTED_EXPORTER_TYPES,
)

_SETUP_CANCEL_WORDS = {"cancel", "quit", "exit"}
_NEWRELIC_DEFAULT_ENDPOINT = "https://otlp.nr-data.net/v1/metrics"
_BOOLEAN_TRUE_VALUE = "true"
_BOOLEAN_FALSE_VALUE = "false"


class SetupCancelled(RuntimeError):
    """Raised when the user aborts the setup wizard."""


def resume_setup_command() -> str:
    """Return the supported resume command shown to the user."""
    return f"sudo {INSTALLED_BINARY_PATH} setup"


def run_setup_wizard() -> int:
    """Run the interactive packaged setup flow."""
    if os.geteuid() != 0:
        sys.stderr.write(f"Run setup as root: {resume_setup_command()}\n")
        return 1

    if not sys.stdin.isatty():
        sys.stderr.write(
            "Interactive setup requires a terminal. "
            f"Resume with {resume_setup_command()}.\n"
        )
        return 1

    existing_values = _load_existing_values()
    sys.stdout.write(
        "Heka Insights Agent setup\n"
        "Type 'cancel' at any prompt to stop setup and finish installation later.\n\n"
    )

    try:
        config_values = _collect_config(existing_values)
        _write_config_file(config_values)
        _apply_runtime_permissions()
        _enable_and_start_service()
        sys.stdout.write(
            f"Setup complete. Configuration written to {ENV_FILE}.\n"
            f"Service enabled and started: {SERVICE_NAME}\n"
        )
        return 0
    except SetupCancelled:
        sys.stdout.write(
            f"Setup cancelled. You can resume setup using {resume_setup_command()}.\n"
        )
        return 130
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.stderr.write(f"Setup failed: {exc}\n")
        sys.stderr.write(
            f"You can resume setup using {resume_setup_command()}.\n"
        )
        return 1


def _collect_config(existing_values: dict[str, str]) -> dict[str, str]:
    config_values: dict[str, str] = {
        LOG_LOCATION_ENV_KEY: _prompt_value(
            label="Log file path",
            default=existing_values.get(LOG_LOCATION_ENV_KEY, DEFAULT_LOG_LOCATION),
            validate=_validate_non_empty,
        ),
        CPU_POLL_INTERVAL_ENV_KEY: _prompt_value(
            label="CPU poll interval seconds",
            default=existing_values.get(
                CPU_POLL_INTERVAL_ENV_KEY,
                str(int(DEFAULT_CPU_POLL_INTERVAL_SECONDS)),
            ),
            validate=_validate_positive_float,
        ),
    }

    exporter_type = _prompt_choice(
        label="Exporter type",
        choices=SUPPORTED_EXPORTER_TYPES,
        default=existing_values.get(EXPORTER_TYPE_ENV_KEY, DEFAULT_EXPORTER_TYPE),
    )
    config_values[EXPORTER_TYPE_ENV_KEY] = exporter_type

    if exporter_type == "otlp_http":
        _collect_otlp_http_values(config_values, existing_values)
    elif exporter_type == "datadog_otlp":
        _collect_datadog_otlp_values(config_values, existing_values)
    elif exporter_type == "datadog_native":
        _collect_datadog_native_values(config_values, existing_values)
    elif exporter_type == "newrelic_otlp":
        _collect_newrelic_values(config_values, existing_values)

    return config_values


def _collect_otlp_http_values(
    config_values: dict[str, str],
    existing_values: dict[str, str],
) -> None:
    config_values[OTLP_HTTP_ENDPOINT_ENV_KEY] = _prompt_value(
        label="OTLP HTTP endpoint",
        default=existing_values.get(
            OTLP_HTTP_ENDPOINT_ENV_KEY,
            "http://localhost:4318/v1/metrics",
        ),
        validate=_validate_non_empty,
    )
    intelligence_enabled = _prompt_yes_no(
        label="Use with Heka Insights Intelligence",
        default=_get_existing_boolean_default(
            existing_values,
            key=HEKA_INTELLIGENCE_ENABLED_ENV_KEY,
            fallback=False,
        ),
    )
    config_values[HEKA_INTELLIGENCE_ENABLED_ENV_KEY] = (
        _BOOLEAN_TRUE_VALUE if intelligence_enabled else _BOOLEAN_FALSE_VALUE
    )
    if intelligence_enabled:
        _collect_heka_intelligence_values(config_values, existing_values)
    _collect_shared_otlp_values(config_values, existing_values)


def _collect_datadog_otlp_values(
    config_values: dict[str, str],
    existing_values: dict[str, str],
) -> None:
    _collect_datadog_shared_values(config_values, existing_values)
    _collect_shared_otlp_values(config_values, existing_values)


def _collect_datadog_native_values(
    config_values: dict[str, str],
    existing_values: dict[str, str],
) -> None:
    _collect_datadog_shared_values(config_values, existing_values)
    config_values[DATADOG_METRIC_PREFIX_ENV_KEY] = _prompt_value(
        label="Datadog metric prefix (optional)",
        default=existing_values.get(DATADOG_METRIC_PREFIX_ENV_KEY, ""),
        required=False,
    )
    config_values[OTLP_HTTP_TIMEOUT_SECONDS_ENV_KEY] = _prompt_value(
        label="HTTP timeout seconds",
        default=existing_values.get(
            OTLP_HTTP_TIMEOUT_SECONDS_ENV_KEY,
            str(DEFAULT_OTLP_HTTP_TIMEOUT_SECONDS),
        ),
        validate=_validate_positive_int,
    )


def _collect_newrelic_values(
    config_values: dict[str, str],
    existing_values: dict[str, str],
) -> None:
    config_values[NEWRELIC_OTLP_ENDPOINT_ENV_KEY] = _prompt_value(
        label="New Relic OTLP endpoint",
        default=existing_values.get(
            NEWRELIC_OTLP_ENDPOINT_ENV_KEY,
            _NEWRELIC_DEFAULT_ENDPOINT,
        ),
        validate=_validate_non_empty,
    )
    config_values[NEWRELIC_API_KEY_ENV_KEY] = _prompt_secret(
        label="New Relic API key",
        existing_value=existing_values.get(NEWRELIC_API_KEY_ENV_KEY, ""),
        required=True,
    )
    config_values[NEWRELIC_SERVICE_NAME_ENV_KEY] = _prompt_value(
        label="New Relic service name",
        default=existing_values.get(
            NEWRELIC_SERVICE_NAME_ENV_KEY,
            "heka-insights-agent",
        ),
        validate=_validate_non_empty,
    )
    config_values[NEWRELIC_ENVIRONMENT_ENV_KEY] = _prompt_value(
        label="New Relic environment (optional)",
        default=existing_values.get(NEWRELIC_ENVIRONMENT_ENV_KEY, ""),
        required=False,
    )
    config_values[NEWRELIC_HOST_NAME_ENV_KEY] = _prompt_value(
        label="New Relic host name (optional)",
        default=existing_values.get(NEWRELIC_HOST_NAME_ENV_KEY, ""),
        required=False,
    )
    _collect_shared_otlp_values(config_values, existing_values)


def _collect_datadog_shared_values(
    config_values: dict[str, str],
    existing_values: dict[str, str],
) -> None:
    config_values[DATADOG_SITE_ENV_KEY] = _prompt_value(
        label="Datadog site",
        default=existing_values.get(DATADOG_SITE_ENV_KEY, "datadoghq.com"),
        validate=_validate_non_empty,
    )
    config_values[DATADOG_API_KEY_ENV_KEY] = _prompt_secret(
        label="Datadog API key",
        existing_value=existing_values.get(DATADOG_API_KEY_ENV_KEY, ""),
        required=True,
    )
    config_values[DATADOG_HOSTNAME_ENV_KEY] = _prompt_value(
        label="Datadog hostname (optional)",
        default=existing_values.get(DATADOG_HOSTNAME_ENV_KEY, ""),
        required=False,
    )
    config_values[DATADOG_TAGS_ENV_KEY] = _prompt_value(
        label="Datadog tags (optional key:value,key2:value2)",
        default=existing_values.get(DATADOG_TAGS_ENV_KEY, ""),
        required=False,
    )


def _collect_shared_otlp_values(
    config_values: dict[str, str],
    existing_values: dict[str, str],
) -> None:
    config_values[OTLP_HTTP_HEADERS_ENV_KEY] = _prompt_value(
        label="OTLP HTTP headers (optional key=value,key2=value2)",
        default=existing_values.get(OTLP_HTTP_HEADERS_ENV_KEY, ""),
        required=False,
    )
    config_values[OTLP_RESOURCE_ATTRIBUTES_ENV_KEY] = _prompt_value(
        label="OTLP resource attributes (optional key=value,key2=value2)",
        default=existing_values.get(
            OTLP_RESOURCE_ATTRIBUTES_ENV_KEY,
            "service.name=heka-insights-agent,host.name=localhost",
        ),
        required=False,
    )
    config_values[OTLP_HTTP_TIMEOUT_SECONDS_ENV_KEY] = _prompt_value(
        label="HTTP timeout seconds",
        default=existing_values.get(
            OTLP_HTTP_TIMEOUT_SECONDS_ENV_KEY,
            str(DEFAULT_OTLP_HTTP_TIMEOUT_SECONDS),
        ),
        validate=_validate_positive_int,
    )
    config_values[OTLP_HTTP_RETRY_MAX_ATTEMPTS_ENV_KEY] = _prompt_value(
        label="Retry max attempts",
        default=existing_values.get(
            OTLP_HTTP_RETRY_MAX_ATTEMPTS_ENV_KEY,
            str(DEFAULT_OTLP_HTTP_RETRY_MAX_ATTEMPTS),
        ),
        validate=_validate_positive_int,
    )
    config_values[OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS_ENV_KEY] = _prompt_value(
        label="Retry initial backoff seconds",
        default=existing_values.get(
            OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS_ENV_KEY,
            str(DEFAULT_OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS),
        ),
        validate=_validate_positive_float,
    )
    config_values[OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS_ENV_KEY] = _prompt_value(
        label="Retry max backoff seconds",
        default=existing_values.get(
            OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS_ENV_KEY,
            str(DEFAULT_OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS),
        ),
        validate=_validate_positive_float,
    )


def _collect_heka_intelligence_values(
    config_values: dict[str, str],
    existing_values: dict[str, str],
) -> None:
    config_values[HEKA_AGENT_ID_ENV_KEY] = _prompt_value(
        label="Heka agent ID",
        default=existing_values.get(HEKA_AGENT_ID_ENV_KEY, ""),
        validate=_validate_non_empty,
    )
    config_values[HEKA_API_KEY_ENV_KEY] = _prompt_secret(
        label="Heka API key",
        existing_value=existing_values.get(HEKA_API_KEY_ENV_KEY, ""),
        required=True,
    )


def _prompt_choice(
    *,
    label: str,
    choices: tuple[str, ...],
    default: str,
) -> str:
    allowed_values = ", ".join(choices)

    def validate(value: str) -> None:
        if value not in choices:
            raise ValueError(f"choose one of: {allowed_values}")

    return _prompt_value(
        label=f"{label} [{allowed_values}]",
        default=default,
        validate=validate,
    )


def _prompt_yes_no(*, label: str, default: bool) -> bool:
    default_label = "yes" if default else "no"

    while True:
        response = input(f"{label} [yes/no] [{default_label}]: ").strip()
        _raise_if_cancelled(response)

        if not response:
            return default

        normalized = response.lower()
        if normalized in {"y", "yes"}:
            return True
        if normalized in {"n", "no"}:
            return False

        sys.stdout.write("Enter yes or no.\n")


def _prompt_secret(
    *,
    label: str,
    existing_value: str,
    required: bool,
) -> str:
    prompt_suffix = " [press Enter to keep existing value]" if existing_value else ""

    while True:
        response = getpass.getpass(f"{label}{prompt_suffix}: ").strip()
        _raise_if_cancelled(response)

        if response:
            return response
        if existing_value:
            return existing_value
        if not required:
            return ""
        sys.stdout.write("A value is required.\n")


def _prompt_value(
    *,
    label: str,
    default: str,
    required: bool = True,
    validate: Callable[[str], None] | None = None,
) -> str:
    prompt = f"{label}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "

    while True:
        response = input(prompt).strip()
        _raise_if_cancelled(response)

        value = response or default
        if not value and not required:
            return ""
        if not value:
            sys.stdout.write("A value is required.\n")
            continue

        if validate is not None:
            try:
                validate(value)
            except ValueError as exc:
                sys.stdout.write(f"{exc}\n")
                continue
        return value


def _raise_if_cancelled(value: str) -> None:
    if value.lower() in _SETUP_CANCEL_WORDS:
        raise SetupCancelled()


def _validate_non_empty(value: str) -> None:
    if not value.strip():
        raise ValueError("A value is required.")


def _validate_positive_int(value: str) -> None:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("Value must be greater than zero.")


def _validate_positive_float(value: str) -> None:
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("Value must be greater than zero.")


def _get_existing_boolean_default(
    existing_values: dict[str, str],
    *,
    key: str,
    fallback: bool,
) -> bool:
    raw_value = existing_values.get(key, "").strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    return fallback


def _load_existing_values() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    loaded = dotenv_values(ENV_FILE)
    return {key: value for key, value in loaded.items() if value is not None}


def _write_config_file(config_values: dict[str, str]) -> None:
    ENV_DIRECTORY.mkdir(parents=True, exist_ok=True)

    lines = [f"{key}={value}" for key, value in config_values.items() if value]
    lines.append("")
    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")


def _apply_runtime_permissions() -> None:
    log_file_path = Path(
        _load_existing_values().get(LOG_LOCATION_ENV_KEY, DEFAULT_LOG_LOCATION)
    )
    log_directory = log_file_path.parent
    log_directory.mkdir(parents=True, exist_ok=True)
    log_file_path.touch(exist_ok=True)

    _safe_chown(ENV_DIRECTORY, user="root", group=SERVICE_GROUP)
    ENV_DIRECTORY.chmod(0o750)

    _safe_chown(ENV_FILE, user="root", group=SERVICE_GROUP)
    ENV_FILE.chmod(0o640)

    _safe_chown(log_directory, user=SERVICE_USER, group=SERVICE_GROUP)
    log_directory.chmod(0o750)

    _safe_chown(log_file_path, user=SERVICE_USER, group=SERVICE_GROUP)


def _safe_chown(path: Path, *, user: str, group: str) -> None:
    shutil.chown(path, user=user, group=group)


def _enable_and_start_service() -> None:
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", SERVICE_NAME], check=True)
    subprocess.run(["systemctl", "restart", SERVICE_NAME], check=True)
