"""Offline transport/validation contracts; these do not benchmark model accuracy."""
from __future__ import annotations

import copy
import io
import json
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock
from urllib.error import HTTPError

import reminder_ai as ai

CAPTURE = "2026-10-29T14:00:17.123456Z"
NOW = datetime.fromisoformat("2026-10-29T09:01:00-05:00")


def proposal(**changes):
    value = {
        "action": "create_reminder", "title": "Llamar a mamá",
        "timezone": "America/Bogota",
        "schedule": {"mode": "absolute", "date": "2026-10-30", "time": "14:00", "offset_minutes": None},
        "question": None, "deadline": None, "recurrence": None, "custom_alert": None,
    }
    value.update(changes)
    return value


def completed(value=None, *, text=None):
    return {"status": "completed", "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "role": "assistant", "status": "completed", "content": [
            {"type": "output_text", "text": text if text is not None else json.dumps(value or proposal())}
        ]},
    ]}


class InterpretationTests(unittest.TestCase):
    def test_spanish_and_english_mock_responses_use_same_strict_api_contract(self):
        for text in ("Porfa, mañana a las dos de la tarde recuérdame llamar a mamá", "Remind me to call Mom tomorrow at 2 pm"):
            with self.subTest(text=text), mock.patch.object(ai, "_post_json", return_value=completed()) as post:
                value = ai.interpret(text, CAPTURE, api_key="synthetic-key", model="gpt-6-luna", timeout=2)
                self.assertEqual(ai.validate(value, CAPTURE, NOW)["due"]["start"], "2026-10-30T14:00:00-05:00")
                args = post.call_args.args
                body = json.loads(args[0])
                self.assertEqual(args[1:], ("synthetic-key", 2.0))
                self.assertEqual(body["model"], "gpt-6-luna")
                self.assertEqual(body["reasoning"], {"effort": "low"})
                self.assertFalse(body["store"])
                self.assertNotIn("temperature", body)
                self.assertNotIn("top_p", body)
                self.assertNotIn("tools", body)
                self.assertEqual(body["text"]["format"]["type"], "json_schema")
                self.assertTrue(body["text"]["format"]["strict"])
                self.assertEqual(set(ai.REMINDER_SCHEMA["required"]), set(ai.REMINDER_SCHEMA["properties"]))
                self.assertFalse(ai.REMINDER_SCHEMA["additionalProperties"])
                original = json.loads(body["input"])
                self.assertEqual(original["captured_at"], CAPTURE)
                self.assertEqual(original["captured_at_bogota"], "2026-10-29T09:00:17.123456-05:00")
                self.assertEqual(original["text"], text)

    def test_model_is_configurable(self):
        with mock.patch.object(ai, "_post_json", return_value=completed()) as post:
            ai.interpret("Call Mom tomorrow at 14:00", CAPTURE, api_key="synthetic", model="deployment-model")
        self.assertEqual(json.loads(post.call_args.args[0])["model"], "deployment-model")

    def test_missing_configuration_and_invalid_inputs_never_contact_provider(self):
        cases = [
            {"api_key": ""}, {"model": "invalid model"}, {"timeout": 0}, {"timeout": True},
            {"timeout": float("nan")}, {"timeout": 31}, {"text": ""}, {"text": "x" * 4001},
            {"captured_at": "2026-10-29"}, {"captured_at": "2026-10-29T14:00:00"},
        ]
        for changes in cases:
            args = {"text": "Llamar mañana a las 14:00", "captured_at": CAPTURE, "api_key": "synthetic"}
            args.update(changes)
            with self.subTest(changes=changes), mock.patch.object(ai, "_post_json") as post:
                with self.assertRaises(ai.InterpretationUnavailable):
                    ai.interpret(**args)
                post.assert_not_called()

    def test_incomplete_failed_refused_and_tool_outputs_never_become_proposals(self):
        refusal = completed()
        refusal["output"][1]["content"] = [{"type": "refusal", "refusal": "private raw refusal"}]
        wrong_role = completed()
        wrong_role["output"][1]["role"] = "user"
        tool = completed()
        tool["output"].append({"type": "function_call", "name": "write"})
        variants = [
            {"status": "incomplete", "output": []}, {"status": "failed", "error": {"message": "private"}},
            {"status": "completed", "output": []}, refusal, wrong_role, tool,
            {"status": "completed", "output": ["bad"]},
        ]
        for variant in variants:
            with self.subTest(variant=variant), mock.patch.object(ai, "_post_json", return_value=variant):
                with self.assertRaises(ai.InterpretationUnavailable) as caught:
                    ai.interpret("Llamar mañana a las 14:00", CAPTURE, api_key="synthetic")
                self.assertNotIn("private", str(caught.exception))

    def test_invalid_json_duplicate_keys_and_schema_do_not_escape(self):
        bad = proposal(destination="outside-inbox")
        missing = proposal()
        del missing["custom_alert"]
        for text in ("not-json", "[]", "[" * 2000 + "]" * 2000, '{"action":"create_reminder","action":"unsupported"}', json.dumps(bad), json.dumps(missing)):
            with self.subTest(text=text), mock.patch.object(ai, "_post_json", return_value=completed(text=text)):
                with self.assertRaisesRegex(ai.InterpretationUnavailable, "invalid_schema"):
                    ai.interpret("Llamar mañana a las 14:00", CAPTURE, api_key="synthetic")

    def test_errors_are_sanitized(self):
        secret = "synthetic-sensitive-value"
        with mock.patch.object(ai, "_post_json", side_effect=HTTPError(ai.OPENAI_RESPONSES_URL, 401, secret, {}, io.BytesIO(secret.encode()))):
            with self.assertRaises(ai.InterpretationUnavailable) as caught:
                ai.interpret("Llamar mañana a las 14:00", CAPTURE, api_key=secret)
        self.assertEqual(str(caught.exception), "interpreter_unavailable")
        self.assertIsNone(caught.exception.__cause__)

    def test_wall_timeout_returns_before_a_slow_transport(self):
        release = threading.Event()
        finished = threading.Event()
        def slow(*args):
            release.wait(2)
            finished.set()
            return completed()
        try:
            with mock.patch.object(ai, "_post_json", side_effect=slow):
                started = time.monotonic()
                with self.assertRaisesRegex(ai.InterpretationUnavailable, "interpreter_timeout"):
                    ai.interpret("Llamar mañana a las 14:00", CAPTURE, api_key="synthetic", timeout=0.03)
                self.assertLess(time.monotonic() - started, 0.5)
        finally:
            release.set()
            self.assertTrue(finished.wait(1))

    def test_transport_concurrency_is_bounded(self):
        slot = threading.BoundedSemaphore(1)
        slot.acquire()
        with mock.patch.object(ai, "_TRANSPORT_SLOTS", slot), mock.patch.object(ai, "_post_json") as post:
            with self.assertRaisesRegex(ai.InterpretationUnavailable, "interpreter_busy"):
                ai.interpret("Llamar mañana a las 14:00", CAPTURE, api_key="synthetic")
        post.assert_not_called()
        slot.release()

    def test_http_endpoint_redirect_and_response_size_are_bounded(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"x" * (ai.MAX_RESPONSE_BYTES + 1)
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(ai.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(ValueError, "response_too_large"):
                ai._post_json(b"{}", "synthetic-key", 3)
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 3)
        response.read.assert_called_once_with(ai.MAX_RESPONSE_BYTES + 1)
        self.assertIsNone(ai._NoRedirect().redirect_request(None, None, 302, None, None, "https://example.invalid"))


class ValidationTests(unittest.TestCase):
    def test_original_capture_relative_schedule_does_not_shift_on_retry(self):
        value = proposal(schedule={"mode": "relative", "date": None, "time": None, "offset_minutes": 20})
        first = ai.validate(value, CAPTURE, NOW)
        later = ai.validate(value, CAPTURE, NOW + timedelta(minutes=5))
        self.assertEqual(first, later)
        self.assertEqual(first["due"]["start"], "2026-10-29T09:20:17.123456-05:00")
        expired = ai.validate(value, CAPTURE, NOW + timedelta(minutes=21))
        self.assertEqual(expired["reason"], "elapsed_schedule")
        self.assertNotIn("due", expired)

    def test_day_boundary_uses_bogota_original_day(self):
        value = proposal(schedule={"mode": "absolute", "date": "2026-10-30", "time": "09:00", "offset_minutes": None})
        result = ai.validate(value, "2026-10-30T04:50:00Z", datetime.fromisoformat("2026-10-29T23:51:00-05:00"))
        self.assertEqual(result["due"]["start"], "2026-10-30T09:00:00-05:00")

    def test_timestamp_gate_rejects_missing_naive_invalid_and_future(self):
        for stamp in (None, "", "2026-10-29", "2026-10-29T09:00:00", "2026-02-30T14:00:00Z", "2026-10-29T09:02:00-05:00"):
            with self.subTest(stamp=stamp):
                with self.assertRaises((ValueError, OverflowError)):
                    ai.validate_capture_timestamp(stamp, NOW)
                result = ai.validate(proposal(), stamp, NOW)
                self.assertNotEqual(result["status"], "ready")
        self.assertEqual(ai.validate_capture_timestamp(CAPTURE, NOW).isoformat(), "2026-10-29T09:00:17.123456-05:00")

    def test_ambiguous_missing_and_unsupported_mock_interpretations_never_write(self):
        cases = [
            proposal(action="needs_input", title=None, schedule=None, question="¿A qué hora mañana?"),
            proposal(action="unsupported", title=None, schedule=None, question="Solo puedo crear un recordatorio."),
            proposal(schedule=None), proposal(title=""), proposal(question="¿Qué fecha?"),
        ]
        for value in cases:
            with self.subTest(value=value):
                result = ai.validate(value, CAPTURE, NOW)
                self.assertIn(result["status"], ("needs_input", "unsupported"))
                self.assertNotIn("due", result)

    def test_deadline_recurrence_custom_alert_are_distinct_from_task_time(self):
        for field, concept in (("deadline", "by Friday"), ("recurrence", "cada lunes"), ("custom_alert", "10 minutos antes")):
            with self.subTest(field=field):
                result = ai.validate(proposal(**{field: concept}), CAPTURE, NOW)
                self.assertEqual(result["status"], "unsupported")
                self.assertEqual(result["reason"], "unsupported_schedule_feature")
                self.assertNotIn("due", result)

    def test_invalid_calendar_times_and_past_due_are_rejected(self):
        for day, hour in (("2026-02-30", "14:00"), ("2026-10-30", "24:00"), ("2026-10-30", "2:00"), ("2026-10-30", None), ("2026-10-28", "14:00"), ("2026-10-29", "09:01")):
            with self.subTest(day=day, hour=hour):
                value = proposal(schedule={"mode": "absolute", "date": day, "time": hour, "offset_minutes": None})
                self.assertNotEqual(ai.validate(value, CAPTURE, NOW)["status"], "ready")

    def test_invalid_or_mixed_relative_values_are_rejected(self):
        for minutes in (0, -1, True, 2.5, "20", ai.MAX_RELATIVE_MINUTES + 1):
            value = proposal(schedule={"mode": "relative", "date": None, "time": None, "offset_minutes": minutes})
            with self.subTest(minutes=minutes):
                self.assertNotEqual(ai.validate(value, CAPTURE, NOW)["status"], "ready")
        value = proposal(schedule={"mode": "relative", "date": "2026-10-30", "time": None, "offset_minutes": 20})
        self.assertNotEqual(ai.validate(value, CAPTURE, NOW)["status"], "ready")
        value = proposal(schedule={"mode": "absolute", "date": "2026-10-30", "time": "14:00", "offset_minutes": 20})
        self.assertNotEqual(ai.validate(value, CAPTURE, NOW)["status"], "ready")

    def test_shape_rejects_extra_missing_wrong_type_and_untrusted_destination(self):
        variants = [proposal(destination="elsewhere"), proposal(timezone="UTC"), proposal(action=[]), proposal(title=[])]
        missing = proposal()
        del missing["question"]
        variants.append(missing)
        value = proposal()
        value["schedule"]["mode"] = []
        variants.append(value)
        for value in variants:
            with self.subTest(value=value):
                self.assertEqual(ai.validate(value, CAPTURE, NOW)["reason"], "invalid_schema")

    def test_title_never_silently_truncated_and_controls_rejected(self):
        for title in ("x" * 201, "Llamar\nMamá", "\x00Llamar", "  "):
            with self.subTest(title=repr(title)):
                self.assertEqual(ai.validate(proposal(title=title), CAPTURE, NOW)["reason"], "invalid_title")

    def test_question_is_bounded_and_sanitized(self):
        for question in ("x" * 241, "", "\x00private"):
            result = ai.validate(proposal(action="needs_input", schedule=None, question=question), CAPTURE, NOW)
            self.assertEqual(result["question"], "Indica una tarea, fecha y hora futuras claras en Bogotá.")

    def test_validation_does_not_mutate_the_proposal(self):
        value = proposal()
        original = copy.deepcopy(value)
        ai.validate(value, CAPTURE, NOW)
        self.assertEqual(value, original)


if __name__ == "__main__":
    unittest.main()
