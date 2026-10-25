"""Optional lightweight, local-only agent self-diagnostics."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import tracemalloc
import uuid
from datetime import datetime, timezone
from typing import Any

import psutil

from config.runtime import (
    get_agent_diagnostics_enabled,
    get_agent_diagnostics_interval_seconds,
    get_agent_tracemalloc_enabled,
)
from exporters import Exporter


class AgentDiagnostics:
    """Periodically write one diagnostic snapshot without retaining history."""

    def __init__(self, *, exporter: Exporter, logger: logging.Logger) -> None:
        self._exporter = exporter
        self._logger = logger
        self._enabled = get_agent_diagnostics_enabled()
        self._interval = get_agent_diagnostics_interval_seconds()
        self._trace_enabled = get_agent_tracemalloc_enabled()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_id = str(uuid.uuid4())
        self._process = psutil.Process(os.getpid())
        self._previous_counters: dict[str, int] = {}
        self._started_tracing = False

    def start(self) -> None:
        if not self._enabled:
            return
        if self._trace_enabled and not tracemalloc.is_tracing():
            tracemalloc.start()
            self._started_tracing = True
        self._process.cpu_percent(interval=None)
        self._thread = threading.Thread(
            target=self._run,
            name="heka-agent-diagnostics",
            daemon=True,
        )
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=min(self._interval, 2.0))
        if self._started_tracing and tracemalloc.is_tracing():
            tracemalloc.stop()

    def emit_once(self) -> dict[str, Any] | None:
        """Collect and log one snapshot; failures never escape."""
        if not self._enabled:
            return None
        try:
            snapshot = self._build_snapshot()
            self._logger.info(
                "%s",
                json.dumps(snapshot, separators=(",", ":"), sort_keys=True),
            )
            return snapshot
        except Exception as exc:  # diagnostic isolation boundary
            self._logger.warning("Agent self-diagnostics failed; error=%s", exc)
            return None

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.emit_once()

    def _build_snapshot(self) -> dict[str, Any]:
        memory = self._process.memory_info()
        uss = pss = None
        try:
            full = self._process.memory_full_info()
            uss = getattr(full, "uss", None)
            pss = getattr(full, "pss", None)
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            pass

        diagnostic_source = getattr(self._exporter, "diagnostics_snapshot", None)
        export_snapshot = diagnostic_source() if callable(diagnostic_source) else {}
        counters = dict(export_snapshot.get("counters", {}))
        gauges = dict(export_snapshot.get("gauges", {}))
        last_success = gauges.pop("last_success_unix_seconds", None)
        gauges["seconds_since_last_success"] = (
            max(0.0, time.time() - float(last_success))
            if isinstance(last_success, (int, float)) else None
        )
        interval = {
            key: int(value) - self._previous_counters.get(key, 0)
            for key, value in counters.items()
            if isinstance(value, int)
        }
        self._previous_counters = {
            key: int(value) for key, value in counters.items() if isinstance(value, int)
        }
        traced_current = traced_peak = None
        if tracemalloc.is_tracing():
            traced_current, traced_peak = tracemalloc.get_traced_memory()

        return {
            "event": "agent_self_diagnostics",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "process_start_id": self._start_id,
            "interval_seconds": self._interval,
            "memory": {
                "rss_bytes": memory.rss,
                "uss_bytes": uss,
                "pss_bytes": pss,
                "vms_bytes": memory.vms,
                "python_traced_current_bytes": traced_current,
                "python_traced_peak_bytes": traced_peak,
                "tracemalloc_active": tracemalloc.is_tracing(),
            },
            "process": {
                "cpu_percent": self._process.cpu_percent(interval=None),
                "threads": self._process.num_threads(),
                "open_fds": self._safe_num_fds(),
            },
            "exporter": {
                "cumulative": counters,
                "interval": interval,
                "gauges": gauges,
            },
        }

    def _safe_num_fds(self) -> int | None:
        try:
            return self._process.num_fds()
        except (AttributeError, psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            return None
