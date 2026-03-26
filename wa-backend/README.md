# WhatsApp Backend (Baileys)

Backend interno para CRM/cockpit com conexão real no WhatsApp via **Baileys**.

## Entregas deste módulo

- Sessão persistente com `useMultiFileAuthState` (pasta `data/auth/`).
- Reconnect robusto com backoff progressivo.
- Captura de eventos realtime:
  - `messages.upsert`
  - `chats.upsert` / `chats.update`
  - `contacts.upsert`
- Store local rápida (memória) + persistência em disco (`data/store.json`).
- API HTTP interna:
  - `GET /wa/status`
  - `GET /wa/pairing` (QR quando necessário)
  - `GET /wa/chats`
  - `GET /wa/chats/:id/messages`
  - `POST /wa/send`
- Normalização de números/IDs para compatibilidade CRM (`+5511...` -> `5511...@s.whatsapp.net`).

## Requisitos

- Node.js 20+

## Setup

```bash
cd apps/openclaw-cockpit/wa-backend
npm install
cp .env.example .env  # opcional
```

## Rodar

```bash
npm start
# API em http://127.0.0.1:8790
```

## Parar

- Se rodando no terminal atual: `Ctrl+C`
- Se rodando via supervisor/systemd/pm2: parar pelo gerenciador usado.

## Variáveis de ambiente

| Variável | Default | Descrição |
|---|---:|---|
| `WA_HOST` | `127.0.0.1` | Host do servidor HTTP |
| `WA_PORT` | `8790` | Porta do servidor HTTP |
| `WA_AUTH_DIR` | `./data/auth` | Sessão persistente multi-file |
| `WA_STORE_FILE` | `./data/store.json` | Persistência local de chats/mensagens |
| `WA_LOG_LEVEL` | `info` | Nível de log |
| `WA_SYNC_HISTORY` | `true` | Tentar sincronizar histórico |
| `WA_CONNECT_TIMEOUT_MS` | `25000` | Timeout de conexão |
| `WA_DEFAULT_COUNTRY_CODE` | `55` | Prefixo para normalização de telefone |
| `WA_MAX_MESSAGES_PER_CHAT` | `2000` | Retenção local por chat |

## Fluxo de pareamento (QR)

1. Suba o backend.
2. Consulte `GET /wa/status` e confirme `hasQr: true`.
3. Consulte `GET /wa/pairing`.
4. Use `qrPngDataUrl` (ou `qr`) para exibir/scanear no WhatsApp.
5. Após scan, `GET /wa/status` deve ficar `connected: true`.

## Exemplos de uso

```bash
curl -s http://127.0.0.1:8790/wa/status
curl -s http://127.0.0.1:8790/wa/chats
curl -s "http://127.0.0.1:8790/wa/chats/5511999999999/messages?limit=50"
curl -s -X POST http://127.0.0.1:8790/wa/send \
  -H 'content-type: application/json' \
  -d '{"chatId":"+5511999999999","text":"Olá"}'
```

## Observações de segurança/logs

- Não loga conteúdo de credenciais da sessão.
- Logs focam em estado de conexão/erros operacionais.
- Em logout (`DisconnectReason.loggedOut`), é necessário novo pareamento.
