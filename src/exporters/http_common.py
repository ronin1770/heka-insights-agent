"""Shared HTTP export retry and dispatch helpers."""

from __future__ import annotations

import asyncio
import inspect
import logging
import queue
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

SleepFn = Callable[[float], Awaitable[None] | None]


class ShutdownRequestedError(RuntimeError):
    """Raised when an export wait is interrupted by shutdown."""


@dataclass(frozen=True)
class RetryAfterDelay:
    """Normalized Retry-After timing details."""

    seconds: int
    source: str
    default_used: bool
    capped: bool
    parse_ms: float


def get_header_case_insensitive(
    headers: Mapping[str, Any] | None,
    header_name: str,
) -> str | None:
    """Return one header value regardless of header casing."""
    if headers is None:
        return None

    target = header_name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return str(value).strip()
    return None


def mask_identifier(value: str | None) -> str:
    """Mask identifier values before logging."""
    if not value:
        return "missing"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def parse_retry_after_delay(
    *,
    headers: Mapping[str, Any] | None,
    default_seconds: int,
    max_seconds: int,
) -> RetryAfterDelay:
    """Parse and clamp Retry-After seconds from response headers."""
    started = time.monotonic()
    raw_value = get_header_case_insensitive(headers, "Retry-After")
    source = "header"
    default_used = False
    capped = False
    seconds = default_seconds

    if raw_value is None or raw_value == "":
        source = "default"
        default_used = True
    else:
        try:
            parsed = int(raw_value)
            if parsed < 0:
                raise ValueError("negative retry-after")
            seconds = parsed
        except ValueError:
            source = "default"
            default_used = True

    if seconds > max_seconds:
        seconds = max_seconds
        capped = True

    parse_ms = (time.monotonic() - started) * 1000.0
    return RetryAfterDelay(
        seconds=seconds,
        source=source,
        default_used=default_used,
        capped=capped,
        parse_ms=parse_ms,
    )


async def sleep_with_shutdown(
    *,
    seconds: float,
    shutdown_event: threading.Event,
    sleep_fn: SleepFn | None = None,
) -> None:
    """Sleep in short async intervals so shutdown can interrupt waits."""
    if seconds <= 0:
        return

    if sleep_fn is not None:
        if shutdown_event.is_set():
            raise ShutdownRequestedError("Shutdown requested during export retry wait.")
        maybe_awaitable = sleep_fn(seconds)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
        if shutdown_event.is_set():
            raise ShutdownRequestedError("Shutdown requested during export retry wait.")
        return

    resolved_sleep_fn = asyncio.sleep
    deadline = time.monotonic() + seconds
    while True:
        if shutdown_event.is_set():
            raise ShutdownRequestedError("Shutdown requested during export retry wait.")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return

        step_seconds = min(remaining, 0.25)
        maybe_awaitable = resolved_sleep_fn(step_seconds)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable


class BackgroundPayloadDispatcher:
    """Dispatch payloads on a dedicated worker thread."""

    def __init__(
        self,
        *,
        sender: Any,
        worker_name: str,
        shutdown_event: threading.Event,
        logger: logging.Logger | None = None,
    ) -> None:
        self._sender = sender
        self._worker_name = worker_name
        self._shutdown_event = shutdown_event
        self._logger = logger
        self._queue: queue.Queue[Mapping[str, Any] | None] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run,
            name=worker_name,
            daemon=True,
        )
        self._started = False

    def submit(self, payload: Mapping[str, Any]) -> None:
        """Queue one payload for background dispatch."""
        if self._shutdown_event.is_set():
            raise RuntimeError("Exporter is shutting down; cannot queue new payloads.")
        if not self._started:
            self._thread.start()
            self._started = True
        self._queue.put(dict(payload))

    def shutdown(self) -> None:
        """Stop the worker and interrupt any pending retry wait."""
        self._shutdown_event.set()
        if self._started:
            self._queue.put(None)
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while True:
            payload = self._queue.get()
            if payload is None:
                return

            try:
                self._sender.send(payload)
            except ShutdownRequestedError:
                return
            except Exception as exc:  # pragma: no cover - defensive guardrail
                if self._logger is not None:
                    self._logger.error(
                        "%s payload failed; error=%s",
                        self._worker_name,
                        exc,
                    )
