"""Tests for OTLP-specific runtime configuration parsing."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import get_otlp_http_headers, get_otlp_resource_attributes
from config import (
    DEFAULT_OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS,
    DEFAULT_OTLP_HTTP_RETRY_MAX_ATTEMPTS,
    DEFAULT_OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS,
    DEFAULT_OTLP_HTTP_TIMEOUT_SECONDS,
    get_otlp_http_retry_initial_backoff_seconds,
    get_otlp_http_retry_max_attempts,
    get_otlp_http_retry_max_backoff_seconds,
    get_otlp_http_timeout_seconds,
)


class OtlpRuntimeConfigTests(unittest.TestCase):
    """Validate OTLP key-value environment parsing."""

    def test_parses_otlp_http_headers(self) -> None:
        with patch.dict(
            os.environ,
            {"OTLP_HTTP_HEADERS": "api-key=abc123,authorization=Bearer token"},
            clear=True,
        ):
            self.assertEqual(
                get_otlp_http_headers(),
                {"api-key": "abc123", "authorization": "Bearer token"},
            )

    def test_parses_resource_attributes(self) -> None:
        with patch.dict(
            os.environ,
            {"OTLP_RESOURCE_ATTRIBUTES": "service.name=heka,host.name=node-a"},
            clear=True,
        ):
            self.assertEqual(
                get_otlp_resource_attributes(),
                {"service.name": "heka", "host.name": "node-a"},
            )

    def test_returns_empty_mappings_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_otlp_http_headers(), {})
            self.assertEqual(get_otlp_resource_attributes(), {})

    def test_rejects_invalid_key_value_mapping(self) -> None:
        with patch.dict(os.environ, {"OTLP_HTTP_HEADERS": "invalid-entry"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Invalid OTLP_HTTP_HEADERS"):
                get_otlp_http_headers()

        with patch.dict(
            os.environ,
            {"OTLP_RESOURCE_ATTRIBUTES": "service.name="},
            clear=True,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "Invalid OTLP_RESOURCE_ATTRIBUTES"
            ):
                get_otlp_resource_attributes()

    def test_parses_retry_configuration(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OTLP_HTTP_TIMEOUT_SECONDS": "12",
                "OTLP_HTTP_RETRY_MAX_ATTEMPTS": "4",
                "OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS": "0.5",
                "OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS": "6",
            },
            clear=True,
        ):
            self.assertEqual(get_otlp_http_timeout_seconds(), 12)
            self.assertEqual(get_otlp_http_retry_max_attempts(), 4)
            self.assertEqual(get_otlp_http_retry_initial_backoff_seconds(), 0.5)
            self.assertEqual(get_otlp_http_retry_max_backoff_seconds(), 6.0)

    def test_invalid_retry_configuration_falls_back_to_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OTLP_HTTP_TIMEOUT_SECONDS": "0",
                "OTLP_HTTP_RETRY_MAX_ATTEMPTS": "-1",
                "OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS": "bad",
                "OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS": "",
            },
            clear=True,
        ):
            self.assertEqual(
                get_otlp_http_timeout_seconds(),
                DEFAULT_OTLP_HTTP_TIMEOUT_SECONDS,
            )
            self.assertEqual(
                get_otlp_http_retry_max_attempts(),
                DEFAULT_OTLP_HTTP_RETRY_MAX_ATTEMPTS,
            )
            self.assertEqual(
                get_otlp_http_retry_initial_backoff_seconds(),
                DEFAULT_OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS,
            )
            self.assertEqual(
                get_otlp_http_retry_max_backoff_seconds(),
                DEFAULT_OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS,
            )


if __name__ == "__main__":
    unittest.main()
