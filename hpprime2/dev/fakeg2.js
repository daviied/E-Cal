// A stand-in HP Prime G2 for testing the web page's HP Prime panel (hp.js)
// without a calculator: a fake WebHID device that speaks the link protocol
// (ready check, request a note, send a note) from an in-memory set of notes.
//
// Paste into the browser console on a CalcVault page (or run it through a
// test driver), after hp.js has loaded:
//
//   installFakeG2({ CVDATA: '{"CVDB2","","1",{},{}}', CVREV: 'c1' })
//   fakeG2.notes            the calculator's notes, by name
//   fakeG2.busy = true      stops answering, like a G2 running a program
//   fakeG2.appSave(slot, linesText)   a save the way CalcVault 2 makes one
//
// Like a real G2 it never answers a request for a note it does not have,
// and sends no acknowledgement for a note it is sent.
(function () {
  const HP = window.CalcVaultHP;
  const REPORT = 1024;

  class FakeG2 extends EventTarget {
    constructor(notes) {
      super();
      this.vendorId = 0x03f0;
      this.productId = 0x2441;
      this.productName = 'Fake HP Prime';
      this.collections = [];
      this.opened = false;
      this.busy = false;
      this.notes = Object.assign({}, notes);
      this.log = [];
      this._in = null; // message being received: {buf, need}
    }

    async open() {
      this.opened = true;
    }

    async close() {
      this.opened = false;
    }

    async sendReport(_id, data) {
      if (!this.opened) throw new Error('device not open');
      if (this.busy) return new Promise(() => {}); // a G2 running a program stops taking reports
      const payload = new Uint8Array(data.buffer, data.byteOffset + 1, data.byteLength - 1);
      if (!this._in) {
        if (payload[0] === 0xff) {
          this._reply(Uint8Array.of(0xff));
          return;
        }
        if (payload[1] !== 0x01) return;
        const len = ((payload[2] << 24) | (payload[3] << 16) | (payload[4] << 8) | payload[5]) >>> 0;
        this._in = { parts: [], got: 0, need: 6 + len };
      }
      this._in.parts.push(payload.slice());
      this._in.got += payload.length;
      if (this._in.got >= this._in.need) {
        const all = new Uint8Array(this._in.got);
        let off = 0;
        for (const p of this._in.parts) {
          all.set(p, off);
          off += p.length;
        }
        const msg = all.slice(0, this._in.need);
        this._in = null;
        this._handle(msg);
      }
    }

    _handle(msg) {
      const nlen = msg[7];
      const name = new TextDecoder('utf-16le').decode(msg.subarray(10, 10 + nlen)).replace(/\0+$/, '');
      if (msg[0] === 0xf8) {
        this.log.push('read ' + name);
        if (name in this.notes) {
          const content = HP.noteBytes(this.notes[name], new Uint8Array(0));
          this._reply(HP.fileMessage(0xf7, name, msg[6], content));
        }
      } else if (msg[0] === 0xf7) {
        this.log.push('write ' + name);
        this.notes[name] = HP.noteText(msg.subarray(10 + nlen));
      }
    }

    _reply(message) {
      const reports = HP.fragment(message, REPORT - 1);
      setTimeout(() => {
        for (const r of reports) {
          const full = new Uint8Array(REPORT);
          full.set(r);
          const ev = new Event('inputreport');
          ev.data = new DataView(full.buffer);
          ev.device = this;
          ev.reportId = 0;
          this.dispatchEvent(ev);
        }
      }, 15);
    }

    // A save as CalcVault 2 makes one: the calculator's note, a new rev for
    // it in the index (the last field of its entry, after its slot), then a
    // new "c..." token in CVREV.
    appSave(slot, linesText) {
      const rev = 'c' + Date.now();
      this.notes['CVC' + slot] = linesText;
      this.notes.CVDATA = this.notes.CVDATA.replace(new RegExp('("' + slot + '",)"[^"]*"\\}'), '$1"' + rev + '"}');
      this.notes.CVREV = rev;
    }
  }

  window.installFakeG2 = function (notes) {
    const dev = new FakeG2(notes || {});
    window.fakeG2 = dev;
    const hid = navigator.hid;
    hid.getDevices = async () => [dev];
    hid.requestDevice = async () => [dev];
    return dev;
  };
})();
