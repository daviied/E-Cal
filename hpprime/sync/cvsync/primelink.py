"""Talking to an HP Prime over USB, without HP's Connectivity Kit.

The Prime is a USB HID device. This is a Python port of the link layer in
Prime Connection Kit (github.com/56phil/prime_connection_kit, MIT), which
was itself built from libhpcalcs and QtHPConnect and checked against a real
G2 on firmware 2.060. What it relies on, in short:

  - Reports of 1024 bytes on current hardware (64 on early firmware): one
    sequence byte, then payload. The sequence counts 0x00..0xFE and wraps,
    skipping 0xFF.
  - A message is a command byte and its arguments. Bulk messages carry
    `cmd, 0x01, length (4 bytes, big-endian)` and then the body.
  - 0xFF asks "are you there" (answered 0xFF, or 'Y' on current firmware);
    0xF8 asks for one object by name and type; 0xF7 carries one object, in
    both directions. A file body is `type, nameLen, crc16 (LE), name
    (UTF-16LE), content`, with the CRC-16/CCITT taken over the message less
    its last six bytes, the CRC field read as zero.
  - A note travels as its own bytes: UTF-16LE text, a NUL, and (for notes
    made in the Notes app) a formatting tail.
  - Current firmware does not acknowledge a write; reading it back is the
    check, and the sync tool does that.

Only the hidapi package is needed (`pip install hidapi`).
"""
import os
import sys
import threading
import time

VENDOR_ID = 0x03F0
PRODUCT_IDS = (0x2441, 0x1541, 0x0441)  # 1024-byte reports first

CMD_CHECK_READY = 0xFF
CMD_REQUEST_FILE = 0xF8
CMD_FILE = 0xF7
CMD_BACKUP = 0xF9

TYPE_NOTE = 0x05
TYPE_PROGRAM = 0x06


class LinkError(Exception):
    pass


BUSY = ("the calculator stopped taking data. Close CalcVault (or any program) on "
        "the calculator: it does not answer USB while a program is running.")


# ------------------------------------------------------------------ CRC-16

def _crc_table():
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
        table.append(crc & 0xFFFF)
    return table


_TABLE = _crc_table()


def crc16(data):
    crc = 0
    for b in data:
        crc = (_TABLE[((crc >> 8) ^ b) & 0xFF] ^ (crc << 8)) & 0xFFFF
    return crc


# ------------------------------------------------------------- messages

def name_bytes(name):
    if not name or len(name) > 32 or any(c in name for c in '\\/:*?"<>|\0'):
        raise LinkError("not a name the calculator can store: %r" % name)
    nb = name.encode("utf-16-le")
    # The name field must be a whole number of 4-byte words. A name with an
    # odd number of characters (2 bytes short) is otherwise silently
    # ignored: never stored when sent, never answered when asked for.
    # Measured on a G2: 6 of 6 odd-length names failed and 6 of 6 even ones
    # worked; with a NUL character added, odd ones work and are stored
    # under their own name. (Prime Connection Kit and libhpcalcs only met
    # even-length names, which is why neither pads.)
    if len(nb) % 4:
        nb += b"\x00" * (4 - len(nb) % 4)
    return nb


def with_length(cmd, body):
    n = len(body)
    return bytes([cmd, 0x01, (n >> 24) & 0xFF, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF]) + bytes(body)


def file_message(cmd, name, ftype, content=None):
    """0xF8 (request) or 0xF7 (send) for one named object."""
    nb = name_bytes(name)
    body = bytes([ftype, len(nb), 0, 0]) + nb + (bytes(content) if content is not None else b"")
    msg = bytearray(with_length(cmd, body))
    covered = bytearray(msg[:len(msg) - 6])
    for off in (8, 9):
        if off < len(covered):
            covered[off] = 0
    crc = crc16(covered)
    msg[8] = crc & 0xFF
    msg[9] = crc >> 8
    return bytes(msg)


