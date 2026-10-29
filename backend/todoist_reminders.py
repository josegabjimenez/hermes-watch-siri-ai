"""Narrow Todoist v1 gateway for a validated personal Inbox reminder.

The caller must durably store the plan, account identity, command UUID and
temporary ID before calling ``create_or_reconcile``. A retry always reuses
those values. No natural-language parsing or destination selection happens
here, and an acknowledgement is never treated as proof of a matching task.

API contract: https://developer.todoist.com/api/v1/ (Sync command UUIDs,
item_add, fixed-zone due dates, User Info and cursor pagination).
"""
from __future__ import annotations

import json
import math
import queue
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib import error, parse, request
from uuid import UUID

API_ROOT = "https://api.todoist.com/api/v1"
BOGOTA = "America/Bogota"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_PAGES = 10
PAGE_SIZE = 100
# A stalled transport cannot create an unbounded number of background workers.
_TRANSPORT_SLOTS = threading.BoundedSemaphore(4)
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")


class RetryableTodoistError(RuntimeError):
    """No matching saved-task proof; retry/reconcile with the same command."""


class PermanentTodoistError(RuntimeError):
    """Configuration/plan or a definitively rejected command needs attention."""


class _NotFound(Exception):
    pass


def _resource_id(value: Any) -> bool:
    return isinstance(value, str) and _ID_RE.fullmatch(value) is not None


def _uuid(value: Any) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise PermanentTodoistError("invalid_command_identity") from None
    return value


def marker(command_uuid: str) -> str:
    return f"Personal Watch App capture {_uuid(command_uuid)}"


def dispatch_now() -> datetime:
    return datetime.now(timezone.utc)


