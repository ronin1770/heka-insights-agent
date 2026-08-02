"""OTLP HTTP sender and exporter implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import (
    get_heka_agent_id,
    get_heka_api_key,
    get_heka_intelligence_enabled,
    get_heka_intelligence_headers,
    get_otlp_http_endpoint,
    get_otlp_http_headers,
    get_otlp_http_retry_initial_backoff_seconds,
    get_otlp_http_retry_max_attempts,
    get_otlp_http_retry_max_backoff_seconds,
    get_otlp_http_timeout_seconds,
    get_otlp_retry_after_default_seconds,
    get_otlp_retry_after_max_seconds,
    get_otlp_resource_attributes,
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
from .otlp_mapping import OtlpPayloadMapper

# Default per-request timeout for OTLP HTTP exports.
_DEFAULT_TIMEOUT_SECONDS = 10
# Retryable transient HTTP statuses (5xx handled separately).
_RETRYABLE_HTTP_STATUS_CODES = {408, 429}
# Exponential backoff growth factor between retry attempts.
_RETRY_BACKOFF_MULTIPLIER = 2.0


class OtlpHttpMetricSender:
    """Send OTLP metrics payloads to an HTTP endpoint."""

    def __init__(
        self,
        *,
        endpoint: str,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        retry_max_attempts: int = 1,
        retry_initial_backoff_seconds: float = 1.0,
        retry_max_backoff_seconds: float = 5.0,
        retry_after_default_seconds: int = 5,
        retry_after_max_seconds: int = 300,
        headers: Mapping[str, str] | None = None,
        http_client: Callable[..., Any] | None = None,
        sleep_fn: SleepFn | None = None,
        shutdown_event: threading.Event | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._endpoint = endpoint.strip()
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
        self._headers = dict(headers or {})
        self._http_client = http_client or urlopen
        self._sleep_fn = sleep_fn
        self._shutdown_event = shutdown_event or threading.Event()
        self._logger = logger
        self._validate_retry_policy()
        self._validate_endpoint()

    def send(self, payload: Mapping[str, Any]) -> None:
        """Dispatch payload as an OTLP HTTP POST request."""
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        idempotency_key = self._create_idempotency_key()
        asyncio.run(self._send_async(body, idempotency_key=idempotency_key))

    async def _send_async(self, body: bytes, *, idempotency_key: str) -> None:
        batch_started = time.monotonic()
        masked_agent_id = self._masked_agent_id()
        masked_idempotency_key = mask_identifier(idempotency_key)
        self._ensure_agent_id_configured(masked_agent_id=masked_agent_id)

        for attempt in range(1, self._retry_max_attempts + 1):
            if self._shutdown_event.is_set():
                raise ShutdownRequestedError("Shutdown requested before OTLP export.")

            request = self._build_request(body, idempotency_key=idempotency_key)
            request_started = time.monotonic()
            try:
                with self._http_client(request, timeout=self._timeout_seconds) as response:
                    status_code = getattr(response, "status", None)
                    if status_code is None:
                        status_code = response.getcode()
                    request_ms = (time.monotonic() - request_started) * 1000.0
                    response_headers = getattr(response, "headers", None)
                    if status_code >= 200 and status_code < 300:
                        self._log_success(
                            status_code=status_code,
                            attempt=attempt,
                            request_ms=request_ms,
                            total_batch_export_ms=(
                                time.monotonic() - batch_started
                            )
                            * 1000.0,
                            masked_agent_id=masked_agent_id,
                            masked_idempotency_key=masked_idempotency_key,
                        )
                        return

                    if await self._handle_http_status_failure(
                        status_code=status_code,
                        attempt=attempt,
                        headers=response_headers,
                        request_ms=request_ms,
                        batch_started=batch_started,
                        masked_agent_id=masked_agent_id,
                        masked_idempotency_key=masked_idempotency_key,
                    ):
                        continue

                    raise RuntimeError(
                        "OTLP HTTP export failed with non-success status code "
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
                    masked_idempotency_key=masked_idempotency_key,
                ):
                    continue
                raise RuntimeError(
                    f"OTLP HTTP export failed with HTTP error {exc.code}: {exc.reason}."
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
                        masked_idempotency_key=masked_idempotency_key,
                    )
                    await self._sleep_before_retry(attempt=attempt)
                    continue

                self._logger_debug(
                    "OTLP export failed; endpoint=%s status=transport attempt=%s "
                    "max_attempts=%s retry_request_ms=%.3f total_batch_export_ms=%.3f "
                    "x_agent_id=%s x_idempotency_key=%s error=%s",
                    self._endpoint,
                    attempt,
                    self._retry_max_attempts,
                    request_ms,
                    (time.monotonic() - batch_started) * 1000.0,
                    masked_agent_id,
                    masked_idempotency_key,
                    exc.reason,
                )
                raise RuntimeError(
                    f"OTLP HTTP export failed to reach endpoint '{self._endpoint}': "
                    f"{exc.reason}."
                ) from exc

    def _build_request(self, body: bytes, *, idempotency_key: str) -> Request:
        request = Request(url=self._endpoint, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        request.add_header("X-Idempotency-Key", idempotency_key)
        for key, value in self._headers.items():
            request.add_header(key, value)
        return request

    async def _handle_http_status_failure(
        self,
        *,
        status_code: int,
        attempt: int,
        headers: Mapping[str, Any] | None,
        request_ms: float,
        batch_started: float,
        masked_agent_id: str,
        masked_idempotency_key: str,
    ) -> bool:
        if status_code == 429 and self._should_retry(status_code=status_code, attempt=attempt):
            await self._sleep_for_retry_after(
                attempt=attempt,
                headers=headers,
                request_ms=request_ms,
                batch_started=batch_started,
                masked_agent_id=masked_agent_id,
                masked_idempotency_key=masked_idempotency_key,
            )
            return True

        if self._should_retry(status_code=status_code, attempt=attempt):
            self._log_retry(
                status_code=status_code,
                attempt=attempt,
                request_ms=request_ms,
                reason=f"http_status={status_code}",
                masked_agent_id=masked_agent_id,
                masked_idempotency_key=masked_idempotency_key,
            )
            await self._sleep_before_retry(attempt=attempt)
            return True

        self._log_auth_failed(
            status_code=status_code,
            attempt=attempt,
            request_ms=request_ms,
            total_batch_export_ms=(time.monotonic() - batch_started) * 1000.0,
            masked_agent_id=masked_agent_id,
            masked_idempotency_key=masked_idempotency_key,
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
        masked_idempotency_key: str,
    ) -> bool:
        if exc.code == 429 and self._should_retry(status_code=exc.code, attempt=attempt):
            await self._sleep_for_retry_after(
                attempt=attempt,
                headers=exc.headers,
                request_ms=request_ms,
                batch_started=batch_started,
                masked_agent_id=masked_agent_id,
                masked_idempotency_key=masked_idempotency_key,
            )
            return True

        if self._should_retry(status_code=exc.code, attempt=attempt):
            self._log_retry(
                status_code=exc.code,
                attempt=attempt,
                request_ms=request_ms,
                reason=f"http_status={exc.code}",
                masked_agent_id=masked_agent_id,
                masked_idempotency_key=masked_idempotency_key,
            )
            await self._sleep_before_retry(attempt=attempt)
            return True

        self._log_auth_failed(
            status_code=exc.code,
            attempt=attempt,
            request_ms=request_ms,
            total_batch_export_ms=(time.monotonic() - batch_started) * 1000.0,
            masked_agent_id=masked_agent_id,
            masked_idempotency_key=masked_idempotency_key,
        )
        return False

    def _should_retry(self, *, status_code: int | None, attempt: int) -> bool:
        if attempt >= self._retry_max_attempts:
            return False
        if status_code is None:
            return True
        return self._is_retryable_status_code(status_code)

    @staticmethod
    def _is_retryable_status_code(status_code: int) -> bool:
        if status_code in _RETRYABLE_HTTP_STATUS_CODES:
            return True
        return status_code >= 500 and status_code <= 599

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
        attempt: int,
        headers: Mapping[str, Any] | None,
        request_ms: float,
        batch_started: float,
        masked_agent_id: str,
        masked_idempotency_key: str,
    ) -> None:
        retry_after = parse_retry_after_delay(
            headers=headers,
            default_seconds=self._retry_after_default_seconds,
            max_seconds=self._retry_after_max_seconds,
        )
        self._logger_warning(
            "OTLP export rate limited; endpoint=%s status=429 attempt=%s max_attempts=%s "
            "retry_after_seconds=%s retry_after_source=%s retry_after_default_used=%s "
            "retry_after_capped=%s retry_after_parse_ms=%.3f retry_after_sleep_seconds=%s "
            "retry_request_ms=%.3f total_batch_export_ms=%.3f x_agent_id=%s "
            "x_idempotency_key=%s",
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
            masked_idempotency_key,
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
        masked_idempotency_key: str,
    ) -> None:
        next_attempt = attempt + 1
        self._logger_debug(
            "OTLP export retry scheduled; endpoint=%s status=%s attempt=%s max_attempts=%s "
            "retry_request_ms=%.3f next_attempt=%s reason=%s x_agent_id=%s "
            "x_idempotency_key=%s",
            self._endpoint,
            status_code,
            attempt,
            self._retry_max_attempts,
            request_ms,
            next_attempt,
            reason,
            masked_agent_id,
            masked_idempotency_key,
        )

    def _validate_endpoint(self) -> None:
        parsed = urlparse(self._endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(
                f"Invalid OTLP HTTP endpoint '{self._endpoint}'. "
                "Expected absolute http/https URL."
            )

    def _validate_retry_policy(self) -> None:
        if self._timeout_seconds <= 0:
            raise RuntimeError("OTLP HTTP timeout_seconds must be greater than zero.")
        if self._retry_max_attempts <= 0:
            raise RuntimeError("OTLP HTTP retry_max_attempts must be greater than zero.")
        if self._retry_initial_backoff_seconds <= 0:
            raise RuntimeError(
                "OTLP HTTP retry_initial_backoff_seconds must be greater than zero."
            )
        if self._retry_max_backoff_seconds <= 0:
            raise RuntimeError(
                "OTLP HTTP retry_max_backoff_seconds must be greater than zero."
            )
        if self._retry_after_default_seconds < 0:
            raise RuntimeError(
                "OTLP retry_after_default_seconds must be greater than or equal to zero."
            )
        if self._retry_after_max_seconds <= 0:
            raise RuntimeError(
                "OTLP retry_after_max_seconds must be greater than zero."
            )

    def _log_auth_failed(
        self,
        *,
        status_code: int,
        attempt: int,
        request_ms: float,
        total_batch_export_ms: float,
        masked_agent_id: str,
        masked_idempotency_key: str,
    ) -> None:
        if status_code in (401, 403):
            self._logger_debug(
                "OTLP export failed; endpoint=%s status=%s attempt=%s max_attempts=%s "
                "retry_request_ms=%.3f total_batch_export_ms=%.3f x_agent_id=%s "
                "x_idempotency_key=%s error=auth_headers_rejected",
                self._endpoint,
                status_code,
                attempt,
                self._retry_max_attempts,
                request_ms,
                total_batch_export_ms,
                masked_agent_id,
                masked_idempotency_key,
            )
            return
        self._logger_debug(
            "OTLP export failed; endpoint=%s status=%s attempt=%s max_attempts=%s "
            "retry_request_ms=%.3f total_batch_export_ms=%.3f x_agent_id=%s "
            "x_idempotency_key=%s",
            self._endpoint,
            status_code,
            attempt,
            self._retry_max_attempts,
            request_ms,
            total_batch_export_ms,
            masked_agent_id,
            masked_idempotency_key,
        )

    def _log_success(
        self,
        *,
        status_code: int,
        attempt: int,
        request_ms: float,
        total_batch_export_ms: float,
        masked_agent_id: str,
        masked_idempotency_key: str,
    ) -> None:
        if self._headers:
            self._logger_info(
                "OTLP export completed; endpoint=%s status=%s attempt=%s retry_request_ms=%.3f "
                "total_batch_export_ms=%.3f x_agent_id=%s x_idempotency_key=%s",
                self._endpoint,
                status_code,
                attempt,
                request_ms,
                total_batch_export_ms,
                masked_agent_id,
                masked_idempotency_key,
            )

    def _create_idempotency_key(self) -> str:
        try:
            return str(uuid.uuid4())
        except Exception as exc:  # pragma: no cover - defensive guardrail
            self._logger_error(
                "OTLP export skipped; endpoint=%s status=not_sent attempt=0 max_attempts=%s "
                "error=idempotency_key_generation_failed",
                self._endpoint,
                self._retry_max_attempts,
            )
            raise RuntimeError(
                "OTLP HTTP export failed to generate x-idempotency-key; batch not dispatched."
            ) from exc

    def _ensure_agent_id_configured(self, *, masked_agent_id: str) -> None:
        agent_id = self._headers.get("x-agent-id")
        if agent_id:
            return

        self._logger_error(
            "OTLP export skipped; endpoint=%s status=not_sent attempt=0 max_attempts=%s "
            "x_agent_id=%s error=missing_x_agent_id",
            self._endpoint,
            self._retry_max_attempts,
            masked_agent_id,
        )
        raise RuntimeError("OTLP HTTP export missing x-agent-id; batch not dispatched.")

    def _masked_agent_id(self) -> str:
        return mask_identifier(self._headers.get("x-agent-id"))

    def _logger_info(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.info(message, *args)

    def _logger_debug(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.debug(message, *args)

    def _logger_warning(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.warning(message, *args)

    def _logger_error(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.error(message, *args)


class OtlpHttpExporter(Exporter):
    """Exporter that maps canonical metrics and sends OTLP HTTP requests."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        mapper: OtlpPayloadMapper | None = None,
        sender: OtlpHttpMetricSender | None = None,
        headers: Mapping[str, str] | None = None,
        resource_attributes: Mapping[str, str] | None = None,
        include_heka_intelligence_headers: bool = False,
        background_dispatch: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._mapper = mapper
        self._sender = sender
        self._headers = dict(headers) if headers is not None else None
        self._resource_attributes = (
            dict(resource_attributes) if resource_attributes is not None else None
        )
        self._include_heka_intelligence_headers = include_heka_intelligence_headers
        self._background_dispatch = background_dispatch
        self._dispatch_worker: BackgroundPayloadDispatcher | None = None
        self._dispatch_shutdown_event: threading.Event | None = None
        self._logger = logger
        self._initialized = False

    def initialize(self) -> None:
        """Resolve configuration and prepare OTLP sender."""
        resolved_endpoint = self._endpoint or get_otlp_http_endpoint(logger=self._logger)
        self._endpoint = resolved_endpoint

        resolved_headers = self._headers
        if resolved_headers is None:
            resolved_headers = get_otlp_http_headers(logger=self._logger)
        else:
            resolved_headers = dict(resolved_headers)

        if self._include_heka_intelligence_headers:
            if get_heka_intelligence_enabled(logger=self._logger):
                api_key = get_heka_api_key(logger=self._logger)
                if api_key is None:
                    raise RuntimeError(
                        "HEKA_API_KEY is required when EXPORTER_TYPE=otlp_http "
                        "and HEKA_INTELLIGENCE_ENABLED=true."
                    )
                agent_id = get_heka_agent_id(logger=self._logger)
                if agent_id is not None:
                    resolved_headers["x-agent-id"] = agent_id
                resolved_headers["x-api-key"] = api_key
            else:
                resolved_headers.update(get_heka_intelligence_headers(logger=self._logger))

        agent_id = get_heka_agent_id(logger=self._logger)
        if agent_id is not None:
            resolved_headers["x-agent-id"] = agent_id
        self._headers = resolved_headers

        resolved_resource_attributes = self._resource_attributes
        if resolved_resource_attributes is None:
            resolved_resource_attributes = get_otlp_resource_attributes(logger=self._logger)
            self._resource_attributes = resolved_resource_attributes

        if self._mapper is None:
            self._mapper = OtlpPayloadMapper(
                resource_attributes=resolved_resource_attributes,
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
            self._sender = OtlpHttpMetricSender(
                endpoint=resolved_endpoint,
                timeout_seconds=timeout_seconds,
                retry_max_attempts=retry_max_attempts,
                retry_initial_backoff_seconds=retry_initial_backoff_seconds,
                retry_max_backoff_seconds=retry_max_backoff_seconds,
                retry_after_default_seconds=retry_after_default_seconds,
                retry_after_max_seconds=retry_after_max_seconds,
                headers=resolved_headers,
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
                worker_name="otlp-http-export",
                shutdown_event=self._dispatch_shutdown_event,
                logger=self._logger,
            )
        self._initialized = True

    def export(self, metrics: CanonicalMetricCollection) -> None:
        """Export canonical metrics via OTLP HTTP."""
        if not self._initialized:
            raise RuntimeError("OtlpHttpExporter must be initialized before export().")
        if self._sender is None:
            raise RuntimeError("OtlpHttpExporter sender is not initialized.")
        if self._mapper is None:
            raise RuntimeError("OtlpHttpExporter mapper is not initialized.")

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
            "headers_configured": len(self._headers or {}),
            "resource_attributes_configured": len(self._resource_attributes or {}),
        }
