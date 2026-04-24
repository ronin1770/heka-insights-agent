"""Exporter factory for runtime exporter selection."""

from __future__ import annotations

import logging

from config import ExporterType

from .base import Exporter
from .console import ConsoleExporter


def create_exporter(
    exporter_type: ExporterType,
    *,
    logger: logging.Logger | None = None,
) -> Exporter:
    """Return an exporter instance for the selected runtime type."""
    if exporter_type == "console":
        return ConsoleExporter()

    if logger is not None:
        logger.warning(
            "Exporter '%s' is not implemented yet; falling back to 'console'.",
            exporter_type,
        )
    return ConsoleExporter()
