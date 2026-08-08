#!/usr/bin/env python3
"""Hermes mobile-capture v1 synchronous BFF.

A small synchronous server for Watch/iPhone capture:
- verifies HMAC V2: HMAC_SHA256(secret, f"{timestamp}.{raw_body}")
- validates the mobile_capture.v1 envelope
- stores an idempotency ledger in SQLite
- returns short JSON immediately to the client
- permits only explicitly allowlisted server-side write adapters

This is intentionally separate from Hermes generic webhook subscriptions because
the current webhook adapter returns HTTP 202 immediately and runs the agent in
background. The native Watch app needs a synchronous response for good UX.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
DEFAULT_SECRET_FILE = DEFAULT_HERMES_HOME / "mobile-capture-v1-secret.txt"
DEFAULT_LEDGER_PATH = Path(__file__).resolve().parent / "data" / "mobile_capture_ledger.sqlite"
REPLAY_TOLERANCE_SECONDS = 300
MAX_BODY_BYTES = 64 * 1024
BOGOTA = ZoneInfo("America/Bogota")
CAPTURE_EXECUTION_LOCK = threading.Lock()
SUPPORTED_WRITE_DOMAINS = frozenset({"aura.grocery_capture"})

SPANISH_HOURS = {
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
}


@dataclass(frozen=True)
class Config:
    secret: bytes
    ledger_path: Path
    host: str
    port: int
    write_enabled: bool = False
    write_domains: frozenset[str] = frozenset()
    aura_helper: Path | None = None


class WriteExecutionError(RuntimeError):
    pass


def load_secret(path: Path) -> bytes:
    secret = path.read_text(encoding="utf-8").strip()
    if not secret:
        raise RuntimeError(f"empty secret file: {path}")
    return secret.encode("utf-8")


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.parent.chmod(0o700)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mobile_capture_ledger (
                request_id TEXT PRIMARY KEY,
                payload_hash TEXT NOT NULL,
                domain TEXT NOT NULL,
                status TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    path.chmod(0o600)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def json_response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def verify_hmac_v2(headers: Any, raw_body: bytes, secret: bytes) -> tuple[bool, str]:
    sig = headers.get("X-Webhook-Signature-V2", "")
    ts_raw = headers.get("X-Webhook-Timestamp", "")
    if not sig:
        return False, "missing X-Webhook-Signature-V2"
    if not ts_raw:
        return False, "missing X-Webhook-Timestamp"
    try:
        ts = int(ts_raw)
    except ValueError:
        return False, "invalid timestamp"
    if abs(int(time.time()) - ts) > REPLAY_TOLERANCE_SECONDS:
        return False, "timestamp outside replay window"
    expected = hmac.new(secret, ts_raw.encode("utf-8") + b"." + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False, "invalid signature"
    return True, "ok"


def canonical_domain(payload: dict[str, Any]) -> tuple[str, str, str]:
    route = payload.get("route") or {}
    agent = str(route.get("agent") or "argos").strip().lower()
    intent = str(route.get("intent") or "general_capture").strip().lower()
    domain = str(route.get("domain") or "").strip().lower()
    if domain:
        return domain, agent, intent
    mapping = {
        ("megan", "expense"): "megan.expense_capture",
        ("megan", "expense_capture"): "megan.expense_capture",
        ("aura", "reminder"): "aura.reminder_capture",
        ("aura", "reminder_capture"): "aura.reminder_capture",
        ("aura", "grocery"): "aura.grocery_capture",
        ("aura", "grocery_capture"): "aura.grocery_capture",
        ("aura", "home_action"): "aura.home_action",
        ("aura", "general_life_capture"): "aura.general_life_capture",
        ("argos", "general_capture"): "argos.general_capture",
        ("argos", "agent_status"): "argos.agent_status",
        ("pipo", "coding_task"): "pipo.coding_task_capture",
        ("atenea", "research"): "atenea.research_capture",
        ("horacio", "design_brief"): "horacio.design_brief_capture",
    }
    return mapping.get((agent, intent), f"{agent}.{intent}"), agent, intent


def parse_amount_cop(text: str) -> int | None:
    normalized = text.lower().replace("$", " ")
    match = re.search(r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*(mil|k)?", normalized)
    if not match:
        return None
    number = match.group(1)
    suffix = match.group(2)
    if suffix in {"mil", "k"} and not re.search(r"[.,]\d{3}", number):
        try:
            return int(float(number.replace(",", ".")) * 1000)
        except ValueError:
            return None
    digits = re.sub(r"[^0-9]", "", number)
    return int(digits) if digits else None


def parse_created_at(payload: dict[str, Any]) -> datetime:
    raw = str(payload.get("created_at") or "")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(BOGOTA)
        except ValueError:
            pass
    return datetime.now(BOGOTA)


def parse_spanish_due(text: str, base: datetime) -> dict[str, Any] | None:
    t = text.lower()
    due = None
    if "pasado mañana" in t:
        due = base + timedelta(days=2)
    elif "mañana" in t:
        due = base + timedelta(days=1)
    elif "hoy" in t:
        due = base
    elif "en media hora" in t:
        due = base + timedelta(minutes=30)
    else:
        m_rel = re.search(r"en\s+(\d+|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+min", t)
        if m_rel:
            val = m_rel.group(1)
            minutes = int(val) if val.isdigit() else SPANISH_HOURS.get(val, 0)
            due = base + timedelta(minutes=minutes)
    if due is None:
        return None

    hour = None
    minute = 0
    meridiem = None
    m_clock = re.search(r"(?:a\s+las\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?|am|pm)?", t)
    m_words = re.search(r"(?:a\s+las\s+)(una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce)\s*(a\.?m\.?|p\.?m\.?|am|pm)?", t)
    if m_words:
        hour = SPANISH_HOURS[m_words.group(1)]
        meridiem = (m_words.group(2) or "").replace(".", "")
    elif m_clock:
        candidate = int(m_clock.group(1))
        # avoid reading dates like 2026 as time
        if 0 <= candidate <= 23:
            hour = candidate
            minute = int(m_clock.group(2) or 0)
            meridiem = (m_clock.group(3) or "").replace(".", "")
    if hour is not None:
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        due = due.replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        due = due.replace(second=0, microsecond=0)
    return {
        "start": due.isoformat(),
        "timezone": "America/Bogota",
        "display": due.strftime("%Y-%m-%d %I:%M %p America/Bogota"),
    }


def plan_capture(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = str(payload.get("request_id") or "")
    domain, agent, intent = canonical_domain(payload)
    capture = payload.get("capture") or {}
    text = str(capture.get("text") or "").strip()

    # Planning is always side-effect free. execute_capture may separately invoke
    # an exact server-allowlisted adapter; client context never grants authority.
    base: dict[str, Any] = {
        "status": "accepted",
        "dry_run": True,
        "write_committed": False,
        "request_id": request_id,
        "domain": domain,
        "display_message": "Captura validada · dry-run ✅",
        "question": None,
        "plan": {"side_effects": [], "would_write": False, "notes": "Planning response; no external write committed."},
        "gates_missing": [
            "server domain allowlist",
            "external write adapter",
        ],
    }
    if not text:
        base.update(status="needs_confirmation", display_message="No entendí · intenta otra vez", question="¿Qué quieres capturar?")
        return base

    lowered = text.lower()
    if "ignora reglas" in lowered or "crea categoría" in lowered or "salta" in lowered:
        base.update(status="rejected", display_message="No registré: regla insegura")
        base["plan"]["notes"] = "Rejected prompt-injection/safety-bypass style input."
        return base

    if domain == "megan.expense_capture":
        amount = parse_amount_cop(text)
        is_card = any(token in lowered for token in [" fp ", "tc1", "tc2", "tc3", "futuro pago", "tarjeta"])
        if amount is None:
            base.update(status="needs_confirmation", display_message="Falta monto", question="¿Cuánto fue el gasto?")
            return base
        if "tarjeta" in lowered and not any(token in lowered for token in ["tc1", "tc2", "tc3"]):
            base.update(status="needs_confirmation", display_message="¿TC1, TC2 o TC3?", question="¿Con qué tarjeta fue: TC1, TC2 o TC3?")
            return base
        base["display_message"] = f"Dry-run Megan ${amount:,} COP".replace(",", ".")
        base["plan"] = {
            "side_effects": ["firefly.plan_only"],
            "would_write": False,
            "amount_cop": amount,
            "transaction_kind": "fp_card_purchase" if is_card else "cash_expense",
            "notes": "Would query Firefly live for existing account/category/budget/tags before any write.",
        }
        if is_card:
            base["plan"]["expected_movements"] = 2
        return base

    if domain == "aura.reminder_capture":
        due = parse_spanish_due(text, parse_created_at(payload))
        if due:
            base["display_message"] = "Recordatorio dry-run ✅"
            base["interpreted_due"] = due
            base["plan"] = {
                "side_effects": ["notion.task.plan_only", "google_calendar.plan_only"],
                "would_write": False,
                "notes": "Would create/update Notion Task first; Calendar is fail-soft.",
            }
        else:
            base["display_message"] = "Tarea sin fecha · dry-run ✅"
            base["plan"] = {
                "side_effects": ["notion.task.plan_only"],
                "would_write": False,
                "notes": "No due date parsed; would create unscheduled Task or ask if date required.",
            }
        return base

    if domain == "aura.grocery_capture":
        base["display_message"] = "Mercado dry-run ✅"
        base["plan"] = {
            "side_effects": ["notion.official_grocery_list.plan_only"],
            "would_write": False,
            "notes": "Would update official grocery list; unchecked means missing.",
        }
        return base

    if domain == "aura.home_action":
        sensitive = any(word in lowered for word in ["puerta", "cerradura", "alarma"])
        if sensitive:
            base.update(status="needs_confirmation", display_message="Confirma en iPhone", question="Esta acción de casa es sensible. ¿Confirmas desde iPhone?")
        else:
            base["display_message"] = "Casa dry-run ✅"
        base["plan"] = {
            "side_effects": ["homeassistant.plan_only"],
            "would_write": False,
            "notes": "Would execute only if target/action are clear and safe.",
        }
        return base

    base["display_message"] = "Ruta dry-run ✅"
    return base


def client_requests_write(payload: dict[str, Any]) -> bool:
    context = payload.get("context") or {}
    return context.get("dry_run") is False and context.get("allow_write") is True


def write_is_authorized(payload: dict[str, Any], cfg: Config) -> bool:
    domain, _, _ = canonical_domain(payload)
    route = payload.get("route") or {}
    return (
        client_requests_write(payload)
        and cfg.write_enabled
        and route.get("agent") == "aura"
        and route.get("intent") == "grocery"
        and domain in SUPPORTED_WRITE_DOMAINS
        and domain in cfg.write_domains
    )


def run_aura_helper(
    payload: dict[str, Any],
    cfg: Config,
    *,
    dry_run: bool,
    text_override: str | None = None,
) -> dict[str, Any]:
    helper = cfg.aura_helper
    if helper is None or not helper.is_file():
        raise WriteExecutionError("aura_helper_unavailable")
    capture = payload.get("capture") or {}
    helper_payload = {
        "text": text_override or str(capture.get("text") or "").strip(),
        "request_id": str(payload.get("request_id") or ""),
    }
    command = [
        sys.executable,
        str(helper),
        "--payload-file",
        "-",
        "--no-notify",
        "--no-ai-title",
    ]
    if dry_run:
        command.append("--dry-run")
    try:
        process = subprocess.run(
            command,
            input=json.dumps(helper_payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise WriteExecutionError("aura_helper_failed") from error
    try:
        result = json.loads(process.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise WriteExecutionError("aura_helper_invalid_response") from error
    if process.returncode != 0 or result.get("ok") is not True:
        raise WriteExecutionError("aura_helper_rejected")
    return result


def execute_capture(payload: dict[str, Any], cfg: Config) -> dict[str, Any]:
    planned = plan_capture(payload)
    if not write_is_authorized(payload, cfg):
        return planned

    request_id = str(payload.get("request_id") or "")
    domain, _, _ = canonical_domain(payload)
    if domain != "aura.grocery_capture":
        return planned

    # The route is not enough to authorize a side effect. The deterministic
    # helper must independently classify the dictation as a grocery operation.
    capture_text = str((payload.get("capture") or {}).get("text") or "").strip()
    preflight = run_aura_helper(payload, cfg, dry_run=True)
    helper_text = capture_text
    if preflight.get("intent") in {"task_unscheduled", "note"} and not re.search(
        r"\b(anota|guarda|idea|gasto|pague|pagué|compre|compré|enciende|apaga|puerta|alarma)\b|\d[\d.,]*\s*(mil|cop|pesos)",
        capture_text.lower(),
    ):
        # The dedicated Mercado surface commonly dictates a bare noun such as
        # "leche". Give the existing Aura helper the missing route context.
        helper_text = f"falta {capture_text}"
        preflight = run_aura_helper(payload, cfg, dry_run=True, text_override=helper_text)
    if preflight.get("intent") not in {"grocery", "grocery_done"}:
        planned.update(
            status="needs_confirmation",
            display_message="No parece un artículo de mercado · no cambié nada",
            question="¿Qué artículo quieres agregar o marcar como comprado?",
        )
        return planned

    committed = run_aura_helper(payload, cfg, dry_run=False, text_override=helper_text)
    if committed.get("intent") not in {"grocery", "grocery_done"}:
        raise WriteExecutionError("aura_helper_domain_mismatch")
    if not committed.get("block_id") and not committed.get("duplicate"):
        raise WriteExecutionError("aura_helper_missing_external_id")

    item = str(committed.get("item") or committed.get("title") or "artículo")[:160]
    action = "comprado" if committed.get("intent") == "grocery_done" else "faltante"
    return {
        "status": "committed",
        "dry_run": False,
        "write_committed": True,
        "request_id": request_id,
        "domain": domain,
        "display_message": f"Mercado actualizado ✅ · {item} ({action})",
        "question": None,
        "duplicate": bool(committed.get("duplicate", False)),
        "plan": {
            "side_effects": ["notion.official_grocery_list.write"],
            "would_write": True,
            "notes": "Committed by server-allowlisted Aura grocery adapter.",
        },
        "external_ids": {"notion_block_id": committed.get("block_id")},
        "gates_missing": [],
    }


def validate_payload(payload: Any, header_request_id: str) -> tuple[bool, int, dict[str, Any]]:
    if not isinstance(payload, dict):
        return False, HTTPStatus.BAD_REQUEST, {"status": "rejected", "error": "payload must be object"}
    if payload.get("event_type") != "mobile_capture.v1":
        return False, HTTPStatus.OK, {"status": "ignored", "event": payload.get("event_type", "unknown")}
    if payload.get("schema_version") != 1:
        return False, HTTPStatus.BAD_REQUEST, {"status": "rejected", "error": "unsupported schema_version"}
    request_id = str(payload.get("request_id") or "")
    if not request_id:
        return False, HTTPStatus.BAD_REQUEST, {"status": "rejected", "error": "missing request_id"}
    if not header_request_id:
        return False, HTTPStatus.BAD_REQUEST, {"status": "rejected", "error": "missing X-Request-ID"}
    if header_request_id != request_id:
        return False, HTTPStatus.CONFLICT, {"status": "rejected", "error": "X-Request-ID mismatch"}
    capture = payload.get("capture") or {}
    if not str(capture.get("text") or "").strip():
        return True, HTTPStatus.OK, plan_capture(payload)
    return True, HTTPStatus.OK, {}


class MobileCaptureHandler(BaseHTTPRequestHandler):
    server_version = "HermesMobileCaptureStaging/0.1"

    @property
    def cfg(self) -> Config:
        return self.server.cfg  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            enabled_domains = sorted(self.cfg.write_domains & SUPPORTED_WRITE_DOMAINS) if self.cfg.write_enabled else []
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "service": "mobile-capture-v1-staging",
                    "mode": "allowlisted-write" if enabled_domains else "dry-run",
                    "write_domains": enabled_domains,
                },
            )
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/webhooks/mobile-capture-v1":
            json_response(self, HTTPStatus.NOT_FOUND, {"error": "unknown route"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > MAX_BODY_BYTES:
            json_response(self, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"status": "rejected", "error": "invalid body size"})
            return
        raw = self.rfile.read(length)
        ok, reason = verify_hmac_v2(self.headers, raw, self.cfg.secret)
        if not ok:
            json_response(self, HTTPStatus.UNAUTHORIZED, {"status": "rejected", "error": reason})
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            json_response(self, HTTPStatus.BAD_REQUEST, {"status": "rejected", "error": "invalid json"})
            return
        valid, status, response = validate_payload(payload, self.headers.get("X-Request-ID", ""))
        if not valid:
            json_response(self, status, response)
            return

        request_id = str(payload.get("request_id"))
        payload_hash = hashlib.sha256(raw).hexdigest()
        domain, _, _ = canonical_domain(payload)
        try:
            # The service runs as one process. Serialize the ledger decision and
            # adapter execution so same-ID requests cannot race the external
            # helper before either idempotency record is durable.
            with CAPTURE_EXECUTION_LOCK:
                # Defense-in-depth: tests or operators may remove the SQLite
                # file while the process is running.
                init_db(self.cfg.ledger_path)
                with sqlite3.connect(self.cfg.ledger_path, timeout=65.0) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute(
                        "SELECT payload_hash, response_json FROM mobile_capture_ledger WHERE request_id = ?",
                        (request_id,),
                    ).fetchone()
                    if row:
                        old_hash, old_response = row
                        if old_hash != payload_hash:
                            json_response(self, HTTPStatus.CONFLICT, {"status": "rejected", "error": "request_id_conflict", "request_id": request_id})
                            return
                        cached = json.loads(old_response)
                        cached["status"] = "duplicate"
                        cached["duplicate"] = True
                        cached["display_message"] = cached.get("display_message") or "Ya estaba enviado ✅"
                        json_response(self, HTTPStatus.OK, cached)
                        return

                    response = response or execute_capture(payload, self.cfg)
                    response.setdefault("request_id", request_id)
                    response.setdefault("domain", domain)
                    ts = now_iso()
                    conn.execute(
                        "INSERT INTO mobile_capture_ledger(request_id, payload_hash, domain, status, response_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (request_id, payload_hash, domain, str(response.get("status", "accepted")), json.dumps(response, ensure_ascii=False), ts, ts),
                    )
                    conn.commit()
        except WriteExecutionError:
            json_response(
                self,
                HTTPStatus.BAD_GATEWAY,
                {
                    "status": "error",
                    "error": "write_adapter_failed",
                    "request_id": request_id,
                    "domain": domain,
                },
            )
            return
        json_response(self, HTTPStatus.OK, response)


def run_server(cfg: Config) -> None:
    init_db(cfg.ledger_path)
    server = ThreadingHTTPServer((cfg.host, cfg.port), MobileCaptureHandler)
    server.cfg = cfg  # type: ignore[attr-defined]
    print(f"mobile-capture-v1 staging server listening on http://{cfg.host}:{cfg.port}")
    server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("MOBILE_CAPTURE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MOBILE_CAPTURE_PORT", "8650")))
    parser.add_argument("--secret-file", type=Path, default=Path(os.getenv("MOBILE_CAPTURE_SECRET_FILE", str(DEFAULT_SECRET_FILE))))
    parser.add_argument("--ledger", type=Path, default=Path(os.getenv("MOBILE_CAPTURE_LEDGER", str(DEFAULT_LEDGER_PATH))))
    parser.add_argument("--write-enabled", action="store_true", default=env_flag("MOBILE_CAPTURE_WRITE_ENABLED"))
    parser.add_argument("--write-domains", default=os.getenv("MOBILE_CAPTURE_WRITE_DOMAINS", ""))
    parser.add_argument("--aura-helper", type=Path, default=Path(os.getenv("MOBILE_CAPTURE_AURA_HELPER", "/root/.hermes/scripts/apple_watch_capture.py")))
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    domains = frozenset(value.strip() for value in args.write_domains.split(",") if value.strip())
    run_server(
        Config(
            secret=load_secret(args.secret_file),
            ledger_path=args.ledger,
            host=args.host,
            port=args.port,
            write_enabled=args.write_enabled,
            write_domains=domains,
            aura_helper=args.aura_helper,
        )
    )
