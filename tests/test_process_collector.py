"""Tests for bounded process and network telemetry collection."""

from __future__ import annotations

import sys
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from collectors.process import ProcessCollector  # noqa: E402

CpuTimes = namedtuple("CpuTimes", "user system")
MemoryInfo = namedtuple("MemoryInfo", "rss")
DiskIo = namedtuple("DiskIo", "read_bytes write_bytes")
NetworkIo = namedtuple("NetworkIo", "bytes_sent bytes_recv")


class _Oneshot:
    def __init__(self, error: BaseException | None = None) -> None:
        self._error = error

    def __enter__(self):
        if self._error is not None:
            raise self._error
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False


class _FakeProcess:
    def __init__(
        self,
        *,
        pid: int,
        cpu_time: float | None,
        rss: int | None,
        name: str | None = None,
        threads: object = 4,
        open_fds: object = 8,
        disk_io: object = DiskIo(100, 200),
        oneshot_error: BaseException | None = None,
    ) -> None:
        self.info = {
            "pid": pid,
            "name": name or f"process-{pid}",
            "cpu_times": None if cpu_time is None else CpuTimes(cpu_time, 0.0),
            "memory_info": None if rss is None else MemoryInfo(rss),
        }
        self._threads = threads
        self._open_fds = open_fds
        self._disk_io = disk_io
        self._oneshot_error = oneshot_error
        self.enrichment_calls = 0

    def oneshot(self) -> _Oneshot:
        self.enrichment_calls += 1
        return _Oneshot(self._oneshot_error)

    def num_threads(self):
        return self._resolve(self._threads)

    def num_fds(self):
        return self._resolve(self._open_fds)

    def io_counters(self):
        return self._resolve(self._disk_io)

    @staticmethod
    def _resolve(value):
        if isinstance(value, BaseException):
            raise value
        return value


