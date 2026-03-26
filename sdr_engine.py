"""
SDR Data Layer — Conversations, scripts, and metrics storage.

This module manages SDR data for the CRM. The actual AI conversation
logic runs on the local Genie SDR agent, not in the CRM.
The CRM serves as the data layer (scripts, conversations, metrics).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import os

BASE_DIR = Path(__file__).resolve().parent
APP_ENV = (os.environ.get("OPENCLAW_COCKPIT_ENV") or os.environ.get("APP_ENV") or "prod").strip().lower()
if APP_ENV in {"dev", "development"}:
    DATA_DIR = BASE_DIR / "data-dev"
elif APP_ENV in {"test", "testing"}:
    DATA_DIR = BASE_DIR / "data-test"
else:
    DATA_DIR = BASE_DIR / "data"

CONVERSATIONS_FILE = DATA_DIR / "sdr_conversations.json"
SCRIPTS_FILE = DATA_DIR / "sdr_scripts.json"

# ── Conversation State ──

VALID_STATES = ["new", "qualifying", "qualified", "scheduled", "nurture", "disqualified", "escalated", "no_response"]


def _load_conversations() -> dict[str, Any]:
    try:
        return json.loads(CONVERSATIONS_FILE.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_conversations(data: dict[str, Any]) -> None:
    CONVERSATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONVERSATIONS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")


def get_conversation(lead_id: str) -> dict[str, Any] | None:
    convs = _load_conversations()
    return convs.get(str(lead_id))


def list_conversations() -> dict[str, Any]:
    return _load_conversations()


def create_conversation(lead_id: str, name: str, phone: str, source: str = "", form_data: dict | None = None) -> dict[str, Any]:
    convs = _load_conversations()
    lead_key = str(lead_id)

    if lead_key in convs and convs[lead_key]["state"] not in ("no_response", "disqualified"):
        return convs[lead_key]

    conv = {
        "id": str(uuid.uuid4()),
        "lead_id": lead_key,
        "name": name,
        "phone": phone,
        "source": source,
        "form_data": form_data or {},
        "state": "new",
        "messages": [],
        "qualification": {
            "profile_fit": None,
            "urgency": None,
            "budget": None,
            "product_route": None,
            "pain_points": [],
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "scheduled_at": None,
        "escalated_to": None,
    }

    convs[lead_key] = conv
    _save_conversations(convs)
    return conv


def add_message(lead_id: str, role: str, content: str) -> dict[str, Any] | None:
    convs = _load_conversations()
    conv = convs.get(str(lead_id))
    if not conv:
        return None

    msg = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    conv["messages"].append(msg)
    conv["updated_at"] = datetime.now(timezone.utc).isoformat()
    if conv["state"] == "new":
        conv["state"] = "qualifying"
    _save_conversations(convs)
    return conv


def update_state(lead_id: str, state: str) -> dict[str, Any] | None:
    if state not in VALID_STATES:
        return None
    convs = _load_conversations()
    conv = convs.get(str(lead_id))
    if not conv:
        return None
    conv["state"] = state
    conv["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_conversations(convs)
    return conv


def update_qualification(lead_id: str, qual_data: dict[str, Any]) -> dict[str, Any] | None:
    convs = _load_conversations()
    conv = convs.get(str(lead_id))
    if not conv:
        return None
    for k, v in qual_data.items():
        if k in conv["qualification"]:
            conv["qualification"][k] = v
    conv["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_conversations(convs)
    return conv


# ── Scripts ──

DEFAULT_SCRIPT = {
    "id": "default-qualification",
    "name": "Qualificacao Padrao",
    "type": "qualification",
    "product": "both",
    "system_prompt": (
        "Voce e a assistente digital do Daniel Aragao, especialista em Business Analysis.\n"
        "Seu papel e qualificar leads que chegam de anuncios para dois produtos:\n"
        "1. CURSO DE BA - para quem quer fazer transicao para BA ou e BA junior\n"
        "2. MENTORIA - para profissionais de BA, PM ou PO que tem dores especificas e querem desenvolver confianca e habilidades\n\n"
        "Regras da conversa:\n"
        "- Seja natural, amigavel, em portugues brasileiro\n"
        "- Faca UMA pergunta por vez\n"
        "- Descubra: perfil profissional, dores/desafios, urgencia, disposicao para investir\n"
        "- Se a pessoa mencionar orcamento, mencione que existem boas opcoes de pagamento\n"
        "- Quando tiver informacao suficiente, proponha agendar uma ligacao\n"
        "- Se pedirem para falar com humano, diga que vai transferir\n"
        "- NUNCA invente informacoes sobre precos ou conteudo do curso\n"
    ),
    "first_message_template": (
        "Oi {name}! Eu sou a assistente digital do Daniel Aragao. "
        "Vi que voce se interessou pelo nosso conteudo de Business Analysis. "
        "Posso te ajudar a entender qual programa se encaixa melhor pra voce. "
        "Me conta um pouco: voce ja trabalha com analise de negocios ou ta buscando fazer essa transicao?"
    ),
    "qualification_criteria": {
        "profile_fit": "Is this person a BA/transitioning or has BA/PM/PO pain points?",
        "urgency": "How soon do they want to start?",
        "budget": "Are they willing to invest? Mention payment options if hesitant.",
        "product_route": "Course (transitioning/junior) or Mentoring (experienced with pain points)?",
    },
    "escalation_triggers": [
        "quero falar com humano",
        "posso falar com alguem",
        "quero falar com o daniel",
        "falar com uma pessoa",
        "atendente humano",
    ],
    "active": True,
}


def _load_scripts() -> list[dict[str, Any]]:
    try:
        data = json.loads(SCRIPTS_FILE.read_text("utf-8"))
        return data.get("scripts", [])
    except (FileNotFoundError, json.JSONDecodeError):
        _save_scripts([DEFAULT_SCRIPT])
        return [DEFAULT_SCRIPT]


def _save_scripts(scripts: list[dict[str, Any]]) -> None:
    SCRIPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCRIPTS_FILE.write_text(json.dumps({"scripts": scripts}, indent=2, ensure_ascii=False), "utf-8")


def get_scripts() -> list[dict[str, Any]]:
    return _load_scripts()


def get_script(script_id: str) -> dict[str, Any] | None:
    for s in _load_scripts():
        if s["id"] == script_id:
            return s
    return None


def get_active_script() -> dict[str, Any]:
    for s in _load_scripts():
        if s.get("active"):
            return s
    scripts = _load_scripts()
    return scripts[0] if scripts else DEFAULT_SCRIPT


def create_script(data: dict[str, Any]) -> dict[str, Any]:
    scripts = _load_scripts()
    script = {
        "id": data.get("id") or str(uuid.uuid4()),
        "name": data.get("name", "Novo Script"),
        "type": data.get("type", "qualification"),
        "product": data.get("product", "both"),
        "system_prompt": data.get("system_prompt", ""),
        "first_message_template": data.get("first_message_template", ""),
        "qualification_criteria": data.get("qualification_criteria", {}),
        "escalation_triggers": data.get("escalation_triggers", []),
        "active": data.get("active", False),
    }
    scripts.append(script)
    _save_scripts(scripts)
    return script


def update_script(script_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    scripts = _load_scripts()
    for s in scripts:
        if s["id"] == script_id:
            for k, v in data.items():
                if k != "id":
                    s[k] = v
            _save_scripts(scripts)
            return s
    return None


def delete_script(script_id: str) -> bool:
    scripts = _load_scripts()
    before = len(scripts)
    scripts = [s for s in scripts if s["id"] != script_id]
    if len(scripts) < before:
        _save_scripts(scripts)
        return True
    return False


# ── Funnel Metrics ──

def get_funnel_metrics() -> dict[str, Any]:
    convs = _load_conversations()
    total = len(convs)
    states: dict[str, int] = {}
    products: dict[str, int] = {"course": 0, "mentoring": 0, "both": 0, "unclear": 0}

    for conv in convs.values():
        state = conv.get("state", "new")
        states[state] = states.get(state, 0) + 1
        route = (conv.get("qualification") or {}).get("product_route")
        if route and route in products:
            products[route] += 1

    scheduled = states.get("scheduled", 0)
    conversion_rate = round((scheduled / total * 100), 1) if total > 0 else 0

    return {
        "total_leads": total,
        "by_state": states,
        "by_product": products,
        "conversion_rate": conversion_rate,
        "active_conversations": states.get("qualifying", 0),
    }
