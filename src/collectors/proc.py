"""Collect targeted Linux telemetry directly from ``/proc``."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

_TCP_STATES = {
    "01": "established",
    "02": "syn_sent",
    "03": "syn_recv",
    "06": "time_wait",
    "08": "close_wait",
    "0A": "listen",
}
_TCP_STATE_NAMES = tuple(_TCP_STATES.values())
_KERNEL_FIELDS = {
    "ctxt": "context_switches_total",
    "procs_running": "running_tasks",
    "procs_blocked": "blocked_tasks",
}
_MEMORY_FIELDS = {
    "Dirty": "dirty_bytes",
    "Writeback": "writeback_bytes",
}
_LIMIT_FIELDS = {
    "Max open files": "max_open_files",
    "Max processes": "max_processes",
}


class ProcCollector:
    """Read only the procfs files required for Issue #28 telemetry."""

    def __init__(self, *, proc_root: Path | str = Path("/proc")) -> None:
        self._proc_root = Path(proc_root)

    def collect(
        self,
        processes: Iterable[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        """Return available host and selected-process procfs telemetry."""
        return {
            "tcp": self._collect_tcp(),
            "kernel": self._read_and_parse(
                self._proc_root / "stat",
                parse_kernel_stats,
            ),
            "memory": self._read_and_parse(
                self._proc_root / "meminfo",
                parse_memory_stats,
            ),
            "process_limits": self._collect_process_limits(processes),
        }

    def _collect_tcp(self) -> dict[str, int]:
        counts = {state: 0 for state in _TCP_STATE_NAMES}
        readable_sources = 0

        for relative_path in (Path("net/tcp"), Path("net/tcp6")):
            try:
                content = (self._proc_root / relative_path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if not _has_tcp_table_header(content):
                continue
            readable_sources += 1
            for state, value in parse_tcp_states(content).items():
                counts[state] += value

        if readable_sources == 0:
            return {}
        if readable_sources == 2:
            return counts
        return {state: value for state, value in counts.items() if value > 0}

    def _collect_process_limits(
        self,
        processes: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        seen_pids: set[int] = set()

        for process in processes:
            pid = process.get("pid")
            if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1:
                continue
            if pid in seen_pids:
                continue
            seen_pids.add(pid)

            limits = self._read_and_parse(
                self._proc_root / str(pid) / "limits",
                parse_process_limits,
            )
            if not limits:
                continue
            name = process.get("name")
            collected.append(
                {
                    "pid": pid,
                    "name": name if isinstance(name, str) else "",
                    **limits,
                }
            )
        return collected

    @staticmethod
    def _read_and_parse(
        path: Path,
        parser: Callable[[str], Mapping[str, Any]],
    ) -> dict[str, Any]:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return {}
        return dict(parser(content))


def parse_tcp_states(content: str) -> dict[str, int]:
    """Count the six supported TCP states from one procfs socket table."""
    counts: dict[str, int] = {}
    for line in content.splitlines()[1:]:
        fields = line.split()
        if len(fields) <= 3:
            continue
        state = _TCP_STATES.get(fields[3].upper())
        if state is not None:
            counts[state] = counts.get(state, 0) + 1
    return counts


def parse_kernel_stats(content: str) -> dict[str, int]:
    """Parse selected counters and gauges from ``/proc/stat``."""
    result: dict[str, int] = {}
    for line in content.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        output_name = _KERNEL_FIELDS.get(fields[0])
        if output_name is None:
            continue
        value = _parse_nonnegative_integer(fields[1])
        if value is not None:
            result[output_name] = value
    return result


def parse_memory_stats(content: str) -> dict[str, int]:
    """Parse Dirty and Writeback values and convert procfs kB to bytes."""
    result: dict[str, int] = {}
    for line in content.splitlines():
        key, separator, raw_value = line.partition(":")
        output_name = _MEMORY_FIELDS.get(key)
        if not separator or output_name is None:
            continue
        fields = raw_value.split()
        if len(fields) < 2 or fields[1] != "kB":
            continue
        value_kb = _parse_nonnegative_integer(fields[0])
        if value_kb is not None:
            result[output_name] = value_kb * 1024
    return result


def parse_process_limits(content: str) -> dict[str, dict[str, int]]:
    """Parse finite soft and hard values for the two supported limits."""
    result: dict[str, dict[str, int]] = {}
    for line in content.splitlines():
        for proc_name, output_name in _LIMIT_FIELDS.items():
            if not line.startswith(proc_name):
                continue
            fields = line[len(proc_name) :].split()
            if len(fields) < 2:
                break
            values: dict[str, int] = {}
            soft = _parse_nonnegative_integer(fields[0])
            hard = _parse_nonnegative_integer(fields[1])
            if soft is not None:
                values["soft"] = soft
            if hard is not None:
                values["hard"] = hard
            if values:
                result[output_name] = values
            break
    return result


def _parse_nonnegative_integer(raw_value: str) -> int | None:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _has_tcp_table_header(content: str) -> bool:
    lines = content.splitlines()
    if not lines:
        return False
    return "st" in lines[0].split()
