"""Configuration and logging tests for bounded export reliability."""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config.runtime import (
    get_agent_diagnostics_enabled,
    get_agent_diagnostics_interval_seconds,
    get_agent_tracemalloc_enabled,
    get_export_queue_max_batches,
    get_export_queue_overflow_policy,
    get_log_level,
)
from logger.config import get_logger


class Issue33ConfigurationTests(unittest.TestCase):
    def test_new_defaults_and_strict_validation(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_export_queue_max_batches(), 64)
            self.assertEqual(get_export_queue_overflow_policy(), "drop_oldest")
            self.assertTrue(get_agent_diagnostics_enabled())
            self.assertEqual(get_agent_diagnostics_interval_seconds(), 60.0)
            self.assertFalse(get_agent_tracemalloc_enabled())
            self.assertEqual(get_log_level(), logging.INFO)
        with patch.dict(os.environ, {"HEKA_EXPORT_QUEUE_MAX_BATCHES": "0"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "HEKA_EXPORT_QUEUE_MAX_BATCHES"):
                get_export_queue_max_batches()
        with patch.dict(os.environ, {"HEKA_EXPORT_QUEUE_OVERFLOW_POLICY": "block"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "HEKA_EXPORT_QUEUE_OVERFLOW_POLICY"):
                get_export_queue_overflow_policy()

    def test_logger_uses_rotation_and_info_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "agent.log")
            name = f"issue33-test-{id(self)}"
            with patch.dict(
                os.environ,
                {
                    "LOG_LOCATION": path,
                    "HEKA_LOG_LEVEL": "INFO",
                    "HEKA_LOG_MAX_BYTES": "128",
                    "HEKA_LOG_BACKUP_COUNT": "1",
                },
                clear=True,
            ):
                logger = get_logger(name)
                self.assertEqual(logger.level, logging.INFO)
                self.assertIsInstance(logger.handlers[0], RotatingFileHandler)
                logger.debug("hidden payload")
                logger.info("visible lifecycle")
                for handler in logger.handlers:
                    handler.flush()
                self.assertNotIn("hidden payload", Path(path).read_text(encoding="utf-8"))
                for index in range(10):
                    logger.info("rotation-record-%s-%s", index, "x" * 80)
                for handler in logger.handlers:
                    handler.flush()
                self.assertTrue(Path(f"{path}.1").exists())
                self.assertFalse(Path(f"{path}.2").exists())
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
