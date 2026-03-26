import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import express from 'express';
import Pino from 'pino';
import QRCode from 'qrcode';
import { Boom } from '@hapi/boom';
import {
  makeWASocket,
  useMultiFileAuthState,
  fetchLatestWaWebVersion,
  DisconnectReason,
  Browsers,
  jidNormalizedUser,
} from '@whiskeysockets/baileys';

const logger = Pino({ level: process.env.WA_LOG_LEVEL || 'info' });

const config = {
  host: process.env.WA_HOST || '127.0.0.1',
  port: Number(process.env.WA_PORT || 8790),
  authDir: path.resolve(process.cwd(), process.env.WA_AUTH_DIR || './data/auth'),
  storeFile: path.resolve(process.cwd(), process.env.WA_STORE_FILE || './data/store.json'),
  connectTimeoutMs: Number(process.env.WA_CONNECT_TIMEOUT_MS || 25000),
  syncHistory: String(process.env.WA_SYNC_HISTORY || 'true').toLowerCase() === 'true',
  defaultCountryCode: String(process.env.WA_DEFAULT_COUNTRY_CODE || '55').replace(/\D/g, ''),
  maxMessagesPerChat: Number(process.env.WA_MAX_MESSAGES_PER_CHAT || 2000),
};

fs.mkdirSync(config.authDir, { recursive: true });
fs.mkdirSync(path.dirname(config.storeFile), { recursive: true });

const store = {
  chats: new Map(),
  messages: new Map(),
  contacts: new Map(),
};

function loadStore() {
  if (!fs.existsSync(config.storeFile)) return;
  try {
    const parsed = JSON.parse(fs.readFileSync(config.storeFile, 'utf8'));
    for (const item of parsed?.chats || []) store.chats.set(item.id, item);
    for (const [jid, msgs] of Object.entries(parsed?.messages || {})) {
      store.messages.set(jid, Array.isArray(msgs) ? msgs : []);
    }
    for (const item of parsed?.contacts || []) store.contacts.set(item.id, item);
    logger.info({ file: config.storeFile }, 'WA store loaded');
  } catch (err) {
    logger.warn({ err: String(err) }, 'Failed to read WA store file, continuing with empty store');
  }
}

function persistStore() {
  const payload = {
    chats: Array.from(store.chats.values()),
    messages: Object.fromEntries(Array.from(store.messages.entries())),
    contacts: Array.from(store.contacts.values()),
    updatedAt: new Date().toISOString(),
  };
  fs.writeFileSync(config.storeFile, JSON.stringify(payload, null, 2));
}

loadStore();
setInterval(() => {
  try {
    persistStore();
  } catch (err) {
    logger.warn({ err: String(err) }, 'Failed to persist WA store');
  }
}, 10_000);

let sock = null;
let connecting = false;
let reconnectAttempts = 0;
let lastQr = null;
let lastConnectionError = null;
let lastConnectedAt = null;
let connectionState = 'closed';
let isConnected = false;

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function stripJid(jid) {
  if (!jid) return '';
  return String(jid).trim().toLowerCase();
}

function normalizePhone(input) {
  const raw = String(input || '').trim();
  if (!raw) return '';

  if (raw.includes('@')) return jidNormalizedUser(raw);

  let digits = raw.replace(/\D/g, '');
  if (!digits) return '';

  if (digits.startsWith('00')) digits = digits.slice(2);
  if (digits.startsWith('0')) digits = digits.replace(/^0+/, '');

  if (!digits.startsWith(config.defaultCountryCode) && (digits.length === 10 || digits.length === 11)) {
    digits = `${config.defaultCountryCode}${digits}`;
  }

  return jidNormalizedUser(`${digits}@s.whatsapp.net`);
}

function normalizeChatId(input) {
  const value = String(input || '').trim();
  if (!value) return '';
  if (value.includes('@')) return jidNormalizedUser(value);
  return normalizePhone(value);
}

function safeMessageText(msg = {}) {
  return (
    msg?.conversation ||
    msg?.extendedTextMessage?.text ||
    msg?.imageMessage?.caption ||
    msg?.videoMessage?.caption ||
    msg?.documentMessage?.caption ||
    msg?.buttonsResponseMessage?.selectedDisplayText ||
    msg?.listResponseMessage?.title ||
    msg?.templateButtonReplyMessage?.selectedDisplayText ||
    ''
  );
}

function toIsoTimestamp(tsAny) {
  const ts = Number(tsAny || 0);
  if (!ts) return null;
  const ms = ts > 1e12 ? ts : ts * 1000;
  return new Date(ms).toISOString();
}

function upsertChat(chat = {}) {
  const id = stripJid(chat.id || chat.jid);
  if (!id) return;
  const current = store.chats.get(id) || {};
  store.chats.set(id, {
    ...current,
    ...chat,
    id,
  });
}

