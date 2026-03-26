# OpenClaw Cockpit (CRM-Centric)

Local-first Flask cockpit focused on **Dashboard + CRM + Cron** operations.

## Current UI Scope

- ✅ Dashboard (KPI snapshot + OpenClaw usage)
- ✅ CRM Bridge panel (status + lead board render)
- ✅ Cron jobs panel (meta, list, add, validate command, run-now)

Removed from cockpit surface in this refactor:
- ❌ Sessions tab
- ❌ Team/Agents management tab
- ❌ Permissions tab
- ❌ Open Floor (Office) tab
- ❌ Kanban tab
- ❌ Chat tab

## Main Endpoints (kept)

- `GET /api/dashboard/summary`
- `GET /api/dashboard/openclaw-usage`
- `GET /api/crm/bridge`
- `GET /api/crm/bridge/proxy/<path>` (allowlisted)
- `POST /api/crm/bridge/application-status`
- `GET|POST /api/crm/bridge/interactions/...`
- `GET|POST /api/crm/bridge/failed-events...`
- `GET /api/cron/meta`
- `GET|POST|PATCH|DELETE /api/cron/jobs...`
- `POST /api/cron/validate-command`
- `POST /api/cron/jobs/<id>/run`

## Quick Run

```bash
python3 app.py
# http://127.0.0.1:8787
```

## Albert Meet Worker (real mode)

Albert agora usa worker separado (fila local em `data/albert_jobs.json`).

1) Instalar dependências Python:
```bash
pip install -r requirements.txt
```

2) Instalar Chromium do Playwright:
```bash
python3 -m playwright install chromium
```

3) Subir API + worker (em terminais separados):
```bash
python3 app.py
./scripts/start_albert_worker.sh
```

Opcional para captura de áudio externa (MVP hook):
```bash
export ALBERT_AUDIO_CAPTURE_CMD='bash scripts/capture_audio.sh {session_id} {artifact_dir}'
```
Sem esse hook, o estado fica em `joined` com `recordingPending=true` (sem fake de transcrição).

## WhatsApp Backend (Baileys)

Backend real de WhatsApp para integração CRM/cockpit em:

- `apps/openclaw-cockpit/wa-backend`
- Documentação: `apps/openclaw-cockpit/wa-backend/README.md`

## Test / Checks

```bash
python3 -m py_compile app.py
node --check static/app.js
python3 -m unittest discover -s tests -p 'test_*' -q
```
