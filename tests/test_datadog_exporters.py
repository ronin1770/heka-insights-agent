"""Tests for Datadog OTLP preset and Datadog native exporter paths."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from exporters.datadog_native import (  # noqa: E402
    DatadogMetricSender,
    DatadogNativeExporter,
)
from exporters.factory import create_exporter  # noqa: E402
from exporters.otlp_http import OtlpHttpExporter  # noqa: E402


class _SenderStub:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def send(self, payload: dict) -> None:
        self.payloads.append(payload)


class _FakeResponse:
    def __init__(self, *, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class DatadogExporterTests(unittest.TestCase):
    """Validate Datadog exporter paths and request formation."""

    def test_factory_creates_datadog_otlp_exporter_with_derived_endpoint(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATADOG_SITE": "us5.datadoghq.com",
                "DATADOG_API_KEY": "dd-api-key-123",
                "DATADOG_HOSTNAME": "dd-node-a",
                "DATADOG_TAGS": "env:prod,team:platform",
                "OTLP_HTTP_TIMEOUT_SECONDS": "3",
            },
            clear=True,
        ):
            exporter = create_exporter("datadog_otlp")
            self.assertIsInstance(exporter, OtlpHttpExporter)

            exporter.initialize()
            health = exporter.health_status()
            assert health is not None
            self.assertEqual(
                health["endpoint"],
                "https://otlp.us5.datadoghq.com/v1/metrics",
            )
            self.assertEqual(health["headers_configured"], 1)
            self.assertEqual(health["resource_attributes_configured"], 3)

    def test_factory_creates_datadog_native_exporter(self) -> None:
        exporter = create_exporter("datadog_native")
        self.assertIsInstance(exporter, DatadogNativeExporter)

    def test_native_export_maps_metric_types_tags_and_host(self) -> None:
        sender = _SenderStub()
        exporter = DatadogNativeExporter(
            hostname="dd-node-1",
            default_tags=["env:prod"],
            metric_prefix="heka",
            count_interval_seconds=10,
            sender=sender,
            endpoint="https://api.datadoghq.com/api/v1/series",
            api_key="dd-api-key-123",
        )

        metrics = [
            {
                "name": "heka_cpu_usage_percent",
                "description": "CPU usage percentage.",
                "type": "gauge",
                "unit": "percent",
                "value": 42.0,
                "labels": {"service": "agent", "host": "label-host", "env": "staging"},
                "timestamp_unix_ms": 1_700_000_000_000,
            },
            {
                "name": "heka_collections_total",
                "description": "Collection loop executions.",
                "type": "counter",
                "unit": "count",
                "value": 7,
                "labels": {"service": "agent"},
                "timestamp_unix_ms": 1_700_000_010_000,
            },
        ]

        exporter.initialize()
        exporter.export(metrics)

        self.assertEqual(len(sender.payloads), 1)
        series = sender.payloads[0]["series"]
        self.assertEqual(len(series), 2)

        self.assertEqual(series[0]["metric"], "heka.heka_cpu_usage_percent")
        self.assertEqual(series[0]["type"], "gauge")
        self.assertEqual(series[0]["host"], "dd-node-1")
        self.assertEqual(series[0]["points"], [[1_700_000_000, 42.0]])
        self.assertEqual(series[0]["tags"], ["env:prod", "host:label-host", "service:agent"])

        self.assertEqual(series[1]["metric"], "heka.heka_collections_total")
        self.assertEqual(series[1]["type"], "count")
        self.assertEqual(series[1]["interval"], 10)
        self.assertEqual(series[1]["points"], [[1_700_000_010, 7.0]])

    def test_native_export_uses_label_host_when_hostname_unset(self) -> None:
        sender = _SenderStub()
        exporter = DatadogNativeExporter(
            default_tags=["env:dev"],
            sender=sender,
            endpoint="https://api.datadoghq.com/api/v1/series",
            api_key="dd-api-key-123",
        )

        metric = {
            "name": "heka_memory_usage_percent",
            "description": "Memory usage percentage.",
            "type": "gauge",
            "unit": "percent",
            "value": 55.0,
            "labels": {"host": "label-host"},
            "timestamp_unix_ms": 1_700_000_000_000,
        }

        exporter.initialize()
        exporter.export([metric])

        payload = sender.payloads[0]
        self.assertEqual(payload["series"][0]["host"], "label-host")

    def test_native_export_uses_cpu_poll_interval_for_count_interval(self) -> None:
        sender = _SenderStub()
        metric = {
            "name": "heka_collections_total",
            "description": "Collection loop executions.",
            "type": "counter",
            "unit": "count",
            "value": 5,
            "labels": {"service": "agent"},
            "timestamp_unix_ms": 1_700_000_000_000,
        }

        with patch.dict(
            os.environ,
            {"CPU_POLL_INTERVAL_SECONDS": "2.6"},
            clear=True,
        ):
            exporter = DatadogNativeExporter(
                sender=sender,
                endpoint="https://api.datadoghq.com/api/v1/series",
                api_key="dd-api-key-123",
            )
            exporter.initialize()
            exporter.export([metric])

        payload = sender.payloads[0]
        self.assertEqual(payload["series"][0]["interval"], 3)

    def test_native_sender_posts_payload_with_api_key_header(self) -> None:
        captured: dict[str, object] = {}

        def fake_http_client(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakeResponse(status=202)

        sender = DatadogMetricSender(
            endpoint="https://api.datadoghq.com/api/v1/series",
            api_key="dd-api-key-123",
            timeout_seconds=9,
            http_client=fake_http_client,
        )

        payload = {
            "series": [
                {
                    "metric": "heka.cpu.usage",
                    "points": [[1_700_000_000, 42.0]],
                    "type": "gauge",
                }
            ]
        }
        sender.send(payload)

        request = captured["request"]
        assert hasattr(request, "header_items")
        assert hasattr(request, "data")
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(captured["timeout"], 9)
        self.assertEqual(headers["dd-api-key"], "dd-api-key-123")
        self.assertEqual(json.loads(request.data.decode("utf-8")), payload)

    def test_native_sender_raises_on_non_success_status(self) -> None:
        logger = Mock()
        sender = DatadogMetricSender(
            endpoint="https://api.datadoghq.com/api/v1/series",
            api_key="dd-api-key-123",
            http_client=lambda request, timeout: _FakeResponse(status=500),
            logger=logger,
        )

        with self.assertRaisesRegex(RuntimeError, "non-success status code 500"):
            sender.send({"series": []})
        logger.debug.assert_called_once()


if __name__ == "__main__":
    unittest.main()
