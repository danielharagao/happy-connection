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

## AI SDR — Qualificacao automatica via WhatsApp

Sistema de SDR (Sales Development Representative) com IA que qualifica leads de anuncios pagos via WhatsApp e agenda ligacoes para o closer humano.

### Como funciona

1. Lead preenche formulario (anuncio pago) -> CRM recebe via webhook
2. CRM dispara `POST /api/sdr/webhook` com dados do lead
3. AI SDR envia primeira mensagem no WhatsApp (via Baileys backend)
4. Conversa de qualificacao usando Claude (perfil, dores, urgencia, orcamento)
5. IA roteia para Curso de BA ou Mentoria
6. Se qualificado -> agenda ligacao via `/api/sdr/schedule`
7. Closer humano recebe resumo da qualificacao nas notas do lead

### Setup

```bash
# 1. Instalar dependencia
pip install anthropic

# 2. Configurar API key no .env ou environment
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. Garantir que wa-backend esta rodando (porta 8790)
cd wa-backend && npm start

# 4. Iniciar o CRM
python3 app.py
```

### Endpoints SDR

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| `POST` | `/api/sdr/webhook` | Dispara SDR para novo lead (`lead_id`, `name`, `phone`, `source`) |
| `POST` | `/api/sdr/reply` | Processa resposta do lead (`lead_id`, `message`) |
| `POST` | `/api/sdr/schedule` | Agenda ligacao para lead qualificado |
| `GET` | `/api/sdr/conversations` | Lista todas as conversas SDR |
| `GET` | `/api/sdr/conversations/<lead_id>` | Detalhes de uma conversa |
| `POST` | `/api/sdr/conversations/<lead_id>/state` | Atualiza estado da conversa |
| `GET` | `/api/sdr/dashboard` | Metricas do funil SDR |
| `GET` | `/api/sdr/scripts` | Lista scripts de qualificacao |
| `POST` | `/api/sdr/scripts` | Cria novo script |
| `PUT` | `/api/sdr/scripts/<id>` | Atualiza script |
| `DELETE` | `/api/sdr/scripts/<id>` | Remove script |

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

| Variavel | Descricao | Default |
|----------|-----------|---------|
| `ANTHROPIC_API_KEY` | Chave da API Anthropic (obrigatoria) | - |
| `SDR_MODEL` | Modelo Claude a usar | `claude-sonnet-4-20250514` |

## Test / Checks

```bash
python3 -m py_compile app.py
node --check static/app.js
python3 -m unittest discover -s tests -p 'test_*' -q
```
