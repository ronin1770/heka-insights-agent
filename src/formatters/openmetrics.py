"""OpenMetrics formatter for raw collector payloads."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class _FamilyMeta:
    """Metadata for one OpenMetrics metric family."""

    metric_type: str
    unit: str
    help_text: str


_FAMILY_ORDER: tuple[str, ...] = (
    "heka_cpu_usage_percent",
    "heka_cpu_time_percent",
    "heka_memory_virtual_used_bytes",
    "heka_memory_virtual_available_bytes",
    "heka_memory_virtual_total_bytes",
    "heka_memory_swap_used_bytes",
    "heka_memory_swap_total_bytes",
    "heka_disk_read_bytes_total",
    "heka_disk_write_bytes_total",
    "heka_disk_reads_total",
    "heka_disk_writes_total",
)

_FAMILY_META: dict[str, _FamilyMeta] = {
    "heka_cpu_usage_percent": _FamilyMeta(
        metric_type="gauge",
        unit="percent",
        help_text="CPU usage percentage.",
    ),
    "heka_cpu_time_percent": _FamilyMeta(
        metric_type="gauge",
        unit="percent",
        help_text="CPU time distribution by mode as a percentage.",
    ),
    "heka_memory_virtual_used_bytes": _FamilyMeta(
        metric_type="gauge",
        unit="bytes",
        help_text="Virtual memory used in bytes.",
    ),
    "heka_memory_virtual_available_bytes": _FamilyMeta(
        metric_type="gauge",
        unit="bytes",
        help_text="Virtual memory available in bytes.",
    ),
    "heka_memory_virtual_total_bytes": _FamilyMeta(
        metric_type="gauge",
        unit="bytes",
        help_text="Total virtual memory in bytes.",
    ),
    "heka_memory_swap_used_bytes": _FamilyMeta(
        metric_type="gauge",
        unit="bytes",
        help_text="Swap memory used in bytes.",
    ),
    "heka_memory_swap_total_bytes": _FamilyMeta(
        metric_type="gauge",
        unit="bytes",
        help_text="Total swap memory in bytes.",
    ),
    "heka_disk_read_bytes_total": _FamilyMeta(
        metric_type="counter",
        unit="bytes",
        help_text="Total disk bytes read.",
    ),
    "heka_disk_write_bytes_total": _FamilyMeta(
        metric_type="counter",
        unit="bytes",
        help_text="Total disk bytes written.",
    ),
    "heka_disk_reads_total": _FamilyMeta(
        metric_type="counter",
        unit="count",
        help_text="Total disk read operations.",
    ),
    "heka_disk_writes_total": _FamilyMeta(
        metric_type="counter",
        unit="count",
        help_text="Total disk write operations.",
    ),
}


class OpenMetricsFormatter:
    """Render CPU/memory/disk collector payloads in OpenMetrics text format."""

    def format(
        self,
        payloads: Mapping[str, Mapping[str, Any]],
        *,
        timestamp_ms: int | float | None = None,
    ) -> str:
        """Convert raw collector payloads into one OpenMetrics document.

        Required keys in ``payloads``:
        - ``cpu``: output from ``CPUCollector.collect()``
        - ``memory``: output from ``MemoryCollector.collect()``
        - ``disk``: output from ``DiskCollector.collect()``
        """
        cpu_payload = payloads.get("cpu")
        memory_payload = payloads.get("memory")
        disk_payload = payloads.get("disk")

        if not isinstance(cpu_payload, Mapping):
            raise ValueError("payloads['cpu'] must be a mapping")
        if not isinstance(memory_payload, Mapping):
            raise ValueError("payloads['memory'] must be a mapping")
        if not isinstance(disk_payload, Mapping):
            raise ValueError("payloads['disk'] must be a mapping")

        samples: dict[str, list[tuple[dict[str, str], float | int]]] = {
            name: [] for name in _FAMILY_ORDER
        }

        self._collect_cpu_samples(samples, cpu_payload)
        self._collect_memory_samples(samples, memory_payload)
        self._collect_disk_samples(samples, disk_payload)

        lines: list[str] = []
        timestamp = self._format_timestamp(timestamp_ms)
        for family_name in _FAMILY_ORDER:
            family_samples = samples[family_name]
            if not family_samples:
                continue
            meta = _FAMILY_META[family_name]
            lines.append(f"# HELP {family_name} {self._escape_help(meta.help_text)}")
            lines.append(f"# TYPE {family_name} {meta.metric_type}")
            lines.append(f"# UNIT {family_name} {meta.unit}")
            for labels, value in family_samples:
                lines.append(
                    self._format_sample(
                        name=family_name,
                        value=value,
                        labels=labels,
                        timestamp=timestamp,
                    )
                )

        lines.append("# EOF")
        return "\n".join(lines) + "\n"

    def _collect_cpu_samples(
        self,
        samples: dict[str, list[tuple[dict[str, str], float | int]]],
        cpu_payload: Mapping[str, Any],
    ) -> None:
        if cpu_payload.get("warming_up", False):
            return

        percent = cpu_payload.get("percent")
        if isinstance(percent, (int, float)):
            samples["heka_cpu_usage_percent"].append(({}, float(percent)))

        times_percent = cpu_payload.get("times_percent")
        if isinstance(times_percent, Mapping):
            for mode, value in sorted(times_percent.items()):
                if isinstance(value, (int, float)):
                    samples["heka_cpu_time_percent"].append(
                        ({"mode": str(mode)}, float(value))
                    )

    def _collect_memory_samples(
        self,
        samples: dict[str, list[tuple[dict[str, str], float | int]]],
        memory_payload: Mapping[str, Any],
    ) -> None:
        virtual = memory_payload.get("virtual_memory")
        if isinstance(virtual, Mapping):
            self._append_if_numeric(
                samples["heka_memory_virtual_used_bytes"],
                {},
                virtual.get("used"),
            )
            self._append_if_numeric(
                samples["heka_memory_virtual_available_bytes"],
                {},
                virtual.get("available"),
            )
            self._append_if_numeric(
                samples["heka_memory_virtual_total_bytes"],
                {},
                virtual.get("total"),
            )

        swap = memory_payload.get("swap_memory")
        if isinstance(swap, Mapping):
            self._append_if_numeric(
                samples["heka_memory_swap_used_bytes"],
                {},
                swap.get("used"),
            )
            self._append_if_numeric(
                samples["heka_memory_swap_total_bytes"],
                {},
                swap.get("total"),
            )

    def _collect_disk_samples(
        self,
        samples: dict[str, list[tuple[dict[str, str], float | int]]],
        disk_payload: Mapping[str, Any],
    ) -> None:
        aggregate = disk_payload.get("disk_io")
        if isinstance(aggregate, Mapping):
            self._append_disk_counters(samples, aggregate, labels={})

        per_disk = disk_payload.get("disk_io_perdisk")
        if isinstance(per_disk, Mapping):
            for device, counters in sorted(per_disk.items()):
                if not isinstance(counters, Mapping):
                    continue
                self._append_disk_counters(
                    samples,
                    counters,
                    labels={"device": str(device)},
                )

    def _append_disk_counters(
        self,
        samples: dict[str, list[tuple[dict[str, str], float | int]]],
        counters: Mapping[str, Any],
        *,
        labels: dict[str, str],
    ) -> None:
        self._append_if_numeric(
            samples["heka_disk_read_bytes_total"],
            labels,
            counters.get("read_bytes"),
        )
        self._append_if_numeric(
            samples["heka_disk_write_bytes_total"],
            labels,
            counters.get("write_bytes"),
        )
        self._append_if_numeric(
            samples["heka_disk_reads_total"],
            labels,
            counters.get("read_count"),
        )
        self._append_if_numeric(
            samples["heka_disk_writes_total"],
            labels,
            counters.get("write_count"),
        )

    @staticmethod
    def _append_if_numeric(
        family_samples: list[tuple[dict[str, str], float | int]],
        labels: dict[str, str],
        value: Any,
    ) -> None:
        if isinstance(value, (int, float)):
            family_samples.append((dict(labels), value))

    @staticmethod
    def _escape_help(value: str) -> str:
        return value.replace("\\", r"\\").replace("\n", r"\n")

    @staticmethod
    def _escape_label(value: str) -> str:
        return (
            value.replace("\\", r"\\")
            .replace('"', r"\"")
            .replace("\n", r"\n")
        )

    @staticmethod
    def _format_timestamp(timestamp_ms: int | float | None) -> str | None:
        if timestamp_ms is None:
            return None

        timestamp_seconds = float(timestamp_ms) / 1000.0
        return format(timestamp_seconds, ".3f").rstrip("0").rstrip(".")

    def _format_sample(
        self,
        *,
        name: str,
        value: int | float,
        labels: Mapping[str, str],
        timestamp: str | None,
    ) -> str:
        value_str = self._format_value(value)
        if labels:
            rendered_labels = ",".join(
                f'{key}="{self._escape_label(val)}"'
                for key, val in sorted(labels.items())
            )
            sample = f"{name}{{{rendered_labels}}} {value_str}"
        else:
            sample = f"{name} {value_str}"

        if timestamp is None:
            return sample
        return f"{sample} {timestamp}"

    @staticmethod
    def _format_value(value: int | float) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, int):
            return str(value)

        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "+Inf" if value > 0 else "-Inf"
        return format(value, ".15g")
