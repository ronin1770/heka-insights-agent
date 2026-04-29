"""OTLP payload mapping from canonical metric records."""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from .base import CanonicalMetric, CanonicalMetricCollection

_SUPPORTED_CANONICAL_METRIC_TYPES = ("gauge", "counter")
_AGGREGATION_TEMPORALITY_CUMULATIVE = 2


class OtlpPayloadMapper:
    """Map canonical metrics into OTLP HTTP JSON payloads."""

    def __init__(
        self,
        *,
        now_unix_ms: Callable[[], int] | None = None,
        scope_name: str = "heka-insights-agent",
        resource_attributes: Mapping[str, str] | None = None,
    ) -> None:
        self._now_unix_ms = now_unix_ms or (lambda: int(time.time() * 1000))
        self._scope_name = scope_name
        self._resource_attributes = self._normalize_string_mapping(
            resource_attributes or {},
            field_name="resource_attributes",
        )

    def map_metrics(self, metrics: CanonicalMetricCollection) -> dict[str, Any]:
        """Build one OTLP metrics payload for a canonical metric collection."""
        default_timestamp_unix_ms = self._now_unix_ms()
        mapped_metrics = [
            self._map_one(
                metric=metric,
                index=index,
                default_timestamp_unix_ms=default_timestamp_unix_ms,
            )
            for index, metric in enumerate(metrics)
        ]
        return {
            "resourceMetrics": [
                {
                    "resource": {
                        "attributes": self._map_attributes(self._resource_attributes)
                    },
                    "scopeMetrics": [
                        {
                            "scope": {"name": self._scope_name},
                            "metrics": mapped_metrics,
                        }
                    ],
                }
            ]
        }

    def _map_one(
        self,
        *,
        metric: CanonicalMetric,
        index: int,
        default_timestamp_unix_ms: int,
    ) -> dict[str, Any]:
        self._validate_metric(metric, index=index)

        timestamp_unix_ms = metric.get("timestamp_unix_ms", default_timestamp_unix_ms)
        data_point = {
            "attributes": self._map_attributes(metric["labels"]),
            "timeUnixNano": str(int(timestamp_unix_ms) * 1_000_000),
            "asDouble": float(metric["value"]),
        }

        otlp_metric: dict[str, Any] = {
            "name": metric["name"],
            "description": metric["description"],
            "unit": metric["unit"],
        }

        if metric["type"] == "gauge":
            otlp_metric["gauge"] = {"dataPoints": [data_point]}
            return otlp_metric

        otlp_metric["sum"] = {
            "aggregationTemporality": _AGGREGATION_TEMPORALITY_CUMULATIVE,
            "isMonotonic": True,
            "dataPoints": [data_point],
        }
        return otlp_metric

    @staticmethod
    def _map_attributes(labels: Mapping[str, str]) -> list[dict[str, Any]]:
        return [
            {
                "key": key,
                "value": {"stringValue": value},
            }
            for key, value in sorted(labels.items())
        ]

    @staticmethod
    def _validate_metric(metric: Mapping[str, Any], *, index: int) -> None:
        required_fields = ("name", "description", "type", "unit", "value", "labels")
        missing_fields = [field for field in required_fields if field not in metric]
        if missing_fields:
            missing = ", ".join(missing_fields)
            raise ValueError(f"Metric at index {index} is missing required fields: {missing}")

        metric_type = metric["type"]
        if metric_type not in _SUPPORTED_CANONICAL_METRIC_TYPES:
            supported_values = ", ".join(_SUPPORTED_CANONICAL_METRIC_TYPES)
            raise ValueError(
                f"Unsupported canonical metric type '{metric_type}' at index {index}. "
                f"Supported values: {supported_values}."
            )

        value = metric["value"]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(
                f"Metric '{metric['name']}' at index {index} has non-numeric value."
            )

        labels = metric["labels"]
        if not isinstance(labels, Mapping):
            raise ValueError(
                f"Metric '{metric['name']}' at index {index} has non-mapping labels."
            )
        for key, label_value in labels.items():
            if not isinstance(key, str) or not isinstance(label_value, str):
                raise ValueError(
                    f"Metric '{metric['name']}' at index {index} has non-string labels."
                )

        timestamp_unix_ms = metric.get("timestamp_unix_ms")
        if timestamp_unix_ms is not None:
            if not isinstance(timestamp_unix_ms, int) or timestamp_unix_ms < 0:
                raise ValueError(
                    f"Metric '{metric['name']}' at index {index} has invalid "
                    "timestamp_unix_ms."
                )

    @staticmethod
    def _normalize_string_mapping(
        mapping: Mapping[str, str],
        *,
        field_name: str,
    ) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in mapping.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(f"{field_name} must contain only string keys and values.")
            normalized[key] = value
        return normalized
