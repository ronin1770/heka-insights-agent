"""Main entry point for the Heka Insights Agent."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Sequence

from config import (
    ExporterType,
    get_cpu_poll_interval_seconds,
    get_exporter_type,
    get_proc_poll_interval_seconds,
    get_process_poll_interval_seconds,
    get_psi_poll_interval_seconds,
)
from config.runtime import get_log_payloads_enabled
from collectors.cpu import CPUCollector, MonotonicTicker
from collectors.disk import DiskCollector
from collectors.memory import MemoryCollector
from collectors.process import ProcessCollector
from collectors.proc import ProcCollector
from collectors.psi import PSICollector
from diagnostics import AgentDiagnostics
from exporters import Exporter, create_exporter
from logger.config import get_logger
from pipeline import build_canonical_metrics
from setup_wizard import resume_setup_command, run_setup_wizard


def run_collectors_loop(*, exporter: Exporter, exporter_type: ExporterType,
                        logger: logging.Logger) -> None:
    """Run host and process collectors on their configured cadences."""
    interval_seconds = get_cpu_poll_interval_seconds(logger=logger)
    process_interval_seconds = get_process_poll_interval_seconds(logger=logger)
    proc_interval_seconds = get_proc_poll_interval_seconds(logger=logger)
    psi_interval_seconds = get_psi_poll_interval_seconds(logger=logger)
    cpu_collector = CPUCollector(per_cpu=False, detail="detailed")
    memory_collector = MemoryCollector(detail="detailed")
    disk_collector = DiskCollector(detail="detailed")
    process_collector = ProcessCollector()
    proc_collector = ProcCollector()
    psi_collector = PSICollector(logger=logger)
    process_collector.prime()
    schedule_started = time.monotonic()
    next_process_collection = schedule_started + process_interval_seconds
    next_proc_collection = schedule_started + proc_interval_seconds
    next_psi_collection = schedule_started
    selected_processes: list[dict[str, object]] = []
    ticker = MonotonicTicker(interval_seconds=interval_seconds)
    log_payloads = get_log_payloads_enabled()

    logger.info(
        "Collectors initialized | interval_seconds=%.1f | process_interval_seconds=%.1f | "
        "proc_interval_seconds=%.1f | psi_interval_seconds=%.1f | exporter_type=%s",
        interval_seconds, process_interval_seconds, proc_interval_seconds,
        psi_interval_seconds, exporter_type,
    )

    while True:
        cpu_payload = cpu_collector.collect()
        memory_payload = memory_collector.collect()
        disk_payload = disk_collector.collect()
        if cpu_payload["warming_up"]:
            logger.debug("CPU collector warming up")
        if log_payloads:
            logger.debug("CPU metrics: %s", cpu_payload)
            logger.debug("Memory metrics: %s", memory_payload)
            logger.debug("Disk metrics: %s", disk_payload)

        payloads = {"cpu": cpu_payload, "memory": memory_payload, "disk": disk_payload}
        current_monotonic = time.monotonic()
        if current_monotonic >= next_process_collection:
            process_payload = process_collector.collect()
            payloads["process"] = process_payload
            if log_payloads:
                logger.debug("Process and network metrics: %s", process_payload)
            entries = process_payload.get("processes")
            if isinstance(entries, list):
                selected_processes = entries
            while next_process_collection <= current_monotonic:
                next_process_collection += process_interval_seconds

        if current_monotonic >= next_proc_collection:
            proc_payload = proc_collector.collect(selected_processes)
            payloads["proc"] = proc_payload
            if log_payloads:
                logger.debug("Procfs metrics: %s", proc_payload)
            while next_proc_collection <= current_monotonic:
                next_proc_collection += proc_interval_seconds

        if current_monotonic >= next_psi_collection:
            psi_payload = psi_collector.collect()
            if psi_payload:
                payloads["psi"] = psi_payload
                if log_payloads:
                    logger.debug("PSI metrics: %s", psi_payload)
            while next_psi_collection <= current_monotonic:
                next_psi_collection += psi_interval_seconds

        metrics = build_canonical_metrics(payloads, timestamp_unix_ms=int(time.time() * 1000))
        try:
            exporter.export(metrics)
        except RuntimeError as exc:
            logger.error("Batch export failed; error=%s", exc)
        ticker.sleep()


def run_agent() -> int:
    """Run the telemetry collection loop."""
    try:
        logger = get_logger(__name__)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\nYou can resume setup using {resume_setup_command()}.\n")
        return 1

    diagnostics: AgentDiagnostics | None = None
    try:
        logger.info("Application startup complete")
        exporter_type = get_exporter_type(logger=logger)
        exporter = create_exporter(exporter_type, logger=logger)
        exporter.initialize()
        diagnostics = AgentDiagnostics(exporter=exporter, logger=logger)
        diagnostics.start()
        try:
            run_collectors_loop(exporter=exporter, exporter_type=exporter_type, logger=logger)
        except KeyboardInterrupt:
            logger.info("Shutdown requested by user")
        finally:
            if diagnostics is not None:
                diagnostics.shutdown()
            exporter.shutdown()
        return 0
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="heka-insights-agent")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="start the telemetry agent")
    subparsers.add_parser("setup", help="run the interactive setup wizard")
    return parser


def cli(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    command = args.command or "run"
    if command == "setup":
        return run_setup_wizard()
    if command == "run":
        return run_agent()
    parser.error(f"Unsupported command '{command}'.")
    return 2


if __name__ == "__main__":
    raise SystemExit(cli())
