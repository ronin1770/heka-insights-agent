"""Exporter factory for runtime exporter selection."""

from __future__ import annotations

import logging

from config import ExporterType

from .base import Exporter
from .console import ConsoleExporter
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

    message = (
        f"Exporter '{exporter_type}' is configured but not implemented yet. "
        "Set EXPORTER_TYPE=console until this exporter adapter is implemented."
    )
    if logger is not None:
        logger.error(message)
    raise RuntimeError(message)
