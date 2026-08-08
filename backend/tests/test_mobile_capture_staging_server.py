#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import hashlib
import hmac
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from urllib import request
from zoneinfo import ZoneInfo

import mobile_capture_staging_server as srv


class MobileCaptureStagingServerTests(unittest.TestCase):
    @staticmethod
    def grocery_payload(*, live: bool = False, text: str = "leche"):
        return {
            "event_type": "mobile_capture.v1",
            "schema_version": 1,
            "request_id": "unit-grocery-write",
            "route": {"agent": "aura", "intent": "grocery", "domain": "aura.grocery_capture"},
            "capture": {"text": text},
            "context": {"dry_run": not live, "allow_write": live, "allow_firefly_write": False},
        }

    def test_parse_amount_cop(self):
        self.assertEqual(srv.parse_amount_cop("45 mil en Uber"), 45000)
        self.assertEqual(srv.parse_amount_cop("33.500 sandwiches"), 33500)
        self.assertEqual(srv.parse_amount_cop("fp 364.900 ChatGPT tc1"), 364900)

    def test_hmac_v2_accepts_exact_body(self):
        secret = b"test-secret"
        raw = b'{"event_type":"mobile_capture.v1"}'
        ts = str(int(time.time()))
        sig = hmac.new(secret, ts.encode() + b"." + raw, hashlib.sha256).hexdigest()

        class Headers(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        ok, reason = srv.verify_hmac_v2(
            Headers({"X-Webhook-Timestamp": ts, "X-Webhook-Signature-V2": sig}),
            raw,
            secret,
        )
        self.assertTrue(ok, reason)

    def test_hmac_v2_rejects_changed_body(self):
        secret = b"test-secret"
        raw = b'{"event_type":"mobile_capture.v1"}'
        changed = b'{"event_type":"mobile_capture.v1","x":1}'
        ts = str(int(time.time()))
        sig = hmac.new(secret, ts.encode() + b"." + raw, hashlib.sha256).hexdigest()

        class Headers(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        ok, reason = srv.verify_hmac_v2(
            Headers({"X-Webhook-Timestamp": ts, "X-Webhook-Signature-V2": sig}),
            changed,
            secret,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "invalid signature")

    def test_megan_dry_run_plan(self):
        payload = {
            "event_type": "mobile_capture.v1",
            "schema_version": 1,
            "request_id": "unit-megan-1",
            "created_at": "2026-07-06T20:55:00Z",
            "route": {"agent": "megan", "intent": "expense", "domain": "megan.expense_capture"},
            "capture": {"text": "45 mil en Uber"},
            "context": {"dry_run": True, "allow_write": False},
        }
        plan = srv.plan_capture(payload)
        self.assertEqual(plan["status"], "accepted")
        self.assertTrue(plan["dry_run"])
        self.assertFalse(plan["plan"]["would_write"])
        self.assertEqual(plan["plan"]["amount_cop"], 45000)

    def test_megan_ambiguous_card_needs_confirmation(self):
        payload = {
            "event_type": "mobile_capture.v1",
            "schema_version": 1,
            "request_id": "unit-megan-2",
            "route": {"agent": "megan", "intent": "expense", "domain": "megan.expense_capture"},
            "capture": {"text": "gasto tarjeta 80 mil ropa"},
            "context": {"dry_run": True, "allow_write": False},
        }
        plan = srv.plan_capture(payload)
        self.assertEqual(plan["status"], "needs_confirmation")
        self.assertIn("TC1", plan["question"])

    def test_aura_due_parses_spanish_pm(self):
        base = datetime.fromisoformat("2026-07-06T19:00:00-05:00").astimezone(ZoneInfo("America/Bogota"))
        due = srv.parse_spanish_due("recuérdame llamar a mamá mañana a las dos P.M.", base)
        self.assertIsNotNone(due)
        self.assertEqual(due["start"], "2026-07-07T14:00:00-05:00")

    def test_grocery_write_requires_client_and_server_gates(self):
        cfg = srv.Config(
            secret=b"test",
            ledger_path=Path("unused.sqlite"),
            host="127.0.0.1",
            port=0,
            write_enabled=True,
            write_domains=frozenset({"aura.grocery_capture"}),
            aura_helper=Path(__file__),
        )
        self.assertFalse(srv.write_is_authorized(self.grocery_payload(live=False), cfg))
        self.assertTrue(srv.write_is_authorized(self.grocery_payload(live=True), cfg))
        spoofed_route = self.grocery_payload(live=True)
        spoofed_route["route"].update(agent="megan", intent="expense")
        self.assertFalse(srv.write_is_authorized(spoofed_route, cfg))
        self.assertFalse(
            srv.write_is_authorized(
                self.grocery_payload(live=True),
                srv.Config(
                    secret=b"test",
                    ledger_path=Path("unused.sqlite"),
                    host="127.0.0.1",
                    port=0,
                    write_enabled=False,
                    write_domains=frozenset({"aura.grocery_capture"}),
                ),
            )
        )

    def test_bare_grocery_item_commits_through_allowlisted_adapter(self):
        payload = self.grocery_payload(live=True, text="leche")
        cfg = srv.Config(
            secret=b"test",
            ledger_path=Path("unused.sqlite"),
            host="127.0.0.1",
            port=0,
            write_enabled=True,
            write_domains=frozenset({"aura.grocery_capture"}),
            aura_helper=Path(__file__),
        )
        helper_results = [
            {"ok": True, "intent": "note", "title": "Leche"},
            {"ok": True, "intent": "grocery", "title": "Leche"},
            {"ok": True, "intent": "grocery", "item": "leche", "block_id": "notion-block"},
        ]
        with mock.patch.object(srv, "run_aura_helper", side_effect=helper_results) as helper:
            response = srv.execute_capture(payload, cfg)

        self.assertEqual(response["status"], "committed")
        self.assertFalse(response["dry_run"])
        self.assertTrue(response["write_committed"])
        self.assertTrue(response["plan"]["would_write"])
        self.assertEqual(response["request_id"], payload["request_id"])
        self.assertEqual(response["external_ids"]["notion_block_id"], "notion-block")
        self.assertEqual(helper.call_count, 3)
        self.assertEqual(helper.call_args_list[1].kwargs["text_override"], "falta leche")
        self.assertEqual(helper.call_args_list[2].kwargs["text_override"], "falta leche")

    def test_grocery_route_mismatch_does_not_execute_write(self):
        payload = self.grocery_payload(live=True, text="recuérdame llamar mañana")
        cfg = srv.Config(
            secret=b"test",
            ledger_path=Path("unused.sqlite"),
            host="127.0.0.1",
            port=0,
            write_enabled=True,
            write_domains=frozenset({"aura.grocery_capture"}),
            aura_helper=Path(__file__),
        )
        with mock.patch.object(
            srv,
            "run_aura_helper",
            return_value={"ok": True, "intent": "reminder", "title": "Llamar"},
        ) as helper:
            response = srv.execute_capture(payload, cfg)

        self.assertEqual(response["status"], "needs_confirmation")
        self.assertTrue(response["dry_run"])
        self.assertFalse(response["plan"]["would_write"])
        self.assertEqual(helper.call_count, 1)

    def test_validate_wrong_event_is_ignored(self):
        valid, status, response = srv.validate_payload({"event_type": "other", "schema_version": 1}, "")
        self.assertFalse(valid)
        self.assertEqual(status, 200)
        self.assertEqual(response["status"], "ignored")

    def test_validate_requires_x_request_id(self):
        valid, status, response = srv.validate_payload(
            {"event_type": "mobile_capture.v1", "schema_version": 1, "request_id": "body-id", "capture": {"text": "45 mil en Uber"}},
            "",
        )
        self.assertFalse(valid)
        self.assertEqual(status, 400)
        self.assertEqual(response["error"], "missing X-Request-ID")

    def test_validate_rejects_header_body_request_id_mismatch(self):
        valid, status, response = srv.validate_payload(
            {"event_type": "mobile_capture.v1", "schema_version": 1, "request_id": "body-id", "capture": {"text": "45 mil en Uber"}},
            "header-id",
        )
        self.assertFalse(valid)
        self.assertEqual(status, 409)
        self.assertEqual(response["error"], "X-Request-ID mismatch")

    def test_concurrent_duplicate_requests_return_cached_result(self):
        secret = b"concurrent-test-secret"
        payload = {
            "event_type": "mobile_capture.v1",
            "schema": "hermes.mobile_capture",
            "schema_version": 1,
            "request_id": "concurrent-request-id",
            "created_at": "2026-08-04T22:00:00Z",
            "source": {
                "platform": "watchOS",
                "surface": "watch_app",
                "app_version": "0.3.1",
                "os_version": "27.0",
                "device_id": "unit-device",
            },
            "route": {
                "agent": "argos",
                "intent": "general_capture",
                "domain": "argos.general_capture",
            },
            "capture": {"modality": "watch_dictation", "text": "concurrent test"},
            "context": {"dry_run": True, "allow_write": False, "allow_firefly_write": False},
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        original_execute = srv.execute_capture

        def slow_execute(value, cfg):
            time.sleep(0.05)
            return original_execute(value, cfg)

        class QuietHandler(srv.MobileCaptureHandler):
            def log_message(self, fmt, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            cfg = srv.Config(
                secret=secret,
                ledger_path=Path(directory) / "ledger.sqlite",
                host="127.0.0.1",
                port=0,
            )
            srv.init_db(cfg.ledger_path)
            self.assertEqual(cfg.ledger_path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(cfg.ledger_path.stat().st_mode & 0o777, 0o600)
            server = srv.ThreadingHTTPServer((cfg.host, 0), QuietHandler)
            server.cfg = cfg
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            endpoint = f"http://127.0.0.1:{server.server_address[1]}/webhooks/mobile-capture-v1"
            worker_count = 8
            barrier = threading.Barrier(worker_count)

            def send(_):
                barrier.wait()
                timestamp = str(int(time.time()))
                signature = hmac.new(
                    secret,
                    timestamp.encode("utf-8") + b"." + raw,
                    hashlib.sha256,
                ).hexdigest()
                req = request.Request(
                    endpoint,
                    data=raw,
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Timestamp": timestamp,
                        "X-Webhook-Signature-V2": signature,
                        "X-Request-ID": payload["request_id"],
                    },
                )
                with request.urlopen(req, timeout=5) as response:
                    return response.status, json.loads(response.read())["status"]

            try:
                with mock.patch.object(srv, "execute_capture", side_effect=slow_execute):
                    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                        results = list(executor.map(send, range(worker_count)))
            finally:
                server.shutdown()
                server_thread.join()
                server.server_close()

        self.assertEqual([status for status, _ in results], [200] * worker_count)
        self.assertEqual(sum(result == (200, "accepted") for result in results), 1)
        self.assertEqual(sum(result == (200, "duplicate") for result in results), worker_count - 1)


if __name__ == "__main__":
    unittest.main()