class ProcessCollectorTests(unittest.TestCase):
    def _collect(
        self,
        initial: list[_FakeProcess],
        current: list[_FakeProcess],
        *,
        process_limit: int = 10,
    ) -> dict:
        times = iter((100.0, 110.0))
        collector = ProcessCollector(
            process_limit=process_limit,
            monotonic_fn=lambda: next(times),
        )
        with (
            patch(
                "collectors.process.psutil.process_iter",
                side_effect=(initial, current),
            ),
            patch(
                "collectors.process.psutil.net_io_counters",
                return_value=NetworkIo(1_000, 2_000),
            ),
        ):
            collector.prime()
            return collector.collect()

    def test_ranks_processes_by_non_blocking_cpu_delta(self) -> None:
        initial = [
            _FakeProcess(pid=1, cpu_time=0.0, rss=10),
            _FakeProcess(pid=2, cpu_time=0.0, rss=20),
            _FakeProcess(pid=3, cpu_time=0.0, rss=30),
        ]
        current = [
            _FakeProcess(pid=1, cpu_time=1.0, rss=10),
            _FakeProcess(pid=2, cpu_time=3.0, rss=20),
            _FakeProcess(pid=3, cpu_time=2.0, rss=30),
        ]

        payload = self._collect(initial, current, process_limit=2)

        self.assertEqual(
            [process["pid"] for process in payload["processes"][:2]],
            [2, 3],
        )
        self.assertEqual(payload["processes"][0]["cpu_percent"], 30.0)

    def test_ranks_processes_by_rss_when_cpu_is_unavailable(self) -> None:
        initial = [
            _FakeProcess(pid=1, cpu_time=None, rss=100),
            _FakeProcess(pid=2, cpu_time=None, rss=300),
            _FakeProcess(pid=3, cpu_time=None, rss=200),
        ]
        current = [
            _FakeProcess(pid=1, cpu_time=None, rss=100),
            _FakeProcess(pid=2, cpu_time=None, rss=300),
            _FakeProcess(pid=3, cpu_time=None, rss=200),
        ]

        payload = self._collect(initial, current, process_limit=2)

        self.assertEqual(
            [process["pid"] for process in payload["processes"]],
            [2, 3],
        )

    def test_deduplicates_pid_union_and_enriches_only_selected_processes(self) -> None:
        initial = [
            _FakeProcess(pid=1, cpu_time=0.0, rss=300),
            _FakeProcess(pid=2, cpu_time=0.0, rss=200),
            _FakeProcess(pid=3, cpu_time=0.0, rss=100),
        ]
        current = [
            _FakeProcess(pid=1, cpu_time=3.0, rss=300),
            _FakeProcess(pid=2, cpu_time=2.0, rss=200),
            _FakeProcess(pid=3, cpu_time=1.0, rss=100),
        ]

        payload = self._collect(initial, current, process_limit=2)

        self.assertEqual([item["pid"] for item in payload["processes"]], [1, 2])
        self.assertEqual(current[0].enrichment_calls, 1)
        self.assertEqual(current[1].enrichment_calls, 1)
        self.assertEqual(current[2].enrichment_calls, 0)

    def test_unions_distinct_cpu_and_rss_rankings(self) -> None:
        initial = [
            _FakeProcess(pid=1, cpu_time=0.0, rss=100),
            _FakeProcess(pid=2, cpu_time=0.0, rss=300),
        ]
        current = [
            _FakeProcess(pid=1, cpu_time=3.0, rss=100),
            _FakeProcess(pid=2, cpu_time=1.0, rss=300),
        ]

        payload = self._collect(initial, current, process_limit=1)

        self.assertEqual([item["pid"] for item in payload["processes"]], [1, 2])

    def test_retains_null_for_unavailable_fields_without_losing_valid_fields(self) -> None:
        denied = psutil.AccessDenied(pid=1)
        initial = [_FakeProcess(pid=1, cpu_time=0.0, rss=100)]
        current = [
            _FakeProcess(
                pid=1,
                cpu_time=1.0,
                rss=100,
                threads=denied,
                open_fds=7,
                disk_io=denied,
            )
        ]

        process = self._collect(initial, current)["processes"][0]

        self.assertIsNone(process["threads"])
        self.assertEqual(process["open_file_descriptors"], 7)
        self.assertIsNone(process["disk_read_bytes"])
        self.assertIsNone(process["disk_write_bytes"])
        self.assertEqual(process["rss_bytes"], 100)

    def test_handles_process_termination_during_enrichment(self) -> None:
        terminated = psutil.NoSuchProcess(pid=1)
        initial = [_FakeProcess(pid=1, cpu_time=0.0, rss=100)]
        current = [
            _FakeProcess(
                pid=1,
                cpu_time=1.0,
                rss=100,
                oneshot_error=terminated,
            )
        ]

        process = self._collect(initial, current)["processes"][0]

        self.assertEqual(process["pid"], 1)
        self.assertIsNone(process["threads"])
        self.assertIsNone(process["open_file_descriptors"])
        self.assertIsNone(process["disk_read_bytes"])
        self.assertIsNone(process["disk_write_bytes"])

    def test_handles_permission_failure_for_entire_enrichment(self) -> None:
        denied = psutil.AccessDenied(pid=1)
        initial = [_FakeProcess(pid=1, cpu_time=0.0, rss=100)]
        current = [
            _FakeProcess(
                pid=1,
                cpu_time=1.0,
                rss=100,
                oneshot_error=denied,
            )
        ]

        process = self._collect(initial, current)["processes"][0]

        self.assertEqual(process["cpu_percent"], 10.0)
        self.assertEqual(process["rss_bytes"], 100)
        self.assertIsNone(process["threads"])

    def test_collects_only_required_network_counters(self) -> None:
        initial = [_FakeProcess(pid=1, cpu_time=0.0, rss=100)]
        current = [_FakeProcess(pid=1, cpu_time=1.0, rss=100)]

        payload = self._collect(initial, current)

        self.assertEqual(
            payload["network"],
            {"bytes_sent": 1_000, "bytes_received": 2_000},
        )


if __name__ == "__main__":
    unittest.main()
