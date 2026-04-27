"""OTLP HTTP sender and exporter implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import get_otlp_http_endpoint

from .base import CanonicalMetricCollection, Exporter
from .otlp_mapping import OtlpPayloadMapper

_DEFAULT_TIMEOUT_SECONDS = 10


class OtlpHttpMetricSender:
    """Send OTLP metrics payloads to an HTTP endpoint."""

    def __init__(
        self,
        *,
        endpoint: str,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        headers: Mapping[str, str] | None = None,
        http_client: Callable[..., Any] | None = None,
    ) -> None:
        self._endpoint = endpoint.strip()
        self._timeout_seconds = timeout_seconds
        self._headers = dict(headers or {})
        self._http_client = http_client or urlopen
        self._validate_endpoint()

    def send(self, payload: Mapping[str, Any]) -> None:
        """Dispatch payload as an OTLP HTTP POST request."""
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(url=self._endpoint, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        for key, value in self._headers.items():
            request.add_header(key, value)

        try:
            with self._http_client(request, timeout=self._timeout_seconds) as response:
                status_code = getattr(response, "status", None)
                if status_code is None:
                    status_code = response.getcode()
                if status_code < 200 or status_code >= 300:
                    raise RuntimeError(
                        "OTLP HTTP export failed with non-success status code "
                        f"{status_code}."
                    )
        except HTTPError as exc:
            raise RuntimeError(
                f"OTLP HTTP export failed with HTTP error {exc.code}: {exc.reason}."
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"OTLP HTTP export failed to reach endpoint '{self._endpoint}': "
                f"{exc.reason}."
            ) from exc

    def _validate_endpoint(self) -> None:
        parsed = urlparse(self._endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(
                f"Invalid OTLP HTTP endpoint '{self._endpoint}'. "
                "Expected absolute http/https URL."
            )


class OtlpHttpExporter(Exporter):
    """Exporter that maps canonical metrics and sends OTLP HTTP requests."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        mapper: OtlpPayloadMapper | None = None,
        sender: OtlpHttpMetricSender | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._mapper = mapper or OtlpPayloadMapper()
        self._sender = sender
        self._logger = logger
        self._initialized = False

    def initialize(self) -> None:
        """Resolve configuration and prepare OTLP sender."""
        if self._sender is None:
            resolved_endpoint = self._endpoint or get_otlp_http_endpoint(logger=self._logger)
            self._endpoint = resolved_endpoint
            self._sender = OtlpHttpMetricSender(endpoint=resolved_endpoint)
        self._initialized = True

    def export(self, metrics: CanonicalMetricCollection) -> None:
        """Export canonical metrics via OTLP HTTP."""
        if not self._initialized:
            raise RuntimeError("OtlpHttpExporter must be initialized before export().")
        if self._sender is None:
            raise RuntimeError("OtlpHttpExporter sender is not initialized.")

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
        }
