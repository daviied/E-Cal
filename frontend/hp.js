// Sync with an HP Prime G2 from the web page.
//
// The calculator is a USB HID device, and WebHID lets a page in Chrome/Edge on
// a computer talk to one. This file is the browser half: a JavaScript port of
// the USB link layer in hpprime/sync/cvsync/primelink.py (read that for the
// protocol notes), plus a small panel. The merge logic stays on the server
// (backend/app/hp.py): it asks this page, over a WebSocket, to read or write
// one note on the calculator at a time.
//
// Online mode (the panel's Online switch) keeps CalcVault 2 on the calculator
// in step with this page while both are open: see onlineTick below.
//
// Needs: a browser with WebHID (Chrome or Edge on Windows/macOS/Linux/ChromeOS,
// not Firefox, Safari, or Android), and https:// or localhost.

const VENDOR_ID = 0x03f0;
const PRODUCT_IDS = [0x2441, 0x1541, 0x0441]; // 1024-byte reports first
const CMD_CHECK_READY = 0xff;
const CMD_REQUEST_FILE = 0xf8;
const CMD_FILE = 0xf7;
const CMD_BACKUP = 0xf9;
const TYPE_NOTE = 0x05;

class LinkError extends Error {}
class LinkTimeout extends Error {}

const BUSY =
  'the calculator stopped taking data: it does not answer USB while a program is running. Close ' +
  'the program, or in CalcVault 2 turn on Settings > Let the PC sync while open.';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function withTimeout(promise, ms, makeError) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(makeError()), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function cat(...parts) {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

// ------------------------------------------------------------------ CRC-16

const CRC_TABLE = (() => {
  const table = [];
  for (let i = 0; i < 256; i++) {
    let crc = i << 8;
    for (let k = 0; k < 8; k++) crc = crc & 0x8000 ? (crc << 1) ^ 0x1021 : crc << 1;
    table.push(crc & 0xffff);
  }
  return table;
})();

function crc16(data) {
  let crc = 0;
  for (const b of data) crc = (CRC_TABLE[((crc >> 8) ^ b) & 0xff] ^ (crc << 8)) & 0xffff;
  return crc;
}

// ------------------------------------------------------------- messages

function utf16le(text) {
  const out = new Uint8Array(text.length * 2);
  for (let i = 0; i < text.length; i++) {
    const u = text.charCodeAt(i);
    out[2 * i] = u & 0xff;
    out[2 * i + 1] = u >> 8;
  }
  return out;
}

function nameBytes(name) {
  if (!name || name.length > 32 || /[\\/:*?"<>|\0]/.test(name)) {
    throw new LinkError('not a name the calculator can store: ' + name);
  }
  let nb = utf16le(name);
  // The name field must be a whole number of 4-byte words (see primelink.py).
  if (nb.length % 4) nb = cat(nb, new Uint8Array(4 - (nb.length % 4)));
  return nb;
}

function withLength(cmd, body) {
  const n = body.length;
  return cat(Uint8Array.of(cmd, 0x01, (n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff), body);
}

function fileMessage(cmd, name, ftype, content = null) {
  const nb = nameBytes(name);
  const body = cat(Uint8Array.of(ftype, nb.length, 0, 0), nb, content || new Uint8Array(0));
  const msg = withLength(cmd, body);
  const covered = msg.slice(0, Math.max(0, msg.length - 6));
  for (const off of [8, 9]) if (off < covered.length) covered[off] = 0;
  const crc = crc16(covered);
  msg[8] = crc & 0xff;
  msg[9] = crc >> 8;
  return msg;
}

// -> {type, name, content}, or null when the calculator has no such object
function parseFileReply(reply) {
  if (!reply || !reply.length || reply[0] === CMD_BACKUP) return null;
  if (reply[0] !== CMD_FILE) throw new LinkError('expected a file (F7), got ' + reply[0].toString(16));
  if (reply.length < 10) throw new LinkError('file reply too short');
  const ftype = reply[6];
  const nlen = reply[7];
  const embedded = reply[8] | (reply[9] << 8);
  const covered = reply.slice(0, Math.max(0, reply.length - 6));
  for (const off of [8, 9]) if (off < covered.length) covered[off] = 0;
  if (crc16(covered) !== embedded) throw new LinkError('file reply failed its checksum');
  const name = new TextDecoder('utf-16le').decode(reply.subarray(10, 10 + nlen)).replace(/\0+$/, '');
  return { type: ftype, name, content: reply.slice(10 + nlen) };
}

// Splits a message into reports: [sequence] + up to `capacity` bytes. Reports
// always go out padded to full size here (WebHID needs the exact size), which
// is the Windows behaviour in primelink.py: a length-prefixed message says
// where it ends, so no empty closing report is sent.
function fragment(message, capacity) {
  const out = [];
  let seq = 0;
  let off = 0;
  while (message.length - off >= capacity) {
    out.push(cat(Uint8Array.of(seq), message.subarray(off, off + capacity)));
    seq = (seq + 1) % 255;
    off += capacity;
  }
  const tail = message.subarray(off);
  if (tail.length || !(message.length >= 6 && message[1] === 0x01)) out.push(cat(Uint8Array.of(seq), tail));
  return out;
}

// ------------------------------------------------------------- notes

function noteText(content) {
  let b = content || new Uint8Array(0);
  if (b[0] === 0xff && b[1] === 0xfe) b = b.subarray(2);
  if (b.length < 4) return '';
  let end = 0;
  while (end + 1 < b.length && (b[end] | (b[end + 1] << 8)) !== 0) end += 2;
  return new TextDecoder('utf-16le').decode(b.subarray(0, end));
}

function findEvenOffset(hay, needle) {
  outer: for (let i = 0; i + needle.length <= hay.length; i += 2) {
    for (let j = 0; j < needle.length; j++) if (hay[i + j] !== needle[j]) continue outer;
    return i;
  }
  return -1;
}

// A note the calculator already has keeps its shape (formatting tail or none);
// a new note gets the minimal formatted shape the Notes app writes.
function noteBytes(text, existing = null) {
  const body = cat(utf16le(text), Uint8Array.of(0, 0));
  if (existing) {
    const k = findEvenOffset(existing, utf16le('CSW'));
    return k === -1 ? body : cat(body, existing.subarray(k));
  }
  const tail = cat(
    utf16le('CSWD110'),
    Uint8Array.of(0xff, 0xff, 0xff, 0xff),
    utf16le('\\l'),
    Uint8Array.of(0x3e, 0x01),
    utf16le('\\0\\3\\0\\0\\0\\0\\0\\0\\0\\0')
  );
  return cat(body, tail);
}

// ------------------------------------------------------------- the link

function matches(device) {
  return device.vendorId === VENDOR_ID && PRODUCT_IDS.includes(device.productId);
}

class PrimeLink {
  constructor(device, log = () => {}) {
    this.log = log;
    this.inbox = [];
    this.waiter = null;
    this.report = 1024;
    this.outSize = null;
    this.dev = null;
    this._attach(device);
  }

  _attach(device) {
    if (this.dev) this.dev.removeEventListener('inputreport', this._onReport);
    this.dev = device;
    this._onReport = (e) => {
      this.inbox.push(new Uint8Array(e.data.buffer.slice(e.data.byteOffset, e.data.byteOffset + e.data.byteLength)));
      if (this.waiter) {
        const w = this.waiter;
        this.waiter = null;
        w();
      }
    };
    device.addEventListener('inputreport', this._onReport);
  }

  // The report sizes the HID descriptor declares: the largest single input
  // (or output) item, as primelink.py reads it.
  _declaredSizes() {
    let input = null;
    let output = null;
    for (const col of this.dev.collections || []) {
      for (const [list, which] of [[col.inputReports, 'in'], [col.outputReports, 'out']]) {
        for (const rep of list || []) {
          for (const item of rep.items || []) {
            const bytes = Math.floor((item.reportSize * item.reportCount) / 8);
            if (which === 'in') input = Math.max(input || 0, bytes);
            else output = Math.max(output || 0, bytes);
          }
        }
      }
    }
    return { input, output };
  }

  async open() {
    if (!this.dev.opened) {
      try {
        await this.dev.open();
      } catch (e) {
        throw new LinkError(
          "could not open the calculator (" + e.message + "). Is HP's Connectivity Kit (or another " +
            'program or tab) using it? Close that and try again.'
        );
      }
    }
    const declared = this._declaredSizes();
    this.outSize = declared.output;
    const sizes = this.dev.productId === 0x2441 ? [1024, 64] : [64, 1024];
    if (declared.input && sizes.includes(declared.input)) {
      sizes.splice(sizes.indexOf(declared.input), 1);
      sizes.unshift(declared.input);
    }
    let last = null;
    for (const size of sizes) {
      this.report = size;
      try {
        if (await this.checkReady(2000)) {
          this.log('link: ' + size + '-byte reports');
          return;
        }
      } catch (e) {
        if (!(e instanceof LinkError)) throw e;
        last = e;
      }
    }
    await this.closeQuiet();
    throw new LinkError(
      'the calculator did not answer' + (last ? ' (' + last.message + ')' : '') +
        '. Make sure it is on, and on its Home screen or in CalcVault 2.'
    );
  }

  async closeQuiet() {
    try {
      await this.dev.close();
    } catch (e) {
      // already closed
    }
  }

  async close() {
    await this.closeQuiet();
    this.dev.removeEventListener('inputreport', this._onReport);
  }

  // -- report layer

  async readReport(timeoutMs) {
    if (this.inbox.length) return this.inbox.shift();
    await new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.waiter = null;
        resolve();
      }, timeoutMs);
      this.waiter = () => {
        clearTimeout(timer);
        resolve();
      };
    });
    return this.inbox.length ? this.inbox.shift() : null;
  }

  async _drain() {
    for (;;) {
      await sleep(10);
      if (!this.inbox.length) return;
      this.inbox.length = 0;
    }
  }

  // One report, given up on after 5 s: a calculator running a program stops
  // taking reports, and the write then never completes.
  async _write(pkt) {
    const data = new Uint8Array(Math.max(this.outSize || this.report, pkt.length));
    data.set(pkt);
    try {
      await withTimeout(this.dev.sendReport(0, data), 5000, () => new LinkError(BUSY));
    } catch (e) {
      if (e instanceof LinkError) throw e;
      throw new LinkError('USB write failed (' + e.message + ')');
    }
  }

  async _send(message) {
    for (const pkt of fragment(message, this.report - 1)) await this._write(pkt);
  }

  // Reassembles one reply, stopping at the length it declares. `first` limits
  // the wait for the reply to start; `timeout` then limits the whole reply.
  async _reply(cmd, timeout, first = null) {
    const chunks = [];
    let total = 0;
    let expect = cmd === CMD_CHECK_READY ? 1 : null;
    let index = 0;
    const start = performance.now();
    let deadline = start + (first || timeout);
    for (;;) {
      const left = deadline - performance.now();
      if (left <= 0) throw new LinkTimeout('no reply from the calculator');
      const rep = await this.readReport(Math.max(left, 10));
      if (!rep) continue;
      const seq = rep[0];
      const payload = rep.subarray(1, this.report);
      if (seq === 0xff) continue; // out-of-band report
      if (index === 0) {
        const head = payload[0];
        if (cmd === CMD_CHECK_READY && head !== 0xff && head !== 0x59) continue;
        if (cmd === CMD_FILE && head !== CMD_FILE && head !== CMD_BACKUP) continue;
        deadline = start + timeout; // it has started; allow the rest
      }
      if (seq !== index % 255) throw new LinkError('reply out of sequence (' + seq + ', expected ' + (index % 255) + ')');
      index++;
      chunks.push(payload);
      total += payload.length;
      if (expect === null && total >= 6) {
        const head = cat(...chunks);
        if (head[0] === CMD_BACKUP) return head.slice(0, 1);
        if (head[1] !== 0x01) throw new LinkError('unexpected reply header');
        expect = 6 + (((head[2] << 24) | (head[3] << 16) | (head[4] << 8) | head[5]) >>> 0);
        if (expect > 64 * 1024 * 1024) throw new LinkError('implausible reply length');
      }
      if (expect !== null && total >= expect) return cat(...chunks).slice(0, expect);
    }
  }

  async exchange(message, timeout = 8000) {
    await this._drain();
    await this._send(message);
    return this._reply(message[0], timeout);
  }

  // -- operations

  async checkReady(timeout = 8000) {
    let r;
    try {
      r = await this.exchange(Uint8Array.of(CMD_CHECK_READY), timeout);
    } catch (e) {
      if (e instanceof LinkTimeout) return false;
      throw e;
    }
    return !!r && r.length > 0 && (r[0] === 0xff || r[0] === 0x59);
  }

  // A request is usually answered in about 0.1 s, but while the calculator is
  // still storing a note it has just received, answers come seconds late. Every
  // answer names its note, so an answer for another note is set aside. A note
  // that does not exist is never answered at all.
  async getObject(name, ftype, windows = [2500, 2500, 2500, 2500, 2500]) {
    const t0 = performance.now();
    const seen = [];
    this.lastRead = null;
    await sleep(60); // do not hammer the calculator with back-to-back requests
    for (let attempt = 0; attempt < windows.length; attempt++) {
      await this.checkReady(2000);
      await this._drain();
      await this._send(fileMessage(CMD_REQUEST_FILE, name, ftype));
      const end = performance.now() + windows[attempt];
      while (performance.now() < end) {
        let reply;
        try {
          reply = await this._reply(CMD_FILE, 60000, Math.max(50, end - performance.now()));
        } catch (e) {
          if (e instanceof LinkTimeout) break;
          throw e;
        }
        const got = parseFileReply(reply);
        if (got === null) {
          this.lastRead = { name, outcome: 'the calculator said it has no such note', asked: attempt + 1, seen };
          return null;
        }
        if (got.name === name && got.type === ftype) {
          if (attempt > 0) {
            this.log(name + ': answered on request ' + (attempt + 1) + ' after ' + ((performance.now() - t0) / 1000).toFixed(1) + ' s');
          }
          return got.content;
        }
        seen.push(got.name);
      }
    }
    this.lastRead = {
      name,
      outcome: 'no answer',
      asked: windows.length,
      secs: Math.round((performance.now() - t0) / 1000),
      seen,
    };
    return null;
  }

  async putObject(name, ftype, content) {
    if (ftype === TYPE_NOTE && content[0] === 0xff && content[1] === 0xfe) content = content.subarray(2);
    await this.checkReady(2500);
    await this._drain();
    await this._send(fileMessage(CMD_FILE, name, ftype, content));
    try {
      const r = await this._reply(CMD_FILE, 1500);
      if (r && r[0] === CMD_BACKUP) throw new LinkError('the calculator refused the transfer (firmware too old?)');
    } catch (e) {
      if (!(e instanceof LinkTimeout)) throw e; // current firmware sends no acknowledgement
    }
    // After it takes a file, the calculator's next reply fails to read on
    // Windows; a fresh connection reads normally, so reconnect after every write.
    await this.reopen();
  }

  async reopen(waitMs = 8000) {
    await this.closeQuiet();
    const end = performance.now() + waitMs;
    let last = null;
    while (performance.now() < end) {
      await sleep(400);
      try {
        if (!this.dev.opened) {
          try {
            await this.dev.open();
          } catch (e) {
            // The calculator may have re-enumerated: look for it again.
            const found = (await navigator.hid.getDevices()).filter(matches);
            if (!found.length) continue;
            this._attach(found[0]);
            await this.dev.open();
          }
        }
        if (await this.checkReady(2000)) return;
        await this.closeQuiet();
      } catch (e) {
        last = e;
        await this.closeQuiet();
      }
    }
    throw new LinkError('the calculator did not come back after a write' + (last ? ' (' + last.message + ')' : ''));
  }

  async getNote(name, windows) {
    const content = await this.getObject(name, TYPE_NOTE, windows);
    return content === null ? null : noteText(content);
  }

  // An existing note keeps its shape, which costs a read; `isNew` skips it
  // (a request for a note that does not exist goes unanswered, ~20 s).
  async putNote(name, text, isNew = false) {
    const existing = isNew ? null : await this.getObject(name, TYPE_NOTE);
    await this.putObject(name, TYPE_NOTE, noteBytes(text, existing));
  }
}

