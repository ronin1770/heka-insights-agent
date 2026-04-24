"""Canonical metric normalization for collector payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from exporters.base import CanonicalMetric


@dataclass(frozen=True)
class _MetricMeta:
    """Metadata associated with one canonical metric name."""

    description: str
    metric_type: str
    unit: str


_METRIC_META: dict[str, _MetricMeta] = {
    "heka_cpu_usage_percent": _MetricMeta(
        description="CPU usage percentage.",
        metric_type="gauge",
        unit="percent",
    ),
    "heka_cpu_time_percent": _MetricMeta(
        description="CPU time distribution by mode as a percentage.",
        metric_type="gauge",
        unit="percent",
    ),
    "heka_memory_virtual_used_bytes": _MetricMeta(
        description="Virtual memory used in bytes.",
        metric_type="gauge",
        unit="bytes",
    ),
    "heka_memory_virtual_available_bytes": _MetricMeta(
        description="Virtual memory available in bytes.",
        metric_type="gauge",
        unit="bytes",
    ),
    "heka_memory_virtual_total_bytes": _MetricMeta(
        description="Total virtual memory in bytes.",
        metric_type="gauge",
        unit="bytes",
    ),
    "heka_memory_swap_used_bytes": _MetricMeta(
        description="Swap memory used in bytes.",
        metric_type="gauge",
        unit="bytes",
    ),
    "heka_memory_swap_total_bytes": _MetricMeta(
        description="Total swap memory in bytes.",
        metric_type="gauge",
        unit="bytes",
    ),
    "heka_disk_read_bytes_total": _MetricMeta(
        description="Total disk bytes read.",
        metric_type="counter",
        unit="bytes",
    ),
    "heka_disk_write_bytes_total": _MetricMeta(
        description="Total disk bytes written.",
        metric_type="counter",
        unit="bytes",
    ),
    "heka_disk_reads_total": _MetricMeta(
        description="Total disk read operations.",
        metric_type="counter",
        unit="count",
    ),
    "heka_disk_writes_total": _MetricMeta(
        description="Total disk write operations.",
        metric_type="counter",
        unit="count",
    ),
}


def build_canonical_metrics(
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    timestamp_unix_ms: int | None = None,
) -> list[CanonicalMetric]:
    """Normalize collector payloads into canonical metric records."""
    cpu_payload = payloads.get("cpu")
    memory_payload = payloads.get("memory")
    disk_payload = payloads.get("disk")

    if not isinstance(cpu_payload, Mapping):
        raise ValueError("payloads['cpu'] must be a mapping")
    if not isinstance(memory_payload, Mapping):
        raise ValueError("payloads['memory'] must be a mapping")
    if not isinstance(disk_payload, Mapping):
        raise ValueError("payloads['disk'] must be a mapping")

    metrics: list[CanonicalMetric] = []
    _collect_cpu_metrics(metrics, cpu_payload, timestamp_unix_ms=timestamp_unix_ms)
    _collect_memory_metrics(metrics, memory_payload, timestamp_unix_ms=timestamp_unix_ms)
    _collect_disk_metrics(metrics, disk_payload, timestamp_unix_ms=timestamp_unix_ms)
    return metrics


def _collect_cpu_metrics(
    metrics: list[CanonicalMetric],
    cpu_payload: Mapping[str, Any],
    *,
    timestamp_unix_ms: int | None,
) -> None:
    if cpu_payload.get("warming_up", False):
        return

    percent = cpu_payload.get("percent")
    _append_if_numeric(
        metrics,
        name="heka_cpu_usage_percent",
        value=percent,
        labels={},
        timestamp_unix_ms=timestamp_unix_ms,
    )

    times_percent = cpu_payload.get("times_percent")
    if isinstance(times_percent, Mapping):
        for mode, value in sorted(times_percent.items()):
            _append_if_numeric(
                metrics,
                name="heka_cpu_time_percent",
                value=value,
                labels={"mode": str(mode)},
                timestamp_unix_ms=timestamp_unix_ms,
            )


def _collect_memory_metrics(
    metrics: list[CanonicalMetric],
    memory_payload: Mapping[str, Any],
    *,
    timestamp_unix_ms: int | None,
) -> None:
    virtual = memory_payload.get("virtual_memory")
    if isinstance(virtual, Mapping):
        _append_if_numeric(
            metrics,
            name="heka_memory_virtual_used_bytes",
            value=virtual.get("used"),
            labels={},
            timestamp_unix_ms=timestamp_unix_ms,
        )
        _append_if_numeric(
            metrics,
            name="heka_memory_virtual_available_bytes",
            value=virtual.get("available"),
            labels={},
            timestamp_unix_ms=timestamp_unix_ms,
        )
        _append_if_numeric(
            metrics,
            name="heka_memory_virtual_total_bytes",
            value=virtual.get("total"),
            labels={},
            timestamp_unix_ms=timestamp_unix_ms,
        )

    swap = memory_payload.get("swap_memory")
    if isinstance(swap, Mapping):
        _append_if_numeric(
            metrics,
            name="heka_memory_swap_used_bytes",
            value=swap.get("used"),
            labels={},
            timestamp_unix_ms=timestamp_unix_ms,
        )
        _append_if_numeric(
            metrics,
            name="heka_memory_swap_total_bytes",
            value=swap.get("total"),
            labels={},
            timestamp_unix_ms=timestamp_unix_ms,
        )


def _collect_disk_metrics(
    metrics: list[CanonicalMetric],
    disk_payload: Mapping[str, Any],
    *,
    timestamp_unix_ms: int | None,
) -> None:
    aggregate = disk_payload.get("disk_io")
    if isinstance(aggregate, Mapping):
        _append_disk_counters(
            metrics,
            aggregate,
            labels={},
            timestamp_unix_ms=timestamp_unix_ms,
        )

    per_disk = disk_payload.get("disk_io_perdisk")
    if isinstance(per_disk, Mapping):
        for device, counters in sorted(per_disk.items()):
            if not isinstance(counters, Mapping):
                continue
            _append_disk_counters(
                metrics,
                counters,
                labels={"device": str(device)},
                timestamp_unix_ms=timestamp_unix_ms,
            )


def _append_disk_counters(
    metrics: list[CanonicalMetric],
    counters: Mapping[str, Any],
    *,
    labels: dict[str, str],
    timestamp_unix_ms: int | None,
) -> None:
    _append_if_numeric(
        metrics,
        name="heka_disk_read_bytes_total",
        value=counters.get("read_bytes"),
        labels=labels,
        timestamp_unix_ms=timestamp_unix_ms,
    )
    _append_if_numeric(
        metrics,
        name="heka_disk_write_bytes_total",
        value=counters.get("write_bytes"),
        labels=labels,
        timestamp_unix_ms=timestamp_unix_ms,
    )
    _append_if_numeric(
        metrics,
        name="heka_disk_reads_total",
        value=counters.get("read_count"),
        labels=labels,
        timestamp_unix_ms=timestamp_unix_ms,
    )
    _append_if_numeric(
        metrics,
        name="heka_disk_writes_total",
        value=counters.get("write_count"),
        labels=labels,
        timestamp_unix_ms=timestamp_unix_ms,
    )


def _append_if_numeric(
    metrics: list[CanonicalMetric],
    *,
    name: str,
    value: Any,
    labels: Mapping[str, str],
    timestamp_unix_ms: int | None,
) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return
    metrics.append(
        _build_metric(
            name=name,
            value=value,
            labels=labels,
            timestamp_unix_ms=timestamp_unix_ms,
        )
    )


def _build_metric(
    *,
    name: str,
    value: int | float,
    labels: Mapping[str, str],
    timestamp_unix_ms: int | None,
) -> CanonicalMetric:
    meta = _METRIC_META[name]
    metric: CanonicalMetric = {
        "name": name,
        "description": meta.description,
        "type": meta.metric_type,
        "unit": meta.unit,
        "value": value,
        "labels": dict(labels),
    }
    if timestamp_unix_ms is not None:
        metric["timestamp_unix_ms"] = timestamp_unix_ms
    return metric
