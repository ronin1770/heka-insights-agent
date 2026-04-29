"""Tests for OTLP payload mapping behavior."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from exporters.otlp_mapping import OtlpPayloadMapper


class OtlpPayloadMapperTests(unittest.TestCase):
    """Validate canonical metric mapping into OTLP payloads."""

    def test_maps_gauge_and_counter(self) -> None:
        mapper = OtlpPayloadMapper(
            now_unix_ms=lambda: 1_700_000_000_999,
            resource_attributes={
                "host.name": "node-a",
                "service.name": "heka-insights-agent",
            },
        )
        metrics = [
            {
                "name": "heka_cpu_usage_percent",
                "description": "CPU usage percentage.",
                "type": "gauge",
                "unit": "percent",
                "value": 35.5,
                "labels": {"host": "node-a"},
                "timestamp_unix_ms": 1_700_000_000_123,
            },
            {
                "name": "heka_disk_reads_total",
                "description": "Total disk read operations.",
                "type": "counter",
                "unit": "count",
                "value": 900,
                "labels": {"device": "sda"},
            },
        ]

        payload = mapper.map_metrics(metrics)
        resource_attributes = payload["resourceMetrics"][0]["resource"]["attributes"]
        self.assertEqual(
            resource_attributes,
            [
                {"key": "host.name", "value": {"stringValue": "node-a"}},
                {
                    "key": "service.name",
                    "value": {"stringValue": "heka-insights-agent"},
                },
            ],
        )
        mapped = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]

        gauge = mapped[0]
        self.assertEqual(gauge["name"], "heka_cpu_usage_percent")
        self.assertIn("gauge", gauge)
        self.assertEqual(
            gauge["gauge"]["dataPoints"][0]["timeUnixNano"],
            "1700000000123000000",
        )
        self.assertEqual(
            gauge["gauge"]["dataPoints"][0]["attributes"],
            [{"key": "host", "value": {"stringValue": "node-a"}}],
        )

        counter = mapped[1]
        self.assertIn("sum", counter)
        self.assertEqual(counter["sum"]["aggregationTemporality"], 2)
        self.assertTrue(counter["sum"]["isMonotonic"])
        self.assertEqual(
            counter["sum"]["dataPoints"][0]["timeUnixNano"],
            "1700000000999000000",
        )

    def test_rejects_missing_required_fields(self) -> None:
        mapper = OtlpPayloadMapper(now_unix_ms=lambda: 1_700_000_000_000)
        metrics = [
            {
                "description": "Missing name",
                "type": "gauge",
                "unit": "percent",
                "value": 10,
                "labels": {},
            }
        ]

        with self.assertRaisesRegex(ValueError, "missing required fields"):
            mapper.map_metrics(metrics)

    def test_rejects_unsupported_type(self) -> None:
        mapper = OtlpPayloadMapper(now_unix_ms=lambda: 1_700_000_000_000)
        metrics = [
            {
                "name": "heka_hist",
                "description": "Histogram unsupported in M4-1",
                "type": "histogram",
                "unit": "bytes",
                "value": 10,
                "labels": {},
            }
        ]

        with self.assertRaisesRegex(ValueError, "Unsupported canonical metric type"):
            mapper.map_metrics(metrics)

    def test_rejects_non_string_resource_attributes(self) -> None:
        with self.assertRaisesRegex(ValueError, "resource_attributes"):
            OtlpPayloadMapper(resource_attributes={"service.version": 1})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