// What cvsync.store.UsbTarget.read does: an unanswered request is retried on
// fresh connections, and an unanswered CVDATA is only taken to mean "no vault"
// when the calculator has no other CalcVault notes either.
// Seconds a G2 is given to answer for a note the index says exists.
const PATIENT_READ = [6000, 10000, 14000];

async function readNote(link, name) {
  let text = await link.getNote(name, name.startsWith('CVC') ? PATIENT_READ : undefined);
  if (text !== null) return text;
  if (name.startsWith('CVC')) {
    // The index lists this note, so it exists: be patient (a G2 can take
    // several seconds to answer) rather than ask over and over.
    for (let i = 0; i < 1; i++) {
      await link.reopen();
      text = await link.getNote(name, PATIENT_READ);
      if (text !== null) return text;
    }
    const r = link.lastRead || {};
    throw new LinkError(
      name + ' did not arrive: ' + (r.outcome || 'no answer') +
        (r.asked ? ' (asked ' + r.asked + ' times over ' + (r.secs || '?') + ' s' : ' (') +
        (r.seen && r.seen.length ? '; other notes it sent instead: ' + [...new Set(r.seen)].join(', ') : '') +
        '). Nothing was changed. Close CalcVault on the calculator, leave it on the Home screen, and try again.'
    );
  }
  if (name !== 'CVDATA') return text;
  for (let i = 0; i < 3; i++) {
    await link.reopen();
    text = await link.getNote(name);
    if (text !== null) return text;
  }
  for (const other of ['CVREV', 'CVBAK', 'CVSET']) {
    if ((await link.getNote(other)) !== null) {
      throw new LinkError(
        'the calculator has CalcVault data but did not answer when asked for it. Make sure it is ' +
          'on the Home screen with nothing open, then try again.'
      );
    }
  }
  return null;
}

