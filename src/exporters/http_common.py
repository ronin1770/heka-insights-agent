"""Shared HTTP retry, accounting, and bounded dispatch helpers."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any

SleepFn = Callable[[float], Awaitable[None] | None]


class ShutdownRequestedError(RuntimeError):
    """Raised when an export wait is interrupted by shutdown."""


class BatchExpiredError(RuntimeError):
    """Raised when a batch exceeds its configured lifetime."""


@dataclass(frozen=True)
class RetryAfterDelay:
    seconds: float
    source: str
    default_used: bool
    capped: bool
    parse_ms: float


@dataclass(frozen=True)
class SerializedBatch:
    body: bytes
    byte_count: int
    record_count: int
    enqueued_at: float


class ExportStatistics:
    """Thread-safe process-lifetime exporter counters and gauges."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()
        self._gauges: dict[str, Any] = {
            "pending_batches": 0, "pending_bytes": 0,
            "in_flight_batches": 0, "in_flight_bytes": 0,
            "oldest_pending_age_seconds": 0.0,
            "max_retained_batches": 0, "max_retained_bytes": 0,
            "cooldown_active": False, "cooldown_remaining_seconds": 0.0,
            "last_success_unix_seconds": None,
        }

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def record_outcome(self, prefix: str, batch: SerializedBatch) -> None:
        with self._lock:
            self._counters[f"{prefix}_batches"] += 1
            self._counters[f"{prefix}_records"] += batch.record_count
            self._counters[f"{prefix}_bytes"] += batch.byte_count

    def update_queue(self, *, pending_batches: int, pending_bytes: int,
                     in_flight_batches: int, in_flight_bytes: int,
                     oldest_pending_age_seconds: float) -> None:
        with self._lock:
            retained_batches = pending_batches + in_flight_batches
            retained_bytes = pending_bytes + in_flight_bytes
            self._gauges.update({
                "pending_batches": pending_batches, "pending_bytes": pending_bytes,
                "in_flight_batches": in_flight_batches,
                "in_flight_bytes": in_flight_bytes,
                "oldest_pending_age_seconds": oldest_pending_age_seconds,
                "max_retained_batches": max(self._gauges["max_retained_batches"], retained_batches),
                "max_retained_bytes": max(self._gauges["max_retained_bytes"], retained_bytes),
            })

    def update_cooldown(self, *, active: bool, remaining_seconds: float) -> None:
        with self._lock:
            self._gauges["cooldown_active"] = active
            self._gauges["cooldown_remaining_seconds"] = max(0.0, remaining_seconds)

    def record_success_time(self) -> None:
        with self._lock:
            self._gauges["last_success_unix_seconds"] = time.time()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"counters": dict(self._counters), "gauges": dict(self._gauges)}


class EndpointCooldown:
    """Cooldown shared by all batches sent through one sender/endpoint."""

    def __init__(self, *, enabled: bool, statistics: ExportStatistics | None = None) -> None:
        self._enabled = enabled
        self._statistics = statistics
        self._lock = threading.Lock()
        self._deadline = 0.0

    def activate(self, seconds: float) -> None:
        if not self._enabled or seconds <= 0:
            return
        with self._lock:
            self._deadline = max(self._deadline, time.monotonic() + seconds)
            self._publish_locked()

    def remaining(self) -> float:
        if not self._enabled:
            return 0.0
        with self._lock:
            value = max(0.0, self._deadline - time.monotonic())
            if value == 0:
                self._deadline = 0.0
            self._publish_locked(value)
            return value

    def complete_wait(self) -> None:
        with self._lock:
            self._deadline = 0.0
            self._publish_locked(0.0)

    def _publish_locked(self, remaining: float | None = None) -> None:
        if self._statistics is not None:
            value = max(0.0, self._deadline - time.monotonic()) if remaining is None else remaining
            self._statistics.update_cooldown(active=value > 0, remaining_seconds=value)


def get_header_case_insensitive(headers: Mapping[str, Any] | None,
                                header_name: str) -> str | None:
    if headers is None:
        return None
    target = header_name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return str(value).strip()
    return None


