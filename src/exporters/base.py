"""Base contracts for exporter implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence, TypedDict


class _CanonicalMetricRequired(TypedDict):
    """One normalized metric record shared across formatter/exporter layers."""

    name: str
    description: str
    type: str
    unit: str
    value: float | int
    labels: dict[str, str]


class CanonicalMetric(_CanonicalMetricRequired, total=False):
    """Canonical metric payload with optional per-sample timestamp."""

    timestamp_unix_ms: int


CanonicalMetricCollection = Sequence[CanonicalMetric]


class Exporter(ABC):
    """Base lifecycle contract for outbound telemetry exporters."""

    @abstractmethod
    def initialize(self) -> None:
        """Validate configuration and prepare transport resources."""

    @abstractmethod
    def export(self, metrics: CanonicalMetricCollection) -> None:
        """Deliver normalized metrics to the exporter destination."""

    @abstractmethod
    def shutdown(self) -> None:
        """Flush pending work and release owned resources."""

    def health_status(self) -> Mapping[str, Any] | None:
        """Return exporter health details when implemented by subclasses."""
        return None
