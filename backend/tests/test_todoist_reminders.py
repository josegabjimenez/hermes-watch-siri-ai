"""Synthetic, offline Todoist v1 contract and recovery tests."""
from __future__ import annotations

import copy
import io
import json
import threading
import time
import unittest
from datetime import datetime
from unittest import mock
from urllib import error, parse

import todoist_reminders as todoist

COMMAND = "96e26ce3-5cd1-4b7b-a393-2f64abac5bdf"
TEMP_ID = "c055f623-d8b0-44cf-b47a-856684b1293c"
IDENTITY = {"user_id": "synthetic-user", "inbox_project_id": "synthetic-inbox", "timezone": "America/Bogota"}
USER = {"id": IDENTITY["user_id"], "inbox_project_id": IDENTITY["inbox_project_id"], "tz_info": {"timezone": IDENTITY["timezone"]}, "token": "private-provider-value", "email": "synthetic@example.invalid"}
PLAN = {"title": "Llamar a mamá", "due": {"start": "2099-10-30T14:00:00-05:00", "timezone": "America/Bogota", "display": "30 oct 2099 14:00 Bogotá"}}


def task(**changes):
    value = {
        "id": "synthetic-task", "user_id": IDENTITY["user_id"],
        "project_id": IDENTITY["inbox_project_id"], "content": PLAN["title"],
        "description": todoist.marker(COMMAND), "parent_id": None, "section_id": None,
        "checked": False, "is_deleted": False, "deadline": None,
        "due": {"date": "2099-10-30T19:00:00.000000Z", "timezone": "America/Bogota", "is_recurring": False},
    }
    value.update(changes)
    return value


def page(rows=None, cursor=None):
    return {"results": rows or [], "next_cursor": cursor}


def sync(mapping=True, status="ok"):
    return {"sync_status": {COMMAND: status}, "temp_id_mapping": {TEMP_ID: "synthetic-task"} if mapping else {}}


class FakeResponse:
    def __init__(self, value, *, raw=None, wait=None):
        self.raw = json.dumps(value, ensure_ascii=False).encode() if raw is None else raw
        self.closed = False
        self.wait = wait

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def read(self, amount):
        if self.wait is not None:
            self.wait.wait(2)
        return self.raw[:amount]


class FakeOpener:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []
        self.responses = []

    def open(self, req, timeout):
        self.calls.append((req, timeout))
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        response = value if isinstance(value, FakeResponse) else FakeResponse(value)
        self.responses.append(response)
        return response


