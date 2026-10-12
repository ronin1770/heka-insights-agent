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
    "heka_process_cpu_usage_percent": _MetricMeta(
        description="Process CPU usage percentage.",
        metric_type="gauge",
        unit="percent",
    ),
    "heka_process_rss_bytes": _MetricMeta(
        description="Process resident set size in bytes.",
        metric_type="gauge",
        unit="bytes",
    ),
    "heka_process_threads": _MetricMeta(
        description="Process thread count.",
        metric_type="gauge",
        unit="count",
    ),
    "heka_process_open_file_descriptors": _MetricMeta(
        description="Process open file descriptor count.",
        metric_type="gauge",
        unit="count",
    ),
    "heka_process_disk_read_bytes_total": _MetricMeta(
        description="Total bytes read by a process.",
        metric_type="counter",
        unit="bytes",
    ),
    "heka_process_disk_write_bytes_total": _MetricMeta(
        description="Total bytes written by a process.",
        metric_type="counter",
        unit="bytes",
    ),
    "heka_network_sent_bytes_total": _MetricMeta(
        description="Total bytes sent by the host.",
        metric_type="counter",
        unit="bytes",
    ),
    "heka_network_received_bytes_total": _MetricMeta(
        description="Total bytes received by the host.",
        metric_type="counter",
        unit="bytes",
    ),
    "heka_tcp_connections": _MetricMeta(
        description="Current TCP connections by state.",
        metric_type="gauge",
        unit="count",
    ),
    "heka_kernel_context_switches_total": _MetricMeta(
        description="Total kernel context switches.",
        metric_type="counter",
        unit="count",
    ),
    "heka_kernel_running_tasks": _MetricMeta(
        description="Current number of runnable kernel tasks.",
        metric_type="gauge",
        unit="count",
    ),
    "heka_kernel_blocked_tasks": _MetricMeta(
        description="Current number of kernel tasks blocked on I/O.",
        metric_type="gauge",
        unit="count",
    ),
    "heka_memory_dirty_bytes": _MetricMeta(
        description="Memory waiting to be written back in bytes.",
        metric_type="gauge",
        unit="bytes",
    ),
    "heka_memory_writeback_bytes": _MetricMeta(
        description="Memory actively being written back in bytes.",
        metric_type="gauge",
        unit="bytes",
    ),
    "heka_process_limit_open_files": _MetricMeta(
        description="Configured process open-file resource limit.",
        metric_type="gauge",
        unit="count",
    ),
    "heka_process_limit_max_processes": _MetricMeta(
        description="Configured process maximum-processes resource limit.",
        metric_type="gauge",
        unit="count",
    ),
    "heka_psi_pressure_percent": _MetricMeta(
        description="Linux pressure stall average as a percentage.",
        metric_type="gauge",
        unit="percent",
    ),
    "heka_psi_stall_time_microseconds_total": _MetricMeta(
        description="Cumulative Linux pressure stall time in microseconds.",
        metric_type="counter",
        unit="microseconds",
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
    process_payload = payloads.get("process")
    proc_payload = payloads.get("proc")
    psi_payload = payloads.get("psi")

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
    if isinstance(process_payload, Mapping):
        _collect_process_metrics(
            metrics,
            process_payload,
            timestamp_unix_ms=timestamp_unix_ms,
        )
    if isinstance(proc_payload, Mapping):
        _collect_proc_metrics(
            metrics,
            proc_payload,
            timestamp_unix_ms=timestamp_unix_ms,
        )
    if isinstance(psi_payload, Mapping):
        _collect_psi_metrics(
            metrics,
            psi_payload,
            timestamp_unix_ms=timestamp_unix_ms,
        )
    return metrics


def _collect_psi_metrics(
    metrics: list[CanonicalMetric],
    psi_payload: Mapping[str, Any],
    *,
    timestamp_unix_ms: int | None,
) -> None:
    for resource in ("cpu", "memory", "io"):
        resource_values = psi_payload.get(resource)
        if not isinstance(resource_values, Mapping):
            continue
        for stall in ("some", "full"):
            stall_values = resource_values.get(stall)
            if not isinstance(stall_values, Mapping):
                continue
            labels = {"resource": resource, "stall": stall}
            for window in ("avg10", "avg60", "avg300"):
                _append_if_numeric(
                    metrics,
                    name="heka_psi_pressure_percent",
                    value=stall_values.get(window),
                    labels={**labels, "window": window},
                    timestamp_unix_ms=timestamp_unix_ms,
                )
            _append_if_numeric(
                metrics,
                name="heka_psi_stall_time_microseconds_total",
                value=stall_values.get("total"),
                labels=labels,
                timestamp_unix_ms=timestamp_unix_ms,
            )


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


def _collect_process_metrics(
    metrics: list[CanonicalMetric],
    process_payload: Mapping[str, Any],
    *,
    timestamp_unix_ms: int | None,
) -> None:
    processes = process_payload.get("processes")
    if isinstance(processes, list):
        field_metrics = (
            ("cpu_percent", "heka_process_cpu_usage_percent"),
            ("rss_bytes", "heka_process_rss_bytes"),
            ("threads", "heka_process_threads"),
            ("open_file_descriptors", "heka_process_open_file_descriptors"),
            ("disk_read_bytes", "heka_process_disk_read_bytes_total"),
            ("disk_write_bytes", "heka_process_disk_write_bytes_total"),
        )
        for process in processes:
            if not isinstance(process, Mapping):
                continue
            pid = process.get("pid")
            if not isinstance(pid, int) or isinstance(pid, bool):
                continue
            process_name = process.get("name")
            labels = {
                "pid": str(pid),
                "process_name": (
                    process_name if isinstance(process_name, str) else ""
                ),
            }
            for field_name, metric_name in field_metrics:
                _append_if_numeric(
                    metrics,
                    name=metric_name,
                    value=process.get(field_name),
                    labels=labels,
                    timestamp_unix_ms=timestamp_unix_ms,
                )

    network = process_payload.get("network")
    if not isinstance(network, Mapping):
        return
    _append_if_numeric(
        metrics,
        name="heka_network_sent_bytes_total",
        value=network.get("bytes_sent"),
        labels={},
        timestamp_unix_ms=timestamp_unix_ms,
    )
    _append_if_numeric(
        metrics,
        name="heka_network_received_bytes_total",
        value=network.get("bytes_received"),
        labels={},
        timestamp_unix_ms=timestamp_unix_ms,
    )


def _collect_proc_metrics(
    metrics: list[CanonicalMetric],
    proc_payload: Mapping[str, Any],
    *,
    timestamp_unix_ms: int | None,
) -> None:
    tcp = proc_payload.get("tcp")
    if isinstance(tcp, Mapping):
        for state, value in sorted(tcp.items()):
            _append_if_numeric(
                metrics,
                name="heka_tcp_connections",
                value=value,
                labels={"state": str(state)},
                timestamp_unix_ms=timestamp_unix_ms,
            )

    kernel = proc_payload.get("kernel")
    if isinstance(kernel, Mapping):
        kernel_fields = (
            ("context_switches_total", "heka_kernel_context_switches_total"),
            ("running_tasks", "heka_kernel_running_tasks"),
            ("blocked_tasks", "heka_kernel_blocked_tasks"),
        )
        for field_name, metric_name in kernel_fields:
            _append_if_numeric(
                metrics,
                name=metric_name,
                value=kernel.get(field_name),
                labels={},
                timestamp_unix_ms=timestamp_unix_ms,
            )

    memory = proc_payload.get("memory")
    if isinstance(memory, Mapping):
        memory_fields = (
            ("dirty_bytes", "heka_memory_dirty_bytes"),
            ("writeback_bytes", "heka_memory_writeback_bytes"),
        )
        for field_name, metric_name in memory_fields:
            _append_if_numeric(
                metrics,
                name=metric_name,
                value=memory.get(field_name),
                labels={},
                timestamp_unix_ms=timestamp_unix_ms,
            )

    process_limits = proc_payload.get("process_limits")
    if not isinstance(process_limits, list):
        return
    limit_fields = (
        ("max_open_files", "heka_process_limit_open_files"),
        ("max_processes", "heka_process_limit_max_processes"),
    )
    for process in process_limits:
        if not isinstance(process, Mapping):
            continue
        pid = process.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool):
            continue
        process_name = process.get("name")
        for field_name, metric_name in limit_fields:
            limit_values = process.get(field_name)
            if not isinstance(limit_values, Mapping):
                continue
            for limit_kind in ("soft", "hard"):
                _append_if_numeric(
                    metrics,
                    name=metric_name,
                    value=limit_values.get(limit_kind),
                    labels={
                        "pid": str(pid),
                        "process_name": (
                            process_name if isinstance(process_name, str) else ""
                        ),
                        "limit": limit_kind,
                    },
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
