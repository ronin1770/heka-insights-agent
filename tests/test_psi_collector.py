"""Tests for Linux Pressure Stall Information collection."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from collectors.psi import PSICollector, parse_psi_pressure  # noqa: E402


class PSIParserTests(unittest.TestCase):
    def test_parses_some_and_full_measurements(self) -> None:
        content = (
            "some avg10=12.50 avg60=8.30 avg300=4.20 total=184729301\n"
            "full avg10=0.50 avg60=0.20 avg300=0.10 total=8291030\n"
        )

        self.assertEqual(
            parse_psi_pressure(content),
            {
                "some": {
                    "avg10": 12.5,
                    "avg60": 8.3,
                    "avg300": 4.2,
                    "total": 184729301,
                },
                "full": {
                    "avg10": 0.5,
                    "avg60": 0.2,
                    "avg300": 0.1,
                    "total": 8291030,
                },
            },
        )

    def test_skips_malformed_full_line_and_retains_valid_some_line(self) -> None:
        logger = Mock()
        content = (
            "some avg10=3.20 avg60=1.50 avg300=0.80 total=56290110\n"
            "full avg10=nan avg60=0.20 avg300=0.10 total=8291030\n"
        )

        parsed = parse_psi_pressure(content, logger=logger, resource="memory")

        self.assertEqual(
            parsed,
            {
                "some": {
                    "avg10": 3.2,
                    "avg60": 1.5,
                    "avg300": 0.8,
                    "total": 56290110,
                }
            },
        )
        logger.debug.assert_called_once()

    def test_does_not_synthesize_cpu_full_when_record_is_missing(self) -> None:
        parsed = parse_psi_pressure(
            "some avg10=0.25 avg60=0.15 avg300=0.05 total=1234567\n",
            resource="cpu",
        )

        self.assertEqual(set(parsed), {"some"})
        self.assertNotIn("full", parsed)

    def test_rejects_missing_nonfinite_negative_and_out_of_range_values(self) -> None:
        invalid_lines = (
            "some avg10=1 avg60=2 total=3",
            "some avg10=inf avg60=2 avg300=3 total=4",
            "some avg10=-1 avg60=2 avg300=3 total=4",
            "some avg10=101 avg60=2 avg300=3 total=4",
            "some avg10=1 avg60=2 avg300=3 total=-4",
        )

        for line in invalid_lines:
            with self.subTest(line=line):
                self.assertEqual(parse_psi_pressure(line), {})


class PSICollectorTests(unittest.TestCase):
    def test_collects_valid_resources_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pressure = root / "pressure"
            pressure.mkdir()
            (pressure / "cpu").write_text(
                "some avg10=1.0 avg60=2.0 avg300=3.0 total=4\n",
                encoding="utf-8",
            )
            (pressure / "memory").write_text(
                "some malformed\n"
                "full avg10=0.1 avg60=0.2 avg300=0.3 total=5\n",
                encoding="utf-8",
            )

            payload = PSICollector(proc_root=root, logger=Mock()).collect()

        self.assertEqual(set(payload), {"cpu", "memory"})
        self.assertEqual(set(payload["cpu"]), {"some"})
        self.assertNotIn("full", payload["cpu"])
        self.assertEqual(set(payload["memory"]), {"full"})

    def test_missing_or_inaccessible_sources_return_no_payload(self) -> None:
        logger = Mock()
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                PSICollector(proc_root=directory, logger=logger).collect(),
                {},
            )
        self.assertEqual(logger.debug.call_count, 3)

        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            self.assertEqual(PSICollector(logger=Mock()).collect(), {})


if __name__ == "__main__":
    unittest.main()
