"""Tests for process telemetry configuration and canonical mapping."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config.process_runtime import (  # noqa: E402
    DEFAULT_PROCESS_POLL_INTERVAL_SECONDS,
    get_process_poll_interval_seconds,
)
from pipeline import build_canonical_metrics  # noqa: E402


class ProcessMetricTests(unittest.TestCase):
    def test_process_interval_defaults_to_thirty_seconds_and_is_configurable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                get_process_poll_interval_seconds(),
                DEFAULT_PROCESS_POLL_INTERVAL_SECONDS,
            )
        with patch.dict(
            os.environ,
            {"PROCESS_POLL_INTERVAL_SECONDS": "45"},
            clear=True,
        ):
            self.assertEqual(get_process_poll_interval_seconds(), 45.0)

    def test_invalid_process_interval_uses_default(self) -> None:
        logger = Mock()
        with patch.dict(
            os.environ,
            {"PROCESS_POLL_INTERVAL_SECONDS": "0"},
            clear=True,
        ):
            interval = get_process_poll_interval_seconds(logger=logger)

        self.assertEqual(interval, DEFAULT_PROCESS_POLL_INTERVAL_SECONDS)
        logger.warning.assert_called_once()

    def test_maps_process_and_network_metrics_and_omits_null_values(self) -> None:
        metrics = build_canonical_metrics(
            {
                "cpu": {"warming_up": True},
                "memory": {},
                "disk": {},
                "process": {
                    "processes": [
                        {
                            "pid": 1421,
                            "name": "gunicorn",
                            "cpu_percent": 42.5,
                            "rss_bytes": 39_403_520,
                            "threads": 4,
                            "open_file_descriptors": None,
                            "disk_read_bytes": 10_485_760,
                            "disk_write_bytes": None,
                        }
                    ],
                    "network": {
                        "bytes_sent": 125_829_120,
                        "bytes_received": 524_288_000,
                    },
                },
            },
            timestamp_unix_ms=1_700_000_000_000,
        )

        by_name = {metric["name"]: metric for metric in metrics}
        self.assertEqual(
            set(by_name),
            {
                "heka_process_cpu_usage_percent",
                "heka_process_rss_bytes",
                "heka_process_threads",
                "heka_process_disk_read_bytes_total",
                "heka_network_sent_bytes_total",
                "heka_network_received_bytes_total",
            },
        )
        self.assertEqual(
            by_name["heka_process_cpu_usage_percent"]["labels"],
            {"pid": "1421", "process_name": "gunicorn"},
        )
        self.assertEqual(by_name["heka_network_sent_bytes_total"]["labels"], {})
        self.assertNotIn("heka_process_open_file_descriptors", by_name)
        self.assertNotIn("heka_process_disk_write_bytes_total", by_name)

    def test_maps_all_authorized_process_and_network_metric_names(self) -> None:
        metrics = build_canonical_metrics(
            {
                "cpu": {"warming_up": True},
                "memory": {},
                "disk": {},
                "process": {
                    "processes": [
                        {
                            "pid": 7,
                            "name": "worker",
                            "cpu_percent": 1.0,
                            "rss_bytes": 2,
                            "threads": 3,
                            "open_file_descriptors": 4,
                            "disk_read_bytes": 5,
                            "disk_write_bytes": 6,
                        }
                    ],
                    "network": {"bytes_sent": 7, "bytes_received": 8},
                },
            }
        )

        self.assertEqual(
            {metric["name"] for metric in metrics},
            {
                "heka_process_cpu_usage_percent",
                "heka_process_rss_bytes",
                "heka_process_threads",
                "heka_process_open_file_descriptors",
                "heka_process_disk_read_bytes_total",
                "heka_process_disk_write_bytes_total",
                "heka_network_sent_bytes_total",
                "heka_network_received_bytes_total",
            },
        )


if __name__ == "__main__":
    unittest.main()