function addMessage(msg = {}) {
  const chatId = stripJid(msg?.key?.remoteJid);
  const id = String(msg?.key?.id || '').trim();
  if (!chatId || !id) return;

  const arr = store.messages.get(chatId) || [];
  if (!arr.some((m) => m.id === id)) {
    const normalized = mapMessage(msg);
    arr.push(normalized);
    if (arr.length > config.maxMessagesPerChat) {
      arr.splice(0, arr.length - config.maxMessagesPerChat);
    }
    store.messages.set(chatId, arr);
  }

  const chat = store.chats.get(chatId) || { id: chatId };
  const unread = normalizedUnread(chat.unreadCount, msg.key?.fromMe);
  store.chats.set(chatId, {
    ...chat,
    id: chatId,
    conversationTimestamp: Number(msg.messageTimestamp || Date.now() / 1000),
    lastMessageText: safeMessageText(msg.message),
    unreadCount: unread,
  });
}

function normalizedUnread(current, fromMe) {
  const n = Number(current || 0);
  if (fromMe) return n;
  return n + 1;
}

function mapChat(chat = {}) {
  const jid = stripJid(chat.id || chat.jid);
  const messages = store.messages.get(jid) || [];
  const convo = messages[messages.length - 1];
  const last = chat.lastMessageText || convo?.text || '';
  const ts = chat.conversationTimestamp || convo?.timestamp || null;

  return {
    id: jid,
    name: chat.name || chat.subject || store.contacts.get(jid)?.name || jid,
    unreadCount: Number(chat.unreadCount || 0),
    archived: Boolean(chat.archived),
    muteEndTime: chat.muteEndTime || null,
    lastMessage: last,
    lastTimestamp: typeof ts === 'string' ? ts : toIsoTimestamp(ts),
  };
}

function mapMessage(message = {}) {
  const key = message.key || {};
  return {
    id: key.id || '',
    chatId: stripJid(key.remoteJid),
    fromMe: Boolean(key.fromMe),
    participant: key.participant || null,
    timestamp: toIsoTimestamp(message.messageTimestamp),
    text: safeMessageText(message.message),
    status: message.status || null,
  };
}

function statusPayload() {
  return {
    ok: true,
    connected: Boolean(isConnected),
    state: connectionState || 'closed',
    hasQr: Boolean(lastQr),
    reconnectAttempts,
    lastConnectedAt,
    lastError: lastConnectionError,
  };
}

async function connectWhatsApp() {
  if (connecting) return;
  connecting = true;

  try {
    logger.info('Starting WhatsApp connection');
    const { state, saveCreds } = await useMultiFileAuthState(config.authDir);
    const { version } = await fetchLatestWaWebVersion();

    sock = makeWASocket({
      version,
      auth: state,
      printQRInTerminal: false,
      browser: Browsers.macOS('OpenClaw Cockpit'),
      syncFullHistory: config.syncHistory,
      connectTimeoutMs: config.connectTimeoutMs,
      markOnlineOnConnect: false,
      defaultQueryTimeoutMs: 20_000,
      generateHighQualityLinkPreview: false,
      logger: logger.child({ module: 'baileys-socket' }),
      shouldSyncHistoryMessage: () => config.syncHistory,
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('messages.upsert', (event) => {
      const list = Array.isArray(event.messages) ? event.messages : [];
      for (const msg of list) addMessage(msg);
      logger.debug({ type: event.type, count: list.length }, 'messages.upsert');
    });

    sock.ev.on('chats.upsert', (chats) => {
      for (const chat of chats || []) upsertChat(chat);
      logger.debug({ count: chats?.length || 0 }, 'chats.upsert');
    });

    sock.ev.on('chats.update', (chats) => {
      for (const chat of chats || []) upsertChat(chat);
      logger.debug({ count: chats?.length || 0 }, 'chats.update');
    });

    sock.ev.on('contacts.upsert', (contacts) => {
      for (const contact of contacts || []) {
        const id = stripJid(contact.id);
        if (!id) continue;
        store.contacts.set(id, { ...store.contacts.get(id), ...contact, id });
      }
      logger.debug({ count: contacts?.length || 0 }, 'contacts.upsert');
    });

    sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (connection) {
        connectionState = String(connection);
      }

      if (qr) {
        lastQr = qr;
        isConnected = false;
        logger.info('QR code updated, waiting for pairing');
      }

      if (connection === 'open') {
        reconnectAttempts = 0;
        lastQr = null;
        lastConnectionError = null;
        lastConnectedAt = new Date().toISOString();
        isConnected = true;
        connectionState = 'open';
        logger.info('WhatsApp connected');
      }

      if (connection === 'close') {
        isConnected = false;
        connectionState = 'closed';
        const code = new Boom(lastDisconnect?.error)?.output?.statusCode;
        const isLoggedOut = code === DisconnectReason.loggedOut;
        const reason = String(lastDisconnect?.error || code || 'unknown');
        lastConnectionError = reason;
        logger.warn({ code, isLoggedOut }, 'WhatsApp connection closed');

        if (isLoggedOut) {
          logger.warn('Session logged out. Delete auth folder and pair again if needed.');
          return;
        }

        reconnectAttempts += 1;
        const backoffMs = Math.min(30_000, 1_500 * reconnectAttempts);
        await wait(backoffMs);
        connectWhatsApp().catch((err) => {
          logger.error({ err: String(err) }, 'Reconnect failed');
        });
      }
    });
  } catch (err) {
    lastConnectionError = String(err);
    logger.error({ err: String(err) }, 'WA connect setup failed');
  } finally {
    connecting = false;
  }
}

