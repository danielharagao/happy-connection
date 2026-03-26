# Next Steps — SDR Data Layer Deployment on VPS

This document contains the step-by-step instructions for the VPS agent to deploy the SDR data layer in the CRM.

**Architecture:** The AI SDR agent runs locally (Genie team member). This CRM on the VPS is the **data layer only** — it stores scripts, conversations, and metrics. No AI/Claude runs here.

## Pre-requisites

- [ ] VPS has Python 3.10+
- [ ] VPS has the happy-connection repo cloned
- [ ] WhatsApp backend (Baileys) is running on port 8790
- [ ] CRM Flask app is running on port 8787

---

## Step 1: Merge the SDR branch

```bash
cd /path/to/happy-connection
git fetch origin
git merge origin/feat/sdr-ai-qualification
```

Or merge via GitHub PR: https://github.com/danielharagao/happy-connection/pull/1

---

## Step 2: Restart the CRM Flask app

No new Python dependencies needed.

```bash
pkill -f "python3 app.py" || true
cd /path/to/happy-connection
python3 app.py &
```

Verify it's running:
```bash
curl -s http://localhost:8787/api/sdr/scripts | python3 -c "import sys,json; d=json.load(sys.stdin); print('Scripts:', len(d.get('scripts',[])))"
```

Expected output: `Scripts: 1` (the default qualification script is auto-created)

---

## Step 3: Verify SDR endpoints

```bash
# Scripts endpoint
curl -s http://localhost:8787/api/sdr/scripts | python3 -m json.tool | head -5

# Dashboard endpoint
curl -s http://localhost:8787/api/sdr/dashboard | python3 -m json.tool

# Conversations endpoint
curl -s http://localhost:8787/api/sdr/conversations | python3 -m json.tool
```

---

## Step 4: Verify the CRM UI

Open the CRM in a browser: `http://<VPS_IP>:8787`

Check that two new tabs appear:
- **SDR** — Dashboard with funnel metrics
- **Scripts** — Script editor for qualification prompts

---

## Step 5: Customize the default script (optional)

1. Go to the **Scripts** tab
2. Click **Editar** on "Qualificacao Padrao"
3. Adjust system prompt, first message template, escalation triggers
4. Click **Salvar**

Changes take effect immediately (no restart needed).

---

## API Endpoints (for the local SDR agent)

The local Genie SDR agent calls these endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sdr/scripts` | List all scripts |
| `GET` | `/api/sdr/scripts/<id>` | Get one script |
| `POST` | `/api/sdr/scripts` | Create script |
| `PUT` | `/api/sdr/scripts/<id>` | Update script |
| `DELETE` | `/api/sdr/scripts/<id>` | Delete script |
| `GET` | `/api/sdr/conversations` | List all conversations |
| `GET` | `/api/sdr/conversations/<lead_id>` | Get one conversation |
| `POST` | `/api/sdr/conversations` | Create conversation |
| `POST` | `/api/sdr/conversations/<lead_id>/message` | Log a message |
| `POST` | `/api/sdr/conversations/<lead_id>/state` | Update state |
| `POST` | `/api/sdr/conversations/<lead_id>/qualification` | Update qualification data |
| `GET` | `/api/sdr/dashboard` | Funnel metrics |

---

## Files Added/Modified

| File | What it does |
|------|-------------|
| `sdr_engine.py` | Data layer: conversations, scripts CRUD, funnel metrics (no AI) |
| `app.py` | SDR data endpoints (conversations, scripts, dashboard) |
| `static/app.js` | SDR Dashboard and Scripts Editor UI |
| `templates/index.html` | SDR and Scripts navigation tabs |
| `data/sdr_scripts.json` | Auto-created with default script |
| `data/sdr_conversations.json` | Auto-created, stores conversation state |

---

## Troubleshooting

### Scripts not loading
```bash
cat data/sdr_scripts.json
```
If missing, restart the CRM — it auto-creates the default.

### Endpoints returning 404
Make sure you merged the `feat/sdr-ai-qualification` branch and restarted Flask.
