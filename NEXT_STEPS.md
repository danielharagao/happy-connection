# Next Steps — SDR AI Deployment on VPS

This document contains the step-by-step instructions for the VPS agent to deploy and activate the AI SDR system.

## Pre-requisites

- [ ] VPS has Python 3.10+
- [ ] VPS has the happy-connection repo cloned
- [ ] WhatsApp backend (Baileys) is running on port 8790
- [ ] CRM Flask app is running on port 8787
- [ ] `ANTHROPIC_API_KEY` is set in the environment

---

## Step 1: Merge the SDR branch

```bash
cd /path/to/happy-connection
git fetch origin
git checkout main
git merge origin/feat/sdr-ai-qualification
```

Or merge via GitHub PR: https://github.com/danielharagao/happy-connection/pull/1

---

## Step 2: Install new Python dependency

```bash
pip install anthropic>=0.40.0
```

Or install from requirements.txt:
```bash
pip install -r requirements.txt
```

---

## Step 3: Set environment variables

Add to your `.env` or export in the shell before starting the CRM:

```bash
# Required — Anthropic API key for Claude conversations
export ANTHROPIC_API_KEY="sk-ant-..."

# Optional — Override the Claude model (default: claude-sonnet-4-20250514)
# export SDR_MODEL="claude-sonnet-4-20250514"
```

---

## Step 4: Restart the CRM Flask app

```bash
# Kill existing process
pkill -f "python3 app.py" || true

# Start with new code
cd /path/to/happy-connection
python3 app.py &
```

Verify it's running:
```bash
curl -s http://localhost:8787/api/sdr/scripts | python3 -c "import sys,json; d=json.load(sys.stdin); print('Scripts:', len(d.get('scripts',[])))"
```

Expected output: `Scripts: 1` (the default qualification script is auto-created)

---

## Step 5: Verify all SDR endpoints

Run these checks to confirm everything is working:

```bash
# 1. Scripts endpoint
curl -s http://localhost:8787/api/sdr/scripts | python3 -m json.tool | head -5

# 2. Dashboard endpoint
curl -s http://localhost:8787/api/sdr/dashboard | python3 -m json.tool

# 3. Conversations endpoint
curl -s http://localhost:8787/api/sdr/conversations | python3 -m json.tool

# 4. WhatsApp backend is reachable
curl -s http://localhost:8790/wa/status | python3 -m json.tool
```

---

## Step 6: Verify the CRM UI

Open the CRM in a browser:
```
http://<VPS_IP>:8787
```

Check that two new tabs appear in the navigation:
- **SDR** (robot icon) — Dashboard with funnel metrics
- **Scripts** (pencil icon) — Script editor

---

## Step 7: Test the webhook (dry run)

Send a test webhook to verify the full flow works:

```bash
curl -s -X POST http://localhost:8787/api/sdr/webhook \
  -H 'Content-Type: application/json' \
  -d '{
    "lead_id": "test-001",
    "name": "Lead Teste",
    "phone": "5511999999999",
    "source": "manual_test"
  }' | python3 -m json.tool
```

Expected: `"success": true` and first WhatsApp message sent to the test number.

**IMPORTANT:** Use a test phone number you control, not a real lead.

After testing, clean up:
```bash
# Remove test conversation
python3 -c "
import json
from pathlib import Path
f = Path('data/sdr_conversations.json')
d = json.loads(f.read_text()) if f.exists() else {}
d.pop('test-001', None)
f.write_text(json.dumps(d, indent=2))
print('Test conversation cleaned up')
"
```

---

## Step 8: Configure the default script (optional)

The default script is pre-loaded but you may want to customize it:

1. Go to the **Scripts** tab in the CRM UI
2. Click **Editar** on "Qualificacao Padrao"
3. Adjust:
   - **System Prompt** — The AI's personality and qualification instructions
   - **Primeira Mensagem** — Template for the first outreach message (use `{name}` for lead name)
   - **Gatilhos de Escalacao** — Phrases that trigger transfer to human (one per line)
4. Click **Salvar**

Changes take effect immediately on the next conversation (no restart needed).

---

## Step 9: Connect to paid media webhook

Configure your ad platform (Meta Ads, Google Ads, etc.) or landing page to send a POST request when a new lead arrives:

**Webhook URL:** `http://<VPS_IP>:8787/api/sdr/webhook`

**Payload format:**
```json
{
  "lead_id": "12345",
  "name": "Nome do Lead",
  "phone": "5511999999999",
  "source": "meta_ads",
  "form_data": {
    "interest": "business analysis",
    "utm_source": "facebook"
  }
}
```

Required fields: `lead_id`, `phone`
Optional fields: `name`, `source`, `form_data`

---

## Architecture Overview

```
Lead fills form (paid ad)
       |
       v
Landing Page / CRM webhook
       |
       v
POST /api/sdr/webhook  (CRM Flask app, port 8787)
       |
       v
sdr_engine.py → Claude API (qualification conversation)
       |
       v
WhatsApp Baileys backend (port 8790) → Lead's WhatsApp
       |
       v
Lead replies → /api/sdr/reply → Claude reasons → replies
       |
       v
Qualified? → /api/sdr/schedule → CRM agenda + lead notes
       |
       v
Human closer gets call with qualification summary
```

---

## Files Added/Modified

| File | What it does |
|------|-------------|
| `sdr_engine.py` | Core SDR engine: conversations, Claude integration, scripts, metrics |
| `app.py` | SDR endpoints added at the end (webhook, reply, schedule, scripts CRUD, dashboard) |
| `requirements.txt` | Added `anthropic>=0.40.0` |
| `static/app.js` | SDR Dashboard and Scripts Editor UI code |
| `templates/index.html` | SDR and Scripts navigation tabs |
| `data/sdr_scripts.json` | Auto-created on first access with default script |
| `data/sdr_conversations.json` | Auto-created, stores active conversation state |

---

## Troubleshooting

### "Anthropic SDK not available"
```bash
pip install anthropic
```

### "ANTHROPIC_API_KEY not set"
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### WhatsApp message not sending
Check Baileys backend:
```bash
curl -s http://localhost:8790/wa/status
```
If disconnected, reconnect via QR code.

### Script not loading
Check if the file exists:
```bash
cat data/sdr_scripts.json
```
If empty or missing, restart the CRM — it auto-creates the default script.

### Claude API errors
Check your API key is valid:
```bash
python3 -c "import anthropic; c=anthropic.Anthropic(); print(c.messages.create(model='claude-sonnet-4-20250514',max_tokens=10,messages=[{'role':'user','content':'oi'}]).content[0].text)"
```

---

## Monitoring

- **SDR Dashboard:** `http://<VPS_IP>:8787/#sdr` — funnel metrics, active conversations
- **API check:** `curl http://localhost:8787/api/sdr/dashboard`
- **Logs:** Flask console output shows all SDR API calls