const app = express();
app.use(express.json({ limit: '1mb' }));

app.get('/wa/status', async (_req, res) => {
  res.json(statusPayload());
});

app.get('/wa/pairing', async (_req, res) => {
  if (!lastQr) {
    return res.status(404).json({ ok: false, error: 'qr_not_available', message: 'No QR available now. Check /wa/status and wait for reconnect.' });
  }
  try {
    const qrPngDataUrl = await QRCode.toDataURL(lastQr, { margin: 1, width: 320 });
    return res.json({ ok: true, qr: lastQr, qrPngDataUrl });
  } catch (err) {
    return res.status(500).json({ ok: false, error: 'qr_encode_failed', detail: String(err) });
  }
});

app.get('/wa/chats', async (req, res) => {
  try {
    const limit = Math.max(1, Math.min(500, Number(req.query.limit || 200)));
    const chats = Array.from(store.chats.values()).map(mapChat);
    chats.sort((a, b) => (Date.parse(b.lastTimestamp || 0) || 0) - (Date.parse(a.lastTimestamp || 0) || 0));
    return res.json({ ok: true, total: chats.length, items: chats.slice(0, limit) });
  } catch (err) {
    logger.error({ err: String(err) }, 'Failed to list chats');
    return res.status(500).json({ ok: false, error: 'failed_to_list_chats' });
  }
});

app.get('/wa/chats/:id/messages', async (req, res) => {
  try {
    const chatId = normalizeChatId(req.params.id);
    if (!chatId) {
      return res.status(400).json({ ok: false, error: 'invalid_chat_id' });
    }

    const limit = Math.max(1, Math.min(1000, Number(req.query.limit || 200)));
    const offset = Math.max(0, Number(req.query.offset || 0));
    const arr = store.messages.get(chatId) || [];
    return res.json({
      ok: true,
      chatId,
      total: arr.length,
      items: arr.slice(offset, offset + limit),
    });
  } catch (err) {
    logger.error({ err: String(err) }, 'Failed to list messages');
    return res.status(500).json({ ok: false, error: 'failed_to_list_messages' });
  }
});

app.post('/wa/send', async (req, res) => {
  const timeoutMs = 20_000;
  const chatId = normalizeChatId(req.body?.chatId || req.body?.to || req.body?.phone || req.body?.target);
  const text = String(req.body?.text || req.body?.message || '').trim();

  if (!chatId) return res.status(400).json({ ok: false, error: 'invalid_target' });
  if (!text) return res.status(400).json({ ok: false, error: 'message_required' });

  // Em alguns ciclos do Baileys, connection=open e isConnected=true,
  // mas ws.readyState pode oscilar momentaneamente. Priorizamos estado lógico.
  const transportReady = Boolean(sock && (sock.ws?.readyState === 1 || isConnected || connectionState === 'open'));
  if (!transportReady) return res.status(503).json({ ok: false, error: 'whatsapp_not_connected' });

  try {
    const sent = await Promise.race([
      sock.sendMessage(chatId, { text }),
      new Promise((_, reject) => setTimeout(() => reject(new Error('send_timeout')), timeoutMs)),
    ]);

    return res.json({
      ok: true,
      to: chatId,
      id: sent?.key?.id || null,
      timestamp: sent?.messageTimestamp || null,
    });
  } catch (err) {
    logger.error({ err: String(err), to: chatId }, 'Failed to send message');
    return res.status(502).json({ ok: false, error: 'send_failed', detail: String(err) });
  }
});

app.use((err, _req, res, _next) => {
  logger.error({ err: String(err) }, 'Unhandled request error');
  res.status(500).json({ ok: false, error: 'internal_error' });
});

app.listen(config.port, config.host, () => {
  logger.info({ host: config.host, port: config.port }, 'WA backend listening');
  connectWhatsApp().catch((err) => {
    lastConnectionError = String(err);
    logger.error({ err: String(err) }, 'Initial WhatsApp connect failed');
  });
});
