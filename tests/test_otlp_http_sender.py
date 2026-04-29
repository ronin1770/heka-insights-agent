"""Tests for OTLP HTTP sender behavior."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
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

    def test_applies_custom_headers(self) -> None:
        captured: dict[str, object] = {}

        def fake_http_client(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakeResponse(status=200)

        sender = OtlpHttpMetricSender(
            endpoint="https://collector.example.com/v1/metrics",
            headers={"api-key": "secret-token"},
            http_client=fake_http_client,
        )
        sender.send({"resourceMetrics": []})

        request = captured["request"]
        assert hasattr(request, "header_items")
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["api-key"], "secret-token")

    def test_logs_info_when_headers_are_accepted(self) -> None:
        logger = Mock()
        sender = OtlpHttpMetricSender(
            endpoint="https://collector.example.com/v1/metrics",
            headers={"api-key": "secret-token"},
            http_client=lambda request, timeout: _FakeResponse(status=200),
            logger=logger,
        )
        sender.send({"resourceMetrics": []})
        logger.info.assert_called_once()
        logger.debug.assert_not_called()

    def test_raises_on_non_2xx_status(self) -> None:
        logger = Mock()
        sender = OtlpHttpMetricSender(
            endpoint="https://collector.example.com/v1/metrics",
            http_client=lambda request, timeout: _FakeResponse(status=500),
            logger=logger,
        )
        with self.assertRaisesRegex(RuntimeError, "non-success status code 500"):
            sender.send({"resourceMetrics": []})
        logger.debug.assert_called_once()

    def test_raises_on_transport_error(self) -> None:
        logger = Mock()

        def failing_http_client(request, timeout):
            raise URLError("network down")

        sender = OtlpHttpMetricSender(
            endpoint="https://collector.example.com/v1/metrics",
            http_client=failing_http_client,
            logger=logger,
        )
        with self.assertRaisesRegex(RuntimeError, "failed to reach endpoint"):
            sender.send({"resourceMetrics": []})
        logger.debug.assert_called_once()

    def test_logs_debug_when_auth_rejected(self) -> None:
        logger = Mock()
        sender = OtlpHttpMetricSender(
            endpoint="https://collector.example.com/v1/metrics",
            headers={"api-key": "bad"},
            http_client=lambda request, timeout: _FakeResponse(status=401),
            logger=logger,
        )
        with self.assertRaisesRegex(RuntimeError, "non-success status code 401"):
            sender.send({"resourceMetrics": []})
        logger.debug.assert_called_once()

    def test_retries_retryable_http_status_then_succeeds(self) -> None:
        logger = Mock()
        sleeps: list[float] = []
        statuses = [503, 200]
        call_count = {"value": 0}

        def flaky_http_client(request, timeout):
            call_count["value"] += 1
            return _FakeResponse(status=statuses[call_count["value"] - 1])

        sender = OtlpHttpMetricSender(
            endpoint="https://collector.example.com/v1/metrics",
            retry_max_attempts=3,
            retry_initial_backoff_seconds=0.25,
            retry_max_backoff_seconds=1.0,
            http_client=flaky_http_client,
            sleep_fn=sleeps.append,
            logger=logger,
        )
        sender.send({"resourceMetrics": []})

        self.assertEqual(call_count["value"], 2)
        self.assertEqual(sleeps, [0.25])
        logger.debug.assert_called_once()

    def test_does_not_retry_non_retryable_status(self) -> None:
        sleeps: list[float] = []
        sender = OtlpHttpMetricSender(
            endpoint="https://collector.example.com/v1/metrics",
            retry_max_attempts=3,
            retry_initial_backoff_seconds=0.25,
            retry_max_backoff_seconds=1.0,
            http_client=lambda request, timeout: _FakeResponse(status=400),
            sleep_fn=sleeps.append,
        )
        with self.assertRaisesRegex(RuntimeError, "non-success status code 400"):
            sender.send({"resourceMetrics": []})
        self.assertEqual(sleeps, [])

    def test_retries_transport_error_until_exhausted(self) -> None:
        logger = Mock()
        sleeps: list[float] = []
        call_count = {"value": 0}

        def failing_http_client(request, timeout):
            call_count["value"] += 1
            raise URLError("network down")

        sender = OtlpHttpMetricSender(
            endpoint="https://collector.example.com/v1/metrics",
            retry_max_attempts=3,
            retry_initial_backoff_seconds=0.25,
            retry_max_backoff_seconds=1.0,
            http_client=failing_http_client,
            sleep_fn=sleeps.append,
            logger=logger,
        )
        with self.assertRaisesRegex(RuntimeError, "failed to reach endpoint"):
            sender.send({"resourceMetrics": []})
        self.assertEqual(call_count["value"], 3)
        self.assertEqual(sleeps, [0.25, 0.5])
        self.assertGreaterEqual(logger.debug.call_count, 2)

    def test_rejects_invalid_retry_configuration(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "retry_max_attempts"):
            OtlpHttpMetricSender(
                endpoint="https://collector.example.com/v1/metrics",
                retry_max_attempts=0,
            )

        with self.assertRaisesRegex(RuntimeError, "timeout_seconds"):
            OtlpHttpMetricSender(
                endpoint="https://collector.example.com/v1/metrics",
                timeout_seconds=0,
            )

    def test_rejects_invalid_endpoint(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Invalid OTLP HTTP endpoint"):
            OtlpHttpMetricSender(endpoint="collector.example.com/v1/metrics")


if __name__ == "__main__":
    unittest.main()