def parse_file_reply(reply):
    """-> (type, name, content), or None when the calculator has no such
    object (it answers with an 0xF9 frame, or nothing)."""
    if not reply or reply[0] == CMD_BACKUP:
        return None
    if reply[0] != CMD_FILE:
        raise LinkError("expected a file (F7), got %02X" % reply[0])
    if len(reply) < 10:
        raise LinkError("file reply too short")
    ftype, nlen = reply[6], reply[7]
    embedded = reply[8] | (reply[9] << 8)
    covered = bytearray(reply[:max(0, len(reply) - 6)])
    for off in (8, 9):
        if off < len(covered):
            covered[off] = 0
    if crc16(covered) != embedded:
        raise LinkError("file reply failed its checksum")
    name = bytes(reply[10:10 + nlen]).decode("utf-16-le", errors="replace").rstrip("\x00")
    return ftype, name, bytes(reply[10 + nlen:])


# Windows pads every report to full size, so a short last report cannot mark
# the end of a message there, and a length-prefixed message says where it
# ends anyway. Elsewhere (Linux, macOS) reports go as they are, and a message
# that fills its last report exactly is closed by an empty one, which is
# what Prime Connection Kit measured on macOS. CVSYNC_PADDED=1/0 overrides.
PADDED = os.environ.get("CVSYNC_PADDED", "1" if sys.platform.startswith("win") else "0") == "1"


def fragment(message, capacity, padded=None):
    """Splits a message into reports: [sequence] + up to `capacity` bytes."""
    if padded is None:
        padded = PADDED
    out, seq, off = [], 0, 0
    while len(message) - off >= capacity:
        out.append(bytes([seq]) + message[off:off + capacity])
        seq = (seq + 1) % 255
        off += capacity
    tail = message[off:]
    if tail or not padded or not (len(message) >= 6 and message[1] == 0x01):
        out.append(bytes([seq]) + tail)
    return out


# ------------------------------------------------------------- notes

def note_text(content):
    """The plain text of a note's bytes: UTF-16LE up to the first NUL."""
    b = bytes(content or b"")
    if b[:2] == b"\xff\xfe":
        b = b[2:]
    if len(b) < 4:
        return ""
    units = []
    for i in range(0, len(b) - 1, 2):
        u = b[i] | (b[i + 1] << 8)
        if u == 0:
            break
        units.append(b[i:i + 2])
    return b"".join(units).decode("utf-16-le", errors="replace")


def note_bytes(text, existing=None):
    """Bytes for a note holding `text`. A note the calculator already has
    keeps its shape: its formatting tail if it had one, or none if it was
    plain (which is what a program writing Notes() makes). A new note gets
    the minimal formatted shape the Notes app writes."""
    body = text.encode("utf-16-le") + b"\x00\x00"
    if existing is not None:
        ex = bytes(existing)
        magic = "CSW".encode("utf-16-le")
        k = ex.find(magic)
        while k != -1 and k % 2:
            k = ex.find(magic, k + 1)
        return body + (ex[k:] if k != -1 else b"")
    tail = "CSWD110".encode("utf-16-le") + b"\xff\xff\xff\xff"
    tail += "\\l".encode("utf-16-le") + b"\x3e\x01"
    tail += "\\0\\3\\0\\0\\0\\0\\0\\0\\0\\0".encode("utf-16-le")
    return body + tail


# ------------------------------------------------------------- the link

def _hid():
    """hidapi's module. On Linux its hidraw backend is preferred: it talks to
    the kernel's own HID driver, which the udev rule from install.sh opens up,
    instead of taking the device away from it."""
    if sys.platform.startswith("linux"):
        try:
            import hidraw
            return hidraw
        except ImportError:
            pass
    try:
        import hid  # the hidapi package
    except ImportError:
        raise LinkError("USB needs the hidapi package: python -m pip install hidapi")
    return hid


def find_calculators():
    """Attached HP Primes, as hidapi device-info dicts."""
    hid = _hid()
    found = []
    for pid in PRODUCT_IDS:
        found.extend(hid.enumerate(VENDOR_ID, pid))
    return found