window.CalcVaultHP = { crc16, nameBytes, fileMessage, parseFileReply, fragment, noteText, noteBytes, PrimeLink, readNote };

// ------------------------------------------------------------- the panel

const $ = (id) => document.getElementById(id);
const panel = {
  open: $('btn-hp'),
  overlay: $('hp-overlay'),
  close: $('hp-close'),
  support: $('hp-support'),
  status: $('hp-status'),
  connect: $('hp-connect'),
  sync: $('hp-sync'),
  online: $('hp-online'),
  confirm: $('hp-confirm'),
  confirmText: $('hp-confirm-text'),
  confirmYes: $('hp-confirm-yes'),
  confirmNo: $('hp-confirm-no'),
  log: $('hp-log'),
};

// Online mode (CalcVault 2 on the calculator): the calculator as a remote for
// this page. About once a second it asks the calculator for CVREV, which the
// app changes on every save, and every couple of seconds the server for the
// tree; a change on either side runs the usual sync (the server's merge). It
// also writes CVLINK every few seconds (the app shows "online" while that
// keeps changing) and, when a calculator is opened here, CVFOCUS (the app
// opens it too). Only one tab runs it, through a Web Lock.
const ONLINE_TICK = 1000;
const WEB_EVERY = 2000;
const BEAT_EVERY = 4000;
const ONLINE_KEY = 'calcvault.hp.online';

