"""Docker-run live Datadog integration tests for milestone 6."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from config import get_exporter_type
from exporters import create_exporter

RUN_OTLP_INTEGRATION_ENV_KEY = "RUN_OTLP_INTEGRATION"
RUN_DATADOG_LIVE_INTEGRATION_ENV_KEY = "RUN_DATADOG_LIVE_INTEGRATION"
DATADOG_SITE_ENV_KEY = "DATADOG_SITE"
DATADOG_API_KEY_ENV_KEY = "DATADOG_API_KEY"


class DatadogLiveIntegrationTests(unittest.TestCase):
    """Validate Datadog OTLP/native exporter behavior against live Datadog APIs."""

    @classmethod
    def setUpClass(cls) -> None:
        if os.getenv(RUN_OTLP_INTEGRATION_ENV_KEY) != "1":
            raise unittest.SkipTest(
                f"Set {RUN_OTLP_INTEGRATION_ENV_KEY}=1 to run Docker integration tests."
            )
        if os.getenv(RUN_DATADOG_LIVE_INTEGRATION_ENV_KEY) != "1":
            raise unittest.SkipTest(
                "Set RUN_DATADOG_LIVE_INTEGRATION=1 to run live Datadog integration tests."
            )

        # Keep the same guard pattern as other Docker-backed integration tests.
        if shutil.which("docker") is None:
            raise unittest.SkipTest("Docker CLI is not available in PATH.")
        docker_info = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=False,
        )
        if docker_info.returncode != 0:
            raise unittest.SkipTest(
                "Docker daemon is unavailable for integration tests "
                f"(docker info failed: {docker_info.stderr.strip()})."
            )

        if not os.getenv(DATADOG_SITE_ENV_KEY, "").strip():
            raise unittest.SkipTest(
                f"Set {DATADOG_SITE_ENV_KEY} for live Datadog integration tests."
            )
        if not os.getenv(DATADOG_API_KEY_ENV_KEY, "").strip():
            raise unittest.SkipTest(
                f"Set {DATADOG_API_KEY_ENV_KEY} for live Datadog integration tests."
            )

    def test_datadog_otlp_preset_exports_gauge_metric(self) -> None:
        logger = Mock()
        run_id = uuid4().hex[:8]
        metric = {
            "name": f"heka_m6_otlp_cpu_usage_percent_{run_id}",
            "description": "Milestone 6 OTLP integration gauge metric.",
            "type": "gauge",
            "unit": "percent",
            "value": 42.0,
            "labels": {"host": f"heka-m6-{run_id}", "suite": "milestone-6"},
            "timestamp_unix_ms": int(time.time() * 1000),
        }

        with patch.dict(
            os.environ,
            {
                **os.environ,
                "EXPORTER_TYPE": "datadog_otlp",
                "DATADOG_TAGS": "env:integration,team:platform",
                "DATADOG_HOSTNAME": f"heka-m6-otlp-{run_id}",
                "OTLP_HTTP_TIMEOUT_SECONDS": "10",
                "OTLP_HTTP_RETRY_MAX_ATTEMPTS": "2",
                "OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS": "1",
                "OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS": "2",
            },
            clear=True,
        ):
            exporter_type = get_exporter_type(logger=logger)
            exporter = create_exporter(exporter_type, logger=logger)
            exporter.initialize()
            try:
                exporter.export([metric])
            finally:
                exporter.shutdown()

        info_messages = [call.args[0] for call in logger.info.call_args_list]
        self.assertTrue(
            any("OTLP auth headers accepted" in message for message in info_messages)
        )

    def test_datadog_native_exports_gauge_and_count_metrics(self) -> None:
        logger = Mock()
        run_id = uuid4().hex[:8]
        metrics = [
            {
                "name": f"heka_m6_native_cpu_usage_percent_{run_id}",
                "description": "Milestone 6 Datadog native gauge metric.",
                "type": "gauge",
                "unit": "percent",
                "value": 37.0,
                "labels": {"host": f"heka-m6-{run_id}", "suite": "milestone-6"},
                "timestamp_unix_ms": int(time.time() * 1000),
            },
            {
                "name": f"heka_m6_native_collections_total_{run_id}",
                "description": "Milestone 6 Datadog native count metric.",
                "type": "counter",
                "unit": "count",
                "value": 3,
                "labels": {"host": f"heka-m6-{run_id}", "suite": "milestone-6"},
                "timestamp_unix_ms": int(time.time() * 1000),
            },
        ]

        with patch.dict(
            os.environ,
            {
                **os.environ,
                "EXPORTER_TYPE": "datadog_native",
                "DATADOG_TAGS": "env:integration,team:platform",
                "DATADOG_HOSTNAME": f"heka-m6-native-{run_id}",
                "DATADOG_METRIC_PREFIX": "heka",
                "CPU_POLL_INTERVAL_SECONDS": "5",
                "OTLP_HTTP_TIMEOUT_SECONDS": "10",
            },
            clear=True,
        ):
            exporter_type = get_exporter_type(logger=logger)
            exporter = create_exporter(exporter_type, logger=logger)
            exporter.initialize()
            health = exporter.health_status() or {}
            self.assertTrue(str(health.get("endpoint", "")).startswith("https://api."))
            self.assertEqual(health.get("count_interval_seconds"), 5)
            try:
                exporter.export(metrics)
            finally:
                exporter.shutdown()


if __name__ == "__main__":
    unittest.main()
