from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from albert_store import ALBERT_ALLOWED_STATES, AlbertStore

BASE_DIR = Path(__file__).resolve().parent
APP_ENV = (os.environ.get("OPENCLAW_COCKPIT_ENV") or os.environ.get("APP_ENV") or "prod").strip().lower()
if APP_ENV in {"dev", "development"}:
    DATA_DIR = BASE_DIR / "data-dev"
elif APP_ENV in {"test", "testing"}:
    DATA_DIR = BASE_DIR / "data-test"
else:
    APP_ENV = "prod"
    DATA_DIR = BASE_DIR / "data"

CRON_JOBS_FILE = DATA_DIR / "cron_jobs.json"
PERMISSIONS_FILE = DATA_DIR / "permissions_matrix.json"
OFFICE_LAYOUT_FILE = DATA_DIR / "office_layout.json"
AGENT_PROFILES_FILE = DATA_DIR / "agent_profiles.json"
KANBAN_TASKS_FILE = DATA_DIR / "kanban_tasks.json"
KANBAN_SYNC_HEALTH_FILE = DATA_DIR / "kanban_sync_health.json"
CRM_INTERACTIONS_FILE = DATA_DIR / "crm_interactions.json"
CRM_LEAD_STATUS_FILE = DATA_DIR / "crm_lead_status.json"
CRM_LEAD_EVENTS_FILE = DATA_DIR / "crm_lead_events.json"
CRM_LEAD_NOTES_FILE = DATA_DIR / "crm_lead_notes.json"
CRM_FAILED_EVENTS_FILE = DATA_DIR / "crm_failed_events.json"
CRM_FLOW_FILE = DATA_DIR / "crm_flow.json"
CRM_CADENCES_FILE = DATA_DIR / "crm_cadences.json"
CHAT_LINKS_FILE = DATA_DIR / "chat_links.json"
CHAT_LOG_INDEX_FILE = DATA_DIR / "chat_log_index.json"
CHAT_CONVERSATIONS_CACHE_FILE = DATA_DIR / "chat_conversations_cache.json"
AGENDA_EVENTS_FILE = DATA_DIR / "agenda_events.json"
ALBERT_SESSIONS_FILE = DATA_DIR / "albert_sessions.json"
MAX_JOBS = 200
MAX_KANBAN_TASKS = 2000
KANBAN_STATUSES = [
    "Novos Leads",
    "Sem Resposta",
    "Interessado",
    "Quer Agendar",
    "Proposta Enviada",
    "Promessa Pagamento",
    "Parceria Interesse",
    "Parceria Sem Interess",
    "Alunos/Suporte",
]

KANBAN_STATUS_ALIASES = {
    # Legacy board mapping (keeps old cards visible after taxonomy update)
    "Recorrente": "Novos Leads",
    "To do": "Novos Leads",
    "Approved": "Interessado",
    "Doing": "Quer Agendar",
    "Review": "Proposta Enviada",
    "Done": "Alunos/Suporte",
}

AUTO_OUTREACH_STAGE = "Sem Resposta"
CLOSED_STAGE_KEYS = {
    "alunos",
    "alunos suporte",
    "suporte",
    "enrolled",
    "paid",
    "done",
    "fechado",
    "fechados",
    "closed",
    "won",
    "perdido",
    "lost",
    "rejected",
    "parceria sem interess",
    "partnership no interest",
}
AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
DEFAULT_SKILLS = [
    "sessions_list",
    "sessions_history",
    "sessions_send",
    "sessions_spawn",
    "subagents",
    "message",
    "nodes",
    "browser",
    "exec",
]
ACTIVE_WINDOW_MS = 15 * 60 * 1000
TEAM_RECENT_WINDOW_MS = 72 * 60 * 60 * 1000
BACKLOG_ALLOWED_CREATORS = {"dan", "alfred", "po.mission-control"}
MAX_RUN_HISTORY = 20
MAX_OUTPUT_STORE_CHARS = 2000
OUTPUT_SUMMARY_CHARS = 240
OFFICE_MAX_X = 1100
OFFICE_MAX_Y = 700
OFFICE_DEPARTMENTS = [
    "Engenharia & Produto",
    "Marketing & Vendas",
    "Operações",
    "Financeiro & BI",
    "Customer Success",
    "People & Hiring",
    "QA & Compliance",
]
CRM_BASE_URL = os.environ.get("CRM_BASE_URL", "http://127.0.0.1:5000").strip().rstrip("/")
CRM_USER = os.environ.get("CRM_USER", "").strip()
CRM_PASS = os.environ.get("CRM_PASS", "").strip()

VAULT_CANDIDATE_ROOTS = [
    "/root/.openclaw/workspace/BA-Pro-Vault",
    "/root/.openclaw/BA-Pro-Vault",
    "/root/.openclaw/workspace",
]
VAULT_ROOT = Path(
    os.environ.get("OPENCLAW_COCKPIT_VAULT_ROOT", "").strip() or next((p for p in VAULT_CANDIDATE_ROOTS if Path(p).exists()), "/root/.openclaw/workspace")
).resolve()


def _load_crm_auth_from_local_backend_env() -> tuple[str, str]:
    """Fallback for cockpit: reuse CRM creds from local funnel_backend gunicorn env."""
    try:
        for pid_name in os.listdir("/proc"):
            if not pid_name.isdigit():
                continue
            cmdline_path = f"/proc/{pid_name}/cmdline"
            environ_path = f"/proc/{pid_name}/environ"
            try:
                cmdline_raw = Path(cmdline_path).read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="ignore")
            except Exception:
                continue
            if "gunicorn" not in cmdline_raw or "127.0.0.1:5000" not in cmdline_raw:
                continue
            try:
                env_raw = Path(environ_path).read_bytes().split(b"\x00")
            except Exception:
                continue
            env_map: dict[str, str] = {}
            for item in env_raw:
                if not item or b"=" not in item:
                    continue
                k, v = item.split(b"=", 1)
                env_map[k.decode("utf-8", errors="ignore")] = v.decode("utf-8", errors="ignore")
            user = str(env_map.get("CRM_USER", "")).strip()
            pwd = str(env_map.get("CRM_PASS", "")).strip()
            if user and pwd:
                return user, pwd
    except Exception:
        pass
    return "", ""


if not CRM_PASS:
    fallback_user, fallback_pass = _load_crm_auth_from_local_backend_env()
    if fallback_user and fallback_pass:
        CRM_USER = fallback_user
        CRM_PASS = fallback_pass

CRM_ALLOWED_PROXY_PREFIXES = ("api/crm/overview", "api/crm/lead/")
CRM_ENABLE_DEDUP = str(os.environ.get("OPENCLAW_COCKPIT_CRM_DEDUP", "false")).strip().lower() in {"1", "true", "yes", "on"}

CRM_MERGED_MAP: dict[str, list[str]] = {}

def _crm_intelligent_deduplication(parsed: dict) -> dict:
    global CRM_MERGED_MAP
    if not isinstance(parsed, dict) or "leads" not in parsed:
        return parsed
    leads = parsed.get("leads", [])
    if not isinstance(leads, list):
        return parsed

    try:
        leads.sort(key=lambda x: int(x.get("id") or 0), reverse=True)
    except Exception:
        pass

    merged_map = {}
    for lead in leads:
        if not isinstance(lead, dict):
            continue
        email = str(lead.get("email") or "").strip().lower()
        phone = str(lead.get("phone") or "").strip()
        phone_digits = "".join(c for c in phone if c.isdigit())
        
        match_key = email if email else (phone_digits if phone_digits else f"id_{lead.get('id')}")
        if email and email in merged_map:
            match_key = email
        elif phone_digits and phone_digits in merged_map:
            match_key = phone_digits
            
        if match_key not in merged_map:
            lead_copy = lead.copy()
            lead_copy["_merged_ids"] = [str(lead.get("id"))]
            merged_map[match_key] = lead_copy
            if email:
                merged_map[email] = lead_copy
            if phone_digits:
                merged_map[phone_digits] = lead_copy
        else:
            base_lead = merged_map[match_key]
            base_lead["signup_count"] = int(base_lead.get("signup_count") or 1) + int(lead.get("signup_count") or 1)
            lid = str(lead.get("id"))
            if lid not in base_lead["_merged_ids"]:
                base_lead["_merged_ids"].append(lid)

    unique_leads = []
    seen_ids = set()
    CRM_MERGED_MAP.clear()
    for l in merged_map.values():
        lid = str(l.get("id"))
        if lid not in seen_ids:
            seen_ids.add(lid)
            unique_leads.append(l)
            CRM_MERGED_MAP[lid] = l.get("_merged_ids", [])

    parsed["leads"] = unique_leads
    return parsed


OFFICE_ZONE_LAYOUT: dict[str, dict[str, Any]] = {
    "Engenharia & Produto": {
        "centroid": {"x": 165, "y": 180},
        "bounds": {"xMin": 20, "xMax": 320, "yMin": 40, "yMax": 330},
        "theme": "eng",
    },
    "Marketing & Vendas": {
        "centroid": {"x": 470, "y": 180},
        "bounds": {"xMin": 330, "xMax": 610, "yMin": 40, "yMax": 330},
        "theme": "mkt",
    },
    "Operações": {
        "centroid": {"x": 760, "y": 180},
        "bounds": {"xMin": 620, "xMax": 900, "yMin": 40, "yMax": 330},
        "theme": "ops",
    },
    "Financeiro & BI": {
        "centroid": {"x": 1020, "y": 180},
        "bounds": {"xMin": 910, "xMax": 1100, "yMin": 40, "yMax": 330},
        "theme": "fin",
    },
    "Customer Success": {
        "centroid": {"x": 165, "y": 540},
        "bounds": {"xMin": 20, "xMax": 320, "yMin": 350, "yMax": 700},
        "theme": "cs",
    },
    "People & Hiring": {
        "centroid": {"x": 470, "y": 540},
        "bounds": {"xMin": 330, "xMax": 610, "yMin": 350, "yMax": 700},
        "theme": "people",
    },
    "QA & Compliance": {
        "centroid": {"x": 760, "y": 540},
        "bounds": {"xMin": 620, "xMax": 1100, "yMin": 350, "yMax": 700},
        "theme": "qa",
    },
}

app = Flask(__name__)
ALBERT_STORE = AlbertStore(DATA_DIR)
ALBERT_SESSION_LOCK = threading.Lock()
_LAST_KANBAN_AUTO_SYNC_TS = 0.0
_LAST_KANBAN_SYNC_HEALTH: dict[str, Any] = {
    "ok": True,
    "lastSyncAt": None,
    "source": "startup",
    "created": 0,
    "updated": 0,
    "scanned": 0,
    "errors": [],
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ms_to_iso(ms: Any) -> str | None:
    try:
        value = int(ms)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def _ensure_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for p in [CRON_JOBS_FILE, PERMISSIONS_FILE, OFFICE_LAYOUT_FILE, AGENT_PROFILES_FILE, KANBAN_TASKS_FILE, KANBAN_SYNC_HEALTH_FILE, CRM_INTERACTIONS_FILE, CRM_LEAD_STATUS_FILE, CRM_LEAD_EVENTS_FILE, CRM_LEAD_NOTES_FILE, CRM_FLOW_FILE, CHAT_LINKS_FILE, CHAT_LOG_INDEX_FILE, CHAT_CONVERSATIONS_CACHE_FILE, AGENDA_EVENTS_FILE, ALBERT_SESSIONS_FILE]:
        p.parent.mkdir(parents=True, exist_ok=True)
    if not CRON_JOBS_FILE.exists():
        CRON_JOBS_FILE.write_text("[]\n", encoding="utf-8")
    if not PERMISSIONS_FILE.exists():
        PERMISSIONS_FILE.write_text(
            json.dumps({"skills": DEFAULT_SKILLS, "agents": {}}, indent=2) + "\n",
            encoding="utf-8",
        )
    if not OFFICE_LAYOUT_FILE.exists():
        OFFICE_LAYOUT_FILE.write_text(
            json.dumps({"desks": {}}, indent=2) + "\n",
            encoding="utf-8",
        )
    if not AGENT_PROFILES_FILE.exists():
        AGENT_PROFILES_FILE.write_text(
            json.dumps({"agents": {}}, indent=2) + "\n",
            encoding="utf-8",
        )
    if not KANBAN_TASKS_FILE.exists():
        KANBAN_TASKS_FILE.write_text("[]\n", encoding="utf-8")
    if not KANBAN_SYNC_HEALTH_FILE.exists():
        KANBAN_SYNC_HEALTH_FILE.write_text(json.dumps(_LAST_KANBAN_SYNC_HEALTH, indent=2) + "\n", encoding="utf-8")
    if not CRM_INTERACTIONS_FILE.exists():
        CRM_INTERACTIONS_FILE.write_text("[]\n", encoding="utf-8")
    if not CRM_LEAD_STATUS_FILE.exists():
        CRM_LEAD_STATUS_FILE.write_text("{}\n", encoding="utf-8")
    if not CRM_LEAD_EVENTS_FILE.exists():
        CRM_LEAD_EVENTS_FILE.write_text("[]\n", encoding="utf-8")
    if not CRM_LEAD_NOTES_FILE.exists():
        CRM_LEAD_NOTES_FILE.write_text("[]\n", encoding="utf-8")
    if not CRM_FLOW_FILE.exists():
        CRM_FLOW_FILE.write_text("{}\n", encoding="utf-8")
    if not CHAT_LINKS_FILE.exists():
        CHAT_LINKS_FILE.write_text("{}\n", encoding="utf-8")
    if not CHAT_LOG_INDEX_FILE.exists():
        CHAT_LOG_INDEX_FILE.write_text("{}\n", encoding="utf-8")
    if not CHAT_CONVERSATIONS_CACHE_FILE.exists():
        CHAT_CONVERSATIONS_CACHE_FILE.write_text("[]\n", encoding="utf-8")
    if not AGENDA_EVENTS_FILE.exists():
        AGENDA_EVENTS_FILE.write_text("[]\n", encoding="utf-8")
    if not ALBERT_SESSIONS_FILE.exists():
        ALBERT_SESSIONS_FILE.write_text("[]\n", encoding="utf-8")
    ALBERT_STORE.ensure()


def _normalize_run_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(entry.get("status") or "unknown"),
        "startedAt": entry.get("startedAt"),
        "finishedAt": entry.get("finishedAt"),
        "durationMs": entry.get("durationMs"),
        "exitCode": entry.get("exitCode"),
        "outputSummary": str(entry.get("outputSummary") or ""),
        "outputStoredChars": int(entry.get("outputStoredChars") or 0),
        "outputTruncated": bool(entry.get("outputTruncated", False)),
    }


def _normalize_job(job: dict[str, Any], sessions: list[dict[str, Any]] | None = None, sessions_error: str | None = None) -> dict[str, Any]:
    history = job.get("runHistory")
    if not isinstance(history, list):
        history = []

    normalized_history = []
    for item in history[:MAX_RUN_HISTORY]:
        if isinstance(item, dict):
            normalized_history.append(_normalize_run_entry(item))

    schedule_mode = str(job.get("scheduleMode") or "").strip().lower()
    if schedule_mode not in {"every", "at", "cron"}:
        schedule_mode = "cron"

    schedule_value = str(job.get("scheduleValue") or "").strip()
    legacy_schedule = str(job.get("schedule") or "").strip()
    if not schedule_value:
        schedule_value = legacy_schedule

    target_agent = str(job.get("targetAgentId") or "").strip()
    tools_profile_id = str(job.get("toolsProfileId") or "").strip()
    message_payload = str(job.get("message") or "").strip()

    effective_policy = job.get("effectivePolicy")
    if not isinstance(effective_policy, dict):
        effective_policy = {
            "profileId": tools_profile_id or None,
            "label": tools_profile_id or ("agent:" + target_agent if target_agent else "default"),
            "allowedSkills": [],
            "enforcedBy": "app-policy",
            "runtimeSandbox": False,
        }

    job["runHistory"] = normalized_history
    job["lastRunAt"] = job.get("lastRunAt")
    job["lastExitCode"] = job.get("lastExitCode")
    job["lastOutput"] = str(job.get("lastOutput") or "")
    job["source"] = str(job.get("source") or "local")
    job["scheduleMode"] = schedule_mode
    job["scheduleValue"] = schedule_value
    job["schedule"] = schedule_value or legacy_schedule
    job["nextRunAt"] = job.get("nextRunAt")
    job["targetAgentId"] = target_agent or None
    job["toolsProfileId"] = tools_profile_id or None
    job["message"] = message_payload
    job["effectivePolicy"] = effective_policy
    job.update(_cron_job_session_preflight(job, sessions=sessions, sessions_error=sessions_error))
    return job


def _load_jobs() -> list[dict[str, Any]]:
    _ensure_store()
    raw = CRON_JOBS_FILE.read_text(encoding="utf-8") or "[]"
    jobs = json.loads(raw)
    if not isinstance(jobs, list):
        raise ValueError("Invalid cron jobs storage format")
    return [_normalize_job(job) for job in jobs if isinstance(job, dict)]


def _save_jobs(jobs: list[dict[str, Any]]) -> None:
    _ensure_store()
    CRON_JOBS_FILE.write_text(json.dumps(jobs, indent=2) + "\n", encoding="utf-8")


def _load_permissions() -> dict[str, Any]:
    _ensure_store()
    raw = PERMISSIONS_FILE.read_text(encoding="utf-8")
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise ValueError("Invalid permissions storage format")

    skills = data.get("skills")
    agents = data.get("agents")
    if not isinstance(skills, list):
        skills = list(DEFAULT_SKILLS)
    if not isinstance(agents, dict):
        agents = {}

    normalized_skills = []
    for skill in skills:
        skill_name = str(skill).strip()
        if skill_name and skill_name not in normalized_skills:
            normalized_skills.append(skill_name)

    data["skills"] = normalized_skills or list(DEFAULT_SKILLS)
    data["agents"] = agents
    return data


def _save_permissions(data: dict[str, Any]) -> None:
    _ensure_store()
    PERMISSIONS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _default_department(agent_id: str) -> str:
    if not OFFICE_DEPARTMENTS:
        return "Unassigned"
    idx = sum(ord(ch) for ch in agent_id) % len(OFFICE_DEPARTMENTS)
    return OFFICE_DEPARTMENTS[idx]


def _normalize_department(agent_id: str, department: Any) -> str:
    dept = str(department or "").strip()
    if dept in OFFICE_DEPARTMENTS:
        return dept
    return _default_department(agent_id)


def _short_agent_id(agent_id: str) -> str:
    compact = re.sub(r"[^a-zA-Z0-9]", "", agent_id or "")
    if compact:
        return compact[:6]
    return (agent_id or "agent")[:6]


def _default_display_name(agent_id: str) -> str:
    return f"Agent {_short_agent_id(agent_id)}"


def _default_lifecycle(agent_id: str) -> str:
    aid = str(agent_id or "").strip().lower()
    if aid == "main" or aid.startswith("po.") or aid.startswith("qa.") or aid.startswith("eng."):
        return "persistent"
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", aid):
        return "disposable"
    return "persistent"


