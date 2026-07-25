"""Datadog native metrics exporter implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import (
    get_cpu_poll_interval_seconds,
    get_datadog_native_config,
    get_heka_agent_id,
    get_otlp_http_retry_initial_backoff_seconds,
    get_otlp_http_retry_max_attempts,
    get_otlp_http_retry_max_backoff_seconds,
    get_otlp_http_timeout_seconds,
    get_otlp_retry_after_default_seconds,
    get_otlp_retry_after_max_seconds,
)

from .base import CanonicalMetricCollection, Exporter
from .http_common import (
    BackgroundPayloadDispatcher,
    ShutdownRequestedError,
    SleepFn,
    mask_identifier,
    parse_retry_after_delay,
    sleep_with_shutdown,
)

_SUPPORTED_CANONICAL_METRIC_TYPES = ("gauge", "counter")
_RETRYABLE_HTTP_STATUS_CODES = {408, 429}
_RETRY_BACKOFF_MULTIPLIER = 2.0


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
        retry_max_attempts: int = 5,
        retry_initial_backoff_seconds: float = 1.0,
        retry_max_backoff_seconds: float = 5.0,
        retry_after_default_seconds: int = 5,
        retry_after_max_seconds: int = 300,
        agent_id: str | None = None,
        http_client: Callable[..., Any] | None = None,
        sleep_fn: SleepFn | None = None,
        shutdown_event: threading.Event | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._endpoint = endpoint.strip()
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._retry_max_attempts = retry_max_attempts
        self._retry_initial_backoff_seconds = retry_initial_backoff_seconds
        self._retry_max_backoff_seconds = max(
            retry_max_backoff_seconds,
            retry_initial_backoff_seconds,
        )
        self._retry_after_default_seconds = retry_after_default_seconds
        self._retry_after_max_seconds = max(
            retry_after_max_seconds,
            retry_after_default_seconds,
        )
        self._agent_id = agent_id
        self._http_client = http_client or urlopen
        self._sleep_fn = sleep_fn
        self._shutdown_event = shutdown_event or threading.Event()
        self._logger = logger
        self._validate_retry_policy()
        self._validate_endpoint()

    def send(self, payload: Mapping[str, Any]) -> None:
        """POST a Datadog metrics payload."""
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        asyncio.run(self._send_async(body))

    async def _send_async(self, body: bytes) -> None:
        batch_started = time.monotonic()
        masked_agent_id = mask_identifier(self._agent_id)
        self._ensure_agent_id_configured(masked_agent_id=masked_agent_id)

        for attempt in range(1, self._retry_max_attempts + 1):
            if self._shutdown_event.is_set():
                raise ShutdownRequestedError(
                    "Shutdown requested before Datadog native export."
                )

            request = self._build_request(body)
            request_started = time.monotonic()
            try:
                with self._http_client(request, timeout=self._timeout_seconds) as response:
                    status_code = getattr(response, "status", None)
                    if status_code is None:
                        status_code = response.getcode()
                    request_ms = (time.monotonic() - request_started) * 1000.0
                    response_headers = getattr(response, "headers", None)
                    if status_code >= 200 and status_code < 300:
                        self._logger_info(
                            "Datadog native export completed; endpoint=%s status=%s "
                            "attempt=%s retry_request_ms=%.3f total_batch_export_ms=%.3f "
                            "x_agent_id=%s",
                            self._endpoint,
                            status_code,
                            attempt,
                            request_ms,
                            (time.monotonic() - batch_started) * 1000.0,
                            masked_agent_id,
                        )
                        return
                    if await self._handle_http_failure(
                        status_code=status_code,
                        headers=response_headers,
                        attempt=attempt,
                        request_ms=request_ms,
                        batch_started=batch_started,
                        masked_agent_id=masked_agent_id,
                    ):
                        continue
                    raise RuntimeError(
                        "Datadog native export failed with non-success status code "
                        f"{status_code}."
                    )
            except HTTPError as exc:
                request_ms = (time.monotonic() - request_started) * 1000.0
                if await self._handle_http_error(
                    exc=exc,
                    attempt=attempt,
                    request_ms=request_ms,
                    batch_started=batch_started,
                    masked_agent_id=masked_agent_id,
                ):
                    continue
                raise RuntimeError(
                    f"Datadog native export failed with HTTP error {exc.code}: "
                    f"{exc.reason}."
                ) from exc
            except URLError as exc:
                request_ms = (time.monotonic() - request_started) * 1000.0
                if self._should_retry(status_code=None, attempt=attempt):
                    self._log_retry(
                        status_code="transport",
                        attempt=attempt,
                        request_ms=request_ms,
                        reason=f"transport_error={exc.reason}",
                        masked_agent_id=masked_agent_id,
                    )
                    await self._sleep_before_retry(attempt=attempt)
                    continue
                self._logger_debug(
                    "Datadog native export failed; endpoint=%s status=transport attempt=%s "
                    "max_attempts=%s retry_request_ms=%.3f total_batch_export_ms=%.3f "
                    "x_agent_id=%s error=%s",
                    self._endpoint,
                    attempt,
                    self._retry_max_attempts,
                    request_ms,
                    (time.monotonic() - batch_started) * 1000.0,
                    masked_agent_id,
                    exc.reason,
                )
                raise RuntimeError(
                    f"Datadog native export failed to reach endpoint '{self._endpoint}': "
                    f"{exc.reason}."
                ) from exc

    def _build_request(self, body: bytes) -> Request:
        request = Request(url=self._endpoint, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        request.add_header("DD-API-KEY", self._api_key)
        if self._agent_id is not None:
            request.add_header("x-agent-id", self._agent_id)
        return request

    async def _handle_http_failure(
        self,
        *,
        status_code: int,
        headers: Mapping[str, Any] | None,
        attempt: int,
        request_ms: float,
        batch_started: float,
        masked_agent_id: str,
    ) -> bool:
        if status_code == 429 and self._should_retry(status_code=status_code, attempt=attempt):
            await self._sleep_for_retry_after(
                headers=headers,
                attempt=attempt,
                request_ms=request_ms,
                batch_started=batch_started,
                masked_agent_id=masked_agent_id,
            )
            return True

        if self._should_retry(status_code=status_code, attempt=attempt):
            self._log_retry(
                status_code=status_code,
                attempt=attempt,
                request_ms=request_ms,
                reason=f"http_status={status_code}",
                masked_agent_id=masked_agent_id,
            )
            await self._sleep_before_retry(attempt=attempt)
            return True

        self._logger_debug(
            "Datadog native export failed; endpoint=%s status=%s attempt=%s max_attempts=%s "
            "retry_request_ms=%.3f total_batch_export_ms=%.3f x_agent_id=%s",
            self._endpoint,
            status_code,
            attempt,
            self._retry_max_attempts,
            request_ms,
            (time.monotonic() - batch_started) * 1000.0,
            masked_agent_id,
        )
        return False

    async def _handle_http_error(
        self,
        *,
        exc: HTTPError,
        attempt: int,
        request_ms: float,
        batch_started: float,
        masked_agent_id: str,
    ) -> bool:
        if exc.code == 429 and self._should_retry(status_code=exc.code, attempt=attempt):
            await self._sleep_for_retry_after(
                headers=exc.headers,
                attempt=attempt,
                request_ms=request_ms,
                batch_started=batch_started,
                masked_agent_id=masked_agent_id,
            )
            return True

        if self._should_retry(status_code=exc.code, attempt=attempt):
            self._log_retry(
                status_code=exc.code,
                attempt=attempt,
                request_ms=request_ms,
                reason=f"http_status={exc.code}",
                masked_agent_id=masked_agent_id,
            )
            await self._sleep_before_retry(attempt=attempt)
            return True

        self._logger_debug(
            "Datadog native export failed; endpoint=%s status=%s attempt=%s max_attempts=%s "
            "retry_request_ms=%.3f total_batch_export_ms=%.3f x_agent_id=%s",
            self._endpoint,
            exc.code,
            attempt,
            self._retry_max_attempts,
            request_ms,
            (time.monotonic() - batch_started) * 1000.0,
            masked_agent_id,
        )
        return False

    def _should_retry(self, *, status_code: int | None, attempt: int) -> bool:
        if attempt >= self._retry_max_attempts:
            return False
        if status_code is None:
            return True
        if status_code in _RETRYABLE_HTTP_STATUS_CODES:
            return True
        return 500 <= status_code <= 599

    async def _sleep_before_retry(self, *, attempt: int) -> None:
        backoff_seconds = min(
            self._retry_max_backoff_seconds,
            self._retry_initial_backoff_seconds
            * (_RETRY_BACKOFF_MULTIPLIER ** (attempt - 1)),
        )
        await sleep_with_shutdown(
            seconds=backoff_seconds,
            shutdown_event=self._shutdown_event,
            sleep_fn=self._sleep_fn,
        )

    async def _sleep_for_retry_after(
        self,
        *,
        headers: Mapping[str, Any] | None,
        attempt: int,
        request_ms: float,
        batch_started: float,
        masked_agent_id: str,
    ) -> None:
        retry_after = parse_retry_after_delay(
            headers=headers,
            default_seconds=self._retry_after_default_seconds,
            max_seconds=self._retry_after_max_seconds,
        )
        self._logger_warning(
            "Datadog native export rate limited; endpoint=%s status=429 attempt=%s "
            "max_attempts=%s retry_after_seconds=%s retry_after_source=%s "
            "retry_after_default_used=%s retry_after_capped=%s retry_after_parse_ms=%.3f "
            "retry_after_sleep_seconds=%s retry_request_ms=%.3f total_batch_export_ms=%.3f "
            "x_agent_id=%s",
            self._endpoint,
            attempt,
            self._retry_max_attempts,
            retry_after.seconds,
            retry_after.source,
            retry_after.default_used,
            retry_after.capped,
            retry_after.parse_ms,
            retry_after.seconds,
            request_ms,
            (time.monotonic() - batch_started) * 1000.0,
            masked_agent_id,
        )
        await sleep_with_shutdown(
            seconds=retry_after.seconds,
            shutdown_event=self._shutdown_event,
            sleep_fn=self._sleep_fn,
        )

    def _log_retry(
        self,
        *,
        status_code: int | str,
        attempt: int,
        request_ms: float,
        reason: str,
        masked_agent_id: str,
    ) -> None:
        self._logger_debug(
            "Datadog native export retry scheduled; endpoint=%s status=%s attempt=%s "
            "max_attempts=%s retry_request_ms=%.3f next_attempt=%s reason=%s x_agent_id=%s",
            self._endpoint,
            status_code,
            attempt,
            self._retry_max_attempts,
            request_ms,
            attempt + 1,
            reason,
            masked_agent_id,
        )

    def _ensure_agent_id_configured(self, *, masked_agent_id: str) -> None:
        if self._agent_id:
            return
        self._logger_error(
            "Datadog native export skipped; endpoint=%s status=not_sent attempt=0 "
            "max_attempts=%s x_agent_id=%s error=missing_x_agent_id",
            self._endpoint,
            self._retry_max_attempts,
            masked_agent_id,
        )
        raise RuntimeError("Datadog native export missing x-agent-id; batch not dispatched.")

    def _validate_endpoint(self) -> None:
        parsed = urlparse(self._endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(
                f"Invalid Datadog native endpoint '{self._endpoint}'. "
                "Expected absolute http/https URL."
            )

    def _validate_retry_policy(self) -> None:
        if self._timeout_seconds <= 0:
            raise RuntimeError("Datadog native timeout_seconds must be greater than zero.")
        if self._retry_max_attempts <= 0:
            raise RuntimeError(
                "Datadog native retry_max_attempts must be greater than zero."
            )
        if self._retry_initial_backoff_seconds <= 0:
            raise RuntimeError(
                "Datadog native retry_initial_backoff_seconds must be greater than zero."
            )
        if self._retry_max_backoff_seconds <= 0:
            raise RuntimeError(
                "Datadog native retry_max_backoff_seconds must be greater than zero."
            )
        if self._retry_after_default_seconds < 0:
            raise RuntimeError(
                "Datadog native retry_after_default_seconds must be greater than or "
                "equal to zero."
            )
        if self._retry_after_max_seconds <= 0:
            raise RuntimeError(
                "Datadog native retry_after_max_seconds must be greater than zero."
            )

    def _logger_debug(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.debug(message, *args)

    def _logger_info(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.info(message, *args)

    def _logger_warning(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.warning(message, *args)

    def _logger_error(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.error(message, *args)


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
        background_dispatch: bool = True,
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
        self._background_dispatch = background_dispatch
        self._dispatch_worker: BackgroundPayloadDispatcher | None = None
        self._dispatch_shutdown_event: threading.Event | None = None
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
            retry_max_attempts = get_otlp_http_retry_max_attempts(logger=self._logger)
            retry_initial_backoff_seconds = (
                get_otlp_http_retry_initial_backoff_seconds(logger=self._logger)
            )
            retry_max_backoff_seconds = get_otlp_http_retry_max_backoff_seconds(
                logger=self._logger
            )
            retry_after_default_seconds = get_otlp_retry_after_default_seconds(
                logger=self._logger
            )
            retry_after_max_seconds = get_otlp_retry_after_max_seconds(
                logger=self._logger
            )
            self._dispatch_shutdown_event = threading.Event()
            self._sender = DatadogMetricSender(
                endpoint=self._endpoint,
                api_key=self._api_key,
                timeout_seconds=timeout_seconds,
                retry_max_attempts=retry_max_attempts,
                retry_initial_backoff_seconds=retry_initial_backoff_seconds,
                retry_max_backoff_seconds=retry_max_backoff_seconds,
                retry_after_default_seconds=retry_after_default_seconds,
                retry_after_max_seconds=retry_after_max_seconds,
                agent_id=get_heka_agent_id(logger=self._logger),
                shutdown_event=self._dispatch_shutdown_event,
                logger=self._logger,
            )
        elif self._dispatch_shutdown_event is None:
            self._dispatch_shutdown_event = threading.Event()

        if self._background_dispatch and self._sender is not None:
            if self._dispatch_shutdown_event is None:
                self._dispatch_shutdown_event = threading.Event()
            self._dispatch_worker = BackgroundPayloadDispatcher(
                sender=self._sender,
                worker_name="datadog-native-export",
                shutdown_event=self._dispatch_shutdown_event,
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
        if self._dispatch_worker is not None:
            self._dispatch_worker.submit(payload)
            return
        self._sender.send(payload)

    def shutdown(self) -> None:
        """Release exporter resources."""
        if self._dispatch_worker is not None:
            self._dispatch_worker.shutdown()
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
