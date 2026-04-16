"""Collect memory telemetry with low overhead at fixed polling intervals."""

from __future__ import annotations

from typing import Any, Literal

import psutil

MetricDetail = Literal["basic", "detailed"]

_VIRTUAL_BASIC_FIELDS = ("total", "available", "used", "percent")
_SWAP_BASIC_FIELDS = ("total", "used", "free", "percent")


class MemoryCollector:
    """Collect memory usage metrics from one psutil sampling source.

    Notes:
    - Uses ``psutil.virtual_memory`` and ``psutil.swap_memory`` once per cycle.
    - ``basic`` mode returns a compact payload for frequent telemetry polling.
    - ``detailed`` mode returns all available fields from both psutil snapshots.
    """

    def __init__(
        self,
        *,
        detail: MetricDetail = "basic",
        round_digits: int | None = 2,
    ) -> None:
        """Initialize memory collector configuration."""
        if detail not in ("basic", "detailed"):
            raise ValueError("detail must be 'basic' or 'detailed'")

        self._detail = detail
        self._round_digits = round_digits
        self._virtual_fields: tuple[str, ...] | None = None
        self._swap_fields: tuple[str, ...] | None = None

    def collect(self) -> dict[str, Any]:
        """Return memory metrics for the current polling cycle."""
        virtual = psutil.virtual_memory()
        swap = psutil.swap_memory()

        if self._detail == "basic":
            return {
                "virtual_memory": self._extract_fields(virtual, _VIRTUAL_BASIC_FIELDS),
                "swap_memory": self._extract_fields(swap, _SWAP_BASIC_FIELDS),
            }

        if self._virtual_fields is None:
            # Cache field names once to avoid repeated runtime introspection.
            self._virtual_fields = tuple(getattr(virtual, "_fields", ()))
        if self._swap_fields is None:
            # Cache field names once to avoid repeated runtime introspection.
            self._swap_fields = tuple(getattr(swap, "_fields", ()))

        return {
            "virtual_memory": self._extract_fields(virtual, self._virtual_fields),
            "swap_memory": self._extract_fields(swap, self._swap_fields),
        }

    def _extract_fields(
        self,
        entry: Any,
        fields: tuple[str, ...],
    ) -> dict[str, Any]:
        """Extract selected memory fields and normalize float precision."""
        payload: dict[str, Any] = {}
        for field_name in fields:
            value = getattr(entry, field_name, 0)
            payload[field_name] = self._round_if_float(value)
        return payload

    def _round_if_float(self, value: Any) -> Any:
        """Round float values using collector precision settings."""
        if self._round_digits is None or not isinstance(value, float):
            return value
        return round(value, self._round_digits)
