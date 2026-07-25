"""Tests for main loop resiliency."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main  # noqa: E402


class _FakeCollector:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def collect(self) -> dict[str, object]:
        return dict(self._payload)


class _FakeTicker:
    def __init__(self, *, interval_seconds: float) -> None:
        del interval_seconds
        self.calls = 0

    def sleep(self) -> None:
        self.calls += 1
        if self.calls >= 2:
            raise KeyboardInterrupt


class _FlakyExporter:
    def __init__(self) -> None:
        self.calls = 0

    def export(self, metrics) -> None:
        del metrics
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("first batch failed")


class MainLoopTests(unittest.TestCase):
    def test_run_collectors_loop_keeps_running_after_batch_export_failure(self) -> None:
        logger = Mock()
        exporter = _FlakyExporter()
        cpu_payload = {"warming_up": False, "value": 1}
        memory_payload = {"value": 2}
        disk_payload = {"value": 3}

        with (
            patch.object(main, "get_cpu_poll_interval_seconds", return_value=5.0),
            patch.object(main, "CPUCollector", return_value=_FakeCollector(cpu_payload)),
            patch.object(main, "MemoryCollector", return_value=_FakeCollector(memory_payload)),
            patch.object(main, "DiskCollector", return_value=_FakeCollector(disk_payload)),
            patch.object(main, "MonotonicTicker", _FakeTicker),
            patch.object(main, "build_canonical_metrics", return_value=[{"name": "metric"}]),
        ):
            with self.assertRaises(KeyboardInterrupt):
                main.run_collectors_loop(
                    exporter=exporter,
                    exporter_type="otlp_http",
                    logger=logger,
                )

        self.assertEqual(exporter.calls, 2)
        logger.error.assert_called_once_with("Batch export failed; error=%s", ANY)


if __name__ == "__main__":
    unittest.main()
