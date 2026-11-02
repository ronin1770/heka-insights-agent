"""Regression tests for CPU and memory collector semantics."""

from __future__ import annotations

import sys
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from collectors.cpu import CPUCollector  # noqa: E402
from collectors.memory import MemoryCollector  # noqa: E402


CPUTime = namedtuple(
    "CPUTime",
    "user nice system idle iowait irq softirq steal guest guest_nice",
)
VirtualMemory = namedtuple("VirtualMemory", "total available percent used free")
SwapMemory = namedtuple("SwapMemory", "total used free percent sin sout")


class CPUCollectorTests(unittest.TestCase):
    def test_first_sample_is_warmup_and_second_is_normalized(self) -> None:
        first = CPUTime(10, 0, 5, 80, 5, 0, 0, 0, 0, 0)
        second = CPUTime(30, 0, 15, 140, 15, 0, 0, 0, 0, 0)
        collector = CPUCollector(detail="detailed", round_digits=None)

        with patch("collectors.cpu.psutil.cpu_times", side_effect=(first, second)):
            warmup = collector.collect()
            measured = collector.collect()

        self.assertTrue(warmup["warming_up"])
        self.assertIsNone(warmup["percent"])
        self.assertFalse(measured["warming_up"])
        self.assertAlmostEqual(measured["percent"], 30.0)

    def test_idle_and_iowait_are_idle_and_steal_is_busy(self) -> None:
        collector = CPUCollector(detail="detailed", round_digits=None)
        collector._field_names = CPUTime._fields
        previous = dict.fromkeys(CPUTime._fields, 0.0)
        current = dict(previous, user=20.0, idle=50.0, iowait=20.0, steal=10.0)

        measured = collector._compute_core(
            previous,
            current,
            include_breakdown=True,
        )

        self.assertAlmostEqual(measured["percent"], 30.0)

    def test_linux_guest_fields_are_not_double_counted(self) -> None:
        collector = CPUCollector(detail="detailed", round_digits=None)
        collector._field_names = CPUTime._fields
        previous = dict.fromkeys(CPUTime._fields, 0.0)
        # Linux /proc/stat already includes guest time in user time.
        current = dict(previous, user=50.0, idle=50.0, guest=20.0)

        measured = collector._compute_core(
            previous,
            current,
            include_breakdown=True,
        )

        self.assertAlmostEqual(measured["percent"], 50.0)
        self.assertAlmostEqual(measured["times_percent"]["guest"], 20.0)


class MemoryCollectorTests(unittest.TestCase):
    def test_preserves_available_memory_reference_semantics(self) -> None:
        virtual = VirtualMemory(
            total=1_000,
            available=400,
            percent=60.0,
            used=600,
            free=100,
        )
        swap = SwapMemory(total=500, used=100, free=400, percent=20.0, sin=10, sout=20)

        with (
            patch("collectors.memory.psutil.virtual_memory", return_value=virtual),
            patch("collectors.memory.psutil.swap_memory", return_value=swap),
        ):
            payload = MemoryCollector(detail="detailed").collect()

        memory = payload["virtual_memory"]
        self.assertEqual(memory["used"], memory["total"] - memory["available"])
        self.assertEqual(memory["percent"], 60.0)
        self.assertEqual(payload["swap_memory"]["used"], 100)
        self.assertEqual(payload["swap_memory"]["sin"], 10)
        self.assertEqual(payload["swap_memory"]["sout"], 20)


if __name__ == "__main__":
    unittest.main()
