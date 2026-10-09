"""Collect resource usage for the busiest processes and host network I/O."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import psutil

_PROCESS_LIMIT = 10
_PROCESS_EXCEPTIONS = (
    psutil.AccessDenied,
    psutil.NoSuchProcess,
    psutil.ZombieProcess,
)
_FIELD_EXCEPTIONS = _PROCESS_EXCEPTIONS + (
    AttributeError,
    NotImplementedError,
    OSError,
)


class ProcessCollector:
    """Collect a bounded set of process metrics with low overhead.

    CPU usage is derived from non-blocking process CPU-time snapshots. The
    collector must be primed once before the first reported sample so that the
    next collection has an elapsed-time baseline.
    """

    def __init__(
        self,
        *,
        process_limit: int = _PROCESS_LIMIT,
        monotonic_fn: Callable[[], float] | None = None,
    ) -> None:
        if process_limit <= 0:
            raise ValueError("process_limit must be > 0")

        self._process_limit = process_limit
        self._monotonic = monotonic_fn or time.monotonic
        self._previous_cpu_times: dict[int, float] = {}
        self._previous_sample_time: float | None = None

    def prime(self) -> None:
        """Initialize CPU sampling state without blocking or enriching processes."""
        self._read_lightweight_samples()

    def collect(self) -> dict[str, Any]:
        """Return top process metrics and cumulative host network counters."""
        samples = self._read_lightweight_samples()
        selected = self._select_processes(samples)
        processes = [self._enrich_process(sample) for sample in selected]
        return {
            "processes": processes,
            "network": self._collect_network(),
        }

    def _read_lightweight_samples(self) -> list[dict[str, Any]]:
        sampled_at = self._monotonic()
        elapsed = (
            None
            if self._previous_sample_time is None
            else max(0.0, sampled_at - self._previous_sample_time)
        )
        current_cpu_times: dict[int, float] = {}
        samples: list[dict[str, Any]] = []

        try:
            iterator = psutil.process_iter(
                ["pid", "name", "cpu_times", "memory_info"],
                ad_value=None,
            )
            for proc in iterator:
                try:
                    info = proc.info
                    pid = int(info["pid"])
                    cpu_time = self._process_cpu_time(info.get("cpu_times"))
                    if cpu_time is not None:
                        current_cpu_times[pid] = cpu_time

                    samples.append(
                        {
                            "process": proc,
                            "pid": pid,
                            "name": info.get("name"),
                            "cpu_percent": self._cpu_percent(
                                pid=pid,
                                current_cpu_time=cpu_time,
                                elapsed=elapsed,
                            ),
                            "rss_bytes": self._rss_bytes(info.get("memory_info")),
                        }
                    )
                except _PROCESS_EXCEPTIONS:
                    continue
        except _PROCESS_EXCEPTIONS:
            pass

        self._previous_cpu_times = current_cpu_times
        self._previous_sample_time = sampled_at
        return samples

    def _cpu_percent(
        self,
        *,
        pid: int,
        current_cpu_time: float | None,
        elapsed: float | None,
    ) -> float | None:
        if current_cpu_time is None or elapsed is None or elapsed <= 0.0:
            return None

        previous_cpu_time = self._previous_cpu_times.get(pid)
        if previous_cpu_time is None:
            return None

        delta = current_cpu_time - previous_cpu_time
        if delta < 0.0:
            return None
        return round((delta / elapsed) * 100.0, 2)

    def _select_processes(
        self,
        samples: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cpu_ranked = sorted(
            (sample for sample in samples if sample["cpu_percent"] is not None),
            key=lambda sample: (-sample["cpu_percent"], sample["pid"]),
        )[: self._process_limit]
        rss_ranked = sorted(
            (sample for sample in samples if sample["rss_bytes"] is not None),
            key=lambda sample: (-sample["rss_bytes"], sample["pid"]),
        )[: self._process_limit]

        selected: list[dict[str, Any]] = []
        selected_pids: set[int] = set()
        for sample in (*cpu_ranked, *rss_ranked):
            pid = sample["pid"]
            if pid in selected_pids:
                continue
            selected.append(sample)
            selected_pids.add(pid)
        return selected

    def _enrich_process(self, sample: dict[str, Any]) -> dict[str, Any]:
        proc = sample["process"]
        threads: int | None = None
        open_fds: int | None = None
        disk_read_bytes: int | None = None
        disk_write_bytes: int | None = None

        try:
            with proc.oneshot():
                threads = self._safe_integer_call(proc.num_threads)
                num_fds = getattr(proc, "num_fds", None)
                if callable(num_fds):
                    open_fds = self._safe_integer_call(num_fds)

                disk_io = self._safe_call(proc.io_counters)
                if disk_io is not None:
                    disk_read_bytes = self._optional_integer(
                        getattr(disk_io, "read_bytes", None)
                    )
                    disk_write_bytes = self._optional_integer(
                        getattr(disk_io, "write_bytes", None)
                    )
        except _PROCESS_EXCEPTIONS:
            pass

        return {
            "pid": sample["pid"],
            "name": sample["name"],
            "cpu_percent": sample["cpu_percent"],
            "rss_bytes": sample["rss_bytes"],
            "threads": threads,
            "open_file_descriptors": open_fds,
            "disk_read_bytes": disk_read_bytes,
            "disk_write_bytes": disk_write_bytes,
        }

    @staticmethod
    def _safe_call(call: Callable[[], Any]) -> Any | None:
        try:
            return call()
        except _FIELD_EXCEPTIONS:
            return None

    @classmethod
    def _safe_integer_call(cls, call: Callable[[], Any]) -> int | None:
        return cls._optional_integer(cls._safe_call(call))

    @staticmethod
    def _optional_integer(value: Any) -> int | None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return int(value)

    @staticmethod
    def _process_cpu_time(cpu_times: Any) -> float | None:
        if cpu_times is None:
            return None
        try:
            return float(cpu_times.user) + float(cpu_times.system)
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _rss_bytes(memory_info: Any) -> int | None:
        if memory_info is None:
            return None
        return ProcessCollector._optional_integer(getattr(memory_info, "rss", None))

    @staticmethod
    def _collect_network() -> dict[str, int | None]:
        try:
            counters = psutil.net_io_counters()
        except (AttributeError, OSError):
            counters = None
        if counters is None:
            return {"bytes_sent": None, "bytes_received": None}
        return {
            "bytes_sent": ProcessCollector._optional_integer(
                getattr(counters, "bytes_sent", None)
            ),
            "bytes_received": ProcessCollector._optional_integer(
                getattr(counters, "bytes_recv", None)
            ),
        }
