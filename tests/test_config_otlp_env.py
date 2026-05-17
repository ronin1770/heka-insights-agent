"""Tests for OTLP-specific runtime configuration parsing."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import (
    get_datadog_native_config,
    get_datadog_otlp_preset,
    get_newrelic_otlp_preset,
    get_otlp_http_headers,
    get_otlp_resource_attributes,
)
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

    def test_parses_newrelic_preset_and_applies_precedence(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NEWRELIC_OTLP_ENDPOINT": "https://otlp.nr-data.net/v1/metrics",
                "NEWRELIC_API_KEY": "nr-license-123",
                "NEWRELIC_SERVICE_NAME": "heka-service",
                "NEWRELIC_ENVIRONMENT": "prod",
                "NEWRELIC_HOST_NAME": "node-a",
                "OTLP_HTTP_HEADERS": "api-key=old-key,x-tenant=eng",
                "OTLP_RESOURCE_ATTRIBUTES": "service.name=legacy,host.name=legacy-host,team=platform",
            },
            clear=True,
        ):
            endpoint, headers, resource_attributes = get_newrelic_otlp_preset()

        self.assertEqual(endpoint, "https://otlp.nr-data.net/v1/metrics")
        self.assertEqual(headers["api-key"], "nr-license-123")
        self.assertEqual(headers["x-tenant"], "eng")
        self.assertEqual(resource_attributes["service.name"], "heka-service")
        self.assertEqual(resource_attributes["deployment.environment"], "prod")
        self.assertEqual(resource_attributes["host.name"], "node-a")
        self.assertEqual(resource_attributes["team"], "platform")

    def test_newrelic_preset_rejects_missing_required_values(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NEWRELIC_API_KEY": "nr-license-123",
                "NEWRELIC_SERVICE_NAME": "heka-service",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "NEWRELIC_OTLP_ENDPOINT"):
                get_newrelic_otlp_preset()

    def test_newrelic_preset_rejects_invalid_endpoint(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NEWRELIC_OTLP_ENDPOINT": "nr-endpoint",
                "NEWRELIC_API_KEY": "nr-license-123",
                "NEWRELIC_SERVICE_NAME": "heka-service",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "Invalid NEWRELIC_OTLP_ENDPOINT"):
                get_newrelic_otlp_preset()

    def test_parses_datadog_otlp_preset(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATADOG_SITE": "us3.datadoghq.com",
                "DATADOG_API_KEY": "dd-api-key-123",
                "DATADOG_HOSTNAME": "dd-node-a",
                "DATADOG_TAGS": "env:prod,team:platform",
                "OTLP_HTTP_HEADERS": "x-tenant=infra",
                "OTLP_RESOURCE_ATTRIBUTES": "service.name=heka,region=us-east-1",
            },
            clear=True,
        ):
            endpoint, headers, resource_attributes = get_datadog_otlp_preset()

        self.assertEqual(endpoint, "https://otlp.us3.datadoghq.com/v1/metrics")
        self.assertEqual(headers["dd-api-key"], "dd-api-key-123")
        self.assertEqual(headers["x-tenant"], "infra")
        self.assertEqual(resource_attributes["host.name"], "dd-node-a")
        self.assertEqual(resource_attributes["env"], "prod")
        self.assertEqual(resource_attributes["team"], "platform")
        self.assertEqual(resource_attributes["service.name"], "heka")
        self.assertEqual(resource_attributes["region"], "us-east-1")

    def test_datadog_site_validation_rejects_unsupported_value(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATADOG_SITE": "invalid-site",
                "DATADOG_API_KEY": "dd-api-key-123",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "Invalid DATADOG_SITE"):
                get_datadog_otlp_preset()

    def test_datadog_native_config_resolves_full_domain_site(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATADOG_SITE": "ap1.datadoghq.com",
                "DATADOG_API_KEY": "dd-api-key-123",
                "DATADOG_HOSTNAME": "host-1",
                "DATADOG_TAGS": "env:staging,team:core",
                "DATADOG_METRIC_PREFIX": "heka",
            },
            clear=True,
        ):
            endpoint, api_key, host_name, default_tags, metric_prefix = (
                get_datadog_native_config()
            )

        self.assertEqual(endpoint, "https://api.ap1.datadoghq.com/api/v1/series")
        self.assertEqual(api_key, "dd-api-key-123")
        self.assertEqual(host_name, "host-1")
        self.assertEqual(default_tags, ["env:staging", "team:core"])
        self.assertEqual(metric_prefix, "heka")

    def test_datadog_otlp_preset_rejects_invalid_tag_pair(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATADOG_SITE": "datadoghq.com",
                "DATADOG_API_KEY": "dd-api-key-123",
                "DATADOG_TAGS": "env",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "Invalid DATADOG_TAGS"):
                get_datadog_otlp_preset()

    def test_datadog_otlp_preset_rejects_empty_api_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATADOG_SITE": "datadoghq.com",
                "DATADOG_API_KEY": "   ",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "DATADOG_API_KEY"):
                get_datadog_otlp_preset()

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
