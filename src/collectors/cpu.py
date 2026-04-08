"""Collect CPU telemetry with low overhead at fixed polling intervals."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

import psutil

MetricDetail = Literal["basic", "detailed"]

_IDLE_FIELDS = frozenset({"idle", "iowait"})
_EPSILON = 1e-12


@dataclass
class MonotonicTicker:
    """Run a fixed-interval loop anchored to monotonic time.

    This ticker reduces drift by scheduling each cycle from the prior
    target time rather than from when the current cycle finishes.
    """

    interval_seconds: float
    _next_run: float = field(default_factory=time.monotonic, init=False)

    def __post_init__(self) -> None:
        """Validate ticker configuration after dataclass initialization."""
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")

    def next_delay(self, now: float | None = None) -> float:
        """Return the delay until the next scheduled run.

        The next run is anchored to monotonic time so the loop stays on a
        stable cadence even when individual collection cycles vary slightly
        in execution time.
        """
        self._next_run += self.interval_seconds
        current = time.monotonic() if now is None else now
        return max(0.0, self._next_run - current)

    def sleep(self) -> None:
        """Block until the next scheduled cycle."""
        delay = self.next_delay()
        if delay > 0:
            # Skip sleeping when the loop is already behind schedule.
            time.sleep(delay)


class CPUCollector:
    """Collect CPU usage metrics from one psutil sampling source.

    Notes:
    - Uses ``psutil.cpu_times`` snapshots and delta math to derive utilization.
    - First call always returns a warm-up payload.
    - If CPU core count changes between polls, collector resets baseline and warms up.
    """

    def __init__(
        self,
        *,
        per_cpu: bool = False,
        detail: MetricDetail = "basic",
        round_digits: int | None = 2,
    ) -> None:
        if detail not in ("basic", "detailed"):
            raise ValueError("detail must be 'basic' or 'detailed'")

        self._per_cpu = per_cpu
        self._detail = detail
        self._round_digits = round_digits
        self._previous: list[dict[str, float]] | None = None
        self._field_names: tuple[str, ...] | None = None

    def collect(self) -> dict[str, Any]:
        """Return CPU metrics for the current polling cycle.

        The first cycle is a warm-up because utilization is derived from
        deltas between consecutive snapshots.
        """
        current = self._read_snapshot()

        if self._previous is None:
            self._previous = current
            return self._warmup_payload()

        if len(current) != len(self._previous):
            self._previous = current
            return self._warmup_payload()

        include_breakdown = self._detail == "detailed"
        per_core = [
            self._compute_core(prev, curr, include_breakdown=include_breakdown)
            for prev, curr in zip(self._previous, current)
        ]
        self._previous = current

        if self._per_cpu:
            payload: dict[str, Any] = {
                "warming_up": False,
                "percent": [self._round_value(item["percent"]) for item in per_core],
            }
            if include_breakdown:
                payload["times_percent"] = [
                    self._round_mapping(item["times_percent"]) for item in per_core
                ]
            return payload

        primary = per_core[0]
        payload = {
            "warming_up": False,
            "percent": self._round_value(primary["percent"]),
        }
        if include_breakdown:
            payload["times_percent"] = self._round_mapping(primary["times_percent"])
        return payload

    def reset(self) -> None:
        """Reset baseline so the next ``collect`` call returns warm-up."""
        self._previous = None

    def _read_snapshot(self) -> list[dict[str, float]]:
        """Read a CPU-times snapshot and normalize entries to float mappings."""
        raw = psutil.cpu_times(percpu=self._per_cpu)
        entries = raw if isinstance(raw, list) else [raw]

        if not entries:
            raise RuntimeError("psutil.cpu_times returned no CPU entries")

        if self._field_names is None:
            # Cache field names once to avoid repeated runtime introspection.
            fields = getattr(entries[0], "_fields", ())
            self._field_names = tuple(str(field_name) for field_name in fields)

        snapshots: list[dict[str, float]] = []
        for entry in entries:
            snapshots.append(
                {
                    field_name: float(getattr(entry, field_name, 0.0))
                    for field_name in self._field_names
                }
            )
        return snapshots

    def _compute_core(
        self,
        previous: dict[str, float],
        current: dict[str, float],
        *,
        include_breakdown: bool,
    ) -> dict[str, Any]:
        """Compute a utilization payload for one CPU core snapshot pair."""
        total = 0.0
        idle = 0.0
        deltas: dict[str, float] | None = {} if include_breakdown else None

        field_names = self._field_names or ()
        for field_name in field_names:
            delta = current.get(field_name, 0.0) - previous.get(field_name, 0.0)
            if delta < 0.0:
                delta = 0.0

            total += delta
            if field_name in _IDLE_FIELDS:
                idle += delta

            if deltas is not None:
                deltas[field_name] = delta

        if total <= _EPSILON:
            # Handle tiny/zero elapsed totals to avoid divide-by-zero noise.
            if deltas is None:
                return {"percent": 0.0}
            return {
                "percent": 0.0,
                "times_percent": {field_name: 0.0 for field_name in field_names},
            }

        percent = ((total - idle) / total) * 100.0
        percent = max(0.0, min(100.0, percent))

        if deltas is None:
            return {"percent": percent}

        factor = 100.0 / total
        return {
            "percent": percent,
            "times_percent": {
                field_name: delta_value * factor
                for field_name, delta_value in deltas.items()
            },
        }

    def _round_mapping(self, values: dict[str, float]) -> dict[str, float]:
        """Round mapping values using collector precision settings."""
        if self._round_digits is None:
            return values
        return {
            key: round(value, self._round_digits)
            for key, value in values.items()
        }

    def _round_value(self, value: float) -> float:
        """Round a scalar value using collector precision settings."""
        if self._round_digits is None:
            return value
        return round(value, self._round_digits)

    def _warmup_payload(self) -> dict[str, Any]:
        """Build a payload indicating the collector is warming up."""
        payload: dict[str, Any] = {
            "warming_up": True,
            "percent": [] if self._per_cpu else None,
        }
        if self._detail == "detailed":
            payload["times_percent"] = [] if self._per_cpu else None
        return payload
