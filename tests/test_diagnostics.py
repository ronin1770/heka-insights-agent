"""Tests for local agent self-diagnostics."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diagnostics import AgentDiagnostics


class _Exporter:
    def health_status(self):
        return {"initialized": True}

    def diagnostics_snapshot(self):
        return {
            "counters": {"accepted_batches": 2, "successful_batches": 1},
            "gauges": {"pending_batches": 1, "pending_bytes": 42},
        }


class AgentDiagnosticsTests(unittest.TestCase):
    def test_disabled_diagnostics_do_not_emit(self) -> None:
        logger = Mock()
        with patch.dict(os.environ, {"HEKA_AGENT_DIAGNOSTICS_ENABLED": "false"}, clear=True):
            diagnostics = AgentDiagnostics(exporter=_Exporter(), logger=logger)
            self.assertIsNone(diagnostics.emit_once())
        logger.info.assert_not_called()

    def test_enabled_diagnostics_emit_compact_json_with_stable_start_id(self) -> None:
        logger = Mock()
        with patch.dict(
            os.environ,
            {"HEKA_AGENT_DIAGNOSTICS_ENABLED": "true", "HEKA_AGENT_DIAGNOSTICS_INTERVAL_SECONDS": "60"},
            clear=True,
        ):
            diagnostics = AgentDiagnostics(exporter=_Exporter(), logger=logger)
            first = diagnostics.emit_once()
            second = diagnostics.emit_once()
        assert first is not None and second is not None
        self.assertEqual(first["event"], "agent_self_diagnostics")
        self.assertEqual(first["process_start_id"], second["process_start_id"])
        self.assertEqual(first["exporter"]["gauges"]["pending_batches"], 1)
        self.assertEqual(second["exporter"]["interval"]["accepted_batches"], 0)
        encoded = logger.info.call_args_list[0].args[1]
        self.assertEqual(json.loads(encoded)["event"], "agent_self_diagnostics")


if __name__ == "__main__":
    unittest.main()
