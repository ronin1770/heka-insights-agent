"""Reproduce retained-memory difference between unbounded objects and bounded bytes."""
from __future__ import annotations

import argparse
import gc
import threading
import time
import tracemalloc

import psutil

from exporters.http_common import BackgroundPayloadDispatcher


class _BlockedSender:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def send_serialized(self, body: bytes, *, expires_at=None) -> None:
        del body, expires_at
        self.entered.set()
        self.release.wait(60)


def payload(index: int, records: int) -> dict:
    return {
        "resourceMetrics": [{
            "scopeMetrics": [{
                "metrics": [
                    {
                        "name": f"heka_test_{item % 20}",
                        "description": "representative metric",
                        "unit": "bytes",
                        "gauge": {"dataPoints": [{
                            "timeUnixNano": str(1_800_000_000_000_000_000 + index),
                            "asDouble": float(index + item),
                            "attributes": [{"key": "pid", "value": {"stringValue": str(item)}}],
                        }]},
                    }
                    for item in range(records)
                ]
            }]
        }]
    }


def measured_growth(build) -> int:
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    retained = build()
    after = tracemalloc.take_snapshot()
    growth = sum(item.size_diff for item in after.compare_to(before, "filename"))
    del retained
    tracemalloc.stop()
    return growth


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches", type=int, default=3000)
    parser.add_argument("--records", type=int, default=50)
    parser.add_argument("--mode", choices=("compare", "baseline", "bounded"), default="compare")
    args = parser.parse_args()

    if args.mode == "baseline":
        retained = [payload(index, args.records) for index in range(args.batches)]
        print({"mode": "baseline", "retained_batches": len(retained), **process_memory()})
        return

    baseline = measured_growth(
        lambda: [payload(index, args.records) for index in range(args.batches)]
    ) if args.mode == "compare" else None
    sender = _BlockedSender()
    dispatcher = BackgroundPayloadDispatcher(
        sender=sender,
        worker_name="benchmark-export",
        shutdown_event=threading.Event(),
        max_batches=64,
        max_bytes=8 * 1024 * 1024,
        max_batch_age_seconds=3600,
        shutdown_timeout_seconds=0.1,
    )

    def fill_bounded():
        for index in range(args.batches):
            dispatcher.submit(payload(index, args.records), record_count=args.records)
        return dispatcher.snapshot()

    bounded = measured_growth(fill_bounded)
    snapshot = dispatcher.snapshot()
    sender.release.set()
    dispatcher.shutdown()
    result = {
        "mode": args.mode,
        "batches_submitted": args.batches,
        "records_per_batch": args.records,
        "unbounded_object_growth_bytes": baseline,
        "bounded_dispatch_growth_bytes": bounded,
        "bounded_queue": snapshot,
        **process_memory(),
    }
    print(result)


def process_memory() -> dict[str, int | None]:
    process = psutil.Process()
    memory = process.memory_info()
    uss = pss = None
    try:
        full = process.memory_full_info()
        uss, pss = getattr(full, "uss", None), getattr(full, "pss", None)
    except (psutil.AccessDenied, OSError):
        pass
    return {"rss_bytes": memory.rss, "uss_bytes": uss, "pss_bytes": pss}


if __name__ == "__main__":
    main()