class PrimeLink:
    REPLY_TIMEOUT = 8.0
    WRITE_ACK_WINDOW = 1.5

    def __init__(self, info=None, log=None):
        hid = _hid()
        if info is None:
            devs = find_calculators()
            if not devs:
                raise LinkError(
                    "no HP Prime found on USB. Plug it in, turn it on, and close HP's "
                    "Connectivity Kit if it is open.")
            info = devs[0]
        self.info = info
        self.log = log or (lambda *_: None)
        self.dev = hid.device()
        try:
            self.dev.open_path(info["path"])
        except (IOError, OSError) as e:
            if sys.platform.startswith("linux"):
                raise LinkError("could not open the calculator (%s). On Linux this is usually "
                                "permission: run install.sh once (it adds a udev rule), then unplug "
                                "and replug the calculator." % e)
            raise LinkError("could not open the calculator (%s). Is the Connectivity Kit "
                            "running? Close it and try again." % e)
        self.dev.set_nonblocking(0)
        sizes = [1024, 64] if info.get("product_id") == 0x2441 else [64, 1024]
        declared = self._declared_report_size()
        if declared in sizes:
            sizes.remove(declared)
            sizes.insert(0, declared)
        last = None
        for size in sizes:
            self.report = size
            try:
                if self.check_ready(timeout=2.0):
                    self.log("link: %d-byte reports" % size)
                    return
            except LinkError as e:
                last = e
        self.close()
        raise LinkError("the calculator did not answer%s. Make sure it is on and on its "
                        "Home screen, not running a program." % (" (%s)" % last if last else ""))

    def _declared_report_size(self):
        """The input report size the device's HID descriptor declares, which
        is what decides the framing; None if it cannot be read."""
        try:
            desc = bytes(self.dev.get_report_descriptor())
        except Exception:  # noqa: BLE001 - older hidapi builds lack it
            return None
        size_bits, count, best, i = 0, 0, None, 0
        while i < len(desc):
            prefix = desc[i]
            n = (0, 1, 2, 4)[prefix & 0x03]
            data = int.from_bytes(desc[i + 1:i + 1 + n], "little")
            tag = prefix & 0xFC
            if tag == 0x74:      # Report Size (bits)
                size_bits = data
            elif tag == 0x94:    # Report Count
                count = data
            elif tag == 0x80:    # Input
                total = size_bits * count // 8
                best = max(best or 0, total)
            i += 1 + n
        return best

    def close(self):
        try:
            self.dev.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- report layer

    def _drain(self):
        while self.dev.read(self.report + 1, 10):
            pass

    WRITE_TIMEOUT = 5.0
    REOPEN_AFTER_WRITE = True

    def _write(self, data):
        """One report, given up on after WRITE_TIMEOUT: a calculator that is
        running a program stops taking reports, and hidapi's write then
        waits for ever."""
        box = {}

        def run():
            try:
                box["n"] = self.dev.write(data)
            except Exception as e:  # noqa: BLE001
                box["e"] = e

        th = threading.Thread(target=run, daemon=True)
        th.start()
        th.join(self.WRITE_TIMEOUT)
        if th.is_alive():
            raise LinkError(BUSY)
        if "e" in box:
            raise LinkError("USB write failed (%s)" % box["e"])
        if box.get("n") is None or box["n"] < 0:
            raise LinkError("USB write failed")

    def _send(self, message):
        for pkt in fragment(message, self.report - 1):
            self._write(b"\x00" + pkt)

    def _reply(self, cmd, timeout, first=None):
        """Reassembles one reply, stopping at the length it declares.
        `first` limits the wait for the reply to start (a G2 answers in
        about 0.1 s or not at all); `timeout` then limits the whole reply.
        A report that cannot start this reply -- a late answer to an earlier
        request, such as a ready check's 'Y' -- is skipped."""
        msg = bytearray()
        expect = 1 if cmd == CMD_CHECK_READY else None
        index = 0
        start = time.time()
        deadline = start + (first or timeout)
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise TimeoutError("no reply from the calculator")
            rep = self.dev.read(self.report + 1, int(max(left, 0.01) * 1000))
            if not rep:
                continue
            rep = bytes(rep)
            seq, payload = rep[0], rep[1:self.report]
            if seq == 0xFF:
                continue  # out-of-band report
            if index == 0:
                head = payload[:1]
                if cmd == CMD_CHECK_READY and head not in (b"\xff", b"\x59"):
                    continue
                if cmd == CMD_FILE and head not in (bytes([CMD_FILE]), bytes([CMD_BACKUP])):
                    continue
                deadline = start + timeout  # it has started; allow the rest
            if seq != index % 255:
                raise LinkError("reply out of sequence (%d, expected %d)" % (seq, index % 255))
            index += 1
            msg += payload
            if expect is None and len(msg) >= 6:
                if msg[0] == CMD_BACKUP:
                    return bytes(msg[:1])
                if msg[1] != 0x01:
                    raise LinkError("unexpected reply header %s" % msg[:6].hex())
                expect = 6 + int.from_bytes(msg[2:6], "big")
                if expect > 64 * 1024 * 1024:
                    raise LinkError("implausible reply length")
            if expect is not None and len(msg) >= expect:
                return bytes(msg[:expect])

    def exchange(self, message, timeout=None):
        self._drain()
        self._send(message)
        return self._reply(message[0], timeout or self.REPLY_TIMEOUT)

    # -- operations

    def check_ready(self, timeout=None):
        try:
            r = self.exchange(bytes([CMD_CHECK_READY]), timeout)
        except TimeoutError:
            return False
        return bool(r) and r[0] in (0xFF, 0x59)

    # Measured on a G2 (over VirtualHere): a request is usually answered in
    # about 0.1 s, but while the calculator is still storing a note it has
    # just received, answers come seconds late -- and a late answer to one
    # request can arrive while the next is waiting. Every answer names the
    # note it carries, so an answer for another note is set aside, not taken
    # for this one. A note that does not exist is never answered at all.
    GET_ATTEMPTS = 5
    FIRST_REPLY = 2.5
    WHOLE_REPLY = 60.0

    def get_object(self, name, ftype):
        for _ in range(self.GET_ATTEMPTS):
            self.check_ready(timeout=2.0)
            self._drain()
            self._send(file_message(CMD_REQUEST_FILE, name, ftype))
            end = time.time() + self.FIRST_REPLY
            while time.time() < end:
                try:
                    reply = self._reply(CMD_FILE, self.WHOLE_REPLY, first=max(0.05, end - time.time()))
                except TimeoutError:
                    break
                got = parse_file_reply(reply)
                if got is None:
                    return None  # the calculator says it has no such object
                if got[1] == name and got[0] == ftype:
                    return got[2]
                # someone else's late answer: keep waiting for ours
        return None

    def put_object(self, name, ftype, content):
        content = bytes(content)
        if ftype in (TYPE_NOTE, TYPE_PROGRAM) and content[:2] == b"\xff\xfe":
            content = content[2:]  # the firmware refuses a byte order mark
        self.check_ready(timeout=self.FIRST_REPLY)
        self._drain()
        self._send(file_message(CMD_FILE, name, ftype, content))
        try:
            r = self._reply(CMD_FILE, self.WRITE_ACK_WINDOW)
            if r and r[0] == CMD_BACKUP:
                raise LinkError("the calculator refused the transfer (firmware too old?)")
        except TimeoutError:
            pass  # current firmware sends no acknowledgement
        except OSError:
            pass  # see below
        # After it takes a file, the calculator's next reply fails to read
        # on Windows ("read error"; seen with a G2). A fresh connection reads
        # normally, so reconnect after every write.
        if self.REOPEN_AFTER_WRITE:
            self._reopen()

    def _reopen(self, wait=8.0):
        hid = _hid()
        self.close()
        end = time.time() + wait
        last = None
        while time.time() < end:
            time.sleep(0.4)
            try:
                devs = find_calculators()
                if not devs:
                    continue
                self.info = devs[0]
                self.dev = hid.device()
                self.dev.open_path(self.info["path"])
                self.dev.set_nonblocking(0)
                if self.check_ready(timeout=2.0):
                    return
                self.close()
            except (IOError, OSError, LinkError) as e:
                last = e
                self.close()
        raise LinkError("the calculator did not come back after a write%s"
                        % (" (%s)" % last if last else ""))

    def get_note(self, name):
        """The note's text, or None if the calculator has no such note."""
        content = self.get_object(name, TYPE_NOTE)
        return None if content is None else note_text(content)

    def put_note(self, name, text, new=False):
        """Writes a note. An existing note keeps its shape, which costs a
        read; `new` skips that read, since a request for a note that does
        not exist goes unanswered and costs both waits (about 20 s)."""
        existing = None if new else self.get_object(name, TYPE_NOTE)
        self.put_object(name, TYPE_NOTE, note_bytes(text, existing))

    def put_program(self, name, source):
        self.put_object(name, TYPE_PROGRAM, source.encode("utf-16-le"))
