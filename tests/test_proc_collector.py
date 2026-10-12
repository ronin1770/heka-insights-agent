"""Tests for dependency-free targeted procfs collection."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from collectors.proc import (  # noqa: E402
    ProcCollector,
    parse_kernel_stats,
    parse_memory_stats,
    parse_process_limits,
    parse_tcp_states,
)


class ProcParserTests(unittest.TestCase):
    def test_parses_only_supported_tcp_states(self) -> None:
        content = """sl local_address rem_address st
0: 0100007F:0016 00000000:0000 0A
1: 0100007F:1000 0100007F:2000 01
2: 0100007F:1001 0100007F:2001 06
3: 0100007F:1002 0100007F:2002 08
4: 0100007F:1003 0100007F:2003 02
5: 0100007F:1004 0100007F:2004 03
6: 0100007F:1005 0100007F:2005 04
malformed
"""
        self.assertEqual(
            parse_tcp_states(content),
            {
                "listen": 1,
                "established": 1,
                "time_wait": 1,
                "close_wait": 1,
                "syn_sent": 1,
                "syn_recv": 1,
            },
        )

    def test_parses_kernel_stats_and_ignores_malformed_values(self) -> None:
        self.assertEqual(
            parse_kernel_stats(
                "ctxt 98472301\nprocs_running 3\nprocs_blocked 1\nprocesses bad\n"
            ),
            {
                "context_switches_total": 98_472_301,
                "running_tasks": 3,
                "blocked_tasks": 1,
            },
        )

    def test_parses_memory_stats_and_converts_kb_to_bytes(self) -> None:
        self.assertEqual(
            parse_memory_stats(
                "MemAvailable: 1258291 kB\nDirty: 8192 kB\n"
                "Writeback: 1024 kB\nInvalid\n"
            ),
            {
                "dirty_bytes": 8_388_608,
                "writeback_bytes": 1_048_576,
            },
        )

    def test_parses_finite_soft_and_hard_process_limits(self) -> None:
        content = """Limit Soft Limit Hard Limit Units
Max open files            1024                 1048576              files
Max processes             15421                16000                processes
Max file size             unlimited            unlimited            bytes
"""
        self.assertEqual(
            parse_process_limits(content),
            {
                "max_open_files": {"soft": 1024, "hard": 1_048_576},
                "max_processes": {"soft": 15_421, "hard": 16_000},
            },
        )

    def test_omits_only_individual_unlimited_values(self) -> None:
        content = """Limit Soft Limit Hard Limit Units
Max open files            unlimited            1048576              files
Max processes             15421                unlimited            processes
"""
        self.assertEqual(
            parse_process_limits(content),
            {
                "max_open_files": {"hard": 1_048_576},
                "max_processes": {"soft": 15_421},
            },
        )

    def test_ignores_malformed_process_limits_and_keeps_valid_values(self) -> None:
        content = """Limit Soft Limit Hard Limit Units
Max open files malformed
Max processes 100 200 processes
"""
        self.assertEqual(
            parse_process_limits(content),
            {"max_processes": {"soft": 100, "hard": 200}},
        )


class ProcCollectorTests(unittest.TestCase):
    def test_combines_ipv4_and_ipv6_and_returns_zeros(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "net").mkdir()
            (root / "net" / "tcp").write_text(
                "sl local rem st\n0: local remote 01\n",
                encoding="utf-8",
            )
            (root / "net" / "tcp6").write_text(
                "sl local rem st\n0: local remote 0A\n",
                encoding="utf-8",
            )

            tcp = ProcCollector(proc_root=root).collect()["tcp"]

        self.assertEqual(tcp["established"], 1)
        self.assertEqual(tcp["listen"], 1)
        self.assertEqual(tcp["time_wait"], 0)

    def test_does_not_generate_zeros_when_a_tcp_source_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "net").mkdir()
            (root / "net" / "tcp").write_text(
                "sl local rem st\n0: local remote 01\n",
                encoding="utf-8",
            )

            tcp = ProcCollector(proc_root=root).collect()["tcp"]

        self.assertEqual(tcp, {"established": 1})

    def test_does_not_generate_zeros_for_malformed_tcp_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "net").mkdir()
            (root / "net" / "tcp").write_text("malformed\n", encoding="utf-8")
            (root / "net" / "tcp6").write_text("", encoding="utf-8")

            tcp = ProcCollector(proc_root=root).collect()["tcp"]

        self.assertEqual(tcp, {})

    def test_collects_limits_and_handles_a_disappearing_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "42").mkdir()
            (root / "42" / "limits").write_text(
                "Limit Soft Limit Hard Limit Units\n"
                "Max open files 1024 2048 files\n"
                "Max processes 100 unlimited processes\n",
                encoding="utf-8",
            )

            limits = ProcCollector(proc_root=root).collect(
                [{"pid": 42, "name": "worker"}, {"pid": 43, "name": "gone"}]
            )["process_limits"]

        self.assertEqual(
            limits,
            [
                {
                    "pid": 42,
                    "name": "worker",
                    "max_open_files": {"soft": 1024, "hard": 2048},
                    "max_processes": {"soft": 100},
                }
            ],
        )

    def test_missing_and_denied_files_return_partial_empty_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = ProcCollector(proc_root=directory).collect(
                [{"pid": 42, "name": "gone"}]
            )
        self.assertEqual(
            payload,
            {"tcp": {}, "kernel": {}, "memory": {}, "process_limits": []},
        )

        with patch.object(Path, "read_text", side_effect=PermissionError):
            denied_payload = ProcCollector().collect(
                [{"pid": 42, "name": "denied"}]
            )
        self.assertEqual(
            denied_payload,
            {"tcp": {}, "kernel": {}, "memory": {}, "process_limits": []},
        )


if __name__ == "__main__":
    unittest.main()