def mask_identifier(value: str | None) -> str:
    if not value:
        return "missing"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def parse_retry_after_delay(*, headers: Mapping[str, Any] | None,
                            default_seconds: int, max_seconds: int,
                            wall_time_fn: Callable[[], float] | None = None) -> RetryAfterDelay:
    """Parse delay-seconds or an HTTP-date and clamp it to the configured maximum."""
    started = time.monotonic()
    raw = get_header_case_insensitive(headers, "Retry-After")
    source, default_used, capped = "header", False, False
    seconds = float(default_seconds)
    if not raw:
        source, default_used = "default", True
    else:
        try:
            seconds = float(int(raw))
            if seconds < 0:
                raise ValueError
        except ValueError:
            try:
                parsed = parsedate_to_datetime(raw)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                seconds = max(0.0, parsed.timestamp() - (wall_time_fn or time.time)())
                source = "http-date"
            except (TypeError, ValueError, OverflowError):
                source, default_used, seconds = "default", True, float(default_seconds)
    if seconds > max_seconds:
        seconds, capped = float(max_seconds), True
    return RetryAfterDelay(seconds, source, default_used, capped,
                           (time.monotonic() - started) * 1000.0)


async def sleep_with_shutdown(*, seconds: float, shutdown_event: threading.Event,
                              sleep_fn: SleepFn | None = None) -> None:
    if seconds <= 0:
        return
    if sleep_fn is not None:
        if shutdown_event.is_set():
            raise ShutdownRequestedError("Shutdown requested during export retry wait.")
        result = sleep_fn(seconds)
        if inspect.isawaitable(result):
            await result
        if shutdown_event.is_set():
            raise ShutdownRequestedError("Shutdown requested during export retry wait.")
        return
    deadline = time.monotonic() + seconds
    while True:
        if shutdown_event.is_set():
            raise ShutdownRequestedError("Shutdown requested during export retry wait.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(remaining, 0.25))


class BackgroundPayloadDispatcher:
    """Serialize once and dispatch through a bounded, thread-safe queue."""

    def __init__(self, *, sender: Any, worker_name: str,
                 shutdown_event: threading.Event, max_batches: int = 64,
                 max_bytes: int = 8 * 1024 * 1024,
                 max_batch_age_seconds: float = 120.0,
                 shutdown_timeout_seconds: float = 5.0,
                 statistics: ExportStatistics | None = None,
                 logger: logging.Logger | None = None,
                 monotonic_fn: Callable[[], float] | None = None) -> None:
        if min(max_batches, max_bytes) <= 0 or max_batch_age_seconds <= 0:
            raise ValueError("Dispatcher capacity and age limits must be positive.")
        if shutdown_timeout_seconds <= 0:
            raise ValueError("Dispatcher shutdown timeout must be positive.")
        self._sender, self._worker_name = sender, worker_name
        self._shutdown_event, self._logger = shutdown_event, logger
        self._max_batches, self._max_bytes = max_batches, max_bytes
        self._max_batch_age_seconds = max_batch_age_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._statistics = statistics or ExportStatistics()
        self._monotonic = monotonic_fn or time.monotonic
        self._condition = threading.Condition()
        self._pending: deque[SerializedBatch] = deque()
        self._pending_bytes = 0
        self._in_flight: SerializedBatch | None = None
        self._thread = threading.Thread(target=self._run, name=worker_name, daemon=True)
        self._started = self._stopping = False
        self._last_warning: dict[str, float] = {}

    @property
    def statistics(self) -> ExportStatistics:
        return self._statistics

    def submit(self, payload: Mapping[str, Any], *, record_count: int = 0) -> bool:
        self._statistics.increment("submitted_batches")
        self._statistics.increment("submitted_records", max(0, record_count))
        with self._condition:
            if self._stopping or self._shutdown_event.is_set():
                self._statistics.increment("other_pre_admission_rejected_batches")
                self._statistics.increment(
                    "other_pre_admission_rejected_records", max(0, record_count)
                )
                raise RuntimeError("Exporter is shutting down; cannot queue new payloads.")
        try:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as exc:
            self._statistics.increment("serialization_rejected_batches")
            self._statistics.increment("serialization_rejected_records", max(0, record_count))
            if self._logger:
                self._logger.error("%s serialization rejected; error=%s", self._worker_name, exc)
            return False
        batch = SerializedBatch(body, len(body), max(0, record_count), self._monotonic())
        if batch.byte_count > self._max_bytes:
            self._statistics.record_outcome("oversized_rejected", batch)
            if self._logger:
                self._logger.warning("%s oversized payload rejected; bytes=%s max_bytes=%s records=%s",
                                     self._worker_name, batch.byte_count, self._max_bytes,
                                     batch.record_count)
            return False
        with self._condition:
            if self._stopping or self._shutdown_event.is_set():
                self._statistics.record_outcome("other_pre_admission_rejected", batch)
                raise RuntimeError("Exporter is shutting down; cannot queue new payloads.")
            self._expire_locked()
            while self._over_capacity_locked(batch) and self._pending:
                self._drop_locked("capacity_dropped")
            if self._over_capacity_locked(batch):
                self._statistics.record_outcome("capacity_dropped", batch)
                self._warn_locked(
                    "capacity",
                    "%s payload rejected because in-flight data occupies queue capacity",
                    self._worker_name,
                )
                self._publish_locked()
                return False
            self._pending.append(batch)
            self._pending_bytes += batch.byte_count
            self._statistics.record_outcome("accepted", batch)
            self._publish_locked()
            if not self._started:
                self._thread.start()
                self._started = True
            self._condition.notify()
        return True

    def snapshot(self) -> dict[str, Any]:
        refresh = getattr(self._sender, "refresh_diagnostics", None)
        if callable(refresh):
            refresh()
        with self._condition:
            self._expire_locked()
            self._publish_locked()
        return self._statistics.snapshot()

    def shutdown(self) -> None:
        with self._condition:
            if self._stopping:
                return
            self._stopping = True
            while self._pending:
                self._drop_locked("shutdown_dropped")
            self._shutdown_event.set()
            self._publish_locked()
            self._condition.notify_all()
        if self._started:
            self._thread.join(timeout=self._shutdown_timeout_seconds)
            if self._thread.is_alive() and self._logger:
                self._logger.warning("%s shutdown timed out; in-flight HTTP may continue until socket timeout",
                                     self._worker_name)

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._stopping:
                    self._condition.wait()
                if self._stopping and not self._pending:
                    return
                self._expire_locked()
                if not self._pending:
                    continue
                current = self._pending.popleft()
                self._pending_bytes -= current.byte_count
                self._in_flight = current
                self._publish_locked()
            outcome = "permanently_failed"
            try:
                send_serialized = getattr(self._sender, "send_serialized", None)
                if callable(send_serialized):
                    send_serialized(
                        current.body,
                        expires_at=current.enqueued_at + self._max_batch_age_seconds,
                    )
                else:  # compatibility for injected legacy sender implementations
                    self._sender.send(json.loads(current.body.decode("utf-8")))
                outcome = "successful"
            except BatchExpiredError:
                outcome = "expired"
            except ShutdownRequestedError:
                outcome = "shutdown_dropped"
            except Exception as exc:  # defensive worker boundary
                if self._logger:
                    self._logger.error("%s payload failed; error=%s", self._worker_name, exc)
            finally:
                self._statistics.record_outcome(outcome, current)
                if outcome == "successful":
                    self._statistics.record_success_time()
                with self._condition:
                    self._in_flight = None
                    self._publish_locked()
                    self._condition.notify_all()

    def _over_capacity_locked(self, batch: SerializedBatch) -> bool:
        active_count = 1 if self._in_flight else 0
        active_bytes = self._in_flight.byte_count if self._in_flight else 0
        return (len(self._pending) + active_count + 1 > self._max_batches or
                self._pending_bytes + active_bytes + batch.byte_count > self._max_bytes)

    def _drop_locked(self, outcome: str) -> None:
        batch = self._pending.popleft()
        self._pending_bytes -= batch.byte_count
        self._statistics.record_outcome(outcome, batch)
        self._warn_locked(
            outcome,
            "%s payload discarded; reason=%s bytes=%s records=%s",
            self._worker_name, outcome, batch.byte_count, batch.record_count,
        )

    def _warn_locked(self, key: str, message: str, *args: Any) -> None:
        if self._logger is None:
            return
        now = self._monotonic()
        if now - self._last_warning.get(key, float("-inf")) >= 60.0:
            self._last_warning[key] = now
            self._logger.warning(message, *args)

    def _expire_locked(self) -> None:
        cutoff = self._monotonic() - self._max_batch_age_seconds
        while self._pending and self._pending[0].enqueued_at <= cutoff:
            self._drop_locked("expired")

    def _publish_locked(self) -> None:
        self._statistics.update_queue(
            pending_batches=len(self._pending), pending_bytes=self._pending_bytes,
            in_flight_batches=1 if self._in_flight else 0,
            in_flight_bytes=self._in_flight.byte_count if self._in_flight else 0,
            oldest_pending_age_seconds=(
                max(0.0, self._monotonic() - self._pending[0].enqueued_at)
                if self._pending else 0.0
            ),
        )
