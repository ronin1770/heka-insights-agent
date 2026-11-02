"""Regression tests for Issue #34 timing and availability diagnostics."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from collectors.psi import PSICollector  # noqa: E402
from diagnostics import AgentDiagnostics, CollectionStatistics  # noqa: E402
from main import _advance_schedule  # noqa: E402


class _Exporter:
    def diagnostics_snapshot(self):
        return {"counters": {}, "gauges": {}}


class CollectionObservabilityTests(unittest.TestCase):
    def test_schedule_reports_only_missed_occurrences_as_skipped(self) -> None:
        next_collection, skipped = _advance_schedule(
            30.0,
            interval_seconds=30.0,
            current_monotonic=95.0,
        )

        self.assertEqual(next_collection, 120.0)
        self.assertEqual(skipped, 2)

    def test_collection_statistics_are_included_in_agent_diagnostics(self) -> None:
        statistics = CollectionStatistics()
        statistics.record_cycle(interval_seconds=None, delayed=False)
        statistics.record_cycle(interval_seconds=12.0, delayed=True)
        statistics.record_skipped("psi", 2)
        logger = Mock()

        diagnostics = AgentDiagnostics(
            exporter=_Exporter(),  # type: ignore[arg-type]
            logger=logger,
            collection_statistics=statistics,
        )
        diagnostics._enabled = True
        snapshot = diagnostics.emit_once()

        assert snapshot is not None
        collection = snapshot["collection"]
        self.assertEqual(collection["counters"]["completed_cycles"], 2)
        self.assertEqual(collection["counters"]["delayed_cycles"], 1)
        self.assertEqual(collection["counters"]["skipped_psi_cycles"], 2)
        self.assertEqual(collection["gauges"]["last_interval_seconds"], 12.0)

    def test_psi_unavailability_and_recovery_are_logged_once_per_transition(self) -> None:
        logger = Mock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            collector = PSICollector(proc_root=root, logger=logger)

            self.assertEqual(collector.collect(), {})
            self.assertEqual(collector.collect(), {})
            self.assertEqual(logger.warning.call_count, 3)

            pressure = root / "pressure"
            pressure.mkdir()
            content = "some avg10=1 avg60=2 avg300=3 total=4\n"
            for resource in ("cpu", "memory", "io"):
                (pressure / resource).write_text(content, encoding="utf-8")

            self.assertEqual(set(collector.collect()), {"cpu", "memory", "io"})
            self.assertEqual(logger.info.call_count, 3)
            self.assertEqual(
                collector.availability_snapshot(),
                {"cpu": True, "memory": True, "io": True},
            )


if __name__ == "__main__":
    unittest.main()
