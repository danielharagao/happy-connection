# QA Report — CRM Mission Control
Date (UTC): 2026-03-18T12:34:33.594Z
Base URL used: https://crm.danhausch.cloud

## Test Cases (PASS/FAIL)
- **1) Auth + landing load**: PASS
  - Evidence: Landing loaded with app-related text visible.
- **2) Tabs switch: Leads, Chat, Agenda, Mission KB**: PASS
  - Evidence: All tabs interacted: {"leads":"Leads","chat":"Chat","agenda":"Agenda","kb":"Mission KB"}
- **3) Chat flows**: FAIL
  - Evidence: Checks passed 3/5
- **4) Leads board + tray tabs**: PASS
  - Evidence: Checks passed 3/3
- **5) Agenda calendar render + date switch**: PASS
  - Evidence: Checks passed 2/2
- **6) Mission KB docs + edit controls**: FAIL
  - Evidence: Checks passed 0/4
- **7) API endpoints GET + payload sanity**: FAIL
  - Evidence: GET passed 4/5

## Additional UI Evidence
- Selected base URL: https://crm.danhausch.cloud (status 200)
- Chat conversation list count (heuristic): 2
- Leads tray tabs clicked: 3/3
- Mission KB docs count (heuristic): 0

## Endpoint Results
| Method | Endpoint | Status | OK | Body sample |
|---|---|---:|:---:|---|
| GET | /api/crm/bridge | 200 | ✅ | {"crm":{"allowedProxyPrefixes":["api/crm/overview","api/crm/lead/"],"authConfigured":true,"baseUrl":"http://127.0.0.1:5000","embedUrl":"http://127.0.0.1:5000","health":{"error":nul |
| GET | /api/chat/conversations | 200 | ✅ | {"connection":{"ok":true,"online":true,"source":"baileys","state":"open"},"items":[{"aliases":["35450727202836@lid"],"id":"35450727202836@lid","lastAt":"2026-03-18T12:30:40+00:00", |
| GET | /api/chat/connection | 200 | ✅ | {"ok":true,"online":true,"source":"baileys","state":"open"}  |
| GET | /api/agenda?date=today | 400 | ❌ | {"error":"data inv\u00e1lida (use YYYY-MM-DD)"}  |
| GET | /api/knowledge/mission-control | 200 | ✅ | {"content":"# Estrat\u00e9gia da Empresa \u2014 Danhausch\n\n> Documento mestre de dire\u00e7\u00e3o estrat\u00e9gica, posicionamento e opera\u00e7\u00e3o comercial.\n> Este materi |
| POST | /api/knowledge/mission-control/save | 404 | ❌ | {"error":"doc not found"}  |

## Bugs Found
### 1. [High] Chat flow incomplete
- Repro steps: Open Chat and test conversation/thread/snippets/composer/send behavior.
- Expected: All chat checks pass
- Actual: Only 3/5 checks passed
### 2. [High] Mission KB flow incomplete
- Repro steps: Open Mission KB, switch docs, test editor and buttons.
- Expected: 2 docs shown, switchable, editable, undo/save present
- Actual: Only 0/4 checks passed
### 3. [High] One or more required GET endpoints failing
- Repro steps: Call required endpoints with Basic Auth.
- Expected: All GET endpoints should return 2xx/3xx with non-empty payload
- Actual: Only 4/5 passed