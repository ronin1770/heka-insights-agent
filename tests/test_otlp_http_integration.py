"""Docker-backed OTLP HTTP exporter integration tests."""

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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from exporters.otlp_http import OtlpHttpExporter

RUN_OTLP_INTEGRATION_ENV_KEY = "RUN_OTLP_INTEGRATION"
COLLECTOR_IMAGE_ENV_KEY = "OTELCOL_IMAGE"
OTLP_IT_BASE_PORT_ENV_KEY = "OTLP_IT_BASE_PORT"
DEFAULT_COLLECTOR_IMAGE = "otel/opentelemetry-collector-contrib:latest"
DEFAULT_OTLP_IT_BASE_PORT = 14318
COLLECTOR_CONTAINER_PORT = 4318
COLLECTOR_STARTUP_TIMEOUT_SECONDS = 20.0


class OtlpHttpIntegrationTests(unittest.TestCase):
    """Validate OTLP HTTP exporter behavior against a real collector container."""

    @classmethod
    def setUpClass(cls) -> None:
        if os.getenv(RUN_OTLP_INTEGRATION_ENV_KEY) != "1":
            raise unittest.SkipTest(
                f"Set {RUN_OTLP_INTEGRATION_ENV_KEY}=1 to run Docker OTLP integration tests."
            )
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

    def setUp(self) -> None:
        self._started_containers: list[str] = []

    def tearDown(self) -> None:
        for container_name in reversed(self._started_containers):
            self._stop_collector(container_name=container_name)

    def test_auth_success_with_bearer_header(self) -> None:
        port = self._port_for(0)
        self._start_collector(
            fixture_name="collector-auth-required.yaml",
            host_port=port,
        )
        logger = Mock()

        self._export_once(
            endpoint=f"http://localhost:{port}/v1/metrics",
            headers="key=Bearer abcd1234",
            logger=logger,
        )

        info_messages = [call.args[0] for call in logger.info.call_args_list]
        self.assertTrue(
            any("OTLP auth headers accepted" in message for message in info_messages)
        )

    def test_auth_rejected_without_retry_for_401(self) -> None:
        port = self._port_for(1)
        self._start_collector(
            fixture_name="collector-auth-required.yaml",
            host_port=port,
        )
        logger = Mock()

        with self.assertRaisesRegex(RuntimeError, "HTTP error 401"):
            self._export_once(
                endpoint=f"http://localhost:{port}/v1/metrics",
                headers="key=Bearer wrong-token",
                logger=logger,
                retry_max_attempts=5,
            )

        debug_messages = [call.args[0] for call in logger.debug.call_args_list]
        self.assertTrue(
            any("auth headers rejected" in message for message in debug_messages)
        )
        self.assertFalse(
            any("retry scheduled" in message for message in debug_messages)
        )

    def test_no_auth_collector_accepts_without_headers(self) -> None:
        port = self._port_for(2)
        self._start_collector(
            fixture_name="collector-no-auth.yaml",
            host_port=port,
        )
        logger = Mock()

        self._export_once(
            endpoint=f"http://localhost:{port}/v1/metrics",
            headers=None,
            logger=logger,
        )

        info_messages = [call.args[0] for call in logger.info.call_args_list]
        self.assertFalse(
            any("OTLP auth headers accepted" in message for message in info_messages)
        )

    def _start_collector(self, *, fixture_name: str, host_port: int) -> None:
        fixture_path = (
            Path(__file__).resolve().parent / "fixtures" / "otlp" / fixture_name
        ).resolve()
        container_name = f"heka-otlp-it-{uuid4().hex[:8]}"
        collector_image = os.getenv(COLLECTOR_IMAGE_ENV_KEY, DEFAULT_COLLECTOR_IMAGE)

        command = [
            "docker",
            "run",
            "--rm",
            "--detach",
            "--name",
            container_name,
            "--publish",
            f"{host_port}:{COLLECTOR_CONTAINER_PORT}",
            "--volume",
            f"{fixture_path}:/etc/otelcol/config.yaml:ro",
            collector_image,
            "--config=/etc/otelcol/config.yaml",
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Failed to start collector container.\n"
                f"stdout: {completed.stdout}\n"
                f"stderr: {completed.stderr}"
            )

        self._started_containers.append(container_name)
        self._wait_for_collector_ready(container_name=container_name)

    @staticmethod
    def _stop_collector(*, container_name: str) -> None:
        subprocess.run(
            ["docker", "stop", container_name],
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _wait_for_collector_ready(*, container_name: str) -> None:
        deadline = time.time() + COLLECTOR_STARTUP_TIMEOUT_SECONDS
        while time.time() < deadline:
            running_result = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Running}}",
                    container_name,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            is_running = running_result.returncode == 0 and (
                running_result.stdout.strip() == "true"
            )
            if not is_running:
                break

            logs_result = subprocess.run(
                ["docker", "logs", "--tail", "50", container_name],
                capture_output=True,
                text=True,
                check=False,
            )
            combined_logs = f"{logs_result.stdout}\n{logs_result.stderr}"
            if "Everything is ready" in combined_logs:
                return

            time.sleep(0.2)

        logs_result = subprocess.run(
            ["docker", "logs", "--tail", "200", container_name],
            capture_output=True,
            text=True,
            check=False,
        )
        raise TimeoutError(
            "Collector did not report readiness within "
            f"{COLLECTOR_STARTUP_TIMEOUT_SECONDS:.0f}s.\n"
            f"stdout: {logs_result.stdout}\n"
            f"stderr: {logs_result.stderr}"
        )

    @staticmethod
    def _port_for(offset: int) -> int:
        base_port = int(
            os.getenv(OTLP_IT_BASE_PORT_ENV_KEY, str(DEFAULT_OTLP_IT_BASE_PORT))
        )
        return base_port + offset

    @staticmethod
    def _export_once(
        *,
        endpoint: str,
        headers: str | None,
        logger: Mock,
        retry_max_attempts: int = 2,
    ) -> None:
        env = {
            "EXPORTER_TYPE": "otlp_http",
            "OTLP_HTTP_ENDPOINT": endpoint,
            "OTLP_HTTP_TIMEOUT_SECONDS": "3",
            "OTLP_HTTP_RETRY_MAX_ATTEMPTS": str(retry_max_attempts),
            "OTLP_HTTP_RETRY_INITIAL_BACKOFF_SECONDS": "0.1",
            "OTLP_HTTP_RETRY_MAX_BACKOFF_SECONDS": "0.2",
            "OTLP_RESOURCE_ATTRIBUTES": "service.name=heka-it",
        }
        if headers is not None:
            env["OTLP_HTTP_HEADERS"] = headers

        metric = {
            "name": "heka_cpu_usage_percent",
            "description": "CPU usage percentage.",
            "type": "gauge",
            "unit": "percent",
            "value": 42.0,
            "labels": {"host": "it-node"},
            "timestamp_unix_ms": 1_700_000_000_000,
        }

        with patch.dict(os.environ, env, clear=True):
            exporter = OtlpHttpExporter(logger=logger)
            exporter.initialize()
            try:
                exporter.export([metric])
            finally:
                exporter.shutdown()


if __name__ == "__main__":
    unittest.main()
