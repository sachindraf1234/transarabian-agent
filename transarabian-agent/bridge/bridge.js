/**
 * bridge/bridge.js - tiny WhatsApp Web bridge (whatsapp-web.js)
 *
 * WHY THIS EXISTS
 *   The Cloud API cannot post into a WhatsApp GROUP. Your Romania section
 *   group therefore needs a normal (business) WhatsApp account connected via
 *   WhatsApp Web. This service logs in once (scan the QR) and exposes:
 *
 *     POST /send         {to:"94xxxxxxxxx", text:"..."}
 *     POST /send-group   {jid:"120363xxxx@g.us", text:"..."}
 *     POST /send-media   {to, media, filename, caption}
 *     GET  /groups       list groups with their JIDs (copy the Romania one)
 *     GET  /status       ready / qr / disconnected
 *     GET  /qr           current QR (text) for the terminal
 *
 *   Everything is protected by x-bridge-token (WA_BRIDGE_TOKEN in .env).
 *
 * RUN
 *   cd bridge && npm i && node bridge.js
 *   then set WA_BRIDGE_ENABLED=true, WA_BRIDGE_URL=http://127.0.0.1:3001,
 *        WA_BRIDGE_TOKEN=..., ROMANIA_GROUP_JID=... in ../.env
 *
 * ANTI-BAN NOTES
 *   - one phone, one session; never log the same number into two places
 *   - pacing (typing + gaps between recipients) is done by the Python side
 *     (human_behavior.py) — this bridge only speaks when it is told to
 *   - keep daily volume modest and only message people who contacted you
 */
const express = require('express');
const qrcode = require('qrcode-terminal');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');

const PORT = process.env.BRIDGE_PORT || 3001;
const TOKEN = process.env.WA_BRIDGE_TOKEN || 'change_me_local_token';

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: './.wwebjs_auth' }),
  puppeteer: { headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] },
});

let state = { ready: false, qr: null, info: null };

client.on('qr', (qr) => { state.qr = qr; qrcode.generate(qr, { small: true }); console.log('Scan the QR above with WhatsApp (Linked devices).'); });
client.on('ready', () => { state.ready = true; state.qr = null; state.info = client.info; console.log('WhatsApp bridge READY'); });
client.on('disconnected', () => { state.ready = false; console.log('WhatsApp bridge DISCONNECTED'); });

const app = express();
app.use(express.json({ limit: '20mb' }));
app.use((req, res, next) => {
  if (req.path === '/status' || req.path === '/qr') return next();
  if ((req.headers['x-bridge-token'] || '') !== TOKEN) return res.status(401).json({ error: 'bad token' });
  next();
});

const jid = (to) => (String(to).includes('@') ? to : `${String(to).replace(/[^0-9]/g, '')}@c.us`);

app.get('/status', (req, res) => res.json({ ready: state.ready, info: state.info }));
app.get('/qr', (req, res) => res.json({ qr: state.qr }));
app.get('/groups', async (req, res) => {
  if (!state.ready) return res.status(503).json({ error: 'not ready' });
  const chats = await client.getChats();
  const groups = chats.filter((c) => c.isGroup).map((c) => ({ jid: c.id._serialized, name: c.name }));
  res.json({ groups });
});

app.get('/contacts', async (req, res) => {
  try {
    if (!state.ready) return res.status(503).json({ error: 'not ready' });
    const list = await client.getContacts();
    const contacts = list.map((c) => ({
      number: c.number || (c.id && c.id.user) || '',
      name: c.name || c.pushname || '',
      isBusiness: !!c.isBusiness,
    })).filter((c) => c.number);
    res.json({ count: contacts.length, contacts });
  } catch (e) { res.status(500).json({ error: String(e.message || e) }); }
});

app.post('/send', async (req, res) => {
  try {
    if (!state.ready) return res.status(503).json({ error: 'not ready' });
    const m = await client.sendMessage(jid(req.body.to), req.body.text);
    res.json({ ok: true, id: m.id._serialized });
  } catch (e) { res.status(500).json({ error: String(e.message || e) }); }
});

app.post('/send-group', async (req, res) => {
  try {
    if (!state.ready) return res.status(503).json({ error: 'not ready' });
    const m = await client.sendMessage(jid(req.body.jid), req.body.text);
    res.json({ ok: true, id: m.id._serialized });
  } catch (e) { res.status(500).json({ error: String(e.message || e) }); }
});

app.post('/send-media', async (req, res) => {
  try {
    if (!state.ready) return res.status(503).json({ error: 'not ready' });
    const media = await MessageMedia.fromUrl(req.body.media, { unsafeMime: true });
    media.filename = req.body.filename || media.filename;
    const m = await client.sendMessage(jid(req.body.to), media, { caption: req.body.caption || '' });
    res.json({ ok: true, id: m.id._serialized });
  } catch (e) { res.status(500).json({ error: String(e.message || e) }); }
});

/**
 * INBOUND -> forward to the Python agent so the AI can answer/escalate.
 * Set AGENT_WEBHOOK=http://127.0.0.1:8000/api/bridge/inbound
 */
const AGENT_WEBHOOK = process.env.AGENT_WEBHOOK || '';
client.on('message', async (msg) => {
  if (!AGENT_WEBHOOK) return;
  try {
    await fetch(AGENT_WEBHOOK, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-bridge-token': TOKEN },
      body: JSON.stringify({ from: msg.from, body: msg.body, name: msg._data?.notifyName || '', id: msg.id._serialized }),
    });
  } catch (e) { console.error('forward failed', e.message); }
});

client.initialize();
app.listen(PORT, () => console.log(`whatsapp bridge on http://127.0.0.1:${PORT}`));
