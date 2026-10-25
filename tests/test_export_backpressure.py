"""Tests for bounded serialized HTTP dispatch."""
from __future__ import annotations

import sys
import threading
import time
import unittest
import weakref
import gc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from exporters.http_common import BackgroundPayloadDispatcher, ExportStatistics


class _BlockingSender:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.bodies: list[bytes] = []

    def send_serialized(self, body: bytes, *, expires_at=None) -> None:
        del expires_at
        self.entered.set()
        self.release.wait(2)
        self.bodies.append(body)


class _ImmediateSender:
    def __init__(self) -> None:
        self.bodies: list[bytes] = []

    def send_serialized(self, body: bytes, *, expires_at=None) -> None:
        del expires_at
        self.bodies.append(body)


class _LegacySender:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def send(self, payload: dict) -> None:
        self.payloads.append(payload)


class _Payload(dict):
    pass


class BoundedDispatcherTests(unittest.TestCase):
    def _dispatcher(self, sender, **overrides):
        options = {
            "sender": sender,
            "worker_name": "test-export",
            "shutdown_event": threading.Event(),
            "max_batches": 2,
            "max_bytes": 1024,
            "max_batch_age_seconds": 30,
            "shutdown_timeout_seconds": 0.2,
        }
        options.update(overrides)
        return BackgroundPayloadDispatcher(**options)

    def test_drop_oldest_preserves_in_flight_and_newest(self) -> None:
        sender = _BlockingSender()
        dispatcher = self._dispatcher(sender)
        self.assertTrue(dispatcher.submit({"id": 1}, record_count=1))
        self.assertTrue(sender.entered.wait(1))
        self.assertTrue(dispatcher.submit({"id": 2}, record_count=2))
        self.assertTrue(dispatcher.submit({"id": 3}, record_count=3))
        snapshot = dispatcher.snapshot()
        self.assertEqual(snapshot["gauges"]["in_flight_batches"], 1)
        self.assertEqual(snapshot["gauges"]["pending_batches"], 1)
        self.assertEqual(snapshot["counters"]["capacity_dropped_batches"], 1)
        self.assertEqual(snapshot["counters"]["capacity_dropped_records"], 2)
        sender.release.set()
        dispatcher.shutdown()

    def test_oversized_and_serialization_rejections_are_separate(self) -> None:
        dispatcher = self._dispatcher(_ImmediateSender(), max_bytes=12)
        self.assertFalse(dispatcher.submit({"payload": "too large"}, record_count=4))
        circular: dict[str, object] = {}
        circular["self"] = circular
        self.assertFalse(dispatcher.submit(circular, record_count=5))
        counters = dispatcher.snapshot()["counters"]
        self.assertEqual(counters["oversized_rejected_batches"], 1)
        self.assertEqual(counters["serialization_rejected_batches"], 1)

    def test_successful_batch_conserves_accounting(self) -> None:
        sender = _ImmediateSender()
        dispatcher = self._dispatcher(sender)
        self.assertTrue(dispatcher.submit({"ok": True}, record_count=7))
        deadline = time.monotonic() + 1
        while dispatcher.snapshot()["counters"].get("successful_batches", 0) < 1:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.005)
        snapshot = dispatcher.snapshot()
        counters, gauges = snapshot["counters"], snapshot["gauges"]
        admitted_terminal = (
            counters.get("successful_batches", 0)
            + counters.get("permanently_failed_batches", 0)
            + counters.get("capacity_dropped_batches", 0)
            + counters.get("expired_batches", 0)
            + counters.get("shutdown_dropped_batches", 0)
            + gauges["pending_batches"] + gauges["in_flight_batches"]
        )
        self.assertEqual(counters["accepted_batches"], admitted_terminal)
        self.assertEqual(counters["successful_records"], 7)
        dispatcher.shutdown()

    def test_legacy_injected_sender_remains_compatible(self) -> None:
        sender = _LegacySender()
        dispatcher = self._dispatcher(sender)
        dispatcher.submit({"compatible": True})
        deadline = time.monotonic() + 1
        while not sender.payloads:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.005)
        self.assertEqual(sender.payloads, [{"compatible": True}])
        dispatcher.shutdown()

    def test_only_in_flight_capacity_rejects_new_batch(self) -> None:
        sender = _BlockingSender()
        dispatcher = self._dispatcher(sender, max_batches=1)
        self.assertTrue(dispatcher.submit({"id": 1}))
        self.assertTrue(sender.entered.wait(1))
        self.assertFalse(dispatcher.submit({"id": 2}))
        self.assertEqual(
            dispatcher.snapshot()["counters"]["capacity_dropped_batches"], 1
        )
        sender.release.set()
        dispatcher.shutdown()

    def test_byte_limit_drops_oldest_pending_body(self) -> None:
        sender = _BlockingSender()
        one_body_bytes = len(b'{"value":"aaaaaaaaaa"}')
        dispatcher = self._dispatcher(
            sender, max_batches=10, max_bytes=one_body_bytes * 2
        )
        dispatcher.submit({"value": "aaaaaaaaaa"}, record_count=1)
        self.assertTrue(sender.entered.wait(1))
        dispatcher.submit({"value": "bbbbbbbbbb"}, record_count=2)
        dispatcher.submit({"value": "cccccccccc"}, record_count=3)
        snapshot = dispatcher.snapshot()
        self.assertEqual(snapshot["counters"]["capacity_dropped_records"], 2)
        self.assertLessEqual(
            snapshot["gauges"]["pending_bytes"] + snapshot["gauges"]["in_flight_bytes"],
            one_body_bytes * 2,
        )
        sender.release.set()
        dispatcher.shutdown()

    def test_expiration_and_shutdown_are_distinct_terminal_losses(self) -> None:
        clock = {"now": 10.0}
        sender = _BlockingSender()
        dispatcher = self._dispatcher(
            sender, max_batches=3, max_batch_age_seconds=5,
            monotonic_fn=lambda: clock["now"],
        )
        dispatcher.submit({"id": 1})
        self.assertTrue(sender.entered.wait(1))
        dispatcher.submit({"id": 2})
        clock["now"] = 16.0
        self.assertEqual(dispatcher.snapshot()["counters"]["expired_batches"], 1)
        dispatcher.submit({"id": 3})
        dispatcher.shutdown()
        self.assertEqual(dispatcher.snapshot()["counters"]["shutdown_dropped_batches"], 1)
        sender.release.set()

    def test_serialization_does_not_retain_original_mapping(self) -> None:
        sender = _BlockingSender()
        dispatcher = self._dispatcher(sender)
        original = _Payload(value="x")
        reference = weakref.ref(original)
        dispatcher.submit(original)
        del original
        gc.collect()
        self.assertIsNone(reference())
        sender.release.set()
        dispatcher.shutdown()

    def test_concurrent_producers_never_exceed_capacity(self) -> None:
        sender = _BlockingSender()
        dispatcher = self._dispatcher(sender, max_batches=8, max_bytes=512)

        def produce(offset: int) -> None:
            for value in range(100):
                dispatcher.submit({"value": offset + value}, record_count=1)

        threads = [threading.Thread(target=produce, args=(index * 1000,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        gauges = dispatcher.snapshot()["gauges"]
        self.assertLessEqual(gauges["pending_batches"] + gauges["in_flight_batches"], 8)
        self.assertLessEqual(gauges["pending_bytes"] + gauges["in_flight_bytes"], 512)
        sender.release.set()
        dispatcher.shutdown()

    def test_shutdown_is_idempotent_and_rejects_new_submissions(self) -> None:
        dispatcher = self._dispatcher(_ImmediateSender())
        dispatcher.shutdown()
        dispatcher.shutdown()
        with self.assertRaisesRegex(RuntimeError, "shutting down"):
            dispatcher.submit({"late": True})
        self.assertEqual(
            dispatcher.snapshot()["counters"]["other_pre_admission_rejected_batches"], 1
        )


if __name__ == "__main__":
    unittest.main()
