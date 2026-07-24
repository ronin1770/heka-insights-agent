"""Tests for packaged setup wizard prompting and config persistence."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import setup_wizard
from config import (
    CPU_POLL_INTERVAL_ENV_KEY,
    EXPORTER_TYPE_ENV_KEY,
    HEKA_AGENT_ID_ENV_KEY,
    HEKA_API_KEY_ENV_KEY,
    HEKA_INTELLIGENCE_ENABLED_ENV_KEY,
    LOG_LOCATION_ENV_KEY,
    OTLP_HTTP_ENDPOINT_ENV_KEY,
    OTLP_HTTP_HEADERS_ENV_KEY,
    OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS_ENV_KEY,
    OTLP_HTTP_RETRY_MAX_ATTEMPTS_ENV_KEY,
    OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS_ENV_KEY,
    OTLP_HTTP_TIMEOUT_SECONDS_ENV_KEY,
    OTLP_RESOURCE_ATTRIBUTES_ENV_KEY,
)


class SetupWizardConfigTests(unittest.TestCase):
    """Validate Heka Intelligence setup prompts and persisted config."""

    def test_collect_config_persists_intelligence_values_for_otlp_http(self) -> None:
        user_inputs = [
            "/var/log/heka-insights-agent/agent.log",
            "10",
            "otlp_http",
            "https://ingest.heka-insights.com/v1/metrics",
            "yes",
            "agt_01JXYZ123",
            "",
            "service.name=heka-insights-agent,host.name=localhost",
            "10",
            "5",
            "1",
            "5",
        ]

        with patch("builtins.input", side_effect=user_inputs), patch(
            "getpass.getpass",
            return_value="hek_live_secret_123",
        ):
            config = setup_wizard._collect_config({})

        self.assertEqual(config[LOG_LOCATION_ENV_KEY], "/var/log/heka-insights-agent/agent.log")
        self.assertEqual(config[CPU_POLL_INTERVAL_ENV_KEY], "10")
        self.assertEqual(config[EXPORTER_TYPE_ENV_KEY], "otlp_http")
        self.assertEqual(
            config[OTLP_HTTP_ENDPOINT_ENV_KEY],
            "https://ingest.heka-insights.com/v1/metrics",
        )
        self.assertEqual(config[HEKA_INTELLIGENCE_ENABLED_ENV_KEY], "true")
        self.assertEqual(config[HEKA_AGENT_ID_ENV_KEY], "agt_01JXYZ123")
        self.assertEqual(config[HEKA_API_KEY_ENV_KEY], "hek_live_secret_123")
        self.assertEqual(config[OTLP_HTTP_HEADERS_ENV_KEY], "")
        self.assertEqual(
            config[OTLP_RESOURCE_ATTRIBUTES_ENV_KEY],
            "service.name=heka-insights-agent,host.name=localhost",
        )
        self.assertEqual(config[OTLP_HTTP_TIMEOUT_SECONDS_ENV_KEY], "10")
        self.assertEqual(config[OTLP_HTTP_RETRY_MAX_ATTEMPTS_ENV_KEY], "5")
        self.assertEqual(config[OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS_ENV_KEY], "1")
        self.assertEqual(config[OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS_ENV_KEY], "5")

    def test_collect_config_skips_intelligence_credentials_when_disabled(self) -> None:
        user_inputs = [
            "/var/log/heka-insights-agent/agent.log",
            "10",
            "otlp_http",
            "https://collector.example.com/v1/metrics",
            "no",
            "",
            "service.name=heka-insights-agent,host.name=localhost",
            "10",
            "5",
            "1",
            "5",
        ]

        with patch("builtins.input", side_effect=user_inputs), patch(
            "getpass.getpass"
        ) as getpass_mock:
            config = setup_wizard._collect_config({})

        self.assertEqual(config[HEKA_INTELLIGENCE_ENABLED_ENV_KEY], "false")
        self.assertNotIn(HEKA_AGENT_ID_ENV_KEY, config)
        self.assertNotIn(HEKA_API_KEY_ENV_KEY, config)
        getpass_mock.assert_not_called()

    def test_write_config_file_persists_heka_intelligence_values(self) -> None:
        config_values = {
            LOG_LOCATION_ENV_KEY: "/var/log/heka-insights-agent/agent.log",
            EXPORTER_TYPE_ENV_KEY: "otlp_http",
            OTLP_HTTP_ENDPOINT_ENV_KEY: "https://ingest.heka-insights.com/v1/metrics",
            HEKA_INTELLIGENCE_ENABLED_ENV_KEY: "true",
            HEKA_AGENT_ID_ENV_KEY: "agt_01JXYZ123",
            HEKA_API_KEY_ENV_KEY: "hek_live_secret_123",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            env_directory = Path(temp_dir) / "heka-insights-agent"
            env_file = env_directory / ".env"

            with patch.object(setup_wizard, "ENV_DIRECTORY", env_directory), patch.object(
                setup_wizard, "ENV_FILE", env_file
            ):
                setup_wizard._write_config_file(config_values)

            written = env_file.read_text(encoding="utf-8")

        self.assertIn("HEKA_INTELLIGENCE_ENABLED=true\n", written)
        self.assertIn("HEKA_AGENT_ID=agt_01JXYZ123\n", written)
        self.assertIn("HEKA_API_KEY=hek_live_secret_123\n", written)


if __name__ == "__main__":
    unittest.main()
