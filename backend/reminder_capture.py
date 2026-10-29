"""Durable, single-purpose Reminder -> structured interpretation -> Todoist.

Per-request OS locks cover network I/O, never the server's global execution
lock or a SQLite transaction. The OS releases a lock on a crash; frozen plans,
command UUIDs, account binding and receipts survive in the existing ledger.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import stat
from typing import Any
import uuid

import reminder_ai
from todoist_reminders import TodoistGateway, RetryableTodoistError, PermanentTodoistError

DOMAIN = "aura.reminder_capture"


class ReminderRetryable(RuntimeError):
    """No authoritative receipt yet; retain original outbox payload for retry."""


class ReminderConflict(RuntimeError):
    pass


def init_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS reminder_operation_ledger (
            request_id TEXT PRIMARY KEY,
            payload_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            command_uuid TEXT NOT NULL UNIQUE,
            temp_id TEXT NOT NULL UNIQUE,
            plan_json TEXT,
            identity_json TEXT,
            task_id TEXT,
            response_json TEXT,
            updated_at TEXT NOT NULL
        )""")


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat()


def _update(path: Path, request_id: str, **fields: Any) -> None:
    fields["updated_at"] = _timestamp()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE reminder_operation_ledger SET "
            + ", ".join(key + " = ?" for key in fields) + " WHERE request_id = ?",
            (*fields.values(), request_id),
        )


