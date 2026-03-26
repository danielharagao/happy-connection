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

## AI SDR — Camada de Dados para Qualificacao via WhatsApp

Camada de dados para o sistema SDR. O agente IA roda localmente (Genie), este CRM serve como fonte de dados (scripts, conversas, metricas). Nenhuma dependencia de IA/Claude aqui.

### Arquitetura

```
Agente SDR (local, Genie) <--API--> CRM (VPS, este repo) <--Baileys--> WhatsApp
```

1. Agente SDR local le scripts do CRM via API
2. Agente envia mensagens no WhatsApp via omni
3. Agente registra conversas e qualificacoes no CRM via API
4. CRM exibe dashboard e permite editar scripts na UI

### Setup

```bash
# Nenhuma dependencia extra - so Flask
python3 app.py
```

### Endpoints SDR

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| `GET` | `/api/sdr/scripts` | Lista scripts de qualificacao |
| `GET` | `/api/sdr/scripts/<id>` | Detalhes de um script |
| `POST` | `/api/sdr/scripts` | Cria novo script |
| `PUT` | `/api/sdr/scripts/<id>` | Atualiza script |
| `DELETE` | `/api/sdr/scripts/<id>` | Remove script |
| `GET` | `/api/sdr/conversations` | Lista todas as conversas SDR |
| `GET` | `/api/sdr/conversations/<lead_id>` | Detalhes de uma conversa |
| `POST` | `/api/sdr/conversations` | Cria conversa (agente chama ao iniciar lead) |
| `POST` | `/api/sdr/conversations/<lead_id>/message` | Registra mensagem na conversa |
| `POST` | `/api/sdr/conversations/<lead_id>/state` | Atualiza estado da conversa |
| `POST` | `/api/sdr/conversations/<lead_id>/qualification` | Atualiza dados de qualificacao |
| `GET` | `/api/sdr/dashboard` | Metricas do funil SDR |

### Scripts Live

Scripts de qualificacao sao editaveis pela UI (aba "Scripts") sem precisar de deploy. Ficam em `data/sdr_scripts.json`. O script ativo define:
- System prompt do Claude
- Template da primeira mensagem
- Criterios de qualificacao
- Gatilhos de escalacao para humano

### Arquivos

- `sdr_engine.py` — Motor principal: conversas, Claude, scripts, metricas
- `data/sdr_scripts.json` — Scripts de qualificacao (criado automaticamente)
- `data/sdr_conversations.json` — Estado das conversas ativas

### Variaveis de ambiente

Nenhuma variavel adicional necessaria para o SDR. A IA roda no agente local, nao no CRM.

## Test / Checks

```bash
python3 -m py_compile app.py
node --check static/app.js
python3 -m unittest discover -s tests -p 'test_*' -q
```
