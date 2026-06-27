"""Datadog native metrics exporter implementation."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import (
    get_cpu_poll_interval_seconds,
    get_datadog_native_config,
    get_otlp_http_timeout_seconds,
)

from .base import CanonicalMetricCollection, Exporter

_SUPPORTED_CANONICAL_METRIC_TYPES = ("gauge", "counter")


class DatadogSeriesMapper:
    """Map canonical metrics into Datadog v1 /series payloads."""

    def __init__(
        self,
        *,
        hostname: str | None = None,
        default_tags: Sequence[str] | None = None,
        metric_prefix: str | None = None,
        count_interval_seconds: int = 1,
        now_unix_ms: Callable[[], int] | None = None,
    ) -> None:
        self._hostname = hostname
        self._default_tags = list(default_tags or [])
        self._metric_prefix = metric_prefix
        self._count_interval_seconds = max(1, count_interval_seconds)
        self._now_unix_ms = now_unix_ms or (lambda: int(time.time() * 1000))

    def map_metrics(self, metrics: CanonicalMetricCollection) -> dict[str, Any]:
        """Build Datadog timeseries payload from canonical metrics."""
        default_timestamp_unix_ms = self._now_unix_ms()
        series = [
            self._map_one(
                metric=metric,
                index=index,
                default_timestamp_unix_ms=default_timestamp_unix_ms,
            )
            for index, metric in enumerate(metrics)
        ]
        return {"series": series}

    def _map_one(
        self,
        *,
        metric: Mapping[str, Any],
        index: int,
        default_timestamp_unix_ms: int,
    ) -> dict[str, Any]:
        self._validate_metric(metric, index=index)

        timestamp_unix_ms = metric.get("timestamp_unix_ms", default_timestamp_unix_ms)
        timestamp_seconds = int(int(timestamp_unix_ms) // 1000)

        metric_name = metric["name"]
        if self._metric_prefix is not None:
            prefix = self._metric_prefix
            if metric_name.startswith(f"{prefix}."):
                full_metric_name = metric_name
            else:
                full_metric_name = f"{prefix}.{metric_name}"
        else:
            full_metric_name = metric_name

        labels = metric["labels"]
        tags = self._merge_and_normalize_tags(
            default_tags=self._default_tags,
            label_tags=self._labels_to_tags(labels),
        )

        host = self._hostname
        if host is None:
            candidate_host = labels.get("host")
            if isinstance(candidate_host, str) and candidate_host:
                host = candidate_host

        mapped: dict[str, Any] = {
            "metric": full_metric_name,
            "points": [[timestamp_seconds, float(metric["value"])]],
            "type": "gauge" if metric["type"] == "gauge" else "count",
        }
        if mapped["type"] == "count":
            mapped["interval"] = self._count_interval_seconds
        if host is not None:
            mapped["host"] = host
        if tags:
            mapped["tags"] = tags
        return mapped

    @staticmethod
    def _labels_to_tags(labels: Mapping[str, str]) -> list[str]:
        tags: list[str] = []
        for key, value in sorted(labels.items()):
            if value:
                tags.append(f"{key}:{value}")
            else:
                tags.append(key)
        return tags

    @staticmethod
    def _normalize_tags(tags: Sequence[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            trimmed = tag.strip()
            if not trimmed or trimmed in seen:
                continue
            normalized.append(trimmed)
            seen.add(trimmed)
        return normalized

    @classmethod
    def _merge_and_normalize_tags(
        cls,
        *,
        default_tags: Sequence[str],
        label_tags: Sequence[str],
    ) -> list[str]:
        """Merge tags with deterministic key precedence (defaults win)."""
        tag_by_key: dict[str, str] = {}

        for tag in label_tags:
            key, value = cls._split_tag(tag)
            tag_by_key[key] = value

        for tag in default_tags:
            key, value = cls._split_tag(tag)
            tag_by_key[key] = value

        merged = [f"{key}:{tag_by_key[key]}" for key in sorted(tag_by_key)]
        return cls._normalize_tags(merged)

    @staticmethod
    def _split_tag(tag: str) -> tuple[str, str]:
        """Split Datadog tag strings into key/value parts."""
        key, value = tag.split(":", 1)
        return key.strip(), value.strip()

    @staticmethod
    def _validate_metric(metric: Mapping[str, Any], *, index: int) -> None:
        required_fields = ("name", "description", "type", "unit", "value", "labels")
        missing_fields = [field for field in required_fields if field not in metric]
        if missing_fields:
            missing = ", ".join(missing_fields)
            raise ValueError(f"Metric at index {index} is missing required fields: {missing}")

        metric_type = metric["type"]
        if metric_type not in _SUPPORTED_CANONICAL_METRIC_TYPES:
            supported_values = ", ".join(_SUPPORTED_CANONICAL_METRIC_TYPES)
            raise ValueError(
                f"Unsupported canonical metric type '{metric_type}' at index {index}. "
                f"Supported values: {supported_values}."
            )

        value = metric["value"]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(
                f"Metric '{metric['name']}' at index {index} has non-numeric value."
            )

        labels = metric["labels"]
        if not isinstance(labels, Mapping):
            raise ValueError(
                f"Metric '{metric['name']}' at index {index} has non-mapping labels."
            )
        for key, label_value in labels.items():
            if not isinstance(key, str) or not isinstance(label_value, str):
                raise ValueError(
                    f"Metric '{metric['name']}' at index {index} has non-string labels."
                )

        timestamp_unix_ms = metric.get("timestamp_unix_ms")
        if timestamp_unix_ms is not None:
            if not isinstance(timestamp_unix_ms, int) or timestamp_unix_ms < 0:
                raise ValueError(
                    f"Metric '{metric['name']}' at index {index} has invalid "
                    "timestamp_unix_ms."
                )


class DatadogMetricSender:
    """Send Datadog v1 series payloads over HTTP."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        timeout_seconds: int = 10,
        http_client: Callable[..., Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._endpoint = endpoint.strip()
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or urlopen
        self._logger = logger
        self._validate_endpoint()

    def send(self, payload: Mapping[str, Any]) -> None:
        """POST a Datadog metrics payload."""
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(url=self._endpoint, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        request.add_header("DD-API-KEY", self._api_key)

        try:
            with self._http_client(request, timeout=self._timeout_seconds) as response:
                status_code = getattr(response, "status", None)
                if status_code is None:
                    status_code = response.getcode()
                if status_code >= 200 and status_code < 300:
                    return
                self._logger_debug(
                    "Datadog native request failed for endpoint '%s' (status=%s).",
                    self._endpoint,
                    status_code,
                )
                raise RuntimeError(
                    "Datadog native export failed with non-success status code "
                    f"{status_code}."
                )
        except HTTPError as exc:
            self._logger_debug(
                "Datadog native request failed for endpoint '%s' (status=%s).",
                self._endpoint,
                exc.code,
            )
            raise RuntimeError(
                f"Datadog native export failed with HTTP error {exc.code}: "
                f"{exc.reason}."
            ) from exc
        except URLError as exc:
            self._logger_debug(
                "Datadog native request failed for endpoint '%s': %s",
                self._endpoint,
                exc.reason,
            )
            raise RuntimeError(
                f"Datadog native export failed to reach endpoint '{self._endpoint}': "
                f"{exc.reason}."
            ) from exc

    def _validate_endpoint(self) -> None:
        parsed = urlparse(self._endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(
                f"Invalid Datadog native endpoint '{self._endpoint}'. "
                "Expected absolute http/https URL."
            )

    def _logger_debug(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.debug(message, *args)


class DatadogNativeExporter(Exporter):
    """Datadog-native exporter backed by API v1 /series."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        hostname: str | None = None,
        default_tags: Sequence[str] | None = None,
        metric_prefix: str | None = None,
        count_interval_seconds: int | None = None,
        mapper: DatadogSeriesMapper | None = None,
        sender: DatadogMetricSender | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._hostname = hostname
        self._default_tags = list(default_tags or [])
        self._metric_prefix = metric_prefix
        self._count_interval_seconds = count_interval_seconds
        self._mapper = mapper
        self._sender = sender
        self._logger = logger
        self._initialized = False

    def initialize(self) -> None:
        """Resolve Datadog config and prepare mapper/sender."""
        if self._endpoint is None or self._api_key is None:
            (
                resolved_endpoint,
                resolved_api_key,
                resolved_hostname,
                resolved_default_tags,
                resolved_metric_prefix,
            ) = get_datadog_native_config(logger=self._logger)
            if self._endpoint is None:
                self._endpoint = resolved_endpoint
            if self._api_key is None:
                self._api_key = resolved_api_key
            if self._hostname is None:
                self._hostname = resolved_hostname
            if not self._default_tags:
                self._default_tags = resolved_default_tags
            if self._metric_prefix is None:
                self._metric_prefix = resolved_metric_prefix
        if self._count_interval_seconds is None:
            poll_interval = get_cpu_poll_interval_seconds(logger=self._logger)
            self._count_interval_seconds = max(1, int(round(poll_interval)))

        if self._mapper is None:
            self._mapper = DatadogSeriesMapper(
                hostname=self._hostname,
                default_tags=self._default_tags,
                metric_prefix=self._metric_prefix,
                count_interval_seconds=self._count_interval_seconds,
            )

        if self._sender is None:
            timeout_seconds = get_otlp_http_timeout_seconds(logger=self._logger)
            self._sender = DatadogMetricSender(
                endpoint=self._endpoint,
                api_key=self._api_key,
                timeout_seconds=timeout_seconds,
                logger=self._logger,
            )

        self._initialized = True

    def export(self, metrics: CanonicalMetricCollection) -> None:
        """Map and send canonical metrics to Datadog."""
        if not self._initialized:
            raise RuntimeError("DatadogNativeExporter must be initialized before export().")
        if self._mapper is None:
            raise RuntimeError("DatadogNativeExporter mapper is not initialized.")
        if self._sender is None:
            raise RuntimeError("DatadogNativeExporter sender is not initialized.")

        payload = self._mapper.map_metrics(metrics)
        self._sender.send(payload)

    def shutdown(self) -> None:
        """Release exporter resources."""
        self._initialized = False

    def health_status(self) -> dict[str, Any] | None:
        """Return exporter health details."""
        return {
            "initialized": self._initialized,
            "endpoint": self._endpoint,
            "hostname": self._hostname,
            "default_tags_configured": len(self._default_tags),
            "metric_prefix": self._metric_prefix,
            "count_interval_seconds": self._count_interval_seconds,
        }
