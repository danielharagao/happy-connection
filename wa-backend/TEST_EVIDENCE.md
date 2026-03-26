# Evidências de Teste Manual

Data: 2026-03-14 (UTC)

## 1) Status da API

Comando:
```bash
curl -s http://127.0.0.1:8790/wa/status
```

Saída:
```json
{"ok":true,"connected":false,"state":"closed","hasQr":true,"reconnectAttempts":0,"lastConnectedAt":null,"lastError":null}
```

Resultado: endpoint responde corretamente; sessão aguardando pareamento (QR disponível).

---

## 2) Listagem de chats

Comando:
```bash
curl -s http://127.0.0.1:8790/wa/chats
```

Saída:
```json
{"ok":true,"total":0,"items":[]}
```

Resultado: endpoint funcional; sem chats ainda por não estar autenticado.

---

## 3) Fluxo de QR para pareamento

Comando:
```bash
curl -s http://127.0.0.1:8790/wa/pairing | python3 -c 'import sys,json;d=json.load(sys.stdin);print({"ok":d.get("ok"),"qrLen":len(d.get("qr","")),"hasPng":bool(d.get("qrPngDataUrl"))})'
```

Saída:
```text
{'ok': True, 'qrLen': 237, 'hasPng': True}
```

Resultado: endpoint de pareamento OK, QR serializado e PNG disponível.

---

## 4) Envio de mensagem (comportamento em sessão desconectada)

Comando:
```bash
curl -s -X POST http://127.0.0.1:8790/wa/send -H 'content-type: application/json' -d '{"chatId":"+5511999999999","text":"teste"}'
```

Saída:
```json
{"ok":false,"error":"whatsapp_not_connected"}
```

Resultado: tratamento de erro/estado esperado sem travar request.
