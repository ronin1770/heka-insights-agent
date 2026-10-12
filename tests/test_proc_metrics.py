"""Tests for procfs telemetry configuration and canonical mapping."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config.proc_runtime import (  # noqa: E402
    DEFAULT_PROC_POLL_INTERVAL_SECONDS,
    get_proc_poll_interval_seconds,
)
from exporters.datadog_native import DatadogSeriesMapper  # noqa: E402
from exporters.otlp_http import OtlpHttpExporter  # noqa: E402
from exporters.otlp_mapping import OtlpPayloadMapper  # noqa: E402
from formatters.prometheus import PrometheusFormatter  # noqa: E402
from pipeline import build_canonical_metrics  # noqa: E402


class _SenderStub:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def send(self, payload: dict) -> None:
        self.payloads.append(payload)


class ProcMetricTests(unittest.TestCase):
    def test_proc_interval_defaults_to_thirty_seconds_and_is_configurable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                get_proc_poll_interval_seconds(),
                DEFAULT_PROC_POLL_INTERVAL_SECONDS,
            )
        with patch.dict(
            os.environ,
            {"PROC_POLL_INTERVAL_SECONDS": "45"},
            clear=True,
        ):
            self.assertEqual(get_proc_poll_interval_seconds(), 45.0)

    def test_invalid_proc_interval_uses_default(self) -> None:
        logger = Mock()
        with patch.dict(
            os.environ,
            {"PROC_POLL_INTERVAL_SECONDS": "0"},
            clear=True,
        ):
            interval = get_proc_poll_interval_seconds(logger=logger)

        self.assertEqual(interval, DEFAULT_PROC_POLL_INTERVAL_SECONDS)
        logger.warning.assert_called_once()

    def test_maps_all_proc_metrics_and_omits_missing_limit_values(self) -> None:
        metrics = build_canonical_metrics(
            {
                "cpu": {"warming_up": True},
                "memory": {},
                "disk": {},
                "proc": {
                    "tcp": {
                        "established": 145,
                        "listen": 8,
                        "time_wait": 320,
                    },
                    "kernel": {
                        "context_switches_total": 98_472_301,
                        "running_tasks": 3,
                        "blocked_tasks": 1,
                    },
                    "memory": {
                        "dirty_bytes": 8_388_608,
                        "writeback_bytes": 1_048_576,
                    },
                    "process_limits": [
                        {
                            "pid": 1421,
                            "name": "gunicorn",
                            "max_open_files": {
                                "soft": 1024,
                                "hard": 1_048_576,
                            },
                            "max_processes": {"soft": 15_421},
                        }
                    ],
                },
            },
            timestamp_unix_ms=1_700_000_000_000,
        )

        names = [metric["name"] for metric in metrics]
        self.assertEqual(names.count("heka_tcp_connections"), 3)
        self.assertIn("heka_kernel_context_switches_total", names)
        self.assertIn("heka_kernel_running_tasks", names)
        self.assertIn("heka_kernel_blocked_tasks", names)
        self.assertIn("heka_memory_dirty_bytes", names)
        self.assertIn("heka_memory_writeback_bytes", names)
        self.assertEqual(names.count("heka_process_limit_open_files"), 2)
        self.assertEqual(names.count("heka_process_limit_max_processes"), 1)

        tcp_metrics = [
            metric for metric in metrics if metric["name"] == "heka_tcp_connections"
        ]
        self.assertEqual(
            {metric["labels"]["state"] for metric in tcp_metrics},
            {"established", "listen", "time_wait"},
        )
        limit_metrics = [
            metric
            for metric in metrics
            if metric["name"] == "heka_process_limit_max_processes"
        ]
        self.assertEqual(
            limit_metrics[0]["labels"],
            {"pid": "1421", "process_name": "gunicorn", "limit": "soft"},
        )
        self.assertEqual(limit_metrics[0]["type"], "gauge")

    def test_context_switches_are_a_cumulative_counter(self) -> None:
        metrics = build_canonical_metrics(
            {
                "cpu": {"warming_up": True},
                "memory": {},
                "disk": {},
                "proc": {
                    "kernel": {"context_switches_total": 10},
                },
            }
        )

        self.assertEqual(metrics[0]["name"], "heka_kernel_context_switches_total")
        self.assertEqual(metrics[0]["type"], "counter")

    def test_proc_metric_maps_through_supported_exporter_formats(self) -> None:
        metrics = build_canonical_metrics(
            {
                "cpu": {"warming_up": True},
                "memory": {},
                "disk": {},
                "proc": {"tcp": {"established": 2}},
            },
            timestamp_unix_ms=1_700_000_000_000,
        )

        prometheus = PrometheusFormatter().format_canonical(metrics)
        self.assertIn(
            'heka_tcp_connections{state="established"} 2 1700000000000',
            prometheus,
        )

        otlp = OtlpPayloadMapper().map_metrics(metrics)
        otlp_metric = otlp["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]
        self.assertEqual(otlp_metric["name"], "heka_tcp_connections")
        self.assertEqual(
            otlp_metric["gauge"]["dataPoints"][0]["attributes"],
            [{"key": "state", "value": {"stringValue": "established"}}],
        )

        datadog = DatadogSeriesMapper().map_metrics(metrics)
        self.assertEqual(datadog["series"][0]["metric"], "heka_tcp_connections")
        self.assertEqual(datadog["series"][0]["tags"], ["state:established"])

    def test_all_proc_metrics_pass_through_otlp_http_exporter(self) -> None:
        tcp = {
            "established": 145,
            "listen": 8,
            "time_wait": 320,
            "close_wait": 3,
            "syn_sent": 2,
            "syn_recv": 5,
        }
        metrics = build_canonical_metrics(
            {
                "cpu": {"warming_up": True},
                "memory": {},
                "disk": {},
                "proc": {
                    "tcp": tcp,
                    "kernel": {
                        "context_switches_total": 98_472_301,
                        "running_tasks": 3,
                        "blocked_tasks": 1,
                    },
                    "memory": {
                        "dirty_bytes": 8_388_608,
                        "writeback_bytes": 1_048_576,
                    },
                    "process_limits": [
                        {
                            "pid": 1421,
                            "name": "gunicorn",
                            "max_open_files": {
                                "soft": 1024,
                                "hard": 1_048_576,
                            },
                            "max_processes": {
                                "soft": 15_421,
                                "hard": 15_421,
                            },
                        }
                    ],
                },
            },
            timestamp_unix_ms=1_700_000_000_000,
        )
        sender = _SenderStub()
        exporter = OtlpHttpExporter(
            endpoint="https://collector.example.com/v1/metrics",
            sender=sender,  # type: ignore[arg-type]
            background_dispatch=False,
        )

        exporter.initialize()
        exporter.export(metrics)
        exporter.shutdown()

        self.assertEqual(len(sender.payloads), 1)
        mapped = sender.payloads[0]["resourceMetrics"][0]["scopeMetrics"][0][
            "metrics"
        ]
        self.assertEqual(len(mapped), len(metrics))

        tcp_metrics = [item for item in mapped if item["name"] == "heka_tcp_connections"]
        self.assertEqual(len(tcp_metrics), 6)
        self.assertTrue(all("gauge" in item for item in tcp_metrics))
        self.assertEqual(
            {
                point["attributes"][0]["value"]["stringValue"]: point["asDouble"]
                for item in tcp_metrics
                for point in item["gauge"]["dataPoints"]
            },
            {state: float(value) for state, value in tcp.items()},
        )

        by_name = {item["name"]: item for item in mapped}
        context_switches = by_name["heka_kernel_context_switches_total"]
        self.assertTrue(context_switches["sum"]["isMonotonic"])
        self.assertEqual(context_switches["sum"]["aggregationTemporality"], 2)
        self.assertEqual(
            context_switches["sum"]["dataPoints"][0]["asDouble"],
            98_472_301.0,
        )
        for gauge_name in (
            "heka_kernel_running_tasks",
            "heka_kernel_blocked_tasks",
            "heka_memory_dirty_bytes",
            "heka_memory_writeback_bytes",
            "heka_process_limit_open_files",
            "heka_process_limit_max_processes",
        ):
            self.assertIn("gauge", by_name[gauge_name])

        open_file_metric = next(
            item
            for item in mapped
            if item["name"] == "heka_process_limit_open_files"
            and self._attributes(item)["limit"] == "soft"
        )
        self.assertEqual(
            self._attributes(open_file_metric),
            {
                "limit": "soft",
                "pid": "1421",
                "process_name": "gunicorn",
            },
        )
        self.assertEqual(
            open_file_metric["gauge"]["dataPoints"][0]["asDouble"],
            1024.0,
        )

    @staticmethod
    def _attributes(metric: dict) -> dict[str, str]:
        point_kind = "gauge" if "gauge" in metric else "sum"
        attributes = metric[point_kind]["dataPoints"][0]["attributes"]
        return {
            attribute["key"]: attribute["value"]["stringValue"]
            for attribute in attributes
        }


if __name__ == "__main__":
    unittest.main()
