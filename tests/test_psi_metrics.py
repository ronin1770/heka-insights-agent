"""Tests for PSI configuration and canonical exporter integration."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config.psi_runtime import (  # noqa: E402
    DEFAULT_PSI_POLL_INTERVAL_SECONDS,
    get_psi_poll_interval_seconds,
)
from exporters.otlp_http import OtlpHttpExporter  # noqa: E402
from formatters.prometheus import PrometheusFormatter  # noqa: E402
from pipeline import build_canonical_metrics  # noqa: E402


class _SenderStub:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def send(self, payload: dict) -> None:
        self.payloads.append(payload)


class PSIMetricTests(unittest.TestCase):
    def test_interval_defaults_to_thirty_seconds_and_is_configurable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                get_psi_poll_interval_seconds(),
                DEFAULT_PSI_POLL_INTERVAL_SECONDS,
            )
        with patch.dict(
            os.environ,
            {"PSI_POLL_INTERVAL_SECONDS": "45.5"},
            clear=True,
        ):
            self.assertEqual(get_psi_poll_interval_seconds(), 45.5)

    def test_nonfinite_and_nonpositive_intervals_use_default(self) -> None:
        for raw_value in ("nan", "inf", "-inf", "0", "-1", "invalid"):
            with self.subTest(raw_value=raw_value):
                logger = Mock()
                with patch.dict(
                    os.environ,
                    {"PSI_POLL_INTERVAL_SECONDS": raw_value},
                    clear=True,
                ):
                    interval = get_psi_poll_interval_seconds(logger=logger)
                self.assertEqual(interval, DEFAULT_PSI_POLL_INTERVAL_SECONDS)
                logger.warning.assert_called_once()

    def test_maps_psi_values_without_unit_conversion(self) -> None:
        metrics = build_canonical_metrics(
            {
                "cpu": {"warming_up": True},
                "memory": {},
                "disk": {},
                "psi": {
                    "cpu": {
                        "some": {
                            "avg10": 12.5,
                            "avg60": 8.3,
                            "avg300": 4.2,
                            "total": 184729301,
                        }
                    },
                    "memory": {
                        "full": {
                            "avg10": 0.5,
                            "avg60": 0.2,
                            "avg300": 0.1,
                            "total": 8291030,
                        }
                    },
                },
            },
            timestamp_unix_ms=1_700_000_000_000,
        )

        pressure = [
            metric for metric in metrics if metric["name"] == "heka_psi_pressure_percent"
        ]
        totals = [
            metric
            for metric in metrics
            if metric["name"] == "heka_psi_stall_time_microseconds_total"
        ]
        self.assertEqual(len(pressure), 6)
        self.assertEqual(len(totals), 2)
        self.assertEqual(pressure[0]["value"], 12.5)
        self.assertEqual(pressure[0]["unit"], "percent")
        self.assertEqual(totals[0]["value"], 184729301)
        self.assertEqual(totals[0]["type"], "counter")
        self.assertEqual(totals[0]["unit"], "microseconds")

    def test_psi_metrics_pass_through_prometheus_and_otlp(self) -> None:
        psi_payload = {
            resource: {
                stall: {
                    "avg10": float(resource_index + stall_index + 1),
                    "avg60": float(resource_index + stall_index + 2),
                    "avg300": float(resource_index + stall_index + 3),
                    "total": (resource_index + 1) * (stall_index + 1) * 1000,
                }
                for stall_index, stall in enumerate(("some", "full"))
            }
            for resource_index, resource in enumerate(("cpu", "memory", "io"))
        }
        metrics = build_canonical_metrics(
            {
                "cpu": {"warming_up": True},
                "memory": {},
                "disk": {},
                "psi": psi_payload,
            },
            timestamp_unix_ms=1_700_000_000_000,
        )

        prometheus = PrometheusFormatter().format_canonical(metrics)
        self.assertIn(
            'heka_psi_pressure_percent{resource="io",stall="full",window="avg300"} 6 1700000000000',
            prometheus,
        )

        sender = _SenderStub()
        exporter = OtlpHttpExporter(
            endpoint="https://collector.example.com/v1/metrics",
            sender=sender,  # type: ignore[arg-type]
            background_dispatch=False,
        )
        exporter.initialize()
        exporter.export(metrics)
        exporter.shutdown()

        self.assertEqual(len(sender.payloads), 1)
        mapped = sender.payloads[0]
        otlp_metrics = mapped["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        self.assertEqual(len(otlp_metrics), 24)

        pressure = [
            item
            for item in otlp_metrics
            if item["name"] == "heka_psi_pressure_percent"
        ]
        totals = [
            item
            for item in otlp_metrics
            if item["name"] == "heka_psi_stall_time_microseconds_total"
        ]
        self.assertEqual(len(pressure), 18)
        self.assertEqual(len(totals), 6)
        self.assertEqual(
            {
                (
                    self._attributes(item)["resource"],
                    self._attributes(item)["stall"],
                    self._attributes(item)["window"],
                )
                for item in pressure
            },
            {
                (resource, stall, window)
                for resource in ("cpu", "memory", "io")
                for stall in ("some", "full")
                for window in ("avg10", "avg60", "avg300")
            },
        )
        self.assertTrue(all(item["unit"] == "microseconds" for item in totals))
        self.assertTrue(all(item["sum"]["isMonotonic"] for item in totals))

    @staticmethod
    def _attributes(metric: dict) -> dict[str, str]:
        point_kind = "gauge" if "gauge" in metric else "sum"
        attributes = metric[point_kind]["dataPoints"][0]["attributes"]
        return {
            attribute["key"]: attribute["value"]["stringValue"]
            for attribute in attributes
        }


if __name__ == "__main__":
    unittest.main()
