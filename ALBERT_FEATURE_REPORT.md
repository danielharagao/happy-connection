# ALBERT FEATURE REPORT (REAL MVP)

## Status real atual

✅ Backend Albert saiu do mock e agora usa **fila + worker real** para tentativa de entrada no Google Meet.

⚠️ No ambiente validado agora, o teste real terminou em `failed` com motivo explícito: `missing_playwright` (pacote Python não instalado neste runtime do teste). Isso é comportamento honesto (não mockado).

---

## O que foi implementado

### 1) Worker real (`albert_worker.py`)
- Consome jobs de `data/albert_jobs.json`.
- Processa sessão com Playwright Chromium (quando disponível).
- Fluxo de join guest:
  - abre link Meet
  - tenta clicar "Use without an account" (variações)
  - preenche nome guest: **Albert | Danhausch Notes**
  - tenta desligar mic/cam
  - tenta clicar Join/Ask to join
- Estados reais suportados:
  - `created`, `joining`, `waiting_admit`, `joined`, `recording`, `processing`, `done`, `failed`
- Atualiza sessão persistentemente com timeline e erro real.
- Gera artefatos por sessão em `data/albert_artifacts/<session_id>/`:
  - `runtime.log`
  - `meet-proof.png` (quando browser sobe e screenshot é possível)

### 2) Integração em `app.py`
- Endpoints mantidos:
  - `POST /api/albert/session/start`
  - `POST /api/albert/session/schedule`
  - `GET /api/albert/sessions`
  - `GET /api/albert/sessions/<id>`
- Sessão criada com:
  - `mode: "real"`
  - `trigger: "now" | "scheduled"`
  - `artifacts: {}` inicial
- Em vez de fake thread, agora enfileira job real para o worker.

### 3) Store compartilhado (`albert_store.py`)
- Centraliza persistência de sessões/fila.
- Lock de arquivo (`fcntl`) para coordenação API + worker em processos separados.

### 4) Recording/transcription MVP honesto
- Hook explícito por env: `ALBERT_AUDIO_CAPTURE_CMD`.
- Sem hook configurado: sessão pode permanecer `joined` com `recordingPending=true` e motivo claro.
- Sem fake de transcrição/insights/sumário automáticos.
- TODO explícito no fluxo: pipeline de transcrição pós-captura.

### 5) Ops
- Script adicionado: `scripts/start_albert_worker.sh`
- `requirements.txt` atualizado com `playwright`.
- `README.md` atualizado com instalação e execução.

---

## Validação executada

### Checks
- `python3 -m py_compile app.py albert_store.py albert_worker.py` ✅
- `node --check static/app.js` ✅

### Execução real (sem mock)
- App iniciado em porta alternativa (`8799`) para evitar conflito local.
- Worker iniciado.
- `POST /api/albert/session/start` com `https://meet.google.com/abc-defg-hij`.
- Sessão evoluiu para `failed` com erro real:
  - `error: "missing_playwright"`
  - timeline com detalhe: `Playwright não está instalado no ambiente Python.`
- Artefato gerado:
  - `data/albert_artifacts/alb-0e32337ed6b0/runtime.log`

---

## Limitações atuais (reais)
- Ainda depende de instalar Playwright + Chromium no ambiente para efetuar join real em browser.
- Captura/recording/transcrição ainda não completos de ponta a ponta no código base; há hook de gravação externa + TODO explícito para transcrição.
- Seletores do Meet podem variar por idioma/layout da conta Google; fluxo atual cobre heurísticas comuns de guest join.

---

## Próximo passo recomendado

1. `pip install -r requirements.txt`
2. `python3 -m playwright install chromium`
3. Rodar novo teste real com link válido e anfitrião disponível para admitir.
4. Implementar script de captura de áudio (hook) + etapa de transcrição real.
