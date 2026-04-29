"""Tests for OTLP HTTP exporter wiring."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from exporters.factory import create_exporter
from exporters.otlp_http import OtlpHttpExporter


class _SenderStub:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def send(self, payload: dict) -> None:
        self.payloads.append(payload)


class OtlpHttpExporterTests(unittest.TestCase):
    """Validate exporter factory and startup behavior."""

    def test_factory_creates_otlp_http_exporter(self) -> None:
        exporter = create_exporter("otlp_http")
        self.assertIsInstance(exporter, OtlpHttpExporter)

    def test_initialize_fails_without_endpoint(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            exporter = OtlpHttpExporter()
            with self.assertRaisesRegex(RuntimeError, "OTLP_HTTP_ENDPOINT"):
                exporter.initialize()

    def test_export_maps_and_sends(self) -> None:
        sender = _SenderStub()
        exporter = OtlpHttpExporter(
            endpoint="https://collector.example.com/v1/metrics",
            sender=sender,
        )
        metric = {
            "name": "heka_cpu_usage_percent",
            "description": "CPU usage percentage.",
            "type": "gauge",
            "unit": "percent",
            "value": 50.0,
            "labels": {"host": "node-a"},
            "timestamp_unix_ms": 1_700_000_000_000,
        }

        exporter.initialize()
        exporter.export([metric])

        self.assertEqual(len(sender.payloads), 1)
        mapped = sender.payloads[0]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]
        self.assertEqual(mapped["name"], "heka_cpu_usage_percent")

    def test_initialize_applies_env_headers_and_resource_attributes(self) -> None:
        sender = _SenderStub()
        with patch.dict(
            os.environ,
            {
                "OTLP_HTTP_ENDPOINT": "https://collector.example.com/v1/metrics",
                "OTLP_HTTP_HEADERS": "api-key=abc123,authorization=Bearer token",
                "OTLP_RESOURCE_ATTRIBUTES": "service.name=heka,host.name=node-a",
            },
            clear=True,
        ):
            exporter = OtlpHttpExporter(sender=sender)
            exporter.initialize()

            self.assertEqual(
                exporter.health_status(),
                {
                    "initialized": True,
                    "endpoint": "https://collector.example.com/v1/metrics",
                    "headers_configured": 2,
                    "resource_attributes_configured": 2,
                },
            )

            metric = {
                "name": "heka_cpu_usage_percent",
                "description": "CPU usage percentage.",
                "type": "gauge",
                "unit": "percent",
                "value": 50.0,
                "labels": {},
            }
            exporter.export([metric])

        self.assertEqual(len(sender.payloads), 1)
        resource_attrs = sender.payloads[0]["resourceMetrics"][0]["resource"]["attributes"]
        self.assertEqual(
            resource_attrs,
            [
                {"key": "host.name", "value": {"stringValue": "node-a"}},
                {"key": "service.name", "value": {"stringValue": "heka"}},
            ],
        )

    def test_initialize_fails_on_invalid_otlp_http_headers(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OTLP_HTTP_ENDPOINT": "https://collector.example.com/v1/metrics",
                "OTLP_HTTP_HEADERS": "invalid-entry",
            },
            clear=True,
        ):
            exporter = OtlpHttpExporter()
            with self.assertRaisesRegex(RuntimeError, "Invalid OTLP_HTTP_HEADERS"):
                exporter.initialize()

    def test_initialize_fails_on_invalid_resource_attributes(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OTLP_HTTP_ENDPOINT": "https://collector.example.com/v1/metrics",
                "OTLP_RESOURCE_ATTRIBUTES": "service.name=",
            },
            clear=True,
        ):
            exporter = OtlpHttpExporter()
            with self.assertRaisesRegex(
                RuntimeError, "Invalid OTLP_RESOURCE_ATTRIBUTES"
            ):
                exporter.initialize()


if __name__ == "__main__":
    unittest.main()
