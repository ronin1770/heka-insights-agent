"""Tests for OTLP HTTP sender behavior."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from exporters.otlp_http import OtlpHttpMetricSender


class _FakeResponse:
    def __init__(self, *, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class OtlpHttpMetricSenderTests(unittest.TestCase):
    """Validate OTLP HTTP request dispatch behavior."""

    def test_posts_json_payload(self) -> None:
        captured: dict[str, object] = {}

        def fake_http_client(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakeResponse(status=200)

        sender = OtlpHttpMetricSender(
            endpoint="https://collector.example.com/v1/metrics",
            timeout_seconds=9,
            http_client=fake_http_client,
        )
        payload = {"resourceMetrics": []}
        sender.send(payload)

        request = captured["request"]
        assert hasattr(request, "full_url")
        assert hasattr(request, "get_method")
        assert hasattr(request, "data")
        assert hasattr(request, "header_items")

        self.assertEqual(captured["timeout"], 9)
        self.assertEqual(request.full_url, "https://collector.example.com/v1/metrics")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode("utf-8")), payload)
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(headers["accept"], "application/json")

    def test_raises_on_non_2xx_status(self) -> None:
        sender = OtlpHttpMetricSender(
            endpoint="https://collector.example.com/v1/metrics",
            http_client=lambda request, timeout: _FakeResponse(status=500),
        )
        with self.assertRaisesRegex(RuntimeError, "non-success status code 500"):
            sender.send({"resourceMetrics": []})

    def test_raises_on_transport_error(self) -> None:
        def failing_http_client(request, timeout):
            raise URLError("network down")

        sender = OtlpHttpMetricSender(
            endpoint="https://collector.example.com/v1/metrics",
            http_client=failing_http_client,
        )
        with self.assertRaisesRegex(RuntimeError, "failed to reach endpoint"):
            sender.send({"resourceMetrics": []})

    def test_rejects_invalid_endpoint(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Invalid OTLP HTTP endpoint"):
            OtlpHttpMetricSender(endpoint="collector.example.com/v1/metrics")


if __name__ == "__main__":
    unittest.main()
