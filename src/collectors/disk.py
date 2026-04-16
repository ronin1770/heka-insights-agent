"""Collect disk I/O telemetry with minimal per-cycle overhead."""

from __future__ import annotations

from typing import Any, Literal

import psutil

MetricDetail = Literal["basic", "detailed"]

_PHYSICAL_DEVICE_PREFIXES = (
    "sd",
    "hd",
    "vd",
    "xvd",
    "nvme",
    "mmcblk",
    "dm-",
    "md",
    "sr",
)
_EXCLUDED_DEVICE_PREFIXES = ("loop", "ram", "fd")
_DEFAULT_COUNTER_FIELDS = (
    "read_bytes",
    "write_bytes",
    "read_count",
    "write_count",
    "read_time",
    "write_time",
    "busy_time",
)


class DiskCollector:
    """Collect disk I/O counters from one psutil sampling source.

    Notes:
    - Uses cumulative counters from ``psutil.disk_io_counters(perdisk=True)``.
    - Filters to physical devices only to avoid virtual device noise.
    - ``basic`` mode returns aggregate counters only.
    - ``detailed`` mode returns aggregate and per-disk counters.
    """

    def __init__(self, *, detail: MetricDetail = "detailed") -> None:
        """Initialize disk collector configuration."""
        if detail not in ("basic", "detailed"):
            raise ValueError("detail must be 'basic' or 'detailed'")
        self._detail = detail
        self._counter_fields: tuple[str, ...] | None = None
        self._cached_devices: tuple[str, ...] | None = None
        self._collect_calls = 0
        self._device_cache_refresh_every = 12

    def collect(self) -> dict[str, Any]:
        """Return disk I/O counters for the current polling cycle."""
        self._collect_calls += 1
        raw_per_disk = psutil.disk_io_counters(perdisk=True) or {}
        self._refresh_cached_devices(raw_per_disk)

        aggregate: dict[str, int] = {}
        per_disk_payload: dict[str, dict[str, int]] = {}
        include_per_disk = self._detail == "detailed"

        for device_name in self._cached_devices or ():
            stats = raw_per_disk.get(device_name)
            if stats is None:
                continue

            counters = self._extract_counters(stats)
            if include_per_disk:
                per_disk_payload[device_name] = counters
            self._accumulate(aggregate, counters)

        payload: dict[str, Any] = {"disk_io": aggregate}
        if include_per_disk:
            payload["disk_io_perdisk"] = per_disk_payload
        return payload

    def _refresh_cached_devices(self, raw_per_disk: dict[str, Any]) -> None:
        """Refresh cached physical-device names on a fixed cadence."""
        should_refresh = (
            self._cached_devices is None
            or self._collect_calls % self._device_cache_refresh_every == 0
        )
        if not should_refresh:
            return

        # Cache filtered device names to avoid repeated prefix checks each cycle.
        self._cached_devices = tuple(
            name for name in raw_per_disk if self._is_physical_device(name)
        )

    def _extract_counters(self, stats: Any) -> dict[str, int]:
        """Extract integer counter fields from one psutil disk sample."""
        if self._counter_fields is None:
            # Cache available fields once to avoid repeated runtime introspection.
            discovered = tuple(getattr(stats, "_fields", ()))
            if discovered:
                self._counter_fields = discovered
            else:
                self._counter_fields = _DEFAULT_COUNTER_FIELDS

        payload: dict[str, int] = {}
        for field_name in self._counter_fields:
            value = getattr(stats, field_name, None)
            if value is None:
                continue
            payload[field_name] = int(value)
        return payload

    @staticmethod
    def _accumulate(target: dict[str, int], counters: dict[str, int]) -> None:
        """Accumulate one disk counter mapping into aggregate totals."""
        for field_name, value in counters.items():
            target[field_name] = target.get(field_name, 0) + value

    @staticmethod
    def _is_physical_device(name: str) -> bool:
        """Return whether a disk name looks like a physical block device."""
        normalized = name.strip().lower()
        if not normalized:
            return False
        if any(normalized.startswith(prefix) for prefix in _EXCLUDED_DEVICE_PREFIXES):
            return False
        if not any(normalized.startswith(prefix) for prefix in _PHYSICAL_DEVICE_PREFIXES):
            return False
        return not DiskCollector._is_partition_device(normalized)

    @staticmethod
    def _is_partition_device(name: str) -> bool:
        """Return whether a disk name appears to be a partition device."""
        if name.startswith(("sd", "hd", "vd", "xvd")) and name[-1:].isdigit():
            return True
        if name.startswith("nvme") and "p" in name and name.split("p")[-1].isdigit():
            return True
        if name.startswith("mmcblk") and "p" in name and name.split("p")[-1].isdigit():
            return True
        return False
