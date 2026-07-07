#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import mobile_capture_staging_server as srv


class MobileCaptureStagingServerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