def _instant(value: Any) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("timed_date_required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("fixed_timezone_required")
    return result


def _validate_plan(plan: Any) -> tuple[str, datetime]:
    if not isinstance(plan, dict):
        raise PermanentTodoistError("invalid_reminder_plan")
    title, due = plan.get("title"), plan.get("due")
    if (
        not isinstance(title, str) or not title.strip() or len(title) > 500
        or any(ord(char) < 32 or ord(char) == 127 for char in title)
        or not isinstance(due, dict) or due.get("timezone") != BOGOTA
    ):
        raise PermanentTodoistError("invalid_reminder_plan")
    try:
        instant = _instant(due.get("start"))
    except (TypeError, ValueError, OverflowError):
        raise PermanentTodoistError("invalid_reminder_plan") from None
    return title, instant


def _validate_identity(identity: Any) -> dict[str, str]:
    if not isinstance(identity, dict) or not all(
        _resource_id(identity.get(field)) for field in ("user_id", "inbox_project_id")
    ) or identity.get("timezone") != BOGOTA:
        raise PermanentTodoistError("todoist_identity_not_verified")
    return {field: identity[field] for field in ("user_id", "inbox_project_id", "timezone")}


class TodoistGateway:
    def __init__(self, token: str, timeout: float = 5):
        if not isinstance(token, str) or not token or any(char.isspace() for char in token):
            raise PermanentTodoistError("todoist_token_not_configured")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise PermanentTodoistError("invalid_todoist_timeout")
        self._token = token
        self.timeout = float(timeout)

    def _request(self, method: str, path: str, deadline: float, *, form: dict[str, str] | None = None) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not _TRANSPORT_SLOTS.acquire(blocking=False):
            raise RetryableTodoistError("todoist_timeout_or_busy")
        data = parse.urlencode(form).encode("utf-8") if form is not None else None
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = request.Request(API_ROOT + path, data=data, headers=headers, method=method)
        result: queue.Queue[Any] = queue.Queue(maxsize=1)

        def transport() -> None:
            try:
                # Redirects could send the bearer token elsewhere. This API has
                # a fixed origin and is not expected to redirect.
                opener = request.build_opener(_NoRedirect())
                with opener.open(req, timeout=remaining) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise RetryableTodoistError("todoist_response_too_large")
                decoded = json.loads(raw)
                if not isinstance(decoded, dict):
                    raise RetryableTodoistError("todoist_invalid_response")
                result.put(decoded)
            except error.HTTPError as exc:
                code = exc.code
                exc.close()
                if code == 404:
                    result.put(_NotFound())
                elif code in {400, 401, 403, 409, 422}:
                    result.put(PermanentTodoistError("todoist_request_rejected"))
                else:
                    result.put(RetryableTodoistError("todoist_transport_failed"))
            except (ValueError, UnicodeError):
                result.put(RetryableTodoistError("todoist_invalid_response"))
            except RetryableTodoistError as exc:
                result.put(exc)
            except Exception:
                # Transport exception strings can contain URLs, headers or
                # provider response bodies. Do not propagate any of them.
                result.put(RetryableTodoistError("todoist_transport_failed"))
            finally:
                _TRANSPORT_SLOTS.release()

        threading.Thread(target=transport, name="todoist-reminder-http", daemon=True).start()
        try:
            value = result.get(timeout=max(0.001, deadline - time.monotonic()))
        except queue.Empty:
            raise RetryableTodoistError("todoist_timeout_or_busy") from None
        if isinstance(value, BaseException):
            raise value
        return value

    def _identity(self, deadline: float) -> dict[str, str]:
        try:
            user = self._request("GET", "/user", deadline)
        except _NotFound:
            raise PermanentTodoistError("todoist_identity_not_verified") from None
        tz_info = user.get("tz_info")
        return _validate_identity({
            "user_id": user.get("id"),
            "inbox_project_id": user.get("inbox_project_id"),
            "timezone": tz_info.get("timezone") if isinstance(tz_info, dict) else None,
        })

    def identity(self) -> dict[str, str]:
        """Read only the authenticated user's minimal destination identity."""
        return self._identity(time.monotonic() + self.timeout)

    def _verify_identity(self, identity: dict[str, str], deadline: float) -> dict[str, str]:
        expected = _validate_identity(identity)
        if self._identity(deadline) != expected:
            raise PermanentTodoistError("todoist_account_changed")
        return expected

    @staticmethod
    def _receipt(task: Any, plan: dict[str, Any], command_uuid: str, identity: dict[str, str], *, duplicate: bool) -> dict[str, Any]:
        title, due_instant = _validate_plan(plan)
        due = task.get("due") if isinstance(task, dict) else None
        try:
            matches = (
                isinstance(task, dict) and _resource_id(task.get("id"))
                and task.get("content") == title
                and task.get("description") == marker(command_uuid)
                and task.get("project_id") == identity["inbox_project_id"]
                and task.get("user_id", identity["user_id"]) == identity["user_id"]
                and task.get("parent_id") is None and task.get("section_id") is None
                and task.get("is_deleted", False) is False and task.get("checked", False) is False
                and task.get("deadline") is None
                and isinstance(due, dict) and due.get("timezone") == BOGOTA
                and due.get("is_recurring") is False and _instant(due.get("date")) == due_instant
            )
        except (TypeError, ValueError, OverflowError):
            matches = False
        if not matches:
            raise RetryableTodoistError("todoist_task_readback_mismatch")
        return {
            "task_id": task["id"], "duplicate": duplicate,
            "auto_reminder_requested": True,
            # A timed task and a requested default reminder do not prove that
            # a reminder exists, is enabled on this plan, or reached a phone.
            "alert_configured": None,
        }

    def _reconcile(self, plan: dict[str, Any], command_uuid: str, identity: dict[str, str], deadline: float, *, external_id: str | None = None) -> dict[str, Any] | None:
        if external_id is not None:
            if not _resource_id(external_id):
                raise PermanentTodoistError("invalid_external_task_id")
            try:
                task = self._request("GET", "/tasks/" + parse.quote(external_id, safe=""), deadline)
            except _NotFound:
                raise RetryableTodoistError("todoist_known_task_unavailable") from None
            if task.get("id") != external_id:
                raise RetryableTodoistError("todoist_task_readback_mismatch")
            return self._receipt(task, plan, command_uuid, identity, duplicate=True)
        matches: dict[str, dict[str, Any]] = {}
        cursor = None
        cursors: set[str] = set()
        for _ in range(MAX_PAGES):
            params = {"project_id": identity["inbox_project_id"], "limit": PAGE_SIZE}
            if cursor is not None:
                params["cursor"] = cursor
            try:
                page = self._request("GET", "/tasks?" + parse.urlencode(params), deadline)
            except _NotFound:
                raise RetryableTodoistError("todoist_inbox_unavailable") from None
            rows = page.get("results")
            if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
                raise RetryableTodoistError("todoist_invalid_page")
            for task in rows:
                if not isinstance(task, dict):
                    raise RetryableTodoistError("todoist_invalid_page")
                if task.get("description") == marker(command_uuid):
                    if not _resource_id(task.get("id")):
                        raise RetryableTodoistError("todoist_task_readback_mismatch")
                    matches[task["id"]] = task
            cursor = page.get("next_cursor")
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or cursor in cursors:
                raise RetryableTodoistError("todoist_invalid_cursor")
            cursors.add(cursor)
        else:
            raise RetryableTodoistError("todoist_reconciliation_page_limit")
        if len(matches) > 1:
            raise RetryableTodoistError("todoist_multiple_matching_tasks")
        if not matches:
            return None
        return self._receipt(next(iter(matches.values())), plan, command_uuid, identity, duplicate=True)

    def reconcile(self, plan: dict[str, Any], command_uuid: str, identity: dict[str, str], external_id: str | None = None) -> dict[str, Any] | None:
        """Read-only recovery; a known missing/changed task never permits POST."""
        _validate_plan(plan)
        _uuid(command_uuid)
        deadline = time.monotonic() + self.timeout
        expected = self._verify_identity(identity, deadline)
        return self._reconcile(plan, command_uuid, expected, deadline, external_id=external_id)

    def create_or_reconcile(self, plan: dict[str, Any], command_uuid: str, temp_id: str, identity: dict[str, str], external_id: str | None = None, *, on_external_id: Callable[[str], None] | None = None) -> dict[str, Any]:
        """Use one persisted Sync command, then require exact task readback.

        ``on_external_id(task_id)`` lets the caller durably record the provider
        mapping before a potentially failing GET. Callback failure propagates;
        a subsequent attempt must still use the original command UUID.
        """
        title, due_instant = _validate_plan(plan)
        _uuid(command_uuid)
        _uuid(temp_id)
        deadline = time.monotonic() + self.timeout
        expected = self._verify_identity(identity, deadline)
        previous = self._reconcile(plan, command_uuid, expected, deadline, external_id=external_id)
        if previous is not None:
            if on_external_id:
                on_external_id(previous["task_id"])
            return previous
        # Identity/pagination can take time. An elapsed schedule permits only
        # recovery of an existing task; it must never dispatch a new command.
        if due_instant <= dispatch_now():
            raise PermanentTodoistError("todoist_due_elapsed_before_dispatch")
        command = {
            "type": "item_add", "uuid": command_uuid, "temp_id": temp_id,
            "args": {
                "content": title, "description": marker(command_uuid),
                "project_id": expected["inbox_project_id"],
                "due": {"date": due_instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "timezone": BOGOTA, "is_recurring": False},
                "auto_reminder": True, "auto_parse_labels": False,
            },
        }
        try:
            sync = self._request("POST", "/sync", deadline, form={"commands": json.dumps([command], ensure_ascii=False, separators=(",", ":"))})
        except _NotFound:
            raise PermanentTodoistError("todoist_sync_unavailable") from None
        statuses = sync.get("sync_status")
        status = statuses.get(command_uuid) if isinstance(statuses, dict) else None
        if status != "ok":
            if isinstance(status, dict) and status.get("http_code") in {400, 401, 403, 404, 409, 422}:
                raise PermanentTodoistError("todoist_command_rejected")
            raise RetryableTodoistError("todoist_command_unconfirmed")
        mapping = sync.get("temp_id_mapping")
        task_id = mapping.get(temp_id) if isinstance(mapping, dict) else None
        if task_id is not None and not _resource_id(task_id):
            raise RetryableTodoistError("todoist_invalid_task_mapping")
        if task_id is not None and on_external_id:
            on_external_id(task_id)
        receipt = self._reconcile(plan, command_uuid, expected, deadline, external_id=task_id)
        if receipt is None:
            raise RetryableTodoistError("todoist_saved_task_not_verified")
        receipt["duplicate"] = False
        if task_id is None and on_external_id:
            on_external_id(receipt["task_id"])
        return receipt


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
