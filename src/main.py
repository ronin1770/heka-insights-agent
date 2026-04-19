"""
file: main.py
description: Main entry point for the software
author: Farhan Munir (ronin1770)
dev_started_on: 2026-04-01
epic_or_related_story: EPIC ID: #2
"""

import os
from pathlib import Path

from collectors.cpu import CPUCollector, MonotonicTicker
from collectors.disk import DiskCollector
from collectors.memory import MemoryCollector
from dotenv import load_dotenv
from formatters.openmetrics import OpenMetricsFormatter
from logger.config import get_logger

logger = get_logger(__name__)
CPU_POLL_INTERVAL_ENV_KEY = "CPU_POLL_INTERVAL_SECONDS"
DEFAULT_CPU_POLL_INTERVAL_SECONDS = 5.0
ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_FILE, override=False)


def _cpu_poll_interval_seconds() -> float:
    raw_value = os.getenv(CPU_POLL_INTERVAL_ENV_KEY)
    if not raw_value:
        return DEFAULT_CPU_POLL_INTERVAL_SECONDS

    try:
        interval = float(raw_value)
        if interval > 0:
            return interval
    except ValueError:
        pass

    logger.warning(
        "Invalid %s value '%s'; using default %.1f",
        CPU_POLL_INTERVAL_ENV_KEY,
        raw_value,
        DEFAULT_CPU_POLL_INTERVAL_SECONDS,
    )
    return DEFAULT_CPU_POLL_INTERVAL_SECONDS


def run_collectors_loop() -> None:
    """Run CPU, memory, and disk collectors with a fixed, drift-safe cadence."""
    interval_seconds = _cpu_poll_interval_seconds()
    cpu_collector = CPUCollector(per_cpu=False, detail="detailed")
    memory_collector = MemoryCollector(detail="detailed")
    disk_collector = DiskCollector(detail="detailed")
    openmetrics_formatter = OpenMetricsFormatter()
    ticker = MonotonicTicker(interval_seconds=interval_seconds)

    logger.info(
        "CPU, memory, and disk collectors initialized | interval_seconds=%.1f",
        interval_seconds,
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

        openmetrics_output = openmetrics_formatter.format(
            {
                "cpu": cpu_payload,
                "memory": memory_payload,
                "disk": disk_payload,
            }
        )
        print(openmetrics_output, end="", flush=True)

        ticker.sleep()


def main() -> None:
    logger.info("Application startup complete")
    try:
        run_collectors_loop()
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")


if __name__ == "__main__":
    main()