@contextmanager
def _request_lock(path: Path, request_id: str):
    directory = path.with_suffix(".reminder-locks")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = hashlib.sha256(request_id.encode()).hexdigest() + ".lock"
    with (directory / filename).open("a+b") as lock:
        (directory / filename).chmod(0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReminderRetryable("reminder_in_progress") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _token(path: Path | None) -> str:
    try:
        if path is None or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("private credential file required")
        value = path.read_text(encoding="utf-8").strip()
        if not value or len(value) > 4096 or any(c.isspace() for c in value):
            raise ValueError("invalid credential")
        return value
    except (OSError, ValueError, UnicodeError):
        raise ReminderRetryable("reminder_configuration_unavailable") from None


def _no_write(payload: dict, *, rejected: bool = False, question: str | None = None) -> dict:
    return {
        "status": "rejected" if rejected else "needs_input",
        "dry_run": False, "write_committed": False,
        "request_id": payload["request_id"], "domain": DOMAIN,
        "display_message": "No creé el recordatorio · " + (question or "indica una tarea con fecha y hora claras en Bogotá"),
        "question": question,
        "gates_missing": [],
        "plan": {"would_write": False, "side_effects": [], "notes": "No external write dispatched."},
    }


def _saved(payload: dict, plan: dict, receipt: dict) -> dict:
    title = " ".join(plan["title"].split())[:96]
    return {
        "status": "committed", "dry_run": False, "write_committed": True,
        "request_id": payload["request_id"], "domain": DOMAIN,
        "display_message": f"Guardado en Todoist ✅ · {title} · {plan['due']['display']} · alertas pendientes de verificar",
        "question": None, "duplicate": bool(receipt.get("duplicate")),
        "interpreted_due": plan["due"],
        "external_ids": {"todoist_task_id": receipt["task_id"]},
        "notification_verified": False, "delivery_status": "pending_verification",
        "auto_reminder_requested": True, "alert_configured": None,
        "gates_missing": [],
        "plan": {"would_write": True, "side_effects": ["todoist.task.write"],
                 "notes": "Inbox task and exact intended task time read back. Default auto-reminder requested; alert configuration and phone delivery unverified."},
    }


def execute(payload: dict, cfg: Any, *, now: Any) -> dict:
    """Called only after the server's exact Reminder route/authority checks."""
    request_id = payload["request_id"]
    binding = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    init_db(cfg.ledger_path)
    with _request_lock(cfg.ledger_path, request_id):
        with sqlite3.connect(cfg.ledger_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM reminder_operation_ledger WHERE request_id = ?", (request_id,)).fetchone()
            if row is not None and row["payload_hash"] != binding:
                raise ReminderConflict("request_id_conflict")
            if row is None:
                conn.execute("""INSERT INTO reminder_operation_ledger
                    (request_id,payload_hash,status,command_uuid,temp_id,updated_at)
                    VALUES (?,?,'interpreting',?,?,?)""", (request_id, binding, str(uuid.uuid4()), str(uuid.uuid4()), _timestamp()))
                row = conn.execute("SELECT * FROM reminder_operation_ledger WHERE request_id = ?", (request_id,)).fetchone()
            operation = dict(row)
        if operation["response_json"]:
            result = json.loads(operation["response_json"])
            if result.get("write_committed"):
                result.update(status="duplicate", duplicate=True)
            return result

        # Missing server credentials are retryable configuration gates. They are
        # never sourced from a desktop connector or another process environment.
        plan = json.loads(operation["plan_json"]) if operation["plan_json"] else None
        if plan is None:
            try:
                reminder_ai.validate_capture_timestamp(payload.get("created_at"), now())
            except ValueError:
                response = _no_write(payload, question="Necesito la fecha original de captura válida con zona horaria.")
                _update(cfg.ledger_path, request_id, status="terminal", response_json=json.dumps(response, ensure_ascii=False))
                return response
            if cfg.reminder_provider != "openai":
                raise ReminderRetryable("reminder_provider_not_configured")
            api_key = _token(cfg.reminder_openai_key_file)
            try:
                proposal = reminder_ai.interpret(
                    payload["capture"]["text"], payload.get("created_at"),
                    api_key=api_key, model=cfg.reminder_model, timeout=cfg.reminder_ai_timeout,
                )
                validated = reminder_ai.validate(proposal, payload.get("created_at"), now())
            except reminder_ai.InterpretationUnavailable as exc:
                if str(exc) in {"interpreter_refused", "interpreter_incomplete", "interpreter_invalid_output", "interpreter_invalid_schema", "invalid_capture_text"}:
                    response = _no_write(payload, question="No pude interpretar la captura completa. Indica una sola tarea con fecha y hora claras en Bogotá.")
                    _update(cfg.ledger_path, request_id, status="terminal", response_json=json.dumps(response, ensure_ascii=False))
                    return response
                raise ReminderRetryable("reminder_interpretation_unavailable") from None
            if validated["status"] != "ready":
                response = _no_write(payload, rejected=validated["status"] == "unsupported", question=validated.get("question"))
                _update(cfg.ledger_path, request_id, status="terminal", response_json=json.dumps(response, ensure_ascii=False))
                return response
            plan = {"title": validated["title"], "due": validated["due"]}
            # This commit precedes even the read-only Todoist preflight. Retrying
            # must reuse the exact plan and must never re-anchor a relative date.
            _update(cfg.ledger_path, request_id, status="ready", plan_json=json.dumps(plan, ensure_ascii=False))
            operation["status"] = "ready"

        todoist_token = _token(cfg.reminder_todoist_token_file)
        gateway = TodoistGateway(todoist_token, timeout=cfg.reminder_todoist_timeout)
        identity = json.loads(operation["identity_json"]) if operation["identity_json"] else None
        dispatched = operation["status"] in {"writing", "uncertain"}
        try:
            if identity is None:
                identity = gateway.identity()
                _update(cfg.ledger_path, request_id, identity_json=json.dumps(identity))
            was_dispatched = operation["status"] in {"writing", "uncertain"}
            if was_dispatched:
                # Reconcile even after task time elapsed. A missing active task
                # does not prove a previous POST failed (it may be completed).
                receipt = gateway.reconcile(plan, operation["command_uuid"], identity, external_id=operation["task_id"])
                if receipt is not None:
                    response = _saved(payload, plan, receipt)
                    _update(cfg.ledger_path, request_id, status="committed", task_id=receipt["task_id"], response_json=json.dumps(response, ensure_ascii=False))
                    return response
            if datetime.fromisoformat(plan["due"]["start"]) <= now():
                if was_dispatched:
                    raise ReminderRetryable("reminder_elapsed_requires_reconciliation")
                response = _no_write(payload, question="La hora ya pasó. ¿Para cuándo lo programo en Bogotá?")
                _update(cfg.ledger_path, request_id, status="terminal", response_json=json.dumps(response, ensure_ascii=False))
                return response
            # Commit intent before any POST. The same UUID is reused after every
            # timeout/crash; neither a retry nor a lost ack creates a new command.
            _update(cfg.ledger_path, request_id, status="writing")
            dispatched = True
            receipt = gateway.create_or_reconcile(
                plan, operation["command_uuid"], operation["temp_id"], identity,
                external_id=operation["task_id"],
                on_external_id=lambda task_id: _update(cfg.ledger_path, request_id, task_id=task_id),
            )
        except (RetryableTodoistError, PermanentTodoistError) as exc:
            # The gateway can positively attest this first call stopped before
            # POST. Prior uncertain attempts must remain uncertain even then.
            if isinstance(exc, PermanentTodoistError) and str(exc) == "todoist_due_elapsed_before_dispatch" and not was_dispatched:
                response = _no_write(payload, question="La hora ya pasó. ¿Para cuándo lo programo en Bogotá?")
                _update(cfg.ledger_path, request_id, status="terminal", response_json=json.dumps(response, ensure_ascii=False))
                return response
            _update(cfg.ledger_path, request_id, status="uncertain" if dispatched else "ready")
            raise ReminderRetryable("reminder_receipt_unverified") from None
        response = _saved(payload, plan, receipt)
        _update(cfg.ledger_path, request_id, status="committed", task_id=receipt["task_id"], response_json=json.dumps(response, ensure_ascii=False))
        return response
