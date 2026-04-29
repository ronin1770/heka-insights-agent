"""OTLP HTTP sender and exporter implementation."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import (
    get_otlp_http_endpoint,
    get_otlp_http_headers,
    get_otlp_http_retry_initial_backoff_seconds,
    get_otlp_http_retry_max_attempts,
    get_otlp_http_retry_max_backoff_seconds,
    get_otlp_http_timeout_seconds,
    get_otlp_resource_attributes,
)

from .base import CanonicalMetricCollection, Exporter
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
        headers: Mapping[str, str] | None = None,
        http_client: Callable[..., Any] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
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
        self._headers = dict(headers or {})
        self._http_client = http_client or urlopen
        self._sleep_fn = sleep_fn or time.sleep
        self._logger = logger
        self._validate_retry_policy()
        self._validate_endpoint()

    def send(self, payload: Mapping[str, Any]) -> None:
        """Dispatch payload as an OTLP HTTP POST request."""
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        for attempt in range(1, self._retry_max_attempts + 1):
            request = self._build_request(body)
            try:
                with self._http_client(request, timeout=self._timeout_seconds) as response:
                    status_code = getattr(response, "status", None)
                    if status_code is None:
                        status_code = response.getcode()
                    if status_code >= 200 and status_code < 300:
                        if self._headers:
                            self._logger_info(
                                "OTLP auth headers accepted by endpoint '%s' (status=%s, attempt=%s).",
                                self._endpoint,
                                status_code,
                                attempt,
                            )
                        return

                    self._handle_http_status_failure(
                        status_code=status_code,
                        attempt=attempt,
                    )
            except HTTPError as exc:
                if self._should_retry(status_code=exc.code, attempt=attempt):
                    self._log_retry(
                        attempt=attempt,
                        reason=f"http_status={exc.code}",
                    )
                    self._sleep_before_retry(attempt=attempt)
                    continue

                self._log_auth_failed(status_code=exc.code)
                raise RuntimeError(
                    f"OTLP HTTP export failed with HTTP error {exc.code}: {exc.reason}."
                ) from exc
            except URLError as exc:
                if self._should_retry(status_code=None, attempt=attempt):
                    self._log_retry(
                        attempt=attempt,
                        reason=f"transport_error={exc.reason}",
                    )
                    self._sleep_before_retry(attempt=attempt)
                    continue

                self._logger_debug(
                    "OTLP auth/header request failed for endpoint '%s': %s",
                    self._endpoint,
                    exc.reason,
                )
                raise RuntimeError(
                    f"OTLP HTTP export failed to reach endpoint '{self._endpoint}': "
                    f"{exc.reason}."
                ) from exc

    def _build_request(self, body: bytes) -> Request:
        request = Request(url=self._endpoint, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        for key, value in self._headers.items():
            request.add_header(key, value)
        return request

    def _handle_http_status_failure(self, *, status_code: int, attempt: int) -> None:
        if self._should_retry(status_code=status_code, attempt=attempt):
            self._log_retry(
                attempt=attempt,
                reason=f"http_status={status_code}",
            )
            self._sleep_before_retry(attempt=attempt)
            return

        self._log_auth_failed(status_code=status_code)
        raise RuntimeError(
            "OTLP HTTP export failed with non-success status code "
            f"{status_code}."
        )

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

    def _sleep_before_retry(self, *, attempt: int) -> None:
        backoff_seconds = min(
            self._retry_max_backoff_seconds,
            self._retry_initial_backoff_seconds
            * (_RETRY_BACKOFF_MULTIPLIER ** (attempt - 1)),
        )
        self._sleep_fn(backoff_seconds)

    def _log_retry(self, *, attempt: int, reason: str) -> None:
        next_attempt = attempt + 1
        self._logger_debug(
            "OTLP export retry scheduled for endpoint '%s' (attempt %s/%s, reason=%s).",
            self._endpoint,
            next_attempt,
            self._retry_max_attempts,
            reason,
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

    def _log_auth_failed(self, *, status_code: int) -> None:
        if status_code in (401, 403):
            self._logger_debug(
                "OTLP auth headers rejected by endpoint '%s' (status=%s).",
                self._endpoint,
                status_code,
            )
            return
        self._logger_debug(
            "OTLP request with auth headers failed for endpoint '%s' (status=%s).",
            self._endpoint,
            status_code,
        )

    def _logger_info(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.info(message, *args)

    def _logger_debug(self, message: str, *args: Any) -> None:
        if self._logger is not None:
            self._logger.debug(message, *args)


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
        logger: logging.Logger | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._mapper = mapper
        self._sender = sender
        self._headers = dict(headers) if headers is not None else None
        self._resource_attributes = (
            dict(resource_attributes) if resource_attributes is not None else None
        )
        self._logger = logger
        self._initialized = False

    def initialize(self) -> None:
        """Resolve configuration and prepare OTLP sender."""
        resolved_endpoint = self._endpoint or get_otlp_http_endpoint(logger=self._logger)
        self._endpoint = resolved_endpoint

        resolved_headers = self._headers
        if resolved_headers is None:
            resolved_headers = get_otlp_http_headers(logger=self._logger)
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
            self._sender = OtlpHttpMetricSender(
                endpoint=resolved_endpoint,
                timeout_seconds=timeout_seconds,
                retry_max_attempts=retry_max_attempts,
                retry_initial_backoff_seconds=retry_initial_backoff_seconds,
                retry_max_backoff_seconds=retry_max_backoff_seconds,
                headers=resolved_headers,
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
        self._sender.send(payload)

    def shutdown(self) -> None:
        """Release exporter resources."""
        self._initialized = False

    def health_status(self) -> dict[str, Any] | None:
        """Return exporter health details."""
        return {
            "initialized": self._initialized,
            "endpoint": self._endpoint,
            "headers_configured": len(self._headers or {}),
            "resource_attributes_configured": len(self._resource_attributes or {}),
        }