class TodoistGatewayTests(unittest.TestCase):
    def gateway(self, values, *, timeout=5):
        opener = FakeOpener(values)
        patch = mock.patch.object(todoist.request, "build_opener", return_value=opener)
        patch.start()
        self.addCleanup(patch.stop)
        return todoist.TodoistGateway("synthetic-token", timeout=timeout), opener

    def test_identity_retains_only_destination_binding(self):
        gateway, opener = self.gateway([USER])
        self.assertEqual(gateway.identity(), IDENTITY)
        req, timeout = opener.calls[0]
        self.assertEqual(req.full_url, "https://api.todoist.com/api/v1/user")
        self.assertEqual(req.method, "GET")
        self.assertLessEqual(timeout, 5)
        self.assertTrue(opener.responses[0].closed)

    def test_item_add_exact_schedule_inbox_and_readback(self):
        gateway, opener = self.gateway([USER, page(), sync(), task()])
        mapping = []
        result = gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY, on_external_id=mapping.append)
        self.assertEqual(result, {"task_id": "synthetic-task", "duplicate": False, "auto_reminder_requested": True, "alert_configured": None})
        self.assertEqual(mapping, ["synthetic-task"])
        req = opener.calls[2][0]
        self.assertEqual(req.full_url, "https://api.todoist.com/api/v1/sync")
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.get_header("Content-type"), "application/x-www-form-urlencoded")
        command = json.loads(parse.parse_qs(req.data.decode())["commands"][0])[0]
        self.assertEqual(command, {
            "type": "item_add", "uuid": COMMAND, "temp_id": TEMP_ID,
            "args": {"content": PLAN["title"], "description": todoist.marker(COMMAND), "project_id": IDENTITY["inbox_project_id"],
                     "due": {"date": "2099-10-30T19:00:00Z", "timezone": "America/Bogota", "is_recurring": False},
                     "auto_reminder": True, "auto_parse_labels": False},
        })
        self.assertTrue(all(response.closed for response in opener.responses))

    def test_lost_ack_retries_same_uuid_and_same_temp_id(self):
        gateway, opener = self.gateway([USER, page(), error.URLError("private timeout"), USER, page(), sync(), task()])
        with self.assertRaises(todoist.RetryableTodoistError):
            gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY)
        result = gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY)
        posts = [call[0] for call in opener.calls if call[0].method == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0].data, posts[1].data)
        self.assertEqual(result["task_id"], "synthetic-task")

    def test_lost_ack_finds_marker_without_second_post(self):
        gateway, opener = self.gateway([USER, page([task()])])
        result = gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY)
        self.assertTrue(result["duplicate"])
        self.assertTrue(all(req.method == "GET" for req, _ in opener.calls))

    def test_missing_temp_mapping_reconciles_marker(self):
        gateway, _ = self.gateway([USER, page(), sync(mapping=False), page([task()])])
        result = gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY)
        self.assertEqual(result["task_id"], "synthetic-task")

    def test_ack_without_task_is_never_saved(self):
        gateway, _ = self.gateway([USER, page(), sync(mapping=False), page()])
        with self.assertRaisesRegex(todoist.RetryableTodoistError, "saved_task_not_verified"):
            gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY)

    def test_mapping_is_persisted_before_readback_failure(self):
        gateway, _ = self.gateway([USER, page(), sync(), error.URLError("read failed")])
        mapping = []
        with self.assertRaises(todoist.RetryableTodoistError):
            gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY, on_external_id=mapping.append)
        self.assertEqual(mapping, ["synthetic-task"])

    def test_existing_id_only_reads_and_never_reposts(self):
        gateway, opener = self.gateway([USER, task()])
        result = gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY, external_id="synthetic-task")
        self.assertTrue(result["duplicate"])
        self.assertEqual([req.method for req, _ in opener.calls], ["GET", "GET"])

    def test_deleted_known_task_remains_uncertain_without_post(self):
        missing = error.HTTPError("https://api.todoist.com/private", 404, "private", {}, io.BytesIO(b"private"))
        gateway, opener = self.gateway([USER, missing])
        with self.assertRaisesRegex(todoist.RetryableTodoistError, "known_task_unavailable"):
            gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY, external_id="synthetic-task")
        self.assertTrue(all(req.method == "GET" for req, _ in opener.calls))

    def test_readback_requires_exact_time_title_destination_marker_and_timezone(self):
        for changes in (
            {"content": "Different task"}, {"project_id": "other-inbox"}, {"description": "wrong marker"},
            {"user_id": "other-user"}, {"id": "different-id"}, {"checked": True}, {"is_deleted": True},
            {"deadline": {"date": "2099-10-30"}}, {"parent_id": "a-parent"}, {"section_id": "a-section"},
            {"due": {"date": "2099-10-30T20:00:00Z", "timezone": "America/Bogota", "is_recurring": False}},
            {"due": {"date": "2099-10-30T19:00:00Z", "timezone": None, "is_recurring": False}},
            {"due": {"date": "2099-10-30T19:00:00", "timezone": "America/Bogota", "is_recurring": False}},
            {"due": {"date": "2099-10-30", "timezone": "America/Bogota", "is_recurring": False}},
            {"due": {"date": "2099-10-30T19:00:00Z", "timezone": "America/Bogota", "is_recurring": True}},
        ):
            with self.subTest(changes=changes):
                gateway, _ = self.gateway([USER, task(**changes)])
                with self.assertRaises(todoist.RetryableTodoistError):
                    gateway.reconcile(PLAN, COMMAND, IDENTITY, external_id="synthetic-task")

    def test_identity_mismatch_never_posts(self):
        for user in ({**USER, "id": "other-user"}, {**USER, "inbox_project_id": "other-inbox"}, {**USER, "tz_info": {"timezone": "UTC"}}):
            with self.subTest(user=user):
                gateway, opener = self.gateway([user])
                with self.assertRaises(todoist.PermanentTodoistError):
                    gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY)
                self.assertEqual(len(opener.calls), 1)

    def test_reconciliation_is_read_only_after_schedule_elapsed(self):
        past = copy.deepcopy(PLAN)
        past["due"]["start"] = "2020-10-30T14:00:00-05:00"
        due = {"date": "2020-10-30T19:00:00Z", "timezone": "America/Bogota", "is_recurring": False}
        gateway, opener = self.gateway([USER, page([task(due=due)])])
        self.assertTrue(gateway.reconcile(past, COMMAND, IDENTITY)["duplicate"])
        self.assertTrue(all(req.method == "GET" for req, _ in opener.calls))

    def test_elapsed_before_dispatch_never_posts(self):
        gateway, opener = self.gateway([USER, page()])
        with mock.patch.object(todoist, "dispatch_now", return_value=datetime.fromisoformat("2099-10-30T19:00:01+00:00")):
            with self.assertRaisesRegex(todoist.PermanentTodoistError, "due_elapsed"):
                gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY)
        self.assertEqual(len(opener.calls), 2)

    def test_pagination_keeps_inbox_scope_and_opaque_cursor(self):
        cursor = "opaque/+?=cursor"
        gateway, opener = self.gateway([USER, page([{"id": "other-task"}], cursor), page([task()])])
        result = gateway.reconcile(PLAN, COMMAND, IDENTITY)
        self.assertEqual(result["task_id"], "synthetic-task")
        params = [parse.parse_qs(parse.urlsplit(req.full_url).query) for req, _ in opener.calls[1:]]
        self.assertEqual(params[0], {"project_id": ["synthetic-inbox"], "limit": ["100"]})
        self.assertEqual(params[1], {**params[0], "cursor": [cursor]})

    def test_repeated_or_excessive_pagination_fails_closed(self):
        for pages in ([page(cursor="repeat"), page(cursor="repeat")], [page(cursor=str(i)) for i in range(todoist.MAX_PAGES)]):
            with self.subTest(pages=len(pages)):
                gateway, opener = self.gateway([USER] + pages)
                with self.assertRaises(todoist.RetryableTodoistError):
                    gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY)
                self.assertTrue(all(req.method == "GET" for req, _ in opener.calls))

    def test_duplicate_marker_candidates_fail_closed(self):
        gateway, _ = self.gateway([USER, page([task(), task(id="another-task")])])
        with self.assertRaisesRegex(todoist.RetryableTodoistError, "multiple_matching"):
            gateway.reconcile(PLAN, COMMAND, IDENTITY)

    def test_command_rejection_is_sanitized(self):
        gateway, _ = self.gateway([USER, page(), sync(status={"http_code": 400, "error": "private provider body"})])
        with self.assertRaisesRegex(todoist.PermanentTodoistError, "^todoist_command_rejected$"):
            gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY)

    def test_missing_command_status_is_uncertain(self):
        gateway, _ = self.gateway([USER, page(), {}])
        with self.assertRaisesRegex(todoist.RetryableTodoistError, "command_unconfirmed"):
            gateway.create_or_reconcile(PLAN, COMMAND, TEMP_ID, IDENTITY)

    def test_http_and_transport_errors_never_expose_provider_content(self):
        for exc, kind in (
            (error.HTTPError("https://private.invalid/token", 401, "private-token", {}, io.BytesIO(b"private body")), todoist.PermanentTodoistError),
            (error.HTTPError("https://private.invalid/token", 500, "private-token", {}, io.BytesIO(b"private body")), todoist.RetryableTodoistError),
            (error.URLError("private-token"), todoist.RetryableTodoistError),
        ):
            with self.subTest(kind=kind):
                gateway, _ = self.gateway([exc])
                with self.assertRaises(kind) as raised:
                    gateway.identity()
                self.assertNotIn("private", str(raised.exception))

    def test_invalid_and_oversized_json_is_uncertain(self):
        for raw in (b"{private invalid json", b"[]", b"x" * (todoist.MAX_RESPONSE_BYTES + 1)):
            with self.subTest(size=len(raw)):
                gateway, opener = self.gateway([FakeResponse(None, raw=raw)])
                with self.assertRaises(todoist.RetryableTodoistError):
                    gateway.identity()
                self.assertTrue(opener.responses[0].closed)

    def test_total_timeout_bounds_stalled_response(self):
        release = threading.Event()
        gateway, opener = self.gateway([FakeResponse(USER, wait=release)], timeout=0.04)
        started = time.monotonic()
        try:
            with self.assertRaises(todoist.RetryableTodoistError):
                gateway.identity()
            self.assertLess(time.monotonic() - started, 0.3)
        finally:
            release.set()

    def test_validation_prevents_requests(self):
        gateway, opener = self.gateway([])
        for plan, command, temporary, identity in (
            ({**PLAN, "title": ""}, COMMAND, TEMP_ID, IDENTITY),
            ({**PLAN, "due": {"start": "2099-10-30", "timezone": "America/Bogota"}}, COMMAND, TEMP_ID, IDENTITY),
            ({**PLAN, "due": {"start": "2099-10-30T19:00:00Z", "timezone": "UTC"}}, COMMAND, TEMP_ID, IDENTITY),
            (PLAN, "new command please", TEMP_ID, IDENTITY),
            (PLAN, COMMAND, "https://other.invalid", IDENTITY),
            (PLAN, COMMAND, TEMP_ID, {**IDENTITY, "inbox_project_id": "../tasks"}),
        ):
            with self.subTest(command=command):
                with self.assertRaises(todoist.PermanentTodoistError):
                    gateway.create_or_reconcile(plan, command, temporary, identity)
        self.assertEqual(opener.calls, [])

    def test_gateway_never_accepts_nonfinite_timeout_or_header_whitespace(self):
        for token, timeout in (("", 5), ("secret\nheader", 5), ("synthetic", float("inf")), ("synthetic", 0), ("synthetic", True)):
            with self.subTest(timeout=timeout):
                with self.assertRaises(todoist.PermanentTodoistError):
                    todoist.TodoistGateway(token, timeout)


if __name__ == "__main__":
    unittest.main()