function rememberOnline(on) {
  try {
    if (on) localStorage.setItem(ONLINE_KEY, '1');
    else localStorage.removeItem(ONLINE_KEY);
  } catch (e) {
    // private window or blocked storage: online just will not restart by itself
  }
}

function rememberedOnline() {
  try {
    return localStorage.getItem(ONLINE_KEY) === '1';
  } catch (e) {
    return false;
  }
}

if (panel.open) {
  let link = null;
  let busy = false; // a sync is running
  let ticking = false; // an online check is using the link
  let serverOk = null;

  let online = false;
  let onlineTimer = null;
  let releaseLock = null;
  let lastRev; // CVREV after the last sync (undefined: none yet)
  let lastWeb = null; // the tree after the last sync
  let tWeb = 0;
  let tBeat = 0;
  let answering = false;
  let misses = 0;
  let lastError = '';
  let pendingFocus = null;

  const supported = !!navigator.hid && window.isSecureContext;

  const stamp = () => new Date().toLocaleTimeString();
  function say(text) {
    panel.log.textContent += (panel.log.textContent ? '\n' : '') + text;
    panel.log.scrollTop = panel.log.scrollHeight;
  }
  function setStatus(text) {
    panel.status.textContent = text;
  }
  function refresh() {
    const ready = supported && serverOk !== false;
    panel.connect.disabled = !ready || busy;
    panel.sync.disabled = !ready || !link || busy || ticking;
    panel.online.disabled = !ready;
    panel.online.checked = online;
    panel.open.classList.toggle('connected', !!link);
    panel.open.classList.toggle('online', online && !!link && answering);
    panel.open.textContent = online ? (link && answering ? 'HP Prime: online' : 'HP Prime: waiting') : 'HP Prime';
    if (!supported) return;
    if (serverOk === false) return;
    if (busy) setStatus('Syncing…');
    else if (online && !link) setStatus('Online: waiting for the calculator (plug it in and turn it on).');
    else if (online && !answering) setStatus('Online: the calculator is not answering yet.');
    else if (online) setStatus('Online: the calculator follows this page.');
    else setStatus(link ? 'Calculator connected.' : 'No calculator connected.');
  }

  if (!navigator.hid) {
    panel.support.textContent =
      "This browser can't talk to USB devices. Open CalcVault in Chrome or Edge on the computer " +
      "the calculator is plugged into (Android and iOS don't support this), or use the PC sync tool.";
  } else if (!window.isSecureContext) {
    panel.support.textContent =
      'Browsers only allow USB access on https:// pages (or localhost). Open CalcVault over HTTPS to use this.';
  }

  async function ensureLink() {
    if (link) return link;
    let device = (await navigator.hid.getDevices()).find(matches);
    if (!device) throw new LinkError('no calculator selected: press Connect calculator');
    const l = new PrimeLink(device, (m) => say(m));
    await l.open();
    link = l;
    return l;
  }

  function dropLink() {
    if (link) link.close().catch(() => {});
    link = null;
  }

  async function connect() {
    try {
      let device = (await navigator.hid.getDevices()).find(matches);
      if (!device) {
        const picked = await navigator.hid.requestDevice({
          filters: PRODUCT_IDS.map((productId) => ({ vendorId: VENDOR_ID, productId })),
        });
        device = picked[0];
      }
      if (!device) {
        say('No calculator was chosen. Plug it in, turn it on (Home screen), close HP\'s Connectivity Kit, and try again.');
        return;
      }
      if (link) await link.close();
      link = null;
      busy = true;
      refresh();
      const l = new PrimeLink(device, (m) => say(m));
      await l.open();
      link = l;
      say(stamp() + '  calculator connected');
    } catch (e) {
      link = null;
      say(stamp() + '  ' + e.message);
    } finally {
      busy = false;
      refresh();
    }
  }

  function askConfirm(text) {
    return new Promise((resolve) => {
      panel.confirmText.textContent = text;
      panel.confirm.hidden = false;
      const done = (yes) => {
        panel.confirm.hidden = true;
        panel.confirmYes.onclick = null;
        panel.confirmNo.onclick = null;
        resolve(yes);
      };
      panel.confirmYes.onclick = () => done(true);
      panel.confirmNo.onclick = () => done(false);
    });
  }

  // One sync, run by the server. Answers true when it finished.
  async function runSync(auto) {
    if (busy || ticking || !supported) return false;
    busy = true;
    refresh();
    let ws = null;
    let ok = false;
    try {
      const l = await ensureLink();
      const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/hp/ws';
      ws = new WebSocket(url);
      await new Promise((resolve, reject) => {
        ws.onopen = resolve;
        ws.onerror = () => reject(new Error('could not reach the CalcVault server'));
        ws.onclose = (e) => reject(new Error(e.code === 4401 ? 'not logged in' : 'connection closed'));
      });
      const send = (obj) => ws.send(JSON.stringify(obj));
      const result = await new Promise((resolve, reject) => {
        ws.onclose = () => reject(new Error('the server closed the connection'));
        ws.onmessage = async (ev) => {
          const m = JSON.parse(ev.data);
          if (m.type === 'say') {
            say(m.text);
          } else if (m.type === 'confirm') {
            send({ type: 'confirm', id: m.id, yes: await askConfirm(m.text) });
          } else if (m.type === 'req') {
            try {
              if (m.op === 'read') {
                send({ type: 'reply', id: m.id, text: await readNote(l, m.name) });
              } else {
                await l.putNote(m.name, m.text, m.new);
                send({ type: 'reply', id: m.id, ok: true });
              }
            } catch (e) {
              send({ type: 'reply', id: m.id, error: e.message });
            }
          } else if (m.type === 'done') {
            resolve(m);
          }
        };
        send({ type: 'sync', auto: !!auto });
      });
      if (result.error) say(stamp() + '  ' + result.error);
      else if (result.code !== 0) say(stamp() + '  stopped; nothing was synced');
      else if (!auto || result.changed) say(stamp() + (result.changed ? '  synced' : '  already in sync'));
      ok = !result.error && result.code === 0;
    } catch (e) {
      say(stamp() + '  ' + e.message);
      // A dead link (unplugged, or left busy) is dropped so the next try reconnects.
      if (e instanceof LinkError || e instanceof LinkTimeout) dropLink();
    } finally {
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
      busy = false;
      refresh();
    }
    return ok;
  }

  // ---- online mode

  async function webTree() {
    const res = await fetch('/api/tree', { credentials: 'same-origin' });
    if (!res.ok) throw new Error('the web app answered ' + res.status + (res.status === 401 ? ' (not logged in)' : ''));
    return res.text();
  }

  // The calculator's CVREV, or null when it does not answer in time (or has
  // no CalcVault notes yet). One short try: this runs every second.
  const revOf = (l) => l.getNote('CVREV', [1500]);

  function token() {
    return Math.random().toString(16).slice(2, 10);
  }

  async function onlineTick() {
    if (!online || busy || ticking) return;
    ticking = true;
    let needSync = false;
    let l = null;
    try {
      l = await ensureLink();
      const rev = await revOf(l);
      const was = answering;
      answering = rev !== null;
      if (answering) {
        misses = 0;
        if (rev !== lastRev) needSync = true;
        if (!was) say(stamp() + '  online: the calculator is answering');
      } else {
        misses++;
        // A calculator never synced has no CVREV yet: one sync makes it.
        if (lastRev === undefined && misses === 1) needSync = true;
        if (misses === 3) {
          say(stamp() + '  online: the calculator does not answer. Open CalcVault 2 on it (with Settings > ' +
            'Let the PC sync while open on), or leave it on its Home screen.');
        }
      }
      if (pendingFocus !== null) tWeb = 0; // a calculator just made here must reach it first
      if (performance.now() - tWeb >= WEB_EVERY) {
        const tree = await webTree();
        tWeb = performance.now();
        if (tree !== lastWeb) needSync = true;
      }
      lastError = '';
    } catch (e) {
      if (e.message !== lastError) say(stamp() + '  online: ' + e.message);
      lastError = e.message;
      answering = false;
      if (e instanceof LinkError || e instanceof LinkTimeout) dropLink();
      ticking = false;
      refresh();
      return;
    }
    ticking = false;
    refresh();

    if (needSync) {
      if (!(await runSync(true))) return;
      ticking = true;
      try {
        lastRev = await revOf(link || l);
        lastWeb = await webTree();
        tWeb = performance.now();
      } catch (e) {
        lastRev = undefined;
      } finally {
        ticking = false;
      }
    }
    if (!online || !answering || !link || busy) return;
    ticking = true;
    try {
      if (pendingFocus !== null) {
        const id = pendingFocus;
        pendingFocus = null;
        await link.putNote('CVFOCUS', id + ';' + token(), true);
      }
      if (performance.now() - tBeat >= BEAT_EVERY) {
        await link.putNote('CVLINK', 'b' + token(), true);
        tBeat = performance.now();
      }
    } catch (e) {
      say(stamp() + '  online: ' + e.message);
      if (e instanceof LinkError || e instanceof LinkTimeout) dropLink();
    } finally {
      ticking = false;
      refresh();
    }
  }

  function loop() {
    onlineTimer = setTimeout(async () => {
      try {
        await onlineTick();
      } finally {
        if (online) loop();
      }
    }, ONLINE_TICK);
  }

  async function setOnline(on, quiet = false) {
    if (on === online) return;
    if (!on) {
      online = false;
      clearTimeout(onlineTimer);
      if (releaseLock) releaseLock();
      releaseLock = null;
      rememberOnline(false);
      say(stamp() + '  online off');
      refresh();
      return;
    }
    // One tab at a time: two would take turns with the same USB connection.
    const got = await new Promise((resolve) => {
      if (!navigator.locks) return resolve(true);
      navigator.locks.request('calcvault-hp-online', { ifAvailable: true }, (lock) => {
        if (!lock) return resolve(false);
        resolve(true);
        return new Promise((release) => {
          releaseLock = release;
        });
      });
    });
    if (!got) {
      if (!quiet) say(stamp() + '  online is already running in another CalcVault tab');
      refresh();
      return;
    }
    online = true;
    lastRev = undefined;
    lastWeb = null;
    tWeb = 0;
    tBeat = 0;
    misses = 0;
    answering = false;
    lastError = '';
    rememberOnline(true);
    say(stamp() + '  online on: keep this page open (it can be in the background)');
    refresh();
    loop();
  }

  window.addEventListener('calcvault:calc-opened', (e) => {
    if (online && e.detail && e.detail.id != null) pendingFocus = e.detail.id;
  });

  panel.open.addEventListener('click', async () => {
    panel.overlay.hidden = false;
    if (serverOk === null && supported) {
      try {
        const res = await fetch('/api/hp/status', { credentials: 'same-origin' });
        const body = await res.json();
        serverOk = !!body.available;
        if (!serverOk) panel.support.textContent = 'This server cannot sync with an HP Prime: ' + body.reason;
      } catch (e) {
        serverOk = null;
      }
    }
    refresh();
  });
  panel.close.addEventListener('click', () => {
    panel.overlay.hidden = true;
  });
  panel.connect.addEventListener('click', connect);
  panel.sync.addEventListener('click', () => runSync(false));
  panel.online.addEventListener('change', () => setOnline(panel.online.checked));

  if (navigator.hid) {
    navigator.hid.addEventListener('disconnect', (e) => {
      if (link && link.dev === e.device) {
        link = null;
        answering = false;
        say(stamp() + '  calculator unplugged');
        refresh();
      }
    });
  }
  refresh();

  // Online stays on for this browser: back on by itself when the page opens,
  // if this browser was already allowed to use the calculator.
  if (supported && rememberedOnline()) {
    navigator.hid.getDevices().then((devs) => {
      if (devs.some(matches)) setOnline(true, true);
    });
  }
}
