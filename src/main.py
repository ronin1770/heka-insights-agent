"""
file: main.py
description: Main entry point for the software
author: Farhan Munir (ronin1770)
dev_started_on: 2026-04-01
epic_or_related_story: EPIC ID: #2
"""

import time

from config import ExporterType, get_cpu_poll_interval_seconds, get_exporter_type
from collectors.cpu import CPUCollector, MonotonicTicker
from collectors.disk import DiskCollector
from collectors.memory import MemoryCollector
from exporters import Exporter, create_exporter
from logger.config import get_logger
from pipeline import build_canonical_metrics

logger = get_logger(__name__)


def run_collectors_loop(*, exporter: Exporter, exporter_type: ExporterType) -> None:
    """Run CPU, memory, and disk collectors with a fixed, drift-safe cadence."""
    interval_seconds = get_cpu_poll_interval_seconds(logger=logger)
    cpu_collector = CPUCollector(per_cpu=False, detail="detailed")
    memory_collector = MemoryCollector(detail="detailed")
    disk_collector = DiskCollector(detail="detailed")
    ticker = MonotonicTicker(interval_seconds=interval_seconds)

    logger.info(
        "CPU, memory, and disk collectors initialized | interval_seconds=%.1f | exporter_type=%s",
        interval_seconds,
        exporter_type,
    )

    while True:
        cpu_payload = cpu_collector.collect()
        if cpu_payload["warming_up"]:
            logger.debug("CPU collector warming up")
        else:
            logger.info("CPU metrics: %s", cpu_payload)

        memory_payload = memory_collector.collect()
        logger.info("Memory metrics: %s", memory_payload)

        disk_payload = disk_collector.collect()
        logger.info("Disk metrics: %s", disk_payload)

        canonical_metrics = build_canonical_metrics(
            {
                "cpu": cpu_payload,
                "memory": memory_payload,
                "disk": disk_payload,
            },
            timestamp_unix_ms=int(time.time() * 1000),
        )
        exporter.export(canonical_metrics)

        ticker.sleep()


def main() -> None:
    logger.info("Application startup complete")
    exporter_type = get_exporter_type(logger=logger)
    exporter = create_exporter(exporter_type, logger=logger)
    exporter.initialize()
    try:
        run_collectors_loop(exporter=exporter, exporter_type=exporter_type)
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    finally:
        exporter.shutdown()


if __name__ == "__main__":
    main()
