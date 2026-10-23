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
  'the program, or in CalcVault 2 wait for its "linked to the PC" box.';

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
  //
  // Measured on a G2 plugged straight into a Windows PC (2026-10-23): it sends
  // every file reply twice, and the second copy can start before the first has
  // finished, so their reports interleave. Both copies number their reports
  // 0, 1, 2, ... and carry the same bytes, so each report is put in its place by
  // its number and a repeat is dropped; the reply's checksum (parseFileReply)
  // still catches a mix-up with another reply. Past 255 reports the numbers
  // wrap, so such a reply is read in order, starting again on a new copy.
  async _reply(cmd, timeout, first = null) {
    const cap = this.report - 1;
    const parts = new Map();
    const chunks = [];
    let total = 0;
    let expect = null;
    let need = null;
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
      const head = payload[0];
      const starts =
        seq === 0 &&
        (cmd === CMD_CHECK_READY ? head === 0xff || head === 0x59 : head === CMD_FILE || head === CMD_BACKUP);
      if (need === null) {
        if (!starts) continue;
        deadline = start + timeout; // it has started; allow the rest
        if (cmd === CMD_CHECK_READY || head === CMD_BACKUP) return payload.slice(0, 1);
        if (payload[1] !== 0x01) throw new LinkError('unexpected reply header');
        expect = 6 + (((payload[2] << 24) | (payload[3] << 16) | (payload[4] << 8) | payload[5]) >>> 0);
        if (expect > 64 * 1024 * 1024) throw new LinkError('implausible reply length');
        need = Math.max(1, Math.ceil(expect / cap));
      }
      if (need <= 255) {
        if (!parts.has(seq)) parts.set(seq, payload.slice());
        if (parts.size >= need) {
          let all = true;
          for (let i = 0; i < need; i++) if (!parts.has(i)) all = false;
          if (all) {
            const list = [];
            for (let i = 0; i < need; i++) list.push(parts.get(i));
            return cat(...list).slice(0, expect);
          }
        }
        continue;
      }
      // Too long to place by number: in order, restarting on a new copy.
      if (starts) {
        chunks.length = 0;
        total = 0;
        index = 0;
      }
      if (seq !== index % 255) continue;
      index++;
      chunks.push(payload.slice());
      total += payload.length;
      if (total >= expect) return cat(...chunks).slice(0, expect);
    }
  }

  // Drops whatever the calculator is still sending (the second copy of a reply)
  // until it has been quiet for `quietMs`.
  async _settle(quietMs = 1000, limitMs = 20000) {
    const end = performance.now() + limitMs;
    let last = performance.now();
    while (performance.now() - last < quietMs && performance.now() < end) {
      if (this.inbox.length) {
        this.inbox.length = 0;
        last = performance.now();
      }
      await sleep(20);
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

  // How the G2 behaves, measured plugged straight into a Windows PC
  // (2026-10-23): it works through requests strictly one at a time, in the
  // order they came, and keeps the rest waiting (ready checks included) for as
  // long as that takes; a backup, about 12 s, holds up everything after it.
  // Nothing is dropped, except a request for a note it does not have, which is
  // never answered. So a request given up on and sent again is answered twice,
  // later, in the middle of whatever is asked next: the "reads one or two
  // notes, then stops" failure. Hence one request at a time, waited for, never
  // re-sent blindly. Answers for other notes that arrive first are passed over.
  async getObject(name, ftype, patienceMs = 30000) {
    await this._drain();
    await this._send(fileMessage(CMD_REQUEST_FILE, name, ftype));
    const end = performance.now() + patienceMs;
    while (performance.now() < end) {
      let got;
      try {
        got = parseFileReply(await this._reply(CMD_FILE, 60000, Math.max(50, end - performance.now())));
      } catch (e) {
        if (e instanceof LinkTimeout) break;
        if (e instanceof LinkError) continue; // a reply mixed up with another; ours may follow
        throw e;
      }
      if (got === null) return null;
      if (got.name === name && got.type === ftype) {
        await this._settle(300); // the second copy of this reply
        return got.content;
      }
    }
    return null;
  }

  // Every note on the calculator, from one backup request (0xF9): the calculator
  // streams all its objects and ends with an F9 frame (about 12 s). Prime
  // Connection Kit reads a calculator this way. A backup asked for earlier and
  // still waiting would look the same, so a note CVMARK is written with a new
  // token first: requests are handled in order, so the first backup holding
  // that token is this one, and shows everything written before it.
  // -> {notes: Map(name -> text), complete}
  async backupNotes(wholeMs = 300000) {
    const token = 'm' + Math.random().toString(16).slice(2, 12);
    await this.putObject('CVMARK', TYPE_NOTE, noteBytes(token));
    await this._send(Uint8Array.of(CMD_BACKUP));
    let notes = new Map();
    const end = performance.now() + wholeMs;
    while (performance.now() < end) {
      let reply;
      try {
        reply = await this._reply(CMD_FILE, 60000, Math.max(1000, end - performance.now()));
      } catch (e) {
        if (e instanceof LinkTimeout) break;
        if (e instanceof LinkError) continue;
        throw e;
      }
      if (reply[0] === CMD_BACKUP) {
        if (notes.get('CVMARK') === token) {
          await this._settle(500, 10000);
          return { notes, complete: true };
        }
        notes = new Map(); // an older backup's stream: not ours
        continue;
      }
      let got = null;
      try {
        got = parseFileReply(reply);
      } catch (e) {
        continue; // a damaged frame; its copy follows
      }
      if (got && got.type === TYPE_NOTE) notes.set(got.name, noteText(got.content)); // a later copy is newer
    }
    return { notes, complete: false };
  }

  async putObject(name, ftype, content) {
    if (ftype === TYPE_NOTE && content[0] === 0xff && content[1] === 0xfe) content = content.subarray(2);
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

  // A fresh connection, then a ready check waited for patiently: the calculator
  // answers it only after whatever it is still doing. Opening and the first
  // send can fail for a moment after a write; that is tried again.
  async reopen(waitMs = 8000) {
    await this.closeQuiet();
    const end = performance.now() + waitMs;
    let last = null;
    for (;;) {
      await sleep(400);
      try {
        if (!this.dev.opened) {
          try {
            await this.dev.open();
          } catch (e) {
            // The calculator may have re-enumerated: look for it again.
            const found = (await navigator.hid.getDevices()).filter(matches);
            if (found.length) {
              this._attach(found[0]);
              await this.dev.open();
            }
          }
        }
        if (this.dev.opened) {
          if (await this.checkReady(30000)) return;
          throw new LinkError('the calculator did not answer after a write');
        }
      } catch (e) {
        last = e;
        await this.closeQuiet();
        if (e instanceof LinkError && /did not answer/.test(e.message)) throw e;
      }
      if (performance.now() > end) {
        throw new LinkError('the calculator did not come back after a write' + (last ? ' (' + last.message + ')' : ''));
      }
    }
  }

  // Presses one key on the calculator (0xEC, as Prime Connection Kit sends it);
  // measured: Esc (4) closes a program's CHOOSE dialog.
  async sendKey(code) {
    await this._drain();
    await this._send(Uint8Array.of(0xec, 0x01, 0x00, 0x00, 0x00, 0x01, code));
  }

  async getNote(name, patienceMs) {
    const content = await this.getObject(name, TYPE_NOTE, patienceMs);
    return content === null ? null : noteText(content);
  }

  // An existing note keeps its shape, which costs a read; `isNew` skips it
  // (CalcVault's own notes need no shape). The backup held is out of date then.
  async putNote(name, text, isNew = false) {
    const existing = isNew ? null : await this.getObject(name, TYPE_NOTE, 5000);
    await this.putObject(name, TYPE_NOTE, noteBytes(text, existing));
    if (this.snap) this.snap.complete = false;
  }
}

// What cvsync.store.UsbTarget does: a sync reads everything at once with a
// backup (prefetchNotes, about 12 s) and its reads are served from that; a read
// after something was written takes a new backup. `fresh` (CVREV, which is how
// a change on the calculator is noticed) always asks the calculator by name.
async function prefetchNotes(link) {
  link.snap = await link.backupNotes();
  if (!link.snap.complete) {
    throw new LinkError(
      'the calculator did not finish sending its notes. Make sure it is on the Home screen or in ' +
        'CalcVault 2, then try again.'
    );
  }
  return link.snap;
}

function notePresent(link, name) {
  if (!link.snap || !link.snap.complete) return null;
  return link.snap.notes.has(name);
}

async function readNote(link, name, fresh = false) {
  if (fresh) return link.getNote(name);
  if (!link.snap || !link.snap.complete) await prefetchNotes(link);
  return link.snap.notes.has(name) ? link.snap.notes.get(name) : null;
}

window.CalcVaultHP = {
  crc16, nameBytes, fileMessage, parseFileReply, fragment, noteText, noteBytes, PrimeLink, readNote,
  prefetchNotes, notePresent,
};

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
  let lastSyncTree = null; // the web app's tree as the last sync left it

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
    lastSyncTree = null;
    try {
      const l = await ensureLink();
      l.snap = null;
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
              if (m.op === 'prefetch') {
                const snap = await prefetchNotes(l);
                send({ type: 'reply', id: m.id, names: [...snap.notes.keys()], complete: snap.complete });
              } else if (m.op === 'read') {
                send({ type: 'reply', id: m.id, text: await readNote(l, m.name, !!m.fresh) });
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
      lastSyncTree = result.tree ? JSON.stringify(result.tree) : null;
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

  // The web app's folders and calculators, as a string to compare.
  async function webTree() {
    const res = await fetch('/api/tree', { credentials: 'same-origin' });
    if (!res.ok) throw new Error('the web app answered ' + res.status + (res.status === 401 ? ' (not logged in)' : ''));
    return JSON.stringify(await res.json());
  }

  // The calculator's CVREV, or null when it does not answer in time (or has
  // no CalcVault notes yet). One short try: this runs every second.
  const revOf = (l) => l.getNote('CVREV', 5000);

  function token() {
    return Math.random().toString(16).slice(2, 10);
  }

  // CalcVault 2 waits in a "linked to the PC" box while idle, the only time a
  // running program lets the calculator answer; it notes CVBOX "up" meanwhile.
  // Once something was sent, Esc closes the box so the app shows it at once.
  async function closeBox(l) {
    if ((await l.getNote('CVBOX', 5000)) === 'up') await l.sendKey(4);
  }

  async function onlineTick() {
    if (!online || busy || ticking) return;
    ticking = true;
    let needSync = false;
    let l = null;
    let rev = null;
    try {
      l = await ensureLink();
      rev = await revOf(l);
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
          say(stamp() + '  online: the calculator does not answer yet. In CalcVault 2 it answers while its ' +
            '"linked to the PC" box is up (leave it alone for 15 s), or on the Home screen.');
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
        // The tree the server had when the sync ended, not one read now: an
        // edit made in between would otherwise be taken as already synced.
        lastWeb = lastSyncTree || (await webTree());
        tWeb = performance.now();
        lastRev = await revOf(link || l);
        // The sync wrote to the calculator (its mark is a "p..." CVREV).
        if (lastRev && lastRev !== rev && lastRev.startsWith('p')) await closeBox(link || l);
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
        await closeBox(link);
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
