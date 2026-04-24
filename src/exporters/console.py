"""Console exporter implementation for normalized metric delivery."""

from __future__ import annotations

import sys
from typing import TextIO

from formatters.prometheus import PrometheusFormatter

from .base import CanonicalMetricCollection, Exporter


class ConsoleExporter(Exporter):
    """Exporter that prints formatted metrics to stdout."""

    def __init__(
        self,
        *,
        formatter: PrometheusFormatter | None = None,
        stream: TextIO | None = None,
    ) -> None:
        self._formatter = formatter or PrometheusFormatter()
        self._stream = stream or sys.stdout
        self._initialized = False

    def initialize(self) -> None:
        """Prepare console exporter resources."""
        self._initialized = True

    def export(self, metrics: CanonicalMetricCollection) -> None:
        """Write one formatted metrics document to stdout."""
        if not self._initialized:
            raise RuntimeError("ConsoleExporter must be initialized before export().")
        rendered = self._formatter.format_canonical(metrics)
        self._stream.write(rendered)
        self._stream.flush()

    def shutdown(self) -> None:
        """Release exporter resources."""
        self._initialized = False
