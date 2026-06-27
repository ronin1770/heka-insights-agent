"""Exporter factory for runtime exporter selection."""

from __future__ import annotations

import logging

from config import (
    ExporterType,
    get_datadog_otlp_preset,
    get_newrelic_otlp_preset,
)

from .base import Exporter
from .console import ConsoleExporter
from .datadog_native import DatadogNativeExporter
from .otlp_http import OtlpHttpExporter


def create_exporter(
    exporter_type: ExporterType,
    *,
    logger: logging.Logger | None = None,
) -> Exporter:
    """Return an exporter instance for the selected runtime type."""
    if exporter_type == "console":
        return ConsoleExporter()
    if exporter_type == "otlp_http":
        return OtlpHttpExporter(logger=logger)
    if exporter_type == "datadog_otlp":
        endpoint, headers, resource_attributes = get_datadog_otlp_preset(
            logger=logger
        )
        return OtlpHttpExporter(
            endpoint=endpoint,
            headers=headers,
            resource_attributes=resource_attributes,
            logger=logger,
        )
    if exporter_type == "datadog_native":
        return DatadogNativeExporter(logger=logger)
    if exporter_type == "newrelic_otlp":
        endpoint, headers, resource_attributes = get_newrelic_otlp_preset(
            logger=logger
        )
        return OtlpHttpExporter(
            endpoint=endpoint,
            headers=headers,
            resource_attributes=resource_attributes,
            logger=logger,
        )

    message = f"Unsupported exporter type '{exporter_type}'."
    if logger is not None:
        logger.error(message)
    raise RuntimeError(message)
