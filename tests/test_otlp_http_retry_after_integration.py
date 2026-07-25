"""Integration-style tests for OTLP HTTP Retry-After handling."""

from __future__ import annotations

import json
import socketserver
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from exporters.otlp_http import OtlpHttpMetricSender


class _RetryAfterHandler(BaseHTTPRequestHandler):
    request_log: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        self.__class__.request_log.append(
            {
                "at": time.monotonic(),
                "path": self.path,
                "headers": {
                    key.lower(): value for key, value in self.headers.items()
                },
                "body": body,
            }
        )

        if len(self.__class__.request_log) == 1:
            self.send_response(429)
            self.send_header("rEtRy-AfTeR", "1")
            self.end_headers()
            return

        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        del format, args


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


class OtlpHttpRetryAfterIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        _RetryAfterHandler.request_log = []
        self._server = _ThreadingHTTPServer(("127.0.0.1", 0), _RetryAfterHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()

    def tearDown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)

    def test_sender_retries_same_payload_after_retry_after_delay(self) -> None:
        host, port = self._server.server_address
        sender = OtlpHttpMetricSender(
            endpoint=f"http://{host}:{port}/v1/metrics",
            retry_max_attempts=3,
            headers={"x-agent-id": "agt_01JXYZ123"},
        )
        payload = {"resourceMetrics": [{"scopeMetrics": []}]}

        sender.send(payload)

        self.assertEqual(len(_RetryAfterHandler.request_log), 2)
        first, second = _RetryAfterHandler.request_log
        self.assertGreaterEqual(second["at"] - first["at"], 1.0)
        self.assertEqual(first["body"], second["body"])
        self.assertEqual(first["headers"]["x-agent-id"], "agt_01JXYZ123")
        self.assertEqual(second["headers"]["x-agent-id"], "agt_01JXYZ123")
        self.assertEqual(json.loads(first["body"].decode("utf-8")), payload)


if __name__ == "__main__":
    unittest.main()