def _normalize_profile(agent_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    display = str(profile.get("displayName") or profile.get("alias") or "").strip()
    lifecycle = str(profile.get("lifecycle") or "").strip().lower()
    if lifecycle not in {"persistent", "disposable"}:
        lifecycle = _default_lifecycle(agent_id)
    return {
        "agentId": agent_id,
        "displayName": display or _default_display_name(agent_id),
        "department": _normalize_department(agent_id, profile.get("department")),
        "lifecycle": lifecycle,
        "updatedAt": profile.get("updatedAt") or _utc_now_iso(),
    }


def _load_agent_profiles() -> dict[str, Any]:
    _ensure_store()
    raw = AGENT_PROFILES_FILE.read_text(encoding="utf-8") or "{}"
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid agent profiles storage format")

    agents = data.get("agents")
    if not isinstance(agents, dict):
        agents = {}

    normalized: dict[str, dict[str, Any]] = {}
    for agent_id, profile in agents.items():
        aid = str(agent_id).strip()
        if not AGENT_ID_RE.match(aid) or not isinstance(profile, dict):
            continue
        normalized[aid] = _normalize_profile(aid, profile)

    return {"agents": normalized}


def _save_agent_profiles(data: dict[str, Any]) -> None:
    _ensure_store()
    AGENT_PROFILES_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _ensure_profile(agent_id: str, profiles: dict[str, Any]) -> bool:
    if not AGENT_ID_RE.match(agent_id):
        return False
    agents = profiles.setdefault("agents", {})
    if agent_id in agents:
        return False
    agents[agent_id] = {
        "agentId": agent_id,
        "displayName": _default_display_name(agent_id),
        "department": _default_department(agent_id),
        "lifecycle": _default_lifecycle(agent_id),
        "updatedAt": _utc_now_iso(),
    }
    return True


def _display_name_for(agent_id: str | None, profiles: dict[str, Any]) -> str:
    if not agent_id:
        return "-"
    entry = profiles.get("agents", {}).get(agent_id, {})
    if isinstance(entry, dict):
        name = str(entry.get("displayName") or "").strip()
        if name:
            return name
    return agent_id


def _load_office_layout() -> dict[str, Any]:
    _ensure_store()
    raw = OFFICE_LAYOUT_FILE.read_text(encoding="utf-8") or "{}"
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid office layout storage format")
    desks = data.get("desks")
    if not isinstance(desks, dict):
        desks = {}

    normalized: dict[str, dict[str, Any]] = {}
    for agent_id, desk in desks.items():
        if not isinstance(desk, dict):
            continue
        if not AGENT_ID_RE.match(str(agent_id)):
            continue
        x = int(desk.get("x", 0))
        y = int(desk.get("y", 0))
        dept = str(desk.get("department") or "").strip()
        if dept not in OFFICE_DEPARTMENTS:
            dept = _default_department(str(agent_id))
        normalized[str(agent_id)] = {
            "x": max(0, min(OFFICE_MAX_X, x)),
            "y": max(0, min(OFFICE_MAX_Y, y)),
            "department": dept,
        }

    return {"desks": normalized}


def _save_office_layout(data: dict[str, Any]) -> None:
    _ensure_store()
    OFFICE_LAYOUT_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _load_crm_failed_events() -> list[dict[str, Any]]:
    if not CRM_FAILED_EVENTS_FILE.exists():
        return []
    try:
        data = json.loads(CRM_FAILED_EVENTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _save_crm_failed_events(items: list[dict[str, Any]]) -> None:
    tmp = CRM_FAILED_EVENTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CRM_FAILED_EVENTS_FILE)

def _queue_crm_failed_event(method: str, path: str, payload: Any, error: str) -> None:
    items = _load_crm_failed_events()
    event = {
        "id": os.urandom(8).hex(),
        "method": method,
        "path": path,
        "payload": payload,
        "error": error,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "retries": 0
    }
    items.append(event)
    _save_crm_failed_events(items)


def _load_crm_interactions() -> list[dict[str, Any]]:
    _ensure_store()
    raw = CRM_INTERACTIONS_FILE.read_text(encoding="utf-8") or "[]"
    items = json.loads(raw)
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            lead_id = int(item.get("leadId"))
        except (TypeError, ValueError):
            continue
        if lead_id <= 0:
            continue
        channel = str(item.get("channel") or "").strip().lower()
        if channel not in {"email", "whatsapp"}:
            continue
        normalized.append(
            {
                "id": str(item.get("id") or ""),
                "leadId": lead_id,
                "channel": channel,
                "event_type": str(item.get("event_type") or f"contact_{channel}"),
                "event_at": item.get("event_at") or item.get("createdAt") or _utc_now_iso(),
                "message": str(item.get("message") or ""),
                "createdAt": item.get("createdAt") or _utc_now_iso(),
            }
        )
    return normalized


def _save_crm_interactions(items: list[dict[str, Any]]) -> None:
    _ensure_store()
    CRM_INTERACTIONS_FILE.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")


def _load_crm_lead_status_map() -> dict[str, dict[str, Any]]:
    _ensure_store()
    try:
        raw = CRM_LEAD_STATUS_FILE.read_text(encoding="utf-8") or "{}"
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _save_crm_lead_status_map(status_map: dict[str, dict[str, Any]]) -> None:
    _ensure_store()
    CRM_LEAD_STATUS_FILE.write_text(json.dumps(status_map, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_crm_lead_events() -> list[dict[str, Any]]:
    _ensure_store()
    try:
        raw = CRM_LEAD_EVENTS_FILE.read_text(encoding="utf-8") or "[]"
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        data = []
    return data if isinstance(data, list) else []


def _save_crm_lead_events(items: list[dict[str, Any]]) -> None:
    _ensure_store()
    CRM_LEAD_EVENTS_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_crm_lead_notes() -> list[dict[str, Any]]:
    _ensure_store()
    try:
        raw = CRM_LEAD_NOTES_FILE.read_text(encoding="utf-8") or "[]"
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        data = []
    if not isinstance(data, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            lead_id = int(item.get("leadId"))
        except (TypeError, ValueError):
            continue
        if lead_id <= 0:
            continue

        content = str(item.get("content") or item.get("note") or "").strip()
        if not content:
            continue

        now = _utc_now_iso()
        normalized.append({
            "id": str(item.get("id") or f"lead-note-{int(time.time() * 1000)}-{lead_id}"),
            "leadId": lead_id,
            "content": content[:4000],
            "createdAt": item.get("createdAt") or now,
            "createdBy": str(item.get("createdBy") or "operator"),
            "source": str(item.get("source") or "cockpit"),
        })
    return normalized


def _save_crm_lead_notes(items: list[dict[str, Any]]) -> None:
    _ensure_store()
    CRM_LEAD_NOTES_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalize_crm_flow_step(item: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    message = str(item.get("message") or item.get("text") or "").strip()
    if not message:
        return None

    interval_value = item.get("intervalValue")
    try:
        interval_value_int = int(interval_value)
    except (TypeError, ValueError):
        interval_value_int = 1
    interval_value_int = max(1, min(interval_value_int, 9999))

    interval_unit = str(item.get("intervalUnit") or "minutes").strip().lower()
    if interval_unit not in {"minutes", "hours", "days"}:
        interval_unit = "minutes"

    step_id = str(item.get("id") or f"step-{int(time.time() * 1000)}-{index}").strip() or f"step-{index}"
    return {
        "id": step_id,
        "order": int(index),
        "message": message[:4000],
        "intervalValue": interval_value_int,
        "intervalUnit": interval_unit,
    }


def _default_crm_flow() -> dict[str, Any]:
    return {
        "name": "Fluxo Padrão CRM",
        "updatedAt": None,
        "steps": [],
        "stopOnReply": True,
        "isActive": False,
        "autoEnrollNewLeads": False,
    }


def _flow_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    txt = str(value).strip().lower()
    if txt in {"1", "true", "yes", "sim", "y", "on"}:
        return True
    if txt in {"0", "false", "no", "nao", "não", "n", "off"}:
        return False
    return default


def _normalize_cadence_audience(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raw = {}
    status = str(raw.get("status") or "").strip()[:160]
    label = str(raw.get("label") or "").strip()[:160]
    origin = str(raw.get("origin") or "").strip()[:160]
    return {"status": status, "label": label, "origin": origin}


def _audience_has_any_criteria(audience: dict[str, str]) -> bool:
    return bool(audience.get("status") or audience.get("label") or audience.get("origin"))


def _default_cadence(index: int = 0) -> dict[str, Any]:
    return {
        "id": f"cad-{int(time.time() * 1000)}-{index}",
        "name": f"Cadência {index + 1}",
        "isActive": False,
        "stopWhenReply": True,
        "audience": {"status": "", "label": "", "origin": ""},
        "messages": [],
        "updatedAt": None,
    }


def _normalize_cadence(item: Any, index: int) -> dict[str, Any]:
    base = _default_cadence(index)
    if not isinstance(item, dict):
        return base

    cadence_id = str(item.get("id") or base["id"]).strip() or base["id"]
    name = str(item.get("name") or base["name"]).strip() or base["name"]
    is_active = _flow_bool(item.get("isActive"), False)
    stop_when_reply = _flow_bool(item.get("stopWhenReply"), True)
    audience = _normalize_cadence_audience(item.get("audience"))

    raw_messages = item.get("messages")
    if raw_messages is None:
        raw_messages = item.get("steps")
    messages: list[dict[str, Any]] = []
    if isinstance(raw_messages, list):
        for idx, msg in enumerate(raw_messages):
            normalized = _normalize_crm_flow_step(msg, idx)
            if normalized:
                messages.append(normalized)

    return {
        "id": cadence_id,
        "name": name,
        "isActive": is_active,
        "stopWhenReply": stop_when_reply,
        "audience": audience,
        "messages": messages,
        "updatedAt": item.get("updatedAt"),
    }


def _cadence_validation_errors(cadence: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    audience = _normalize_cadence_audience(cadence.get("audience"))
    if not _audience_has_any_criteria(audience):
        errors.append("Selecione pelo menos 1 critério de audiência.")

    messages = cadence.get("messages")
    if not isinstance(messages, list) or len(messages) < 1:
        errors.append("Cadência precisa ter pelo menos 1 mensagem.")

    return errors


def _default_cadences_store() -> dict[str, Any]:
    return {"version": 3, "updatedAt": None, "cadences": []}


def _migrate_flow_to_cadence_store() -> dict[str, Any]:
    default = _default_cadences_store()
    if not CRM_FLOW_FILE.exists():
        return default

    try:
        raw = CRM_FLOW_FILE.read_text(encoding="utf-8") or "{}"
        raw_data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        raw_data = {}

    if not isinstance(raw_data, dict) or not raw_data:
        return default

    flow = _load_crm_flow()
    cadence = _normalize_cadence({
        "id": "cad-legacy-main",
        "name": flow.get("name") or "Cadência Migrada",
        "isActive": flow.get("isActive"),
        "stopWhenReply": flow.get("stopOnReply"),
        "messages": flow.get("steps") or [],
        "audience": {"status": "", "label": "", "origin": ""},
        "updatedAt": flow.get("updatedAt"),
    }, 0)
    default["cadences"] = [cadence]
    default["updatedAt"] = _utc_now_iso()
    return default


def _load_crm_cadences_store() -> dict[str, Any]:
    _ensure_store()
    try:
        raw = CRM_CADENCES_FILE.read_text(encoding="utf-8") if CRM_CADENCES_FILE.exists() else ""
        data = json.loads(raw) if raw.strip() else {}
    except (OSError, json.JSONDecodeError):
        data = {}

    if not isinstance(data, dict) or not isinstance(data.get("cadences"), list):
        migrated = _migrate_flow_to_cadence_store()
        _save_crm_cadences_store(migrated)
        return migrated

    out = _default_cadences_store()
    out["updatedAt"] = data.get("updatedAt")
    cadences: list[dict[str, Any]] = []
    for idx, item in enumerate(data.get("cadences") or []):
        cadences.append(_normalize_cadence(item, idx))
    out["cadences"] = cadences
    return out


def _save_crm_cadences_store(store: dict[str, Any]) -> dict[str, Any]:
    out = _default_cadences_store()
    cadences_raw = store.get("cadences") if isinstance(store, dict) else []
    cadences: list[dict[str, Any]] = []
    if isinstance(cadences_raw, list):
        for idx, item in enumerate(cadences_raw):
            cadence = _normalize_cadence(item, idx)
            cadence["updatedAt"] = _utc_now_iso()
            cadences.append(cadence)
    out["cadences"] = cadences
    out["updatedAt"] = _utc_now_iso()
    _ensure_store()
    CRM_CADENCES_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def _load_crm_flow() -> dict[str, Any]:
    _ensure_store()
    try:
        raw = CRM_FLOW_FILE.read_text(encoding="utf-8") or "{}"
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        data = {}

    if not isinstance(data, dict):
        data = {}
    default = _default_crm_flow()

    steps_raw = data.get("steps")
    steps: list[dict[str, Any]] = []
    if isinstance(steps_raw, list):
        for idx, item in enumerate(steps_raw):
            normalized = _normalize_crm_flow_step(item, idx)
            if normalized:
                steps.append(normalized)

    return {
        "name": str(data.get("name") or default["name"]),
        "updatedAt": data.get("updatedAt") or default["updatedAt"],
        "steps": steps,
        "stopOnReply": _flow_bool(data.get("stopOnReply"), default["stopOnReply"]),
        "isActive": _flow_bool(data.get("isActive"), default["isActive"]),
        "autoEnrollNewLeads": _flow_bool(data.get("autoEnrollNewLeads"), default["autoEnrollNewLeads"]),
    }


def _save_crm_flow(flow: dict[str, Any]) -> dict[str, Any]:
    normalized = _default_crm_flow()
    normalized["name"] = str(flow.get("name") or normalized["name"]).strip() or normalized["name"]

    steps_raw = flow.get("steps")
    steps: list[dict[str, Any]] = []
    if isinstance(steps_raw, list):
        for idx, item in enumerate(steps_raw):
            normalized_step = _normalize_crm_flow_step(item, idx)
            if normalized_step:
                steps.append(normalized_step)

    normalized["steps"] = steps
    normalized["stopOnReply"] = _flow_bool(flow.get("stopOnReply"), normalized["stopOnReply"])
    normalized["isActive"] = _flow_bool(flow.get("isActive"), normalized["isActive"])
    normalized["autoEnrollNewLeads"] = _flow_bool(flow.get("autoEnrollNewLeads"), normalized["autoEnrollNewLeads"])
    normalized["updatedAt"] = _utc_now_iso()

    _ensure_store()
    CRM_FLOW_FILE.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return normalized


def _bool_like(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    txt = str(value or "").strip().lower()
    return txt in {"1", "true", "yes", "sim", "y", "on"}


def _normalize_tags(value: Any) -> list[str]:
    raw_items: list[str] = []
    if isinstance(value, list):
        raw_items = [str(x or "") for x in value]
    else:
        txt = str(value or "")
        raw_items = re.split(r"[\s,]+", txt)

    tags: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        tag = str(item or "").strip().lstrip("#")
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag[:40])
        if len(tags) >= 30:
            break
    return tags


def _lead_status_from_payload(payload: dict[str, Any]) -> tuple[bool, bool, bool, bool, bool, list[str]]:
    has_group = "inGroup" in payload
    has_email = "emailOpened" in payload
    has_tags = "tags" in payload
    in_group = _bool_like(payload.get("inGroup")) if has_group else False
    email_opened = _bool_like(payload.get("emailOpened")) if has_email else False
    tags = _normalize_tags(payload.get("tags")) if has_tags else []
    return has_group, in_group, has_email, email_opened, has_tags, tags


def _default_desk_position(index: int) -> dict[str, int]:
    col = index % 7
    row = index // 7
    return {"x": 45 + col * 155, "y": 90 + row * 125}


def _department_zone(department: str) -> dict[str, Any]:
    zone = OFFICE_ZONE_LAYOUT.get(department)
    if isinstance(zone, dict):
        return zone
    fallback = OFFICE_DEPARTMENTS[0] if OFFICE_DEPARTMENTS else ""
    return OFFICE_ZONE_LAYOUT.get(fallback, {
        "centroid": {"x": OFFICE_MAX_X // 2, "y": OFFICE_MAX_Y // 2},
        "bounds": {"xMin": 0, "xMax": OFFICE_MAX_X, "yMin": 0, "yMax": OFFICE_MAX_Y},
        "theme": "default",
    })


def _clustered_desk_position(agent_id: str, department: str, slot_index: int = 0) -> dict[str, int]:
    zone = _department_zone(department)
    centroid = zone.get("centroid", {})
    bounds = zone.get("bounds", {})

    cx = int(centroid.get("x", OFFICE_MAX_X // 2))
    cy = int(centroid.get("y", OFFICE_MAX_Y // 2))
    x_min = max(0, int(bounds.get("xMin", 0)))
    x_max = min(OFFICE_MAX_X, int(bounds.get("xMax", OFFICE_MAX_X)))
    y_min = max(0, int(bounds.get("yMin", 0)))
    y_max = min(OFFICE_MAX_Y, int(bounds.get("yMax", OFFICE_MAX_Y)))

    ring = max(0, int(slot_index))
    offsets = [
        (0, 0),
        (64, 0),
        (-64, 0),
        (0, 56),
        (0, -56),
        (74, 56),
        (-74, 56),
        (74, -56),
        (-74, -56),
        (124, 0),
        (-124, 0),
    ]
    base_dx, base_dy = offsets[ring % len(offsets)]

    h = sum((idx + 1) * ord(ch) for idx, ch in enumerate(agent_id))
    jitter_x = (h % 19) - 9
    jitter_y = ((h // 19) % 19) - 9

    x = cx + base_dx + jitter_x
    y = cy + base_dy + jitter_y

    return {
        "x": max(x_min, min(x_max, x)),
        "y": max(y_min, min(y_max, y)),
    }


def _organize_desks_by_team(layout: dict[str, Any]) -> dict[str, dict[str, int]]:
    desks = layout.setdefault("desks", {})
    assignments: dict[str, dict[str, int]] = {}
    by_dept: dict[str, list[str]] = {dept: [] for dept in OFFICE_DEPARTMENTS}

    for agent_id, desk in desks.items():
        if not isinstance(desk, dict):
            continue
        dept = _normalize_department(str(agent_id), desk.get("department"))
        by_dept.setdefault(dept, []).append(str(agent_id))

    for dept in by_dept:
        by_dept[dept].sort()

    for dept, agent_ids in by_dept.items():
        for idx, agent_id in enumerate(agent_ids):
            pos = _clustered_desk_position(agent_id, dept, idx)
            desk = desks.get(agent_id, {})
            desk["x"] = pos["x"]
            desk["y"] = pos["y"]
            desk["department"] = dept
            desks[agent_id] = desk
            assignments[agent_id] = {"x": pos["x"], "y": pos["y"]}

    return assignments


def _extract_subagent_id(session_key: str) -> str | None:
    marker = ":subagent:"
    if marker not in session_key:
        return None
    raw = session_key.split(marker, 1)[1].split(":", 1)[0].strip()
    if not raw:
        return None
    if AGENT_ID_RE.match(raw):
        return raw
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "-", raw).strip("-")
    return safe[:64] if safe else None


def _status_from_age_ms(age_ms: Any) -> str:
    if not isinstance(age_ms, int):
        return "offline"
    if age_ms <= 2 * 60 * 1000:
        return "working"
    if age_ms <= ACTIVE_WINDOW_MS:
        return "online"
    if age_ms <= 120 * 60 * 1000:
        return "idle"
    return "offline"


def _agents_from_sessions(sessions: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for sess in sessions:
        key = str(sess.get("key", ""))
        agent_id = _agent_id_from_session_key(key)
        if agent_id and agent_id not in found:
            found.append(agent_id)
    return found


def _office_desks_snapshot() -> dict[str, Any]:
    sessions = _load_openclaw_sessions()
    layout = _load_office_layout()
    profiles = _load_agent_profiles()
    desks = layout["desks"]

    latest: dict[str, dict[str, Any]] = {}
    for sess in sessions:
        key = str(sess.get("key", "")).strip()
        agent_id = _extract_subagent_id(key)
        if not agent_id:
            continue
        age_ms = sess.get("ageMs")
        entry = latest.get(agent_id)
        if entry is None or (isinstance(age_ms, int) and (not isinstance(entry.get("ageMs"), int) or age_ms < entry.get("ageMs"))):
            latest[agent_id] = {"sessionKey": key, "ageMs": age_ms, "updatedAt": sess.get("updatedAt")}

    changed = False
    profiles_changed = False
    for agent_id in sorted(latest.keys()):
        if agent_id not in desks:
            dept = _default_department(agent_id)
            existing_in_dept = [aid for aid, d in desks.items() if isinstance(d, dict) and _normalize_department(aid, d.get("department")) == dept]
            pos = _clustered_desk_position(agent_id, dept, len(existing_in_dept))
            desks[agent_id] = {**pos, "department": dept}
            changed = True
        profiles_changed = _ensure_profile(agent_id, profiles) or profiles_changed

    for agent_id in list(desks.keys()):
        profiles_changed = _ensure_profile(agent_id, profiles) or profiles_changed

    if changed:
        _save_office_layout(layout)
    if profiles_changed:
        _save_agent_profiles(profiles)

    items = []
    for agent_id, desk in desks.items():
        info = latest.get(agent_id, {})
        age_ms = info.get("ageMs")
        items.append(
            {
                "agentId": agent_id,
                "displayName": _display_name_for(agent_id, profiles),
                "sessionKey": info.get("sessionKey"),
                "status": _status_from_age_ms(age_ms),
                "ageMs": age_ms,
                "updatedAt": info.get("updatedAt"),
                "x": desk.get("x", 0),
                "y": desk.get("y", 0),
                "department": desk.get("department") or _default_department(agent_id),
            }
        )

    items.sort(key=lambda x: x.get("agentId", ""))
    return {
        "items": items,
        "count": len(items),
        "departments": OFFICE_DEPARTMENTS,
        "zoneLayout": OFFICE_ZONE_LAYOUT,
    }


def _build_team_agents() -> dict[str, Any]:
    sessions = _load_openclaw_sessions()
    profiles = _load_agent_profiles()
    layout = _load_office_layout()
    matrix = _load_permissions()

    session_by_agent: dict[str, dict[str, Any]] = {}
    all_ids: list[str] = []

    def add_id(agent_id: str) -> None:
        if agent_id and agent_id not in all_ids:
            all_ids.append(agent_id)

    for sess in sessions:
        key = str(sess.get("key", "")).strip()
        aid = _display_agent_id_from_session_key(key)
        if not aid:
            continue
        age_ms = sess.get("ageMs")
        # Team view should surface only recently used agents (72h window), except main.
        is_recent = isinstance(age_ms, int) and age_ms <= TEAM_RECENT_WINDOW_MS
        if aid != "main" and not is_recent:
            continue
        add_id(aid)
        prev = session_by_agent.get(aid)
        if prev is None or (isinstance(age_ms, int) and (not isinstance(prev.get("ageMs"), int) or age_ms < prev.get("ageMs"))):
            session_by_agent[aid] = {
                "ageMs": age_ms,
                "updatedAt": sess.get("updatedAt"),
            }

    for aid in profiles.get("agents", {}).keys():
        add_id(str(aid))
    for aid in layout.get("desks", {}).keys():
        add_id(str(aid))
    for aid in matrix.get("agents", {}).keys():
        add_id(str(aid))

    changed = False
    for aid in all_ids:
        changed = _ensure_profile(aid, profiles) or changed

    items: list[dict[str, Any]] = []
    for aid in sorted(all_ids):
        profile = profiles.get("agents", {}).get(aid, {}) if isinstance(profiles.get("agents", {}), dict) else {}
        desk = layout.get("desks", {}).get(aid, {}) if isinstance(layout.get("desks", {}), dict) else {}
        session = session_by_agent.get(aid, {})

        lifecycle = str(profile.get("lifecycle") or _default_lifecycle(aid)).strip().lower()
        if lifecycle == "disposable":
            continue

        dept = _normalize_department(aid, profile.get("department") or desk.get("department"))
        if isinstance(profile, dict) and profile.get("department") != dept:
            profile["department"] = dept
            profile["updatedAt"] = profile.get("updatedAt") or _utc_now_iso()
            changed = True

        age_ms = session.get("ageMs")
        status = _status_from_age_ms(age_ms) if session else "offline"

        items.append(
            {
                "agentId": aid,
                "displayName": _display_name_for(aid, profiles),
                "department": dept,
                "lifecycle": lifecycle,
                "status": status,
                "updatedAt": profile.get("updatedAt") or session.get("updatedAt"),
                "live": aid in session_by_agent,
            }
        )

    if changed:
        _save_agent_profiles(profiles)

    return {"items": items, "count": len(items), "departments": OFFICE_DEPARTMENTS}


def _next_job_id(jobs: list[dict[str, Any]]) -> str:
    max_n = 0
    for job in jobs:
        jid = str(job.get("id", ""))
        if jid.startswith("job-"):
            try:
                max_n = max(max_n, int(jid.split("-", 1)[1]))
            except ValueError:
                continue
    return f"job-{max_n + 1}"


def _normalize_schedule(payload: dict[str, Any]) -> tuple[str, str, str]:
    mode = str(payload.get("scheduleMode") or "").strip().lower()
    if mode not in {"every", "at", "cron"}:
        mode = "cron"

    value = str(payload.get("scheduleValue") or payload.get("schedule") or "").strip()
    if not value:
        raise ValueError("schedule is required")

    if mode == "every":
        schedule_text = f"every {value}"
    elif mode == "at":
        schedule_text = f"at {value}"
    else:
        schedule_text = value

    return mode, value, schedule_text


def _profile_entry_from_matrix(profile_id: str, matrix: dict[str, Any]) -> dict[str, Any] | None:
    aid = str(profile_id or "").strip()
    entry = matrix.get("agents", {}).get(aid)
    if not isinstance(entry, dict):
        return None
    skills_map = entry.get("skills", {}) if isinstance(entry.get("skills"), dict) else {}
    allowed = sorted([k for k, v in skills_map.items() if bool(v)])
    return {
        "profileId": aid,
        "label": str(entry.get("label") or aid),
        "allowedSkills": allowed,
        "enforcedBy": "app-policy",
        "runtimeSandbox": False,
    }


def _resolve_effective_policy(payload: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any]:
    tools_profile_id = str(payload.get("toolsProfileId") or "").strip()
    target_agent = str(payload.get("targetAgentId") or "").strip()

    if tools_profile_id:
        entry = _profile_entry_from_matrix(tools_profile_id, matrix)
        if entry:
            return entry

    if target_agent:
        entry = _profile_entry_from_matrix(target_agent, matrix)
        if entry:
            return {**entry, "profileId": f"agent:{target_agent}"}

    return {
        "profileId": tools_profile_id or (f"agent:{target_agent}" if target_agent else "default"),
        "label": tools_profile_id or (f"agent:{target_agent}" if target_agent else "default"),
        "allowedSkills": [],
        "enforcedBy": "app-policy",
        "runtimeSandbox": False,
    }


def _sanitize_new_job(payload: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    command = str(payload.get("command", "")).strip()
    target_agent = str(payload.get("targetAgentId") or "").strip()
    message_payload = str(payload.get("message") or "").strip()

    if not name:
        raise ValueError("name is required")
    schedule_mode, schedule_value, schedule_text = _normalize_schedule(payload)

    if not command and not message_payload:
        raise ValueError("command or message is required")
    if target_agent and not AGENT_ID_RE.match(target_agent):
        raise ValueError("invalid targetAgentId")
    if len(jobs) >= MAX_JOBS:
        raise ValueError("max jobs reached")

    matrix = _load_permissions()
    effective_policy = _resolve_effective_policy(payload, matrix)

    return {
        "id": _next_job_id(jobs),
        "name": name,
        "source": "local",
        "scheduleMode": schedule_mode,
        "scheduleValue": schedule_value,
        "schedule": schedule_text,
        "command": command,
        "targetAgentId": target_agent or None,
        "toolsProfileId": str(payload.get("toolsProfileId") or "").strip() or None,
        "message": message_payload,
        "effectivePolicy": effective_policy,
        "enabled": bool(payload.get("enabled", True)),
        "createdAt": _utc_now_iso(),
        "nextRunAt": payload.get("nextRunAt"),
        "lastRunAt": None,
        "lastExitCode": None,
        "lastOutput": "",
        "runHistory": [],
        "status": "enabled" if bool(payload.get("enabled", True)) else "disabled",
        "capabilities": {"canRunNow": True, "canToggle": True, "canRemove": True, "canEdit": True},
    }


def _apply_job_patch(job: dict[str, Any], payload: dict[str, Any]) -> None:
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("name cannot be empty")
        job["name"] = name

    if "schedule" in payload or "scheduleMode" in payload or "scheduleValue" in payload:
        merged = {
            "scheduleMode": payload.get("scheduleMode", job.get("scheduleMode")),
            "scheduleValue": payload.get("scheduleValue", payload.get("schedule", job.get("scheduleValue") or job.get("schedule"))),
        }
        mode, value, text = _normalize_schedule(merged)
        job["scheduleMode"] = mode
        job["scheduleValue"] = value
        job["schedule"] = text

    if "command" in payload:
        job["command"] = str(payload.get("command") or "").strip()
    if "message" in payload:
        job["message"] = str(payload.get("message") or "").strip()
    if "targetAgentId" in payload:
        target_agent = str(payload.get("targetAgentId") or "").strip()
        if target_agent and not AGENT_ID_RE.match(target_agent):
            raise ValueError("invalid targetAgentId")
        job["targetAgentId"] = target_agent or None
    if "toolsProfileId" in payload:
        job["toolsProfileId"] = str(payload.get("toolsProfileId") or "").strip() or None
    if "enabled" in payload:
        job["enabled"] = bool(payload.get("enabled"))

    if not str(job.get("command") or "").strip() and not str(job.get("message") or "").strip():
        raise ValueError("command or message is required")

    matrix = _load_permissions()
    job["effectivePolicy"] = _resolve_effective_policy(job, matrix)
    job["status"] = "enabled" if bool(job.get("enabled", True)) else "disabled"


def _find_job(jobs: list[dict[str, Any]], job_id: str) -> dict[str, Any] | None:
    for job in jobs:
        if job.get("id") == job_id:
            return job
    return None


def _run_cli_json(args: list[str], timeout: int = 20) -> Any:
    proc = subprocess.run(
        args,
        cwd=str(BASE_DIR),
        timeout=timeout,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        },
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "openclaw command failed").strip())

    raw = (proc.stdout or "").strip()
    if not raw:
        return {}

    # Some OpenClaw commands may print doctor/config notices before JSON.
    # Try direct parse first, then recover by slicing from first JSON token.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    ansi_re = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    cleaned = ansi_re.sub("", raw)
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if starts:
        candidate = cleaned[min(starts):].strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid json from {' '.join(args)}: {exc}") from exc

    raise RuntimeError(f"invalid json from {' '.join(args)}: no JSON payload found")


def _infer_openclaw_target_agent(item: dict[str, Any], message_text: str) -> str | None:
    explicit = str(item.get("targetAgentId") or item.get("agentId") or "").strip()
    if explicit and explicit != "main":
        return explicit

    name = str(item.get("name") or "")
    if name.startswith("[PO]") or "po.mission-control" in message_text:
        return "po.mission-control"
    if "Cockpit MVP build loop" in name:
        return "eng.backend"
    if "Vault Audit" in name:
        return "qa.guardian"

    m = re.search(r"\b([a-z]+\.[a-z0-9_.-]{2,64})\b", message_text)
    if m:
        return m.group(1)
    return str(item.get("agentId") or "main")


def _normalize_openclaw_job(item: dict[str, Any]) -> dict[str, Any]:
    raw_id = str(item.get("id") or item.get("jobId") or item.get("name") or "").strip()
    if not raw_id:
        return {}

    enabled = bool(item.get("enabled", True))
    capabilities = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
    state = item.get("state") if isinstance(item.get("state"), dict) else {}
    schedule_obj = item.get("schedule") if isinstance(item.get("schedule"), dict) else {}
    payload_obj = item.get("payload") if isinstance(item.get("payload"), dict) else {}

    schedule_kind = str(schedule_obj.get("kind") or item.get("scheduleMode") or "cron")
    if schedule_obj:
        schedule_value = (
            str(schedule_obj.get("everyMs")) if schedule_kind == "every" and schedule_obj.get("everyMs") is not None else
            str(schedule_obj.get("at")) if schedule_kind == "at" and schedule_obj.get("at") else
            str(schedule_obj.get("expr") or "")
        )
        schedule_text = str(schedule_obj)
    else:
        schedule_value = str(item.get("scheduleValue") or item.get("schedule") or "")
        schedule_text = str(item.get("schedule") or item.get("expression") or "-")

    command_text = str(item.get("command") or "")
    message_text = str(item.get("message") or item.get("task") or payload_obj.get("message") or "")

    next_run = item.get("nextRunAt") or item.get("nextRun") or _ms_to_iso(state.get("nextRunAtMs"))
    last_run = item.get("lastRunAt") or item.get("lastRun") or _ms_to_iso(state.get("lastRunAtMs"))
    created_at = item.get("createdAt") or _ms_to_iso(item.get("createdAtMs"))

    inferred_target = _infer_openclaw_target_agent(item, message_text)

    return {
        "id": raw_id,
        "name": str(item.get("name") or raw_id),
        "source": "openclaw",
        "scheduleMode": schedule_kind,
        "scheduleValue": schedule_value,
        "schedule": schedule_text,
        "command": command_text,
        "targetAgentId": inferred_target,
        "toolsProfileId": item.get("toolsProfileId") or item.get("policyProfileId"),
        "message": message_text,
        "effectivePolicy": item.get("effectivePolicy") if isinstance(item.get("effectivePolicy"), dict) else {
            "profileId": item.get("toolsProfileId") or item.get("policyProfileId"),
            "label": str(item.get("toolsProfileId") or item.get("policyProfileId") or "runtime-managed"),
            "allowedSkills": item.get("allowedSkills") if isinstance(item.get("allowedSkills"), list) else [],
            "enforcedBy": "runtime",
            "runtimeSandbox": True,
        },
        "enabled": enabled,
        "createdAt": created_at,
        "nextRunAt": next_run,
        "lastRunAt": last_run,
        "lastExitCode": item.get("lastExitCode") if item.get("lastExitCode") is not None else state.get("lastExitCode"),
        "lastOutput": str(item.get("lastOutput") or ""),
        "runHistory": item.get("runHistory") if isinstance(item.get("runHistory"), list) else [],
        "status": str(item.get("status") or state.get("lastRunStatus") or ("enabled" if enabled else "disabled")),
        "capabilities": {
            "canRunNow": bool(capabilities.get("canRunNow", True)),
            "canToggle": bool(capabilities.get("canToggle", True)),
            "canRemove": bool(capabilities.get("canRemove", True)),
            "canEdit": bool(capabilities.get("canEdit", False)),
        },
    }


def _load_openclaw_cron_jobs() -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = _run_cli_json(["openclaw", "cron", "list", "--json"], timeout=20)
        items = payload.get("items")
        if not isinstance(items, list):
            items = payload.get("jobs") if isinstance(payload.get("jobs"), list) else payload if isinstance(payload, list) else []
        normalized = []
        for item in items:
            if isinstance(item, dict):
                one = _normalize_openclaw_job(item)
                if one:
                    normalized.append(_normalize_job(one))
        return normalized, None
    except Exception as exc:
        return [], str(exc)


def _list_cron_jobs() -> dict[str, Any]:
    openclaw_items, error = _load_openclaw_cron_jobs()
    sessions: list[dict[str, Any]] | None = None
    sessions_error: str | None = None
    try:
        sessions = _load_openclaw_sessions()
    except Exception as exc:
        sessions_error = str(exc)

    openclaw_items = [_normalize_job(x, sessions=sessions, sessions_error=sessions_error) for x in openclaw_items]
    local_items = [_normalize_job(x, sessions=sessions, sessions_error=sessions_error) for x in _load_jobs()]
    items = openclaw_items + local_items
    return {
        "items": items,
        "sources": {
            "openclaw": {"count": len(openclaw_items), "error": error},
            "local": {"count": len(local_items)},
        },
    }


def _normalize_kanban_status(status: Any) -> str:
    status_text = str(status or "").strip()
    if status_text in KANBAN_STATUSES:
        return status_text
    if status_text in KANBAN_STATUS_ALIASES:
        return KANBAN_STATUS_ALIASES[status_text]
    return KANBAN_STATUSES[0]


def _load_kanban_tasks() -> list[dict[str, Any]]:
    _ensure_store()
    raw = KANBAN_TASKS_FILE.read_text(encoding="utf-8") or "[]"
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Invalid kanban storage format")

    items: list[dict[str, Any]] = []
    for task in data:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or "").strip()
        title = str(task.get("title") or "").strip()
        if not task_id or not title:
            continue
        items.append(
            {
                "id": task_id,
                "title": title,
                "description": str(task.get("description") or "").strip(),
                "assigneeAgentId": str(task.get("assigneeAgentId") or "").strip(),
                "priority": str(task.get("priority") or "").strip(),
                "dueDate": str(task.get("dueDate") or "").strip() or None,
                "status": _normalize_kanban_status(task.get("status")),
                "createdAt": task.get("createdAt") or _utc_now_iso(),
                "updatedAt": task.get("updatedAt") or _utc_now_iso(),
                "externalKey": str(task.get("externalKey") or "").strip() or None,
                "sourceRef": str(task.get("sourceRef") or "").strip() or None,
                "sourceTimestamp": str(task.get("sourceTimestamp") or "").strip() or None,
                "autoSynced": bool(task.get("autoSynced", False)),
            }
        )
    return items


def _save_kanban_tasks(tasks: list[dict[str, Any]]) -> None:
    _ensure_store()
    KANBAN_TASKS_FILE.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")


def _load_kanban_sync_health() -> dict[str, Any]:
    global _LAST_KANBAN_SYNC_HEALTH
    _ensure_store()
    try:
        payload = json.loads(KANBAN_SYNC_HEALTH_FILE.read_text(encoding="utf-8") or "{}")
    except (json.JSONDecodeError, OSError):
        payload = {}
    if isinstance(payload, dict):
        merged = {**_LAST_KANBAN_SYNC_HEALTH, **payload}
        _LAST_KANBAN_SYNC_HEALTH = merged
        return merged
    return dict(_LAST_KANBAN_SYNC_HEALTH)


def _save_kanban_sync_health(health: dict[str, Any]) -> None:
    global _LAST_KANBAN_SYNC_HEALTH
    _ensure_store()
    _LAST_KANBAN_SYNC_HEALTH = dict(health)
    KANBAN_SYNC_HEALTH_FILE.write_text(json.dumps(_LAST_KANBAN_SYNC_HEALTH, indent=2) + "\n", encoding="utf-8")


def _next_kanban_task_id(tasks: list[dict[str, Any]]) -> str:
    max_n = 0
    for task in tasks:
        tid = str(task.get("id") or "")
        if tid.startswith("task-"):
            try:
                max_n = max(max_n, int(tid.split("-", 1)[1]))
            except ValueError:
                continue
    return f"task-{max_n + 1}"


def _find_kanban_task(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any] | None:
    for task in tasks:
        if task.get("id") == task_id:
            return task
    return None


def _sanitize_kanban_task_payload(payload: dict[str, Any], existing_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    task_id = str(payload.get("id") or "").strip()
    if not task_id:
        idx = len(existing_tasks) + 1
        task_id = f"task-{idx}"

    title = str(payload.get("title") or "").strip()
    assignee = str(payload.get("assigneeAgentId") or "").strip()

    if not payload.get("id"):
        if not title:
            raise ValueError("title is required")
        if not assignee:
            raise ValueError("assigneeAgentId is required")

    if assignee and not AGENT_ID_RE.match(assignee):
        raise ValueError("invalid assigneeAgentId format")

    status = str(payload.get("status") or "").strip()
    if status not in KANBAN_STATUSES:
        status = "To do"

    priority = str(payload.get("priority") or "").strip()
    if priority not in ["P0", "P1", "P2"]:
        priority = "P1"

    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": task_id,
        "title": str(payload.get("title") or "").strip(),
        "description": str(payload.get("description") or "").strip(),
        "assigneeAgentId": str(payload.get("assigneeAgentId") or "").strip(),
        "priority": priority,
        "dueDate": payload.get("dueDate"),
        "status": status,
        "createdAt": payload.get("createdAt") or now,
        "updatedAt": now,
        "externalKey": payload.get("externalKey"),
        "sourceRef": payload.get("sourceRef"),
        "sourceTimestamp": payload.get("sourceTimestamp"),
        "autoSynced": payload.get("autoSynced") or False,
        "squad": str(payload.get("squad") or "").strip() or "crm"
    }


def _serialize_kanban_task(task: dict[str, Any], profiles: dict[str, Any]) -> dict[str, Any]:
    item = dict(task)
    aid = str(item.get("assigneeAgentId") or "").strip()
    item["assigneeDisplayName"] = _display_name_for(aid, profiles)
    profile = profiles.get("agents", {}).get(aid, {}) if aid else {}
    item["assigneeDepartment"] = _normalize_department(aid or "main", profile.get("department")) if aid else None
    return item


def _parse_command(command: str) -> list[str]:
    args = shlex.split(command)
    if not args:
        raise ValueError("No command provided")
    return args


def _run_job_command(command: str) -> tuple[int, str]:
    # Local-only and conservative execution:
    # - No shell=True
    # - Parse with shlex
    # - 30s timeout
    try:
        args = _parse_command(command)
    except ValueError as exc:
        return 1, str(exc)

    proc = subprocess.run(
        args,
        cwd=str(BASE_DIR),
        timeout=30,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        },
        check=False,
    )
    output = (proc.stdout or "") + ("\n" if proc.stderr else "") + (proc.stderr or "")
    return proc.returncode, output.strip()


def _summarize_output(output: str) -> tuple[str, int, bool]:
    normalized = " ".join(str(output or "").split())
    summary = normalized[:OUTPUT_SUMMARY_CHARS]
    truncated = len(summary) < len(normalized)
    return summary, len(str(output or "")), truncated


def _sanitize_agent_permissions(agent_id: str, payload: dict[str, Any], skills: list[str]) -> dict[str, Any]:
    if not AGENT_ID_RE.match(agent_id):
        raise ValueError("invalid agent id")

    label = str(payload.get("label", "")).strip()
    incoming = payload.get("skills")
    if not isinstance(incoming, dict):
        raise ValueError("skills object is required")

    values: dict[str, bool] = {}
    for skill in skills:
        values[skill] = bool(incoming.get(skill, False))

    return {
        "agentId": agent_id,
        "label": label,
        "skills": values,
        "updatedAt": _utc_now_iso(),
    }


def _load_openclaw_sessions() -> list[dict[str, Any]]:
    proc = subprocess.run(
        ["openclaw", "sessions", "--json"],
        cwd=str(BASE_DIR),
        timeout=20,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        },
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "failed to run openclaw sessions").strip())

    payload = json.loads(proc.stdout or "{}")
    sessions = payload.get("sessions", [])
    if not isinstance(sessions, list):
        return []
    return [s for s in sessions if isinstance(s, dict)]


def _run_openclaw_json(args: list[str], timeout: int = 20) -> dict[str, Any]:
    proc = subprocess.run(
        ["openclaw", *args, "--json"],
        cwd=str(BASE_DIR),
        timeout=timeout,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        },
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "openclaw call failed").strip())

    payload = json.loads(proc.stdout or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("invalid openclaw JSON payload")
    return payload


def _agent_id_from_session_key(session_key: str) -> str | None:
    parts = session_key.split(":")
    if len(parts) >= 2 and parts[0] == "agent":
        return parts[1] or None
    return None


def _display_agent_id_from_session_key(session_key: str) -> str | None:
    subagent_id = _extract_subagent_id(session_key)
    if subagent_id:
        return subagent_id
    return _agent_id_from_session_key(session_key)


def _resolve_session_key_for_target(target: str, sessions: list[dict[str, Any]]) -> str | None:
    candidate = str(target or "").strip()
    if not candidate:
        return None

    # Allow direct session key usage for backwards compatibility.
    if ":" in candidate:
        for sess in sessions:
            key = str(sess.get("key", "")).strip()
            if key == candidate:
                return key

    best_key: str | None = None
    best_age: int | None = None
    for sess in sessions:
        key = str(sess.get("key", "")).strip()
        if not key:
            continue
        display_id = _display_agent_id_from_session_key(key)
        if display_id != candidate:
            continue
        age_ms = sess.get("ageMs")
        if best_key is None:
            best_key = key
            best_age = age_ms if isinstance(age_ms, int) else None
            continue
        if isinstance(age_ms, int) and (best_age is None or age_ms < best_age):
            best_key = key
            best_age = age_ms
    return best_key


def _cron_job_session_preflight(job: dict[str, Any], sessions: list[dict[str, Any]] | None = None, sessions_error: str | None = None) -> dict[str, Any]:
    message_payload = str(job.get("message") or "").strip()
    target_agent = str(job.get("targetAgentId") or "").strip()
    requires_session = bool(message_payload and target_agent)

    result = {
        "preflightSessionRequired": requires_session,
        "preflightSessionReady": True,
        "preflightSessionKey": None,
        "preflightSessionError": None,
    }

    if not requires_session:
        return result

    if sessions_error:
        result["preflightSessionReady"] = False
        result["preflightSessionError"] = f"session lookup unavailable: {sessions_error}"
        return result

    if not isinstance(sessions, list):
        result["preflightSessionReady"] = False
        result["preflightSessionError"] = "session lookup unavailable"
        return result

    resolved_key = _resolve_session_key_for_target(target_agent, sessions)
    if not resolved_key:
        result["preflightSessionReady"] = False
        result["preflightSessionError"] = f"no active session found for targetAgentId '{target_agent}'"
        return result

    result["preflightSessionKey"] = resolved_key
    return result


def _is_skill_allowed(agent_id: str | None, skill: str, matrix: dict[str, Any]) -> bool:
    if not agent_id:
        return True
    agents = matrix.get("agents", {})
    if not isinstance(agents, dict):
        return True
    entry = agents.get(agent_id)
    if not isinstance(entry, dict):
        return True  # open by default unless explicitly configured
    skill_flags = entry.get("skills", {})
    if not isinstance(skill_flags, dict):
        return True
    return bool(skill_flags.get(skill, False))


def _session_target_items(sessions: list[dict[str, Any]], matrix: dict[str, Any], profiles: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for sess in sessions:
        key = str(sess.get("key", "")).strip()
        if not key:
            continue
        agent_id = _agent_id_from_session_key(key)
        display_agent_id = _display_agent_id_from_session_key(key)
        items.append(
            {
                "sessionKey": key,
                "agentId": agent_id,
                "targetAgentId": display_agent_id,
                "displayName": _display_name_for(display_agent_id, profiles),
                "kind": sess.get("kind", "direct"),
                "model": sess.get("model") or sess.get("modelOverride") or "-",
                "ageMs": sess.get("ageMs"),
                "active": isinstance(sess.get("ageMs"), int) and sess.get("ageMs") <= ACTIVE_WINDOW_MS,
                "canSend": _is_skill_allowed(agent_id, "sessions_send", matrix),
                "canHistory": _is_skill_allowed(agent_id, "sessions_history", matrix),
            }
        )

    items.sort(key=lambda x: (x.get("ageMs") if isinstance(x.get("ageMs"), int) else 10**18))
    return items[:100]


def _build_agents_overview(
    sessions: list[dict[str, Any]],
    profiles: dict[str, Any],
    *,
    type_filter: str | None = None,
    status_filter: str | None = None,
    query: str | None = None,
    sort_by: str | None = None,
    limit: int = 40,
    offset: int = 0,
    page: int = 1,
    pagination_mode: str = "page",
) -> dict[str, Any]:
    main_total = 0
    subagent_total = 0
    active_total = 0
    all_entries: list[dict[str, Any]] = []

    normalized_query = str(query or "").strip().lower()
    normalized_type = str(type_filter or "").strip().lower()
    normalized_status = str(status_filter or "").strip().lower()
    normalized_sort = str(sort_by or "").strip().lower()
    requested_sort = normalized_sort
    sort_fallback_applied = False
    normalized_pagination_mode = str(pagination_mode or "").strip().lower()
    if normalized_pagination_mode not in {"page", "offset"}:
        normalized_pagination_mode = "page"

    for sess in sessions:
        key = str(sess.get("key", ""))
        age_ms = sess.get("ageMs")
        is_active = isinstance(age_ms, int) and age_ms <= ACTIVE_WINDOW_MS
        if is_active:
            active_total += 1

        display_agent_id = _display_agent_id_from_session_key(key)
        if ":subagent:" in key:
            subagent_total += 1
            entry_type = "subagent"
        else:
            main_total += 1
            entry_type = "agent"

        all_entries.append(
            {
                "key": key,
                "agentId": display_agent_id,
                "displayName": _display_name_for(display_agent_id, profiles),
                "type": entry_type,
                "kind": sess.get("kind", "direct"),
                "model": sess.get("model") or sess.get("modelOverride") or "-",
                "ageMs": age_ms,
                "updatedAt": sess.get("updatedAt"),
                "active": is_active,
            }
        )

    if normalized_sort == "oldest":
        all_entries.sort(
            key=lambda x: (-(x.get("ageMs") if isinstance(x.get("ageMs"), int) else -1), str(x.get("displayName") or x.get("agentId") or x.get("key") or ""))
        )
    elif normalized_sort == "name":
        all_entries.sort(
            key=lambda x: (
                str(x.get("displayName") or x.get("agentId") or x.get("key") or "").lower(),
                x.get("ageMs") if isinstance(x.get("ageMs"), int) else 10**18,
            )
        )
    elif normalized_sort == "status":
        all_entries.sort(
            key=lambda x: (
                0 if x.get("active") else 1,
                x.get("ageMs") if isinstance(x.get("ageMs"), int) else 10**18,
            )
        )
    else:
        sort_fallback_applied = bool(requested_sort)
        normalized_sort = "recent"
        all_entries.sort(key=lambda x: (x.get("ageMs") if isinstance(x.get("ageMs"), int) else 10**18))

    filtered_entries: list[dict[str, Any]] = []
    for entry in all_entries:
        if normalized_type in {"agent", "subagent"} and entry.get("type") != normalized_type:
            continue
        if normalized_status == "active" and not entry.get("active"):
            continue
        if normalized_status == "idle" and entry.get("active"):
            continue
        if normalized_query:
            hay = " ".join(
                [
                    str(entry.get("displayName") or ""),
                    str(entry.get("agentId") or ""),
                    str(entry.get("key") or ""),
                    str(entry.get("kind") or ""),
                    str(entry.get("model") or ""),
                ]
            ).lower()
            if normalized_query not in hay:
                continue
        filtered_entries.append(entry)

    requested_limit = int(limit or 40)
    safe_limit = max(1, min(requested_limit, 200))
    limit_was_clamped = safe_limit != requested_limit

    requested_offset = int(0 if offset is None else offset)
    safe_offset = max(0, requested_offset)

    requested_page = int(1 if page is None else page)
    safe_page = max(1, requested_page)

    total_filtered = len(filtered_entries)
    total_pages = max(1, (total_filtered + safe_limit - 1) // safe_limit)
    max_offset = max(0, (total_pages - 1) * safe_limit)
    effective_offset = min(safe_offset, max_offset)
    offset_was_clamped = effective_offset != requested_offset

    current_page = (effective_offset // safe_limit) + 1 if total_filtered else 1
    requested_page_offset = (safe_page - 1) * safe_limit
    page_was_clamped = (
        normalized_pagination_mode == "page"
        and current_page != requested_page
    ) or (
        normalized_pagination_mode == "offset"
        and requested_offset == requested_page_offset
        and safe_page != requested_page
    )
    page_items = filtered_entries[effective_offset : effective_offset + safe_limit]
    next_offset = effective_offset + len(page_items)
    if next_offset >= total_filtered:
        next_offset = None
    prev_offset = effective_offset - safe_limit if effective_offset > 0 else None
    next_page = (current_page + 1) if next_offset is not None else None
    prev_page = (current_page - 1) if prev_offset is not None else None
    range_start = (effective_offset + 1) if page_items else 0
    range_end = effective_offset + len(page_items)
    remaining_before = effective_offset
    remaining_after = max(0, total_filtered - range_end)
    first_offset = 0 if total_filtered else None
    last_offset = max_offset if total_filtered else None

    return {
        "summary": {
            "totalSessions": len(sessions),
            "mainSessions": main_total,
            "subagentSessions": subagent_total,
            "activeSessions": active_total,
            "activeWindowMinutes": ACTIVE_WINDOW_MS // 60000,
            "filteredSessions": total_filtered,
            "filters": {
                "type": normalized_type if normalized_type in {"agent", "subagent"} else "all",
                "status": normalized_status if normalized_status in {"active", "idle"} else "all",
                "query": normalized_query,
                "sort": normalized_sort,
                "requestedSort": requested_sort,
                "sortFallbackApplied": sort_fallback_applied,
                "limit": safe_limit,
                "requestedLimit": requested_limit,
                "limitClamped": limit_was_clamped,
                "offset": effective_offset,
                "page": current_page,
                "requestedOffset": requested_offset,
                "requestedPage": requested_page,
                "requestedPaginationMode": normalized_pagination_mode,
                "offsetClamped": offset_was_clamped,
                "pageClamped": page_was_clamped,
            },
            "page": {
                "offset": effective_offset,
                "requestedOffset": requested_offset,
                "requestedPage": requested_page,
                "requestedPaginationMode": normalized_pagination_mode,
                "offsetClamped": offset_was_clamped,
                "pageClamped": page_was_clamped,
                "limit": safe_limit,
                "requestedLimit": requested_limit,
                "limitClamped": limit_was_clamped,
                "returned": len(page_items),
                "total": total_filtered,
                "rangeStart": range_start,
                "rangeEnd": range_end,
                "remainingBefore": remaining_before,
                "remainingAfter": remaining_after,
                "hasMore": (effective_offset + len(page_items)) < total_filtered,
                "currentPage": current_page,
                "totalPages": total_pages,
                "firstOffset": first_offset,
                "lastOffset": last_offset,
                "nextOffset": next_offset,
                "prevOffset": prev_offset,
                "nextPage": next_page,
                "prevPage": prev_page,
                "hasNextPage": next_offset is not None,
                "hasPrevPage": prev_offset is not None,
                "isFirstPage": effective_offset == 0,
                "isLastPage": ((effective_offset + len(page_items)) >= total_filtered) if total_filtered else True,
            },
        },
        "items": page_items,
    }


def _crm_auth_headers() -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if CRM_USER and CRM_PASS:
        token = (f"{CRM_USER}:{CRM_PASS}").encode("utf-8")
        import base64

        headers["Authorization"] = "Basic " + base64.b64encode(token).decode("ascii")
    return headers


import time

def _crm_health_probe(timeout: float = 2.5) -> dict[str, Any]:
    t0 = time.time()
    probe_url = f"{CRM_BASE_URL}/api/crm/overview"
    req = Request(probe_url, method="GET", headers=_crm_auth_headers())
    try:
        with urlopen(req, timeout=timeout) as resp:
            latency = int((time.time() - t0) * 1000)
            status_code = int(getattr(resp, "status", 200))
            status_str = "ok" if latency < 1000 else "degraded"
            return {
                "status": status_str,
                "online": True,
                "statusCode": status_code,
                "latencyMs": latency,
                "error": None,
                "lastSyncAt": datetime.now(timezone.utc).isoformat()
            }
    except HTTPError as exc:
        latency = int((time.time() - t0) * 1000)
        return {
            "status": "degraded",
            "online": False,
            "statusCode": int(getattr(exc, "code", 0) or 0),
            "latencyMs": latency,
            "error": f"HTTP {getattr(exc, 'code', 'error')}",
            "lastSyncAt": None
        }
    except URLError as exc:
        latency = int((time.time() - t0) * 1000)
        return {
            "status": "down",
            "online": False,
            "statusCode": 0,
            "latencyMs": latency,
            "error": str(exc.reason),
            "lastSyncAt": None
        }
    except Exception as exc:
        latency = int((time.time() - t0) * 1000)
        return {
            "status": "down",
            "online": False,
            "statusCode": 0,
            "latencyMs": latency,
            "error": str(exc),
            "lastSyncAt": None
        }


def _is_safe_local_crm_target(raw_path: str) -> bool:
    clean = str(raw_path or "").lstrip("/")
    if not clean:
        return False
    if clean.startswith(("http://", "https://")):
        return False
    return any(clean.startswith(prefix) for prefix in CRM_ALLOWED_PROXY_PREFIXES)


@app.get("/")
def index():
    return render_template("index.html")


def _vault_resolve_target(raw_path: str | None) -> Path:
    relative = (raw_path or "").strip().replace("\\", "/").lstrip("/")
    candidate = (VAULT_ROOT / relative).resolve()
    if candidate != VAULT_ROOT and VAULT_ROOT not in candidate.parents:
        raise ValueError("unsafe path")
    return candidate


@app.get("/vault/open")
def vault_open():
    return redirect("/vault", code=302)


@app.get("/vault")
def vault_browser():
    requested = request.args.get("p", "")
    query = (request.args.get("q") or "").strip()
    try:
        current = _vault_resolve_target(requested)
    except ValueError:
        abort(400, "invalid vault path")

    if not current.exists():
        abort(404, "path not found")
    if current.is_file():
        rel = current.relative_to(VAULT_ROOT).as_posix()
        return redirect(f"/vault/raw?p={rel}", code=302)

    rel_current = "." if current == VAULT_ROOT else current.relative_to(VAULT_ROOT).as_posix()
    parent_rel = "" if current == VAULT_ROOT else current.parent.relative_to(VAULT_ROOT).as_posix()

    rows: list[str] = []
    try:
        entries = sorted(current.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    except Exception as exc:
        abort(500, f"failed to read vault directory: {exc}")

    for entry in entries:
        if query and query.lower() not in entry.name.lower():
            continue
        name = entry.name
        rel = entry.relative_to(VAULT_ROOT).as_posix()
        if entry.is_dir():
            rows.append(f'<li>📁 <a href="/vault?p={rel}">{name}/</a></li>')
        else:
            rows.append(
                f'<li>📄 <a href="/vault/raw?p={rel}" target="_blank" rel="noopener noreferrer">{name}</a>'
                f' &nbsp;<a href="/vault/download?p={rel}">⬇ download</a>'
                f' <form method="post" action="/vault/rename" style="display:inline; margin-left:8px;">'
                f'<input type="hidden" name="p" value="{rel}" />'
                f'<input type="text" name="newName" placeholder="novo nome" style="width:140px;" />'
                f'<button type="submit">rename</button></form></li>'
            )

    recursive_hits: list[str] = []
    if query:
        try:
            for hit in current.rglob("*"):
                if not hit.is_file():
                    continue
                if query.lower() not in hit.name.lower():
                    continue
                rel_hit = hit.relative_to(VAULT_ROOT).as_posix()
                recursive_hits.append(
                    f'<li>📄 <a href="/vault/raw?p={rel_hit}" target="_blank" rel="noopener noreferrer">{rel_hit}</a>'
                    f' &nbsp;<a href="/vault/download?p={rel_hit}">⬇</a></li>'
                )
                if len(recursive_hits) >= 200:
                    break
        except Exception:
            pass

    html = f"""<!doctype html>
<html lang=\"en\"><head>
<meta charset=\"UTF-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
<title>Vault Drive</title>
<style>
body {{ font-family: Inter, system-ui, sans-serif; margin: 24px; background: #0e1117; color: #e6edf3; }}
a {{ color: #7cc7ff; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.container {{ max-width: 1100px; margin: 0 auto; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 16px 20px; margin-bottom: 14px; }}
ul {{ line-height: 1.8; padding-left: 18px; }}
.meta {{ color: #8b949e; margin-bottom: 12px; }}
input, button {{ background:#0d1117; color:#e6edf3; border:1px solid #30363d; border-radius:8px; padding:6px 8px; }}
button {{ cursor:pointer; }}
</style>
</head><body>
<div class=\"container\">
  <h1>Vault Drive</h1>
  <div class=\"meta\">Root: {VAULT_ROOT} · Current: {rel_current}</div>

  <div class=\"card\">
    <div style=\"margin-bottom:10px;\"><a href=\"/\">← Mission Control</a> &nbsp;|&nbsp; <a href=\"/vault?p={parent_rel}\">⬆ Parent</a></div>
    <form method=\"get\" action=\"/vault\" style=\"display:flex; gap:8px; margin-bottom:10px;\">
      <input type=\"hidden\" name=\"p\" value=\"{rel_current if rel_current != '.' else ''}\" />
      <input type=\"text\" name=\"q\" placeholder=\"Buscar arquivo por nome...\" value=\"{query}\" style=\"min-width:320px;\" />
      <button type=\"submit\">Buscar</button>
      <a href=\"/vault?p={rel_current if rel_current != '.' else ''}\">Limpar</a>
    </form>

    <form method=\"post\" action=\"/vault/upload?p={rel_current if rel_current != '.' else ''}\" enctype=\"multipart/form-data\" style=\"display:flex; gap:8px; align-items:center; margin-bottom:10px;\">
      <input type=\"file\" name=\"file\" required />
      <button type=\"submit\">Upload</button>
    </form>

    <ul>{''.join(rows) or '<li>(empty folder)</li>'}</ul>
  </div>

  {('<div class=\"card\"><h3>Busca recursiva</h3><ul>' + ''.join(recursive_hits) + '</ul></div>') if query else ''}
</div>
</body></html>"""
    return html


@app.post("/vault/upload")
def vault_upload_file():
    requested = request.args.get("p", "")
    try:
        target_dir = _vault_resolve_target(requested)
    except ValueError:
        abort(400, "invalid vault path")

    if not target_dir.exists() or not target_dir.is_dir():
        abort(404, "directory not found")

    file_obj = request.files.get("file")
    if not file_obj or not file_obj.filename:
        abort(400, "file is required")

    safe_name = Path(file_obj.filename).name
    destination = (target_dir / safe_name).resolve()
    if destination != target_dir and target_dir not in destination.parents:
        abort(400, "unsafe filename")

    file_obj.save(destination)
    rel = "" if target_dir == VAULT_ROOT else target_dir.relative_to(VAULT_ROOT).as_posix()
    return redirect(url_for("vault_browser", p=rel), code=302)


@app.post("/vault/rename")
def vault_rename_file():
    requested = request.form.get("p", "")
    new_name = Path((request.form.get("newName") or "").strip()).name
    if not new_name:
        abort(400, "newName is required")
    try:
        target = _vault_resolve_target(requested)
    except ValueError:
        abort(400, "invalid vault path")

    if not target.exists() or not target.is_file():
        abort(404, "file not found")

    destination = (target.parent / new_name).resolve()
    if destination != target.parent and target.parent not in destination.parents:
        abort(400, "unsafe rename target")
    target.rename(destination)
    rel_parent = "" if target.parent == VAULT_ROOT else target.parent.relative_to(VAULT_ROOT).as_posix()
    return redirect(url_for("vault_browser", p=rel_parent), code=302)


@app.get("/vault/download")
def vault_download_file():
    requested = request.args.get("p", "")
    try:
        target = _vault_resolve_target(requested)
    except ValueError:
        abort(400, "invalid vault path")
    if not target.exists() or not target.is_file():
        abort(404, "file not found")
    return send_file(target, as_attachment=True, download_name=target.name)


@app.get("/vault/raw")
def vault_raw_file():
    requested = request.args.get("p", "")
    try:
        target = _vault_resolve_target(requested)
    except ValueError:
        abort(400, "invalid vault path")
    if not target.exists() or not target.is_file():
        abort(404, "file not found")
    return send_file(target, as_attachment=False)


@app.get("/api/system/environment")
def api_system_environment():
    return jsonify(
        {
            "ok": True,
            "environment": APP_ENV,
            "dataDir": str(DATA_DIR),
        }
    )


def _kb_index_path() -> Path:
    return BASE_DIR / "docs/crm/mission-kb-index.json"


def _kb_default_sources() -> list[dict[str, str]]:
    return [
        {"id": "estrategia-empresa-danhausch", "title": "Estratégia da Empresa (Danhausch)", "path": str(BASE_DIR / "docs/crm/estrategia-empresa-danhausch.md")},
        {"id": "script-vendas-completo", "title": "Script de Vendas Completo", "path": str(BASE_DIR / "docs/crm/script-vendas-completo.md")},
        {"id": "persona-dream-outcome", "title": "Persona ICP + Dream Outcome", "path": str(BASE_DIR / "docs/crm/persona-dream-outcome.md")},
        {"id": "vsl-curta-3-5", "title": "Script de VSL curta (3-5 min)", "path": str(BASE_DIR / "docs/crm/vsl-curta-3-5-min.md")},
        {"id": "sequencia-7-anuncios-meta-youtube", "title": "Sequência de 7 anúncios (Meta + YouTube)", "path": str(BASE_DIR / "docs/crm/sequencia-7-anuncios-meta-youtube.md")},
        {"id": "roteiro-call-vendas", "title": "Roteiro de call de vendas alinhado com essa persona", "path": str(BASE_DIR / "docs/crm/roteiro-call-vendas.md")},
    ]


def _kb_slugify(raw: str) -> str:
    s = (raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:80] or "doc"


def _kb_sources() -> list[dict[str, str]]:
    defaults = _kb_default_sources()
    index_path = _kb_index_path()
    if not index_path.exists():
        return defaults
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        docs = payload.get("docs") if isinstance(payload, dict) else None
        out: list[dict[str, str]] = []
        for d in docs or []:
            if not isinstance(d, dict):
                continue
            doc_id = str(d.get("id") or "").strip()
            title = str(d.get("title") or doc_id or "Documento").strip()
            rel = str(d.get("file") or "").strip()
            if not doc_id or not rel:
                continue
            p = (BASE_DIR / "docs/crm" / rel).resolve()
            out.append({"id": doc_id, "title": title, "path": str(p)})
        return out or defaults
    except Exception:
        return defaults


def _kb_save_sources(sources: list[dict[str, str]]) -> None:
    docs_dir = (BASE_DIR / "docs/crm").resolve()
    payload_docs: list[dict[str, str]] = []
    for src in sources:
        doc_id = str(src.get("id") or "").strip()
        title = str(src.get("title") or doc_id or "Documento").strip()
        p = Path(str(src.get("path") or "")).resolve()
        if not doc_id:
            continue
        try:
            rel = p.relative_to(docs_dir).as_posix()
        except Exception:
            rel = f"{_kb_slugify(doc_id)}.md"
        payload_docs.append({"id": doc_id, "title": title, "file": rel})
    _kb_index_path().write_text(json.dumps({"docs": payload_docs}, ensure_ascii=False, indent=2), encoding="utf-8")


def _kb_source_by_id(doc_id: str) -> dict[str, str] | None:
    for src in _kb_sources():
        if src.get("id") == doc_id:
            return src
    return None


@app.get("/api/knowledge/mission-control")
def api_knowledge_mission_control():
    selected = str(request.args.get("doc") or "").strip()
    docs: list[dict[str, Any]] = []
    selected_doc: dict[str, Any] | None = None

    for src in _kb_sources():
        p = Path(src["path"])
        exists = p.exists() and p.is_file()
        item = {
            "id": src["id"],
            "title": src["title"],
            "path": str(p),
            "exists": exists,
            "updatedAt": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat() if exists else None,
        }
        docs.append(item)
        if selected and src["id"] == selected:
            selected_doc = item

    if selected and not selected_doc:
        return jsonify({"error": "doc not found", "docs": docs}), 404

    if not selected_doc:
        selected_doc = next((d for d in docs if d.get("exists")), docs[0] if docs else None)

    content = ""
    if selected_doc and selected_doc.get("exists"):
        try:
            content = Path(selected_doc["path"]).read_text(encoding="utf-8")[:120000]
        except Exception as exc:
            return jsonify({"error": f"failed to read KB doc: {exc}", "docs": docs, "selected": selected_doc}), 500

    return jsonify({
        "ok": True,
        "docs": docs,
        "selected": selected_doc,
        "content": content,
    })


@app.post("/api/knowledge/mission-control/save")
def api_knowledge_mission_control_save():
    payload = request.get_json(silent=True) or {}
    doc_id = str(payload.get("doc") or "").strip()
    content = str(payload.get("content") or "")

    src = _kb_source_by_id(doc_id)
    if not src:
        return jsonify({"error": "doc not found"}), 404

    target = Path(src["path"]).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    if len(content) > 300000:
        return jsonify({"error": "content too long"}), 400

    try:
        target.write_text(content, encoding="utf-8")
    except Exception as exc:
        return jsonify({"error": f"failed to save KB doc: {exc}"}), 500

    return jsonify({
        "ok": True,
        "doc": doc_id,
        "path": str(target),
        "updatedAt": datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc).isoformat(),
    })


@app.post("/api/knowledge/mission-control/create")
def api_knowledge_mission_control_create():
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    requested_id = str(payload.get("id") or "").strip()
    content = str(payload.get("content") or "")

    sources = _kb_sources()
    by_id = {str(s.get("id") or ""): s for s in sources}

    base_id = _kb_slugify(requested_id or title)
    doc_id = base_id
    i = 2
    while doc_id in by_id:
        doc_id = f"{base_id}-{i}"
        i += 1

    filename = f"{doc_id}.md"
    target = (BASE_DIR / "docs/crm" / filename).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        target.write_text(content, encoding="utf-8")
    except Exception as exc:
        return jsonify({"error": f"failed to create KB doc: {exc}"}), 500

    sources.append({"id": doc_id, "title": title, "path": str(target)})
    try:
        _kb_save_sources(sources)
    except Exception as exc:
        return jsonify({"error": f"failed to update KB index: {exc}"}), 500

    return jsonify({"ok": True, "doc": {"id": doc_id, "title": title, "path": str(target)}})


@app.delete("/api/knowledge/mission-control/doc/<doc_id>")
def api_knowledge_mission_control_delete(doc_id: str):
    doc_id = str(doc_id or "").strip()
    if not doc_id:
        return jsonify({"error": "doc id is required"}), 400

    sources = _kb_sources()
    src = next((s for s in sources if str(s.get("id") or "") == doc_id), None)
    if not src:
        return jsonify({"error": "doc not found"}), 404

    target = Path(str(src.get("path") or "")).resolve()
    remaining = [s for s in sources if str(s.get("id") or "") != doc_id]

    try:
        if target.exists() and target.is_file():
            target.unlink()
    except Exception as exc:
        return jsonify({"error": f"failed to delete KB file: {exc}"}), 500

    try:
        _kb_save_sources(remaining)
    except Exception as exc:
        return jsonify({"error": f"failed to update KB index: {exc}"}), 500

    return jsonify({"ok": True, "deleted": doc_id})


@app.get("/api/crm/bridge/flow")
@app.get("/mission-control/api/crm/bridge/flow")
def api_crm_flow_get():
    flow = _load_crm_flow()
    return jsonify({"ok": True, "flow": flow})


@app.post("/api/crm/bridge/flow")
@app.post("/mission-control/api/crm/bridge/flow")
def api_crm_flow_set():
    payload = request.get_json(silent=True) or {}
    flow = payload.get("flow") if isinstance(payload, dict) and isinstance(payload.get("flow"), dict) else payload
    if not isinstance(flow, dict):
        return jsonify({"error": "invalid flow payload"}), 400

    saved = _save_crm_flow(flow)
    return jsonify({"ok": True, "flow": saved})


def _crm_cadence_options() -> dict[str, list[str]]:
    leads, _, _ = _fetch_crm_overview()
    statuses: set[str] = set()
    labels: set[str] = set()
    origins: set[str] = set()

    for lead in leads:
        if not isinstance(lead, dict):
            continue
        stage = str(lead.get("current_stage") or lead.get("stage") or lead.get("status") or "").strip()
        if stage:
            statuses.add(stage)

        origin = str(lead.get("source") or lead.get("origem") or "").strip()
        if origin:
            origins.add(origin)

        raw_tags = lead.get("tags")
        if isinstance(raw_tags, list):
            for item in raw_tags:
                tag = str(item or "").strip()
                if tag:
                    labels.add(tag)
        elif isinstance(raw_tags, str):
            for item in raw_tags.split(","):
                tag = str(item or "").strip()
                if tag:
                    labels.add(tag)

    return {
        "statuses": sorted(statuses),
        "labels": sorted(labels),
        "origins": sorted(origins),
    }


@app.get("/api/crm/bridge/cadences")
@app.get("/mission-control/api/crm/bridge/cadences")
def api_crm_cadences_get():
    store = _load_crm_cadences_store()
    return jsonify({"ok": True, "cadences": store.get("cadences", []), "updatedAt": store.get("updatedAt")})


@app.get("/api/crm/bridge/cadences/options")
@app.get("/mission-control/api/crm/bridge/cadences/options")
def api_crm_cadences_options_get():
    return jsonify({"ok": True, "options": _crm_cadence_options()})


@app.post("/api/crm/bridge/cadences")
@app.post("/mission-control/api/crm/bridge/cadences")
def api_crm_cadences_create():
    payload = request.get_json(silent=True) or {}
    cadence_in = payload.get("cadence") if isinstance(payload, dict) else {}
    cadence = _normalize_cadence(cadence_in, 0)
    errors = _cadence_validation_errors(cadence)
    if errors:
        return jsonify({"error": "validation_error", "errors": errors}), 400

    store = _load_crm_cadences_store()
    cadences = list(store.get("cadences") or [])
    cadence["id"] = str(cadence.get("id") or f"cad-{int(time.time() * 1000)}").strip() or f"cad-{int(time.time() * 1000)}"
    cadence["updatedAt"] = _utc_now_iso()
    cadences.append(cadence)
    saved = _save_crm_cadences_store({"cadences": cadences})
    return jsonify({"ok": True, "cadence": cadence, "cadences": saved.get("cadences", [])}), 201


@app.put("/api/crm/bridge/cadences/<cadence_id>")
@app.put("/mission-control/api/crm/bridge/cadences/<cadence_id>")
def api_crm_cadences_update(cadence_id: str):
    cadence_id = str(cadence_id or "").strip()
    if not cadence_id:
        return jsonify({"error": "cadence id is required"}), 400

    payload = request.get_json(silent=True) or {}
    cadence_in = payload.get("cadence") if isinstance(payload, dict) else {}
    cadence = _normalize_cadence(cadence_in, 0)
    cadence["id"] = cadence_id

    errors = _cadence_validation_errors(cadence)
    if errors:
        return jsonify({"error": "validation_error", "errors": errors}), 400

    store = _load_crm_cadences_store()
    cadences = list(store.get("cadences") or [])
    idx = next((i for i, item in enumerate(cadences) if str(item.get("id") or "") == cadence_id), -1)
    if idx < 0:
        return jsonify({"error": "cadence not found"}), 404

    cadence["updatedAt"] = _utc_now_iso()
    cadences[idx] = cadence
    saved = _save_crm_cadences_store({"cadences": cadences})
    return jsonify({"ok": True, "cadence": cadence, "cadences": saved.get("cadences", [])})


@app.delete("/api/crm/bridge/cadences/<cadence_id>")
@app.delete("/mission-control/api/crm/bridge/cadences/<cadence_id>")
def api_crm_cadences_delete(cadence_id: str):
    cadence_id = str(cadence_id or "").strip()
    if not cadence_id:
        return jsonify({"error": "cadence id is required"}), 400

    store = _load_crm_cadences_store()
    cadences = [item for item in (store.get("cadences") or []) if str(item.get("id") or "") != cadence_id]
    if len(cadences) == len(store.get("cadences") or []):
        return jsonify({"error": "cadence not found"}), 404

    saved = _save_crm_cadences_store({"cadences": cadences})
    return jsonify({"ok": True, "cadences": saved.get("cadences", [])})


@app.get("/crm/open")
def crm_open():
    return redirect(CRM_BASE_URL, code=302)


@app.get("/api/crm/bridge")
@app.get("/mission-control/api/crm/bridge")
def api_crm_bridge():
    health = _crm_health_probe()
    leads, total_leads, overview_error = _fetch_crm_overview()

    status_ok = bool(health.get("online")) and not overview_error
    status_source = "crm-overview" if not overview_error else "health-only"

    return jsonify(
        {
            "ok": True,
            "status": {
                "ok": status_ok,
                "source": status_source,
                "error": overview_error,
                "latencyMs": health.get("latencyMs"),
                "statusCode": health.get("statusCode"),
            },
            "payload": {
                "leads": leads,
                "totals": {
                    "leads": total_leads if total_leads is not None else len(leads),
                },
            },
            "crm": {
                "baseUrl": CRM_BASE_URL,
                "openUrl": "/crm/open",
                "embedUrl": CRM_BASE_URL,
                "proxyBase": "/api/crm/bridge/proxy",
                "allowedProxyPrefixes": list(CRM_ALLOWED_PROXY_PREFIXES),
                "authConfigured": bool(CRM_USER and CRM_PASS),
                "health": health,
            },
        }
    )


@app.get("/api/crm/bridge/proxy/<path:target_path>")
def api_crm_proxy(target_path: str):
    clean = str(target_path or "").lstrip("/")
    if not _is_safe_local_crm_target(clean):
        return jsonify({"error": "path not allowed"}), 400

    upstream_url = urljoin(f"{CRM_BASE_URL}/", clean)
    if urlsplit(upstream_url).netloc != urlsplit(CRM_BASE_URL).netloc:
        return jsonify({"error": "unsafe upstream target"}), 400

    incoming_qs = request.query_string.decode("utf-8", errors="ignore") if request.query_string else ""
    if incoming_qs:
        joiner = "&" if "?" in upstream_url else "?"
        upstream_url = f"{upstream_url}{joiner}{incoming_qs}"
    elif clean == "api/crm/overview":
        # Defensive default: request a larger lead window from CRM when no explicit limit is provided.
        joiner = "&" if "?" in upstream_url else "?"
        upstream_url = f"{upstream_url}{joiner}limit=500"

    req = Request(upstream_url, method="GET", headers=_crm_auth_headers())
    try:
        body_resp, status_code, headers = _crm_request_with_retry(req, max_attempts=3, timeout=5.0)

        # Intelligent Deduplication Intercept
        if clean == "api/crm/overview" and status_code == 200 and CRM_ENABLE_DEDUP:
            parsed = json.loads(body_resp.decode("utf-8", errors="replace"))
            parsed = _crm_intelligent_deduplication(parsed)
            body_resp = json.dumps(parsed).encode("utf-8")
            if "Content-Length" in headers:
                headers["Content-Length"] = str(len(body_resp))
        elif clean.startswith("api/crm/lead/") and status_code == 200:
            lead_id_str = clean.split("/")[-1]
            absorbed_ids = CRM_MERGED_MAP.get(lead_id_str, [])
            if len(absorbed_ids) > 1:
                parsed_lead = json.loads(body_resp.decode("utf-8", errors="replace"))
                timeline = parsed_lead.get("timeline", [])
                for dup_id in absorbed_ids:
                    if dup_id == lead_id_str: continue
                    dup_req = Request(urljoin(f"{CRM_BASE_URL}/", f"api/crm/lead/{dup_id}"), method="GET", headers=_crm_auth_headers())
                    try:
                        dup_body, d_status, _ = _crm_request_with_retry(dup_req, max_attempts=3, timeout=5.0)
                        if d_status == 200:
                            dup_parsed = json.loads(dup_body.decode("utf-8", errors="replace"))
                            timeline.extend(dup_parsed.get("timeline", []))
                    except Exception:
                        pass
                timeline.sort(key=lambda x: str(x.get("event_at") or x.get("createdAt") or ""), reverse=True)
                parsed_lead["timeline"] = timeline
                body_resp = json.dumps(parsed_lead).encode("utf-8")
                if "Content-Length" in headers:
                    headers["Content-Length"] = str(len(body_resp))

        return (
            body_resp,
            status_code,
            {"Content-Type": headers.get("Content-Type", "application/json")},
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return jsonify({"error": f"crm upstream error: {detail[:300]}"}), int(getattr(exc, "code", 502) or 502)
    except URLError as exc:
        return jsonify({"error": f"crm unreachable: {exc.reason}"}), 503
    except Exception as exc:
        return jsonify({"error": f"crm proxy failed: {exc}"}), 503


@app.post("/api/crm/bridge/application-status")
def api_crm_application_status():
    payload = request.get_json(silent=True) or {}
    app_id = payload.get("id")
    status = str(payload.get("status") or "").strip().lower()
    allowed = {"scheduled", "approved", "enrolled", "paid", "rejected"}

    try:
        app_id_int = int(app_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid application id"}), 400

    if app_id_int <= 0 or status not in allowed:
        return jsonify({"error": "invalid status payload"}), 400

    upstream_url = urljoin(f"{CRM_BASE_URL}/", "api/crm/application-status")
    body = json.dumps({"id": app_id_int, "status": status}).encode("utf-8")
    headers = _crm_auth_headers()
    headers["Content-Type"] = "application/json"
    req = Request(upstream_url, method="POST", headers=headers, data=body)

    try:
        body_resp, status_code, _ = _crm_request_with_retry(req, max_attempts=3, timeout=5.0)
        out = body_resp.decode("utf-8", errors="replace") or "{}"
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = {"raw": out}
        return jsonify({"ok": True, "upstream": parsed}), status_code
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        _queue_crm_failed_event("POST", upstream_url, {"id": app_id_int, "status": status}, f"HTTP {getattr(exc, 'code', 502)}: {detail[:300]}")
        return jsonify({"error": f"crm upstream error (queued for retry): {detail[:300]}"}), int(getattr(exc, "code", 502) or 502)
    except URLError as exc:
        _queue_crm_failed_event("POST", upstream_url, {"id": app_id_int, "status": status}, str(exc.reason))
        return jsonify({"error": f"crm unreachable (queued for retry): {exc.reason}"}), 503
    except Exception as exc:
        _queue_crm_failed_event("POST", upstream_url, {"id": app_id_int, "status": status}, str(exc))
        return jsonify({"error": f"crm status update failed (queued): {exc}"}), 503


@app.post("/api/crm/bridge/lead-update")
@app.post("/mission-control/api/crm/bridge/lead-update")
def api_crm_lead_update():
    payload = request.get_json(silent=True) or {}
    lead_id = payload.get("id")

    try:
        lead_id_int = int(lead_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid lead id"}), 400

    if lead_id_int <= 0:
        return jsonify({"error": "invalid lead id"}), 400

    editable_fields = (
        "name",
        "email",
        "phone",
        "nome_whatsapp",
        "source",
        "current_stage",
        "stage",
        "status",
        "applicationStatus",
    )
    clean_payload: dict[str, Any] = {"id": lead_id_int}
    for key in editable_fields:
        if key in payload:
            value = str(payload.get(key) or "").strip()
            if key == "email" and _is_whatsapp_proxy_email(value):
                value = ""
            if value:
                clean_payload[key] = value

    if len(clean_payload) <= 1:
        return jsonify({"error": "no valid lead fields to update"}), 400

    upstream_url = urljoin(f"{CRM_BASE_URL}/", "api/crm/lead-update")
    body = json.dumps(clean_payload, ensure_ascii=False).encode("utf-8")
    headers = _crm_auth_headers()
    headers["Content-Type"] = "application/json"
    req = Request(upstream_url, method="POST", headers=headers, data=body)

    try:
        body_resp, status_code, _ = _crm_request_with_retry(req, max_attempts=3, timeout=5.0)
        out = body_resp.decode("utf-8", errors="replace") or "{}"
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = {"raw": out}
        return jsonify({"ok": True, "upstream": parsed}), status_code
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        _queue_crm_failed_event("POST", upstream_url, clean_payload, f"HTTP {getattr(exc, 'code', 502)}: {detail[:300]}")
        return jsonify({"error": f"crm upstream error (queued for retry): {detail[:300]}"}), int(getattr(exc, "code", 502) or 502)
    except URLError as exc:
        _queue_crm_failed_event("POST", upstream_url, clean_payload, str(exc.reason))
        return jsonify({"error": f"crm unreachable (queued for retry): {exc.reason}"}), 503
    except Exception as exc:
        _queue_crm_failed_event("POST", upstream_url, clean_payload, str(exc))
        return jsonify({"error": f"crm lead update failed (queued): {exc}"}), 503


@app.post("/api/crm/bridge/lead-delete")
@app.post("/mission-control/api/crm/bridge/lead-delete")
def api_crm_lead_delete():
    payload = request.get_json(silent=True) or {}
    lead_id = payload.get("id")

    try:
        lead_id_int = int(lead_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid lead id"}), 400

    if lead_id_int <= 0:
        return jsonify({"error": "invalid lead id"}), 400

    clean_payload: dict[str, Any] = {"id": lead_id_int}

    upstream_url = urljoin(f"{CRM_BASE_URL}/", "api/crm/lead-delete")
    body = json.dumps(clean_payload, ensure_ascii=False).encode("utf-8")
    headers = _crm_auth_headers()
    headers["Content-Type"] = "application/json"
    req = Request(upstream_url, method="POST", headers=headers, data=body)

    try:
        body_resp, status_code, _ = _crm_request_with_retry(req, max_attempts=3, timeout=5.0)
        out = body_resp.decode("utf-8", errors="replace") or "{}"
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = {"raw": out}

        notes = [item for item in _load_crm_lead_notes() if int(item.get("leadId") or 0) != lead_id_int]
        _save_crm_lead_notes(notes)

        return jsonify({"ok": True, "upstream": parsed, "deletedId": lead_id_int}), status_code
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        _queue_crm_failed_event("POST", upstream_url, clean_payload, f"HTTP {getattr(exc, 'code', 502)}: {detail[:300]}")
        return jsonify({"error": f"crm upstream error (queued for retry): {detail[:300]}"}), int(getattr(exc, "code", 502) or 502)
    except URLError as exc:
        _queue_crm_failed_event("POST", upstream_url, clean_payload, str(exc.reason))
        return jsonify({"error": f"crm unreachable (queued for retry): {exc.reason}"}), 503
    except Exception as exc:
        _queue_crm_failed_event("POST", upstream_url, clean_payload, str(exc))
        return jsonify({"error": f"crm lead delete failed (queued): {exc}"}), 503


@app.post("/api/crm/bridge/lead-merge")
@app.post("/mission-control/api/crm/bridge/lead-merge")
def api_crm_lead_merge():
    payload = request.get_json(silent=True) or {}
    try:
        primary_id = int(payload.get("primaryId"))
        secondary_id = int(payload.get("secondaryId"))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid lead ids"}), 400

    if primary_id <= 0 or secondary_id <= 0 or primary_id == secondary_id:
        return jsonify({"error": "invalid lead ids"}), 400

    merged = payload.get("merged") if isinstance(payload.get("merged"), dict) else {}
    merged_payload = {"primaryId": primary_id, "secondaryId": secondary_id, "merged": merged}

    upstream_url = urljoin(f"{CRM_BASE_URL}/", "api/crm/lead-merge")
    body = json.dumps(merged_payload, ensure_ascii=False).encode("utf-8")
    headers = _crm_auth_headers()
    headers["Content-Type"] = "application/json"
    req = Request(upstream_url, method="POST", headers=headers, data=body)

    try:
        body_resp, status_code, _ = _crm_request_with_retry(req, max_attempts=3, timeout=5.0)
        out = body_resp.decode("utf-8", errors="replace") or "{}"
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError:
            parsed = {"raw": out}

        now = _utc_now_iso()
        status_map = _load_crm_lead_status_map()
        p_status = status_map.get(str(primary_id), {}) if isinstance(status_map, dict) else {}
        s_status = status_map.get(str(secondary_id), {}) if isinstance(status_map, dict) else {}
        if not isinstance(p_status, dict):
            p_status = {}
        if not isinstance(s_status, dict):
            s_status = {}

        merged_status = {
            **p_status,
            "leadId": primary_id,
            "inGroup": _bool_like(p_status.get("inGroup")) or _bool_like(s_status.get("inGroup")),
            "emailOpened": _bool_like(p_status.get("emailOpened")) or _bool_like(s_status.get("emailOpened")),
            "updatedAt": now,
            "updatedBy": "merge",
        }
        status_map[str(primary_id)] = merged_status
        status_map.pop(str(secondary_id), None)
        _save_crm_lead_status_map(status_map)

        events = _load_crm_lead_events()
        for item in events:
            if int(item.get("leadId") or 0) == secondary_id:
                item["leadId"] = primary_id
        events.append({
            "id": f"lead-evt-{int(time.time() * 1000)}-{primary_id}-merge",
            "leadId": primary_id,
            "eventType": "lead_merged",
            "eventAt": now,
            "source": "cockpit",
            "actor": "operator",
            "message": f"Merge realizado: lead #{secondary_id} incorporado em #{primary_id}",
            "data": {"fromLeadId": secondary_id, "toLeadId": primary_id},
            "createdAt": now,
        })
        _save_crm_lead_events(events)

        interactions = _load_crm_interactions()
        for item in interactions:
            if int(item.get("leadId") or 0) == secondary_id:
                item["leadId"] = primary_id
        _save_crm_interactions(interactions)

        notes = _load_crm_lead_notes()
        for item in notes:
            if int(item.get("leadId") or 0) == secondary_id:
                item["leadId"] = primary_id
        _save_crm_lead_notes(notes)

        merged_lead = parsed.get("data", {}).get("lead") if isinstance(parsed, dict) else None
        return jsonify({"ok": True, "upstream": parsed, "primaryId": primary_id, "secondaryId": secondary_id, "mergedLead": merged_lead})
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        _queue_crm_failed_event("POST", upstream_url, merged_payload, f"HTTP {getattr(exc, 'code', 502)}: {detail[:300]}")
        return jsonify({"error": f"crm upstream error (queued for retry): {detail[:300]}"}), int(getattr(exc, "code", 502) or 502)
    except URLError as exc:
        _queue_crm_failed_event("POST", upstream_url, merged_payload, str(exc.reason))
        return jsonify({"error": f"crm unreachable (queued for retry): {exc.reason}"}), 503
    except Exception as exc:
        _queue_crm_failed_event("POST", upstream_url, merged_payload, str(exc))
        return jsonify({"error": f"crm lead merge failed (queued): {exc}"}), 503


@app.get("/api/crm/bridge/interactions/<int:lead_id>")
def api_crm_interactions_list(lead_id: int):
    if lead_id <= 0:
        return jsonify({"error": "invalid lead id"}), 400
    items = [item for item in _load_crm_interactions() if int(item.get("leadId") or 0) == lead_id]
    items.sort(key=lambda item: str(item.get("event_at") or ""), reverse=True)
    return jsonify({"ok": True, "leadId": lead_id, "items": items})


@app.post("/api/crm/bridge/interactions")
def api_crm_interactions_create():
    payload = request.get_json(silent=True) or {}
    lead_id = payload.get("leadId")
    channel = str(payload.get("channel") or "").strip().lower()
    message = str(payload.get("message") or "").strip()

    try:
        lead_id_int = int(lead_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid lead id"}), 400

    if lead_id_int <= 0:
        return jsonify({"error": "invalid lead id"}), 400
    if channel not in {"email", "whatsapp"}:
        return jsonify({"error": "invalid channel"}), 400

    now = _utc_now_iso()
    item = {
        "id": f"crm-int-{int(time.time() * 1000)}-{lead_id_int}",
        "leadId": lead_id_int,
        "channel": channel,
        "event_type": f"contact_{channel}",
        "event_at": now,
        "message": message,
        "createdAt": now,
    }
    interactions = _load_crm_interactions()
    interactions.append(item)
    _save_crm_interactions(interactions)
    return jsonify({"ok": True, "item": item}), 201


@app.get("/api/crm/bridge/notes/<int:lead_id>")
@app.get("/mission-control/api/crm/bridge/notes/<int:lead_id>")
def api_crm_lead_notes_list(lead_id: int):
    if lead_id <= 0:
        return jsonify({"error": "invalid lead id"}), 400

    notes = [item for item in _load_crm_lead_notes() if int(item.get("leadId") or 0) == lead_id]
    notes.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return jsonify({"ok": True, "leadId": lead_id, "items": notes})


@app.post("/api/crm/bridge/notes")
@app.post("/mission-control/api/crm/bridge/notes")
def api_crm_lead_notes_create():
    payload = request.get_json(silent=True) or {}
    try:
        lead_id = int(payload.get("leadId"))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid lead id"}), 400

    if lead_id <= 0:
        return jsonify({"error": "invalid lead id"}), 400

    content = str(payload.get("content") or payload.get("note") or "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400
    if len(content) > 4000:
        return jsonify({"error": "content too long (max 4000 chars)"}), 400

    now = _utc_now_iso()
    item = {
        "id": f"lead-note-{int(time.time() * 1000)}-{lead_id}",
        "leadId": lead_id,
        "content": content,
        "createdAt": now,
        "createdBy": str(payload.get("createdBy") or payload.get("actor") or "operator").strip() or "operator",
        "source": str(payload.get("source") or "cockpit").strip() or "cockpit",
    }

    notes = _load_crm_lead_notes()
    notes.append(item)
    _save_crm_lead_notes(notes)
    return jsonify({"ok": True, "item": item}), 201


@app.get("/api/crm/bridge/lead-operational/<int:lead_id>")
@app.get("/mission-control/api/crm/bridge/lead-operational/<int:lead_id>")
def api_crm_lead_operational_get(lead_id: int):
    if lead_id <= 0:
        return jsonify({"error": "invalid lead id"}), 400

    status_map = _load_crm_lead_status_map()
    status = status_map.get(str(lead_id), {}) if isinstance(status_map, dict) else {}
    if not isinstance(status, dict):
        status = {}

    events = [x for x in _load_crm_lead_events() if int(x.get("leadId") or 0) == lead_id]
    interactions = [x for x in _load_crm_interactions() if int(x.get("leadId") or 0) == lead_id]

    timeline = []
    for item in events + interactions:
        timeline.append({
            "id": str(item.get("id") or ""),
            "eventType": str(item.get("eventType") or item.get("event_type") or "evento"),
            "eventAt": item.get("eventAt") or item.get("event_at") or item.get("createdAt") or _utc_now_iso(),
            "source": str(item.get("source") or "cockpit"),
            "actor": str(item.get("actor") or "system"),
            "message": str(item.get("message") or ""),
            "data": item.get("data") if isinstance(item.get("data"), dict) else {},
        })

    timeline.sort(key=lambda x: str(x.get("eventAt") or ""), reverse=True)
    return jsonify({"ok": True, "leadId": lead_id, "status": status, "timeline": timeline})


@app.post("/api/crm/bridge/lead-operational/<int:lead_id>")
@app.post("/mission-control/api/crm/bridge/lead-operational/<int:lead_id>")
def api_crm_lead_operational_set(lead_id: int):
    if lead_id <= 0:
        return jsonify({"error": "invalid lead id"}), 400

    payload = request.get_json(silent=True) or {}
    actor = str(payload.get("actor") or "cockpit").strip() or "cockpit"
    source = str(payload.get("source") or "manual").strip() or "manual"

    status_map = _load_crm_lead_status_map()
    current = status_map.get(str(lead_id), {}) if isinstance(status_map, dict) else {}
    if not isinstance(current, dict):
        current = {}

    has_group, in_group, has_email, email_opened, has_tags, tags = _lead_status_from_payload(payload)
    if not has_group and not has_email and not has_tags:
        return jsonify({"error": "send inGroup and/or emailOpened and/or tags"}), 400

    next_state = dict(current)
    now = _utc_now_iso()
    created_events: list[dict[str, Any]] = []

    if has_group and (("inGroup" not in current) or _bool_like(current.get("inGroup")) != in_group):
        next_state["inGroup"] = in_group
        created_events.append({
            "id": f"lead-evt-{int(time.time() * 1000)}-{lead_id}-group",
            "leadId": lead_id,
            "eventType": "group_membership_changed",
            "eventAt": now,
            "source": source,
            "actor": actor,
            "message": f"Lead {'entrou' if in_group else 'saiu'} do grupo",
            "data": {"inGroup": in_group},
            "createdAt": now,
        })

    if has_email and (("emailOpened" not in current) or _bool_like(current.get("emailOpened")) != email_opened):
        next_state["emailOpened"] = email_opened
        created_events.append({
            "id": f"lead-evt-{int(time.time() * 1000)}-{lead_id}-email",
            "leadId": lead_id,
            "eventType": "email_open_status_changed",
            "eventAt": now,
            "source": source,
            "actor": actor,
            "message": f"E-mail {'aberto' if email_opened else 'não aberto'}",
            "data": {"emailOpened": email_opened},
            "createdAt": now,
        })

    if has_tags:
        current_tags = _normalize_tags(current.get("tags") or [])
        if current_tags != tags:
            next_state["tags"] = tags
            created_events.append({
                "id": f"lead-evt-{int(time.time() * 1000)}-{lead_id}-tags",
                "leadId": lead_id,
                "eventType": "lead_tags_updated",
                "eventAt": now,
                "source": source,
                "actor": actor,
                "message": "Tags do lead atualizadas",
                "data": {"tags": tags},
                "createdAt": now,
            })

    next_state["leadId"] = lead_id
    next_state["updatedAt"] = now
    next_state["updatedBy"] = actor
    status_map[str(lead_id)] = next_state
    _save_crm_lead_status_map(status_map)

    if created_events:
        events = _load_crm_lead_events()
        events.extend(created_events)
        _save_crm_lead_events(events)

    return jsonify({"ok": True, "leadId": lead_id, "status": next_state, "eventsCreated": created_events})


@app.post("/api/crm/bridge/lead-events")
def api_crm_lead_event_create():
    payload = request.get_json(silent=True) or {}
    try:
        lead_id = int(payload.get("leadId"))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid lead id"}), 400
    if lead_id <= 0:
        return jsonify({"error": "invalid lead id"}), 400

    event_type = str(payload.get("eventType") or payload.get("event_type") or "manual_event").strip()
    if not event_type:
        return jsonify({"error": "eventType is required"}), 400

    now = _utc_now_iso()
    item = {
        "id": f"lead-evt-{int(time.time() * 1000)}-{lead_id}",
        "leadId": lead_id,
        "eventType": event_type,
        "eventAt": payload.get("eventAt") or payload.get("event_at") or now,
        "source": str(payload.get("source") or "manual"),
        "actor": str(payload.get("actor") or "cockpit"),
        "message": str(payload.get("message") or "").strip(),
        "data": payload.get("data") if isinstance(payload.get("data"), dict) else {},
        "createdAt": now,
    }

    events = _load_crm_lead_events()
    events.append(item)
    _save_crm_lead_events(events)
    return jsonify({"ok": True, "item": item}), 201


def _parse_crm_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None



def _crm_request_with_retry(req: Request, max_attempts: int = 3, timeout: float = 5.0) -> tuple[bytes, int, dict[str, str]]:
    import time
    last_exc = None
    for attempt in range(max_attempts):
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                headers = {k: v for k, v in resp.headers.items()}
                return body, int(getattr(resp, "status", 200)), headers
        except HTTPError as exc:
            code = int(getattr(exc, "code", 500))
            if code < 500 and code != 429:
                raise exc
            last_exc = exc
        except URLError as exc:
            last_exc = exc
        except Exception as exc:
            last_exc = exc

        if attempt < max_attempts - 1:
            time.sleep(0.5 * (2 ** attempt))

    raise last_exc



@app.get("/api/crm/bridge/failed-events")
def api_crm_failed_events_list():
    items = _load_crm_failed_events()
    return jsonify({"ok": True, "items": items})

@app.post("/api/crm/bridge/failed-events/<event_id>/retry")
def api_crm_failed_events_retry(event_id: str):
    items = _load_crm_failed_events()
    event = next((i for i in items if i["id"] == event_id), None)
    if not event:
        return jsonify({"error": "event not found"}), 404

    req = Request(event["path"], method=event["method"], headers=_crm_auth_headers())
    if event["payload"]:
        req.data = json.dumps(event["payload"]).encode("utf-8")
        req.headers["Content-Type"] = "application/json"

    try:
        _crm_request_with_retry(req, max_attempts=1, timeout=5.0)
        items = [i for i in items if i["id"] != event_id]
        _save_crm_failed_events(items)
        return jsonify({"ok": True})
    except Exception as exc:
        event["retries"] += 1
        event["error"] = str(exc)
        _save_crm_failed_events(items)
        return jsonify({"error": str(exc)}), 500


def _is_whatsapp_placeholder_name(value: Any) -> bool:
    txt = str(value or "").strip()
    if not txt:
        return False
    txt_norm = re.sub(r"\s+", " ", txt).strip().lower()
    # Ex.: "Contato Whatsapp 1234" / "Contato WhatsApp XXXX"
    return bool(re.match(r"^contato\s+whats ?app\s+[\w-]{2,}$", txt_norm))


def _is_whatsapp_proxy_email(value: Any) -> bool:
    txt = str(value or "").strip().lower()
    return txt.endswith("@whatsapp.local") and txt.startswith("wa-")


def _sanitize_lead_display_names(lead: dict[str, Any]) -> dict[str, Any]:
    clean = dict(lead)
    for field in ("name", "full_name", "nome_whatsapp"):
        if _is_whatsapp_placeholder_name(clean.get(field)):
            clean[field] = ""
    if _is_whatsapp_proxy_email(clean.get("email")):
        clean["email"] = ""
    return clean


def _fetch_crm_overview() -> tuple[list[dict[str, Any]], int | None, str | None]:
    upstream_url = urljoin(f"{CRM_BASE_URL}/", "api/crm/overview")
    req = Request(upstream_url, method="GET", headers=_crm_auth_headers())
    try:
        body, status, _ = _crm_request_with_retry(req, max_attempts=3, timeout=5.0)
        parsed = json.loads((body or b"{}").decode("utf-8", errors="replace"))
    except Exception as exc:
        return [], None, str(exc)

    leads = parsed.get("leads") if isinstance(parsed, dict) else None
    if not isinstance(leads, list):
        return [], None, "invalid crm overview payload"

    total_leads = None
    if isinstance(parsed, dict):
        totals = parsed.get("totals")
        if isinstance(totals, dict):
            total_leads = _as_int(totals.get("leads"))

    sanitized = [_sanitize_lead_display_names(item) for item in leads if isinstance(item, dict)]
    return sanitized, total_leads, None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return None
    return iv if iv >= 0 else None


def _build_openclaw_usage_summary(window_hours: int = 24) -> dict[str, Any]:
    sessions_payload = _run_openclaw_json(["sessions"])
    status_payload = _run_openclaw_json(["status", "--usage"], timeout=40)

    sessions = sessions_payload.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []

    now_ms = int(time.time() * 1000)
    window_ms = max(1, int(window_hours)) * 60 * 60 * 1000
    cutoff_ms = now_ms - window_ms

    model_counts: dict[str, int] = {}
    input_tokens_total = 0
    output_tokens_total = 0
    total_tokens_total = 0
    token_samples = 0
    window_requests = 0

    for sess in sessions:
        if not isinstance(sess, dict):
            continue
        model = str(sess.get("model") or sess.get("modelOverride") or "unknown").strip() or "unknown"
        model_counts[model] = model_counts.get(model, 0) + 1

        updated_at = _as_int(sess.get("updatedAt"))
        if updated_at is not None and updated_at >= cutoff_ms:
            window_requests += 1

        in_tok = _as_int(sess.get("inputTokens"))
        out_tok = _as_int(sess.get("outputTokens"))
        total_tok = _as_int(sess.get("totalTokens"))
        if in_tok is not None:
            input_tokens_total += in_tok
        if out_tok is not None:
            output_tokens_total += out_tok
        if total_tok is not None:
            total_tokens_total += total_tok
        if in_tok is not None or out_tok is not None or total_tok is not None:
            token_samples += 1

    total_requests = _as_int(sessions_payload.get("count"))
    if total_requests is None:
        total_requests = len(sessions)

    model_distribution = [
        {
            "model": model,
            "count": count,
            "pct": round((count / total_requests) * 100, 1) if total_requests > 0 else 0.0,
        }
        for model, count in sorted(model_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    usage = status_payload.get("usage", {}) if isinstance(status_payload, dict) else {}
    providers = usage.get("providers", []) if isinstance(usage, dict) else []
    if not isinstance(providers, list):
        providers = []

    return {
        "ok": True,
        "source": {
            "sessions": "openclaw sessions --json",
            "statusUsage": "openclaw status --usage --json",
            "scope": "current default agent sessions",
        },
        "requests": {
            "total": total_requests,
            "windowHours": max(1, int(window_hours)),
            "windowCount": window_requests,
            "windowSupported": True,
        },
        "models": {
            "distribution": model_distribution,
            "topModel": model_distribution[0]["model"] if model_distribution else None,
        },
        "cost": {
            "estimatedUsd": None,
            "available": False,
            "note": "OpenClaw CLI JSON exposes quota windows and token/session metrics here, but not a local USD total.",
        },
        "tokens": {
            "available": token_samples > 0,
            "input": input_tokens_total if token_samples > 0 else None,
            "output": output_tokens_total if token_samples > 0 else None,
            "total": total_tokens_total if token_samples > 0 else None,
            "sampledSessions": token_samples,
            "totalSessions": total_requests,
            "note": None if token_samples > 0 else "Token fields are missing in session payload for this provider/auth flow.",
        },
        "providerUsage": {
            "available": len(providers) > 0,
            "updatedAt": usage.get("updatedAt") if isinstance(usage, dict) else None,
            "providers": providers,
        },
    }


@app.get("/api/agents/overview")
def api_agents_overview():
    try:
        sessions = _load_openclaw_sessions()
        profiles = _load_agent_profiles()
        changed = False
        for sess in sessions:
            display_id = _display_agent_id_from_session_key(str(sess.get("key", "")))
            if display_id:
                changed = _ensure_profile(display_id, profiles) or changed
        if changed:
            _save_agent_profiles(profiles)

        type_filter = str(request.args.get("type") or "").strip().lower()
        status_filter = str(request.args.get("status") or "").strip().lower()
        query = str(request.args.get("q") or "").strip()
        sort_by = str(request.args.get("sort") or "").strip().lower()
        try:
            limit = int(request.args.get("limit") or 40)
        except ValueError:
            limit = 40

        raw_offset = request.args.get("offset")
        raw_page = request.args.get("page")
        pagination_mode = "offset" if raw_offset not in (None, "") else "page"
        try:
            offset = int(raw_offset) if raw_offset not in (None, "") else None
        except ValueError:
            offset = None

        try:
            page = int(raw_page or 1)
        except ValueError:
            page = 1

        effective_limit = max(1, min(limit, 200))
        if offset is None:
            safe_page = max(1, page)
            offset = (safe_page - 1) * effective_limit

        return jsonify(
            _build_agents_overview(
                sessions,
                profiles,
                type_filter=type_filter,
                status_filter=status_filter,
                query=query,
                sort_by=sort_by,
                limit=limit,
                offset=offset,
                page=page,
                pagination_mode=pagination_mode,
            )
        )
    except (RuntimeError, json.JSONDecodeError, ValueError) as exc:
        return jsonify({"error": f"agent overview unavailable: {exc}"}), 503


@app.get("/api/agents/ids")
def api_agent_ids():
    try:
        sessions = _load_openclaw_sessions()
        matrix = _load_permissions()
        layout = _load_office_layout()
        profiles = _load_agent_profiles()
        ids = _agents_from_sessions(sessions)
        for sess in sessions:
            display_id = _display_agent_id_from_session_key(str(sess.get("key", "")))
            if display_id and display_id not in ids:
                ids.append(display_id)
        for agent_id in matrix.get("agents", {}).keys():
            aid = str(agent_id)
            if aid and aid not in ids:
                ids.append(aid)
        for agent_id in layout.get("desks", {}).keys():
            aid = str(agent_id)
            if aid and aid not in ids:
                ids.append(aid)

        changed = False
        for aid in ids:
            changed = _ensure_profile(aid, profiles) or changed
        if changed:
            _save_agent_profiles(profiles)

        ids.sort()
        return jsonify({
            "items": ids,
            "profiles": {aid: profiles.get("agents", {}).get(aid, {}) for aid in ids},
        })
    except (RuntimeError, json.JSONDecodeError, ValueError) as exc:
        return jsonify({"error": f"agent list unavailable: {exc}"}), 503


@app.get("/api/agents/profiles")
def api_agents_profiles():
    try:
        profiles = _load_agent_profiles()
        return jsonify(profiles)
    except (json.JSONDecodeError, ValueError) as exc:
        return jsonify({"error": f"agent profiles unavailable: {exc}"}), 503


@app.put("/api/agents/profiles/<agent_id>")
def api_put_agent_profile(agent_id: str):
    if not AGENT_ID_RE.match(agent_id):
        return jsonify({"error": "invalid agent id"}), 400

    payload = request.get_json(silent=True) or {}
    display_name = str(payload.get("displayName") or payload.get("alias") or "").strip()
    if not display_name:
        return jsonify({"error": "displayName is required"}), 400

    profiles = _load_agent_profiles()
    prior = profiles.setdefault("agents", {}).get(agent_id, {})
    profiles.setdefault("agents", {})[agent_id] = {
        "agentId": agent_id,
        "displayName": display_name,
        "department": _normalize_department(agent_id, prior.get("department")),
        "lifecycle": str(prior.get("lifecycle") or _default_lifecycle(agent_id)),
        "updatedAt": _utc_now_iso(),
    }
    _save_agent_profiles(profiles)
    return jsonify(profiles["agents"][agent_id])



def _normalize_phone_digits(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("55") and len(digits) >= 12:
        return digits
    if len(digits) in {10, 11}:
        return f"55{digits}"
    return digits


def _chat_id_from_target(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    if "@" in raw:
        left, _, domain = raw.partition("@")
        domain = domain.strip().lower()
        left = str(left or "").strip().lower()
        if not domain:
            return ""
        if domain == "s.whatsapp.net":
            digits = _normalize_phone_digits(left)
            left = digits or left
        # Keep @lid verbatim (do not coerce to phone digits).
        return f"{left}@{domain}" if left else ""

    digits = _normalize_phone_digits(raw)
    if digits:
        return f"{digits}@s.whatsapp.net"
    return raw.lower()


def _chat_digits_from_conversation_id(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "@" in raw:
        left, _, domain = raw.partition("@")
        if domain == "s.whatsapp.net":
            return _normalize_phone_digits(left)
        # @lid is an internal WhatsApp identifier, not a reliable phone.
        return ""
    return _normalize_phone_digits(raw)


def _chat_pretty_phone(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw.endswith("@lid"):
        return ""
    digits = _normalize_phone_digits(value)
    if not digits:
        return ""
    return f"+{digits}"


def _chat_display_title(name: str, conversation_id: str) -> str:
    clean_name = str(name or "").strip()
    if clean_name and "@" not in clean_name:
        return clean_name
    pretty_phone = _chat_pretty_phone(conversation_id)
    if pretty_phone:
        return pretty_phone
    normalized = _chat_id_from_target(conversation_id)
    if normalized.endswith("@g.us"):
        return "Grupo WhatsApp"
    return "Conversa WhatsApp"


def _chat_cli_target(conversation_id: str) -> str:
    cid = str(conversation_id or "").strip()
    if not cid:
        return ""
    if "@" in cid:
        return cid
    digits = _normalize_phone_digits(cid)
    if digits:
        return f"+{digits}"
    return cid


def _chat_parse_ts_to_ms(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        iv = int(value)
        if iv > 10**12:
            return iv
        if iv > 10**9:
            return iv * 1000
        return 0
    txt = str(value or "").strip()
    if not txt:
        return 0
    try:
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return 0


def _chat_fmt_hhmm(ms: int) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%H:%M")
    except Exception:
        return ""


def _load_chat_links() -> dict[str, Any]:
    _ensure_store()
    try:
        parsed = json.loads(CHAT_LINKS_FILE.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _save_chat_links(items: dict[str, Any]) -> None:
    _ensure_store()
    CHAT_LINKS_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_chat_log_index() -> dict[str, Any]:
    _ensure_store()
    try:
        parsed = json.loads(CHAT_LOG_INDEX_FILE.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _save_chat_log_index(items: dict[str, Any]) -> None:
    _ensure_store()
    CHAT_LOG_INDEX_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_chat_conversations_cache() -> list[dict[str, Any]]:
    try:
        parsed = json.loads(CHAT_CONVERSATIONS_CACHE_FILE.read_text(encoding="utf-8") or "[]")
        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _save_chat_conversations_cache(items: list[dict[str, Any]]) -> None:
    _ensure_store()
    CHAT_CONVERSATIONS_CACHE_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _openclaw_message_json(args: list[str], timeout: int = 25) -> Any:
    proc = subprocess.run(
        ["openclaw", "message", *args, "--json"],
        cwd=str(BASE_DIR),
        timeout=timeout,
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "message command failed").strip())
    raw = (proc.stdout or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        starts = [i for i in [raw.find("{"), raw.find("[")] if i >= 0]
        if not starts:
            return {}
        return json.loads(raw[min(starts):])


def _chat_extract_message_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "messages", "events", "data", "chats"):
        val = payload.get(key)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]
    return []


def _chat_extract_text(item: dict[str, Any]) -> str:
    for key in ("text", "message", "body", "content", "caption", "preview", "lastMessage", "last_message"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    payload = item.get("payload")
    if isinstance(payload, dict):
        for key in ("text", "message", "body", "conversation"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def _chat_is_noise_text(value: Any) -> bool:
    txt = str(value or "").strip()
    if not txt:
        return True
    # ruído comum: payload contendo apenas timestamp/date
    if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$", txt):
        return True
    return False


def _chat_target_from_item(item: dict[str, Any]) -> str:
    # Strong identity rule: only accept explicit conversation/chat JIDs.
    # Never infer from generic fields like `from`/`to`/`id` to avoid cross-thread contamination.
    for key in ("chatId", "conversationId", "threadId", "jid", "target"):
        val = item.get(key)
        cid = _chat_id_from_target(val)
        if cid and "@" in cid:
            return cid

    payload = item.get("payload")
    if isinstance(payload, dict):
        for key in ("chatId", "conversationId", "threadId", "jid", "target"):
            cid = _chat_id_from_target(payload.get(key))
            if cid and "@" in cid:
                return cid

    key_payload = item.get("key")
    if isinstance(key_payload, dict):
        cid = _chat_id_from_target(key_payload.get("remoteJid"))
        if cid and "@" in cid:
            return cid

    return ""


def _baileys_base_url() -> str:
    # Default local Baileys backend for cockpit chat.
    return str(os.environ.get("OPENCLAW_BAILEYS_API_BASE_URL") or "http://127.0.0.1:8790/wa").strip().rstrip("/")


def _baileys_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = str(os.environ.get("OPENCLAW_BAILEYS_API_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _baileys_timeout_seconds(default: float = 4.5) -> float:
    raw = str(os.environ.get("OPENCLAW_BAILEYS_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
        return min(20.0, max(0.5, val))
    except ValueError:
        return default


def _baileys_request(path: str, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
    base = _baileys_base_url()
    if not base:
        raise RuntimeError("Baileys API base URL não configurada")

    req_body: bytes | None = None
    headers = _baileys_headers()
    if payload is not None:
        req_body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(urljoin(base + "/", path.lstrip("/")), method=method.upper(), headers=headers, data=req_body)
    try:
        with urlopen(req, timeout=timeout or _baileys_timeout_seconds()) as resp:
            raw = (resp.read() or b"{}").decode("utf-8", errors="replace")
    except HTTPError as exc:
        raw = (exc.read() or b"").decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        detail = ""
        try:
            parsed = json.loads(raw or "{}")
            detail = str(parsed.get("error") or parsed.get("message") or "").strip()
        except Exception:
            detail = raw.strip()
        raise RuntimeError(detail or f"Baileys API erro HTTP {int(getattr(exc, 'code', 500))}")
    except URLError as exc:
        raise RuntimeError(f"Baileys indisponível: {exc.reason}")
    except Exception as exc:
        raise RuntimeError(f"Falha ao consultar Baileys: {exc}")

    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        raise RuntimeError("Resposta inválida da API Baileys")
    if isinstance(parsed, dict):
        return parsed
    return {"items": _chat_extract_message_items(parsed)}


def _chat_normalize_message(item: dict[str, Any], conversation_hint: str = "") -> dict[str, Any] | None:
    cid = _chat_target_from_item(item) or _chat_id_from_target(conversation_hint)
    if not cid:
        return None
    msg_id = str(item.get("id") or item.get("messageId") or item.get("key") or "").strip()
    if not msg_id:
        msg_id = f"msg-{hashlib.sha1(json.dumps(item, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]}"
    ts_ms = _chat_parse_ts_to_ms(item.get("timestamp") or item.get("ts") or item.get("messageTimestamp") or item.get("createdAt") or item.get("time"))
    direction = "outbound" if bool(item.get("fromMe") or str(item.get("direction") or "").lower() in {"out", "outbound", "sent"}) else "inbound"
    text = _chat_extract_text(item)
    if _chat_is_noise_text(text):
        text = ""
    return {
        "id": msg_id,
        "conversationId": cid,
        "timestampMs": ts_ms,
        "timestamp": _ms_to_iso(ts_ms),
        "direction": direction,
        "sender": "me" if direction == "outbound" else "contact",
        "text": text,
        "raw": item,
    }


def _chat_baileys_status() -> dict[str, Any]:
    payload = _baileys_request("/status", timeout=2.0)
    connected = bool(payload.get("ok") if "ok" in payload else payload.get("connected"))
    if "state" in payload and isinstance(payload.get("state"), str):
        state = str(payload.get("state") or "").strip()
        if state:
            connected = state.lower() in {"connected", "open", "online", "ready"}
    return {
        "ok": True,
        "online": connected,
        "state": str(payload.get("state") or ("online" if connected else "offline")),
        "source": "baileys",
    }


def _chat_fetch_conversations_from_baileys(limit: int = 100) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(int(limit), 300))
    payload = _baileys_request(f"/chats?limit={bounded_limit}", timeout=_baileys_timeout_seconds(6.0))
    return _chat_extract_message_items(payload)


def _chat_fetch_messages_from_baileys(conversation_id: str, limit: int = 250) -> list[dict[str, Any]]:
    cid = _chat_id_from_target(conversation_id)
    if not cid:
        return []
    bounded_limit = max(1, min(int(limit), 600))
    payload = _baileys_request(f"/chats/{cid}/messages?limit={bounded_limit}", timeout=_baileys_timeout_seconds(6.5))
    raw_items = _chat_extract_message_items(payload)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_items:
        norm = _chat_normalize_message(item, conversation_hint=cid)
        if not norm:
            continue
        dedupe = f"{norm['conversationId']}|{norm['id']}"
        if dedupe in seen:
            continue
        seen.add(dedupe)
        out.append(norm)
    out.sort(key=lambda x: (int(x.get("timestampMs") or 0), str(x.get("id") or "")))
    return out


def _chat_match_lead_by_phone(conversation_id: str, leads: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = _chat_digits_from_conversation_id(conversation_id)
    if not target:
        return None

    exact_matches: list[dict[str, Any]] = []
    fallback_matches: list[dict[str, Any]] = []
    for lead in leads:
        if not isinstance(lead, dict):
            continue
        phones = {
            _normalize_phone_digits(lead.get("phone")),
            _normalize_phone_digits(lead.get("whatsapp")),
            _normalize_phone_digits(lead.get("phone_number")),
            _normalize_phone_digits(lead.get("mobile")),
        }
        phones.discard("")
        if not phones:
            continue
        if target in phones:
            exact_matches.append(lead)
            continue

        # Fallback de alta confiança: diferença apenas de prefixo de país (+55).
        # Se houver ambiguidade, não faz auto-link.
        if target.startswith("55") and target[2:] in phones:
            fallback_matches.append(lead)
        elif f"55{target}" in phones:
            fallback_matches.append(lead)

    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None
    if len(fallback_matches) == 1:
        return fallback_matches[0]
    return None


def _chat_link_lookup(links: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    if not isinstance(links, dict):
        return {}
    cid = _chat_id_from_target(conversation_id)
    candidates = [cid]
    digits = _chat_digits_from_conversation_id(cid)
    if digits:
        candidates.extend([digits, f"+{digits}"])
    for key in candidates:
        val = links.get(key)
        if isinstance(val, dict):
            return val
    return {}


def _chat_sync_interaction_once(lead_id: int, msg: dict[str, Any], conversation_id: str) -> None:
    digest_src = f"{conversation_id}|{msg.get('id')}|{msg.get('direction')}|{msg.get('text')}|{msg.get('timestamp')}"
    digest = hashlib.sha1(digest_src.encode("utf-8")).hexdigest()
    idx = _load_chat_log_index()
    if idx.get(digest):
        return
    interactions = _load_crm_interactions()
    interactions.append({
        "id": f"crm-chat-{digest[:16]}",
        "leadId": int(lead_id),
        "channel": "whatsapp",
        "event_type": "chat_outbound" if msg.get("direction") == "outbound" else "chat_inbound",
        "event_at": msg.get("timestamp") or _utc_now_iso(),
        "message": str(msg.get("text") or "").strip()[:4000],
        "createdAt": _utc_now_iso(),
    })
    _save_crm_interactions(interactions)
    idx[digest] = {"leadId": int(lead_id), "at": _utc_now_iso()}
    _save_chat_log_index(idx)




def _chat_alias_index(raw_convs: list[dict[str, Any]]) -> dict[str, Any]:
    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_convs:
        cid = _chat_id_from_target(item.get("id") or item.get("chatId") or item.get("conversationId") or item.get("jid") or "")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        ts_ms = _chat_parse_ts_to_ms(item.get("lastAt") or item.get("lastTimestamp") or item.get("timestamp") or item.get("lastMessageAt") or item.get("updatedAt"))
        prepared.append({"item": item, "cid": cid, "ts_ms": int(ts_ms or 0)})

    numeric = [x for x in prepared if str(x.get("cid") or "").endswith("@s.whatsapp.net")]
    canonical_for: dict[str, str] = {}

    for row in prepared:
        cid = str(row.get("cid") or "")
        canonical_for[cid] = cid

    for row in prepared:
        cid = str(row.get("cid") or "")
        if not cid.endswith("@lid"):
            continue
        ts = int(row.get("ts_ms") or 0)
        best = None
        best_delta = None
        for cand in numeric:
            delta = abs(int(cand.get("ts_ms") or 0) - ts)
            if best is None or best_delta is None or delta < best_delta:
                best = cand
                best_delta = delta
        if best and best_delta is not None and best_delta <= 45 * 60 * 1000:
            canonical_for[cid] = str(best.get("cid") or cid)

    aliases_by_canon: dict[str, list[str]] = {}
    for cid, canon in canonical_for.items():
        aliases_by_canon.setdefault(canon, []).append(cid)

    return {"prepared": prepared, "canonical_for": canonical_for, "aliases_by_canon": aliases_by_canon}


def _chat_collect_recent_messages_for_aliases(aliases: list[str], limit_per_alias: int = 30) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for alias in aliases:
        try:
            msgs = _chat_fetch_messages_from_baileys(alias, limit=limit_per_alias)
        except Exception:
            continue
        for msg in msgs:
            txt = str(msg.get("text") or "").strip()
            if _chat_is_noise_text(txt):
                continue
            key = f"{msg.get('id')}|{msg.get('timestampMs')}|{msg.get('direction')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(msg)
    merged.sort(key=lambda x: (int(x.get("timestampMs") or 0), str(x.get("id") or "")))
    return merged


def _chat_pick_preview_for_aliases(aliases: list[str]) -> str:
    merged = _chat_collect_recent_messages_for_aliases(aliases, limit_per_alias=25)
    for msg in reversed(merged):
        txt = str(msg.get("text") or "").strip()
        if _chat_is_noise_text(txt):
            continue
        return txt
    return "Sem mensagens"


def _chat_number_label_for_aliases(canon: str, aliases: list[str]) -> str:
    # Regra de UX: lista sempre mostra número (nunca "Contato WhatsApp XXXX")
    candidates = [canon, *aliases]
    for cid in candidates:
        pretty = _chat_pretty_phone(cid)
        if pretty:
            return pretty

    # fallback: usa dígitos do localpart do JID (@lid etc)
    for cid in candidates:
        left = str(cid or "").split("@", 1)[0]
        digits = "".join(ch for ch in left if ch.isdigit())
        if digits:
            return f"+{digits}"

    return "+contato"


def _chat_conversation_dedupe_key(item: dict[str, Any]) -> str:
    phone = str(item.get("phone") or "").strip()
    cid = str(item.get("id") or "").strip()
    digits = _normalize_phone_digits(phone) or _chat_digits_from_conversation_id(cid)
    if digits:
        # normaliza para evitar duplicidade entre +55... e variantes
        if len(digits) >= 11:
            return f"p:{digits[-11:]}"
        if len(digits) >= 10:
            return f"p:{digits[-10:]}"
        return f"p:{digits}"
    return f"id:{cid}"


def _chat_dedupe_conversations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dedup: dict[str, dict[str, Any]] = {}
    for item in items or []:
        key = _chat_conversation_dedupe_key(item)
        prev = dedup.get(key)
        if not prev:
            dedup[key] = dict(item)
            continue

        prev_ts = int(prev.get("lastAtMs") or 0)
        curr_ts = int(item.get("lastAtMs") or 0)
        base = dict(item if curr_ts >= prev_ts else prev)
        other = prev if curr_ts >= prev_ts else item

        base["unreadCount"] = max(int(base.get("unreadCount") or 0), int(other.get("unreadCount") or 0))

        msg_base = str(base.get("lastMessage") or "").strip().lower()
        msg_other = str(other.get("lastMessage") or "").strip()
        if (not msg_base or msg_base == "sem mensagens") and msg_other:
            base["lastMessage"] = msg_other

        # agrega aliases para debug/consistência
        aliases = []
        for part in (base.get("aliases") or [], other.get("aliases") or []):
            s = str(part or "").strip()
            if s and s not in aliases:
                aliases.append(s)
        if aliases:
            base["aliases"] = aliases

        dedup[key] = base

    out = list(dedup.values())
    out.sort(key=lambda x: (int(x.get("lastAtMs") or 0), str(x.get("name") or "")), reverse=True)
    return out


def _chat_build_conversations(limit: int = 250) -> list[dict[str, Any]]:
    raw_convs = _chat_fetch_conversations_from_baileys(limit=limit)
    leads, _total, _err = _fetch_crm_overview()
    links = _load_chat_links()

    idx = _chat_alias_index(raw_convs)
    prepared = idx.get("prepared", [])
    aliases_by_canon = idx.get("aliases_by_canon", {})

    by_cid = {str(x.get("cid") or ""): x for x in prepared}

    out: list[dict[str, Any]] = []
    for canon, aliases in aliases_by_canon.items():
        rows = [by_cid[a] for a in aliases if a in by_cid]
        if not rows:
            continue

        rows.sort(key=lambda r: int(r.get("ts_ms") or 0), reverse=True)
        newest = rows[0]
        newest_item = newest.get("item", {}) if isinstance(newest.get("item"), dict) else {}
        ts_ms = int(newest.get("ts_ms") or 0)

        # Simples e previsível: unread do backend agregado por máximo entre aliases
        unread = 0
        for r in rows:
            item = r.get("item", {}) if isinstance(r.get("item"), dict) else {}
            unread = max(unread, int(item.get("unreadCount") or item.get("unread") or 0))

        phone_label = _chat_number_label_for_aliases(canon, aliases)
        title = phone_label

        # lead lookup por canônico e aliases
        lead = _chat_match_lead_by_phone(canon, leads)
        if not lead:
            for a in aliases:
                lead = _chat_match_lead_by_phone(a, leads)
                if lead:
                    break
        if not lead:
            linked = _chat_link_lookup(links, canon)
            if not linked:
                for a in aliases:
                    linked = _chat_link_lookup(links, a)
                    if linked:
                        break
            if linked:
                linked_id = int(linked.get("leadId") or 0)
                lead = next((l for l in leads if int(l.get("id") or 0) == linked_id), None)

        lead_id = int(lead.get("id") or 0) if isinstance(lead, dict) else 0
        lead_name = str(lead.get("name") or lead.get("full_name") or lead.get("email") or "").strip() if isinstance(lead, dict) else ""

        preview = ""
        for r in rows:
            item = r.get("item", {}) if isinstance(r.get("item"), dict) else {}
            raw_preview = _chat_extract_text(item)
            if not _chat_is_noise_text(raw_preview):
                preview = raw_preview
                break
        if not preview:
            preview = _chat_pick_preview_for_aliases(aliases)

        out.append({
            "id": canon,
            "aliases": aliases,
            "name": title,
            "phone": phone_label,
            "lastMessage": preview or "Sem mensagens",
            "lastAt": _ms_to_iso(ts_ms) if ts_ms else None,
            "lastAtMs": ts_ms,
            "lastAtLabel": _chat_fmt_hhmm(ts_ms),
            "unreadCount": unread,
            "lead": ({"id": lead_id, "name": lead_name} if lead_id > 0 else None),
        })

    out = _chat_dedupe_conversations(out)
    return out[: max(20, min(int(limit), 300))]


def _chat_resolve_lead_for_conversation(conversation_id: str, leads: list[dict[str, Any]], links: dict[str, Any]) -> dict[str, Any] | None:
    cid = _chat_id_from_target(conversation_id)
    if not cid:
        return None
    lead = _chat_match_lead_by_phone(cid, leads)
    if lead:
        return lead
    linked = _chat_link_lookup(links, cid)
    linked_id = int(linked.get("leadId") or 0)
    if linked_id <= 0:
        return None
    return next((l for l in leads if int(l.get("id") or 0) == linked_id), None)


def _crm_stage_key(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    raw = raw.replace("_", " ").replace("/", " ")
    return " ".join(raw.split())


def _crm_is_closed_stage(value: Any) -> bool:
    return _crm_stage_key(value) in CLOSED_STAGE_KEYS


def _chat_apply_post_send_stage_transition(target: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        leads, _total, _err = _fetch_crm_overview()
        links = _load_chat_links()

        lead: dict[str, Any] | None = None
        try:
            payload_lead_id = int(payload.get("leadId") or 0)
        except (TypeError, ValueError):
            payload_lead_id = 0

        if payload_lead_id > 0:
            lead = next((l for l in leads if int(l.get("id") or 0) == payload_lead_id), None)
        if not lead:
            lead = _chat_resolve_lead_for_conversation(target, leads, links)
        if not lead:
            return {"ok": False, "reason": "lead_not_resolved"}

        lead_id = int(lead.get("id") or 0)
        if lead_id <= 0:
            return {"ok": False, "reason": "lead_not_resolved"}

        current_stage = str(lead.get("current_stage") or lead.get("stage") or lead.get("status") or lead.get("applicationStatus") or "").strip()
        if _crm_is_closed_stage(current_stage):
            return {"ok": True, "skipped": True, "reason": "protected_closed_stage", "leadId": lead_id, "currentStage": current_stage}
        if _crm_stage_key(current_stage) == _crm_stage_key(AUTO_OUTREACH_STAGE):
            return {"ok": True, "skipped": True, "reason": "already_target_stage", "leadId": lead_id, "currentStage": current_stage}

        clean_payload = {"id": lead_id, "current_stage": AUTO_OUTREACH_STAGE, "stage": AUTO_OUTREACH_STAGE, "status": AUTO_OUTREACH_STAGE}
        upstream_url = urljoin(f"{CRM_BASE_URL}/", "api/crm/lead-update")
        body = json.dumps(clean_payload, ensure_ascii=False).encode("utf-8")
        headers = _crm_auth_headers()
        headers["Content-Type"] = "application/json"
        req = Request(upstream_url, method="POST", headers=headers, data=body)
        _crm_request_with_retry(req, max_attempts=3, timeout=5.0)

        note_now = _utc_now_iso()
        note_item = {
            "id": f"lead-note-{int(time.time() * 1000)}-{lead_id}",
            "leadId": lead_id,
            "content": f"Mudança automática de estágio após envio no chat: '{current_stage or '-'}' → '{AUTO_OUTREACH_STAGE}'.",
            "createdAt": note_now,
            "createdBy": "system",
            "source": "chat_send_auto_stage",
        }
        notes = _load_crm_lead_notes()
        notes.append(note_item)
        _save_crm_lead_notes(notes)
        return {"ok": True, "leadId": lead_id, "fromStage": current_stage or None, "toStage": AUTO_OUTREACH_STAGE}
    except Exception as exc:
        return {"ok": False, "reason": "post_send_transition_error", "error": str(exc)}


@app.get("/api/chat/connection")
def api_chat_connection():
    try:
        status = _chat_baileys_status()
        return jsonify(status)
    except Exception as exc:
        return jsonify({"ok": False, "online": False, "state": "offline", "error": f"Falha ao consultar conexão do WhatsApp: {exc}"}), 503


@app.get("/api/chat/conversations")
def api_chat_conversations():
    try:
        limit = int(request.args.get("limit") or 120)
    except ValueError:
        limit = 120
    try:
        status = _chat_baileys_status()
        items = _chat_build_conversations(limit=limit)
        _save_chat_conversations_cache(items)
        return jsonify({"ok": True, "items": items, "source": "baileys", "connection": status})
    except Exception as exc:
        # No fallback to CRM leads/cache in conversation listing: WhatsApp-only source of truth.
        return jsonify({"ok": False, "items": [], "source": "baileys", "error": f"chat conversations unavailable: {exc}", "connection": {"ok": False, "online": False, "state": "offline"}}), 503


@app.get("/api/chat/conversations/<conversation_id>/messages")
def api_chat_messages(conversation_id: str):
    cid = _chat_id_from_target(unquote(conversation_id))
    if not cid:
        return jsonify({"error": "invalid conversation id"}), 400
    try:
        convs = _chat_fetch_conversations_from_baileys(limit=300)
        idx = _chat_alias_index(convs)
        canonical_for = idx.get("canonical_for", {}) if isinstance(idx, dict) else {}
        aliases_by_canon = idx.get("aliases_by_canon", {}) if isinstance(idx, dict) else {}

        canon = str(canonical_for.get(cid) or cid)
        aliases = aliases_by_canon.get(canon) if isinstance(aliases_by_canon, dict) else None
        if not aliases:
            aliases = [canon]

        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for alias in aliases:
            try:
                alias_items = _chat_fetch_messages_from_baileys(alias, limit=500)
            except Exception:
                continue
            for m in alias_items:
                txt = str(m.get("text") or "").strip()
                if _chat_is_noise_text(txt):
                    continue
                m["conversationId"] = canon
                key = f"{m.get('id')}|{m.get('timestampMs')}|{m.get('direction')}"
                if key in seen:
                    continue
                seen.add(key)
                merged.append(m)

        merged.sort(key=lambda x: (int(x.get("timestampMs") or 0), str(x.get("id") or "")))

        leads, _total, _err = _fetch_crm_overview()
        links = _load_chat_links()
        lead = _chat_resolve_lead_for_conversation(canon, leads, links)
        lead_id = int(lead.get("id") or 0) if isinstance(lead, dict) else 0
        if lead_id > 0:
            for msg in merged[-40:]:
                if str(msg.get("text") or "").strip():
                    _chat_sync_interaction_once(lead_id, msg, canon)

        return jsonify({"ok": True, "conversationId": canon, "items": merged[-500:]})
    except Exception as exc:
        return jsonify({"error": f"chat thread unavailable: {exc}"}), 503


@app.post("/api/chat/send")
def api_chat_send():
    payload = request.get_json(silent=True) or {}
    target = _chat_id_from_target(payload.get("conversationId") or payload.get("target") or payload.get("phone"))
    text = str(payload.get("text") or payload.get("message") or "").strip()
    if not target:
        return jsonify({"error": "conversationId is required"}), 400
    if not text:
        return jsonify({"error": "text is required"}), 400

    # Segurança UX: não enviar texto de raciocínio interno para clientes.
    if re.match(r"^\s*reasoning\s*:", text, flags=re.IGNORECASE):
        return jsonify({"error": "blocked internal reasoning text"}), 400

    try:
        # Endpoint oficial do wa-backend: POST /wa/send
        try:
            sent = _baileys_request("/send", method="POST", payload={"chatId": target, "text": text}, timeout=_baileys_timeout_seconds(8.5))
        except Exception as primary_exc:
            msg = str(primary_exc)
            # fallback legado somente quando /send não existir
            if "Cannot POST /wa/send" in msg:
                sent = _baileys_request("/messages/send", method="POST", payload={"chatId": target, "text": text}, timeout=_baileys_timeout_seconds(8.5))
            else:
                raise

        sent_to = _chat_id_from_target((sent or {}).get("to")) if isinstance(sent, dict) else ""
        if sent_to and sent_to != target:
            return jsonify({"error": "failed to send message: target_mismatch"}), 502

        post_action = _chat_apply_post_send_stage_transition(target, payload)
        return jsonify({"ok": True, "conversationId": target, "sent": sent, "postAction": post_action})
    except Exception as exc:
        return jsonify({"error": f"failed to send message: {exc}"}), 503


@app.post("/api/chat/link-lead")
def api_chat_link_lead():
    payload = request.get_json(silent=True) or {}
    conversation_id = _chat_id_from_target(payload.get("conversationId") or payload.get("phone") or payload.get("target"))
    lead_id = _as_int(payload.get("leadId"))
    if not conversation_id:
        return jsonify({"error": "conversationId is required"}), 400
    if not lead_id:
        return jsonify({"error": "leadId is required"}), 400

    leads, _total, _err = _fetch_crm_overview()
    lead = next((x for x in leads if int(x.get("id") or 0) == int(lead_id)), None)
    if not lead:
        return jsonify({"error": "lead not found"}), 404

    links = _load_chat_links()
    links[conversation_id] = {
        "conversationId": conversation_id,
        "leadId": int(lead_id),
        "label": str(lead.get("name") or lead.get("full_name") or lead.get("email") or "").strip(),
        "updatedAt": _utc_now_iso(),
    }
    _save_chat_links(links)
    return jsonify({"ok": True, "item": links[conversation_id]})


def _normalize_agenda_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"call", "follow-up", "reunião", "reuniao"}:
        return "reunião" if raw in {"reunião", "reuniao"} else raw
    raise ValueError("tipo inválido")


def _normalize_agenda_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"pendente", "concluido", "concluído", "atrasado"}:
        if raw == "concluído":
            return "concluido"
        return raw
    raise ValueError("status inválido")


def _normalize_agenda_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        raise ValueError("data inválida (use YYYY-MM-DD)")
    try:
        datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("data inválida") from exc
    return raw


def _normalize_agenda_time(value: Any) -> str:
    raw = str(value or "").strip()
    if not re.match(r"^\d{2}:\d{2}$", raw):
        raise ValueError("hora inválida (use HH:MM)")
    hh, mm = raw.split(":", 1)
    if int(hh) > 23 or int(mm) > 59:
        raise ValueError("hora inválida")
    return raw


def _load_agenda_events() -> list[dict[str, Any]]:
    _ensure_store()
    raw = AGENDA_EVENTS_FILE.read_text(encoding="utf-8") or "[]"
    items = json.loads(raw)
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


def _save_agenda_events(items: list[dict[str, Any]]) -> None:
    _ensure_store()
    AGENDA_EVENTS_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _agenda_with_overdue(item: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    out = dict(item)
    now_dt = now or datetime.now()
    status = str(out.get("status") or "pendente").strip().lower()
    is_done = status == "concluido"
    is_overdue = False
    try:
        due_at = datetime.fromisoformat(f"{out.get('date')}T{out.get('time')}:00")
        is_overdue = (not is_done) and due_at < now_dt
    except Exception:
        is_overdue = False
    out["isOverdue"] = is_overdue
    if is_overdue and status != "atrasado":
        out["status"] = "atrasado"
    return out


@app.get("/api/agenda")
def api_agenda_by_date():
    date_raw = request.args.get("date")
    if not date_raw:
        return jsonify({"error": "date is required (YYYY-MM-DD)"}), 400
    try:
        date_key = _normalize_agenda_date(date_raw)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    items = _load_agenda_events()
    selected = [_agenda_with_overdue(x) for x in items if str(x.get("date") or "") == date_key]
    selected.sort(key=lambda x: str(x.get("time") or ""))
    return jsonify({"ok": True, "date": date_key, "items": selected})


@app.post("/api/agenda")
def api_agenda_create():
    payload = request.get_json(silent=True) or {}
    try:
        date_key = _normalize_agenda_date(payload.get("date"))
        time_key = _normalize_agenda_time(payload.get("time"))
        event_type = _normalize_agenda_type(payload.get("type"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        status = _normalize_agenda_status(payload.get("status") or "pendente")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    lead = payload.get("lead") if isinstance(payload.get("lead"), dict) else {}
    lead_name = str(lead.get("name") or payload.get("leadName") or "").strip()
    lead_phone = str(lead.get("phone") or payload.get("leadPhone") or "").strip()
    lead_id = _as_int(lead.get("id") if isinstance(lead, dict) else payload.get("leadId"))

    if not lead_name and not lead_phone and not lead_id:
        return jsonify({"error": "lead reference is required"}), 400

    now = _utc_now_iso()
    item = {
        "id": f"agenda-{int(time.time() * 1000)}",
        "date": date_key,
        "time": time_key,
        "type": event_type,
        "status": status,
        "leadId": lead_id,
        "leadName": lead_name,
        "leadPhone": lead_phone,
        "createdAt": now,
        "updatedAt": now,
    }

    items = _load_agenda_events()
    items.append(item)
    _save_agenda_events(items)
    return jsonify({"ok": True, "item": _agenda_with_overdue(item)}), 201


@app.patch("/api/agenda/<event_id>")
def api_agenda_patch(event_id: str):
    payload = request.get_json(silent=True) or {}
    items = _load_agenda_events()
    item = next((x for x in items if str(x.get("id") or "") == str(event_id)), None)
    if not item:
        return jsonify({"error": "agenda item not found"}), 404

    try:
        if "date" in payload:
            item["date"] = _normalize_agenda_date(payload.get("date"))
        if "time" in payload:
            item["time"] = _normalize_agenda_time(payload.get("time"))
        if "status" in payload:
            item["status"] = _normalize_agenda_status(payload.get("status"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not any(k in payload for k in {"date", "time", "status"}):
        return jsonify({"error": "nothing to update"}), 400

    item["updatedAt"] = _utc_now_iso()
    _save_agenda_events(items)
    return jsonify({"ok": True, "item": _agenda_with_overdue(item)})


def _normalize_meet_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Link do Meet é obrigatório")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Link do Meet inválido")
    if parsed.netloc.lower() not in {"meet.google.com", "www.meet.google.com"}:
        raise ValueError("Use um link válido do Google Meet")
    if not re.match(r"^/[a-z]{3}-[a-z]{4}-[a-z]{3}$", parsed.path or ""):
        raise ValueError("Formato do link do Meet inválido")
    return f"https://meet.google.com{parsed.path}"


def _load_albert_sessions() -> list[dict[str, Any]]:
    ALBERT_STORE.ensure()
    return ALBERT_STORE.list_sessions()


def _albert_update_session(session_id: str, status: str, detail: str, extra: dict[str, Any] | None = None) -> bool:
    ALBERT_STORE.ensure()
    return ALBERT_STORE.update_session(session_id, status, detail, extra=extra)


def _albert_enqueue(session_id: str, meet_link: str, trigger: str, scheduled_for: str | None = None) -> None:
    ALBERT_STORE.ensure()
    ALBERT_STORE.enqueue_job(session_id=session_id, meet_link=meet_link, run_at=scheduled_for, trigger=trigger)


@app.get("/api/albert/sessions")
def api_albert_sessions():
    items = _load_albert_sessions()
    ordered = sorted(items, key=lambda x: str(x.get("createdAt") or ""), reverse=True)
    return jsonify({"ok": True, "items": ordered[:30]})


@app.get("/api/albert/sessions/<session_id>")
def api_albert_session_detail(session_id: str):
    items = _load_albert_sessions()
    found = next((x for x in items if str(x.get("id") or "") == str(session_id)), None)
    if not found:
        return jsonify({"error": "sessão não encontrada"}), 404
    return jsonify({"ok": True, "item": found})


@app.post("/api/albert/session/start")
def api_albert_session_start():
    payload = request.get_json(silent=True) or {}
    try:
        meet_link = _normalize_meet_url(payload.get("meetLink") or payload.get("link"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    now = _utc_now_iso()
    session_id = f"alb-{uuid.uuid4().hex[:12]}"
    item = {
        "id": session_id,
        "mode": "real",
        "trigger": "now",
        "meetLink": meet_link,
        "status": "created",
        "createdAt": now,
        "updatedAt": now,
        "scheduledFor": None,
        "timeline": [{"status": "created", "detail": "Sessão real criada e enfileirada para início imediato.", "at": now}],
        "transcript": "",
        "insights": [],
        "summary": "",
        "error": "",
        "artifacts": {},
    }

    ALBERT_STORE.add_session(item)
    _albert_enqueue(session_id=session_id, meet_link=meet_link, trigger="now", scheduled_for=None)
    return jsonify({"ok": True, "item": item}), 201


@app.post("/api/albert/session/schedule")
def api_albert_session_schedule():
    payload = request.get_json(silent=True) or {}
    try:
        meet_link = _normalize_meet_url(payload.get("meetLink") or payload.get("link"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    scheduled_for_raw = str(payload.get("scheduledFor") or "").strip()
    scheduled_for = None
    if scheduled_for_raw:
        try:
            dt = datetime.fromisoformat(scheduled_for_raw.replace("Z", "+00:00"))
            scheduled_for = dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return jsonify({"error": "Data/hora de agendamento inválida"}), 400

    now = _utc_now_iso()
    session_id = f"alb-{uuid.uuid4().hex[:12]}"
    item = {
        "id": session_id,
        "mode": "real",
        "trigger": "scheduled",
        "meetLink": meet_link,
        "status": "created",
        "createdAt": now,
        "updatedAt": now,
        "scheduledFor": scheduled_for,
        "timeline": [{"status": "created", "detail": "Sessão real agendada e enfileirada.", "at": now}],
        "transcript": "",
        "insights": [],
        "summary": "",
        "error": "",
        "artifacts": {},
    }

    ALBERT_STORE.add_session(item)
    _albert_enqueue(session_id=session_id, meet_link=meet_link, trigger="scheduled", scheduled_for=scheduled_for)
    return jsonify({"ok": True, "item": item}), 201


if __name__ == "__main__":
    host = os.environ.get("OPENCLAW_COCKPIT_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("OPENCLAW_COCKPIT_PORT", "8787"))
    except ValueError:
        port = 8787
    app.run(host=host, port=port, debug=False, threaded=True)


