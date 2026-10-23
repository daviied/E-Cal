"""The calculator's vault: its notes, their text form, and where they live.

The layout the app and the sync tool use now (CVDB2) is split, so that a
sync moves only what changed:

    CVDATA   {"CVDB2", deviceId, nextNewId, folders, calcs}
             folder = {id, parentId, name}
             calc   = {id, folderId, name, locked, slot, rev}
    CVC<slot>  that calculator's lines: {line, line, ...}
             line   = {uid, role, hidden, var, label, text}

`rev` changes whenever a calculator's lines are written (the app writes
"c<ticks>", the PC "p<time>"), so the PC reads a calculator's note only
when its rev differs from the one it saw last time. `slot` never changes for
a calculator, even when the sync swaps a calculator-made id for the web
app's, so notes are never renamed.

The older single-note layout (CVDB1, every calculator's lines inside
CVDATA) is still read, and is what backups are written in, since it is one
complete file:

    {"CVDB1", deviceId, nextNewId, folders, calcs}
    calc = {id, folderId, name, locked, lines}

Every leaf is a string. The parser also takes numbers and `;` between
elements, which is what STRING() writes on a calculator set to use a
decimal comma, so a setting change cannot make the notes unreadable.
"""
import json
import os
import re
import uuid

NOTE = "CVDATA"
# A token that changes whenever the app or the PC writes anything: the app
# reloads when it sees the PC's; the PC syncs when it sees the app's.
REV_NOTE = "CVREV"
MAGIC = "CVDB1"
MAGIC2 = "CVDB2"
# CalcVault 2: the web app's shared lines (written by the PC, only read by
# the app), and the online bridge's heartbeat and "open this calculator".
SHARED_NOTE = "CVSHR"
MAGIC_SH = "CVSH1"
LINK_NOTE = "CVLINK"
FOCUS_NOTE = "CVFOCUS"


def calc_note(slot):
    return "CVC" + slot


class StoreError(Exception):
    pass


# ---------------------------------------------------------- list literals

def parse_list(text):
    """Prime list literal -> nested Python lists of str."""
    s = text.strip()
    pos = 0

    def ws():
        nonlocal pos
        while pos < len(s) and s[pos] in " \t\r\n":
            pos += 1

    def value():
        nonlocal pos
        ws()
        if pos >= len(s):
            raise StoreError("CVDATA ends early")
        c = s[pos]
        if c == "{":
            pos += 1
            items = []
            ws()
            if pos < len(s) and s[pos] == "}":
                pos += 1
                return items
            while True:
                items.append(value())
                ws()
                if pos < len(s) and s[pos] in ",;":
                    pos += 1
                    continue
                if pos < len(s) and s[pos] == "}":
                    pos += 1
                    return items
                raise StoreError("CVDATA: expected , or } at %d" % pos)
        if c == '"':
            end = s.find('"', pos + 1)
            if end < 0:
                raise StoreError("CVDATA: unclosed string")
            out = s[pos + 1:end]
            pos = end + 1
            return out
        m = re.compile(r"[-−+]?(?:\d+\.?\d*|\.\d+)(?:[Eeᴇ][-−+]?\d+)?").match(s, pos)
        if m:
            pos = m.end()
            return m.group(0).replace("−", "-")
        raise StoreError("CVDATA: unexpected %r at %d" % (c, pos))

    out = value()
    ws()
    if pos != len(s):
        raise StoreError("CVDATA: text after the list")
    return out


def clean(s):
    """A string as the calculator can hold it inside CVDATA. A backslash is
    the worst of these: one anywhere makes the calculator's EXPR refuse the
    whole note (measured on the emulator), so it becomes a slash."""
    return str(s).replace('"', "'").replace("\r", " ").replace("\n", " ").replace("\\", "/")


def format_list(v):
    if isinstance(v, (list, tuple)):
        return "{" + ",".join(format_list(x) for x in v) + "}"
    return '"' + clean(v) + '"'


# ---------------------------------------------------------- the vault

def empty_vault(dev=""):
    return {"dev": dev, "next": "1", "folders": [], "calcs": []}


def vault_from_text(text):
    if text is None or not text.strip():
        return empty_vault()
    d = parse_list(text)
    if not isinstance(d, list) or len(d) < 5 or d[0] != MAGIC:
        raise StoreError("CVDATA is not a CalcVault store")
    folders = [{"id": f[0], "parent": f[1], "name": f[2]} for f in d[3]]
    calcs = []
    for c in d[4]:
        calcs.append({
            "id": c[0], "folder": c[1], "name": c[2], "locked": c[3] == "1",
            "lines": [{"uid": ln[0], "role": ln[1], "hidden": ln[2] == "1", "var": ln[3],
                       "label": ln[4], "text": ln[5]} for ln in c[4]],
        })
    return {"dev": d[1], "next": d[2], "folders": folders, "calcs": calcs}


def vault_to_text(v):
    """The whole vault in the single-note layout: what backups are."""
    return format_list([
        MAGIC, v["dev"], v["next"],
        [[f["id"], f["parent"], f["name"]] for f in v["folders"]],
        [[c["id"], c["folder"], c["name"], "1" if c["locked"] else "0", _lines_list(c["lines"])]
         for c in v["calcs"]],
    ])


def _lines_list(lines):
    return [[ln["uid"], ln["role"], "1" if ln["hidden"] else "0", ln["var"], ln["label"], ln["text"]]
            for ln in lines]


def lines_to_text(lines):
    return format_list(_lines_list(lines))


def shared_to_text(global_lines, folders):
    """CVSHR: {"CVSH1", globalLines, {{folderId, lines}, ...}}, folders as
    (id, lines) pairs."""
    return format_list([MAGIC_SH, _lines_list(global_lines),
                        [[fid, _lines_list(lines)] for fid, lines in folders]])


def lines_from_text(text):
    d = parse_list(text)
    if not isinstance(d, list):
        raise StoreError("a calculator's note is not a list")
    return [{"uid": ln[0], "role": ln[1], "hidden": ln[2] == "1", "var": ln[3],
             "label": ln[4], "text": ln[5]} for ln in d]


def _same_lines(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ---------------------------------------------------------- split layout

def read_vault(target, cache=None, log=None):
    """Reads the vault, in either layout. Answers (vault, layout), where
    layout records what is on the calculator: {"format": 1 or 2,
    "slot": {calc id: slot}, "rev": {slot: rev}, "lines": {slot: lines}}.

    `cache` is {slot: {"rev": rev, "lines": lines}} from the last sync (or a
    function from the device id to it); a calculator whose rev matches is
    not read again.

    A calculator whose note the target can say for certain is not there
    (UsbTarget, after a complete backup) comes back with "lines": None and
    its slot in layout["missing"]: a sync fills those in (sync.fill_missing)
    and writes the note again. A note that merely did not arrive still
    stops the read, so a lost answer is never taken for an empty
    calculator."""
    layout = {"format": 2, "slot": {}, "rev": {}, "lines": {}, "missing": []}
    if hasattr(target, "prefetch"):
        target.prefetch()
    present = getattr(target, "present", lambda name: None)
    text = target.read()
    if text is None or not text.strip():
        return empty_vault(), layout
    d = parse_list(text)
    if isinstance(d, list) and d and d[0] == MAGIC:
        layout["format"] = 1
        return vault_from_text(text), layout
    if not isinstance(d, list) or len(d) < 5 or d[0] != MAGIC2:
        raise StoreError("CVDATA is not a CalcVault store")
    if callable(cache):
        cache = cache(d[1])
    cache = cache or {}
    folders = [{"id": f[0], "parent": f[1], "name": f[2]} for f in d[3]]
    calcs, fetched = [], 0
    for c in d[4]:
        cid, slot, rev = c[0], c[4], c[5]
        known = cache.get(slot)
        lines = None
        if present(calc_note(slot)) is False:
            layout["missing"].append(slot)
        elif known and rev and known.get("rev") == rev:
            lines = known["lines"]
        else:
            note = target.read(calc_note(slot))
            if note is None and present(calc_note(slot)) is False:
                layout["missing"].append(slot)
            elif note is None:
                raise StoreError("the note %s for %r is missing or did not arrive; nothing was changed. "
                                 "Try again." % (calc_note(slot), c[2]))
            else:
                lines = lines_from_text(note)
                fetched += 1
        layout["slot"][cid] = slot
        layout["rev"][slot] = rev
        # Its own copy: what the calculator holds must not change when the
        # vault handed back is edited. A missing note has none, so it is
        # written again.
        if lines is not None:
            layout["lines"][slot] = json.loads(json.dumps(lines))
        calcs.append({"id": cid, "folder": c[1], "name": c[2], "locked": c[3] == "1", "lines": lines})
    if log:
        log("read the index and %d of %d calculators" % (fetched, len(calcs)))
    return {"dev": d[1], "next": d[2], "folders": folders, "calcs": calcs}, layout


def write_verified(target, name, text, tries=3, new=False):
    """Writes a note and reads it back, sending it again if what came back
    differs: one lost packet then costs one small resend. `new`: the note
    is not on the calculator yet (so there is no shape to look up)."""
    for attempt in range(tries):
        target.write(text, name, new=new and attempt == 0)
        back = target.read(name)
        if back is not None and back.strip() == text.strip():
            return attempt + 1
    raise StoreError("the calculator did not keep %s after %d tries; run the sync again" % (name, tries))


def write_verified_many(target, items, tries=3):
    """Writes several notes, then reads them all back, sending again the ones
    that did not arrive intact. `items`: [(name, text, new)]. On USB the
    reads after a write may all come from one backup (UsbTarget), so
    checking them together costs one backup rather than one per note."""
    pending = list(items)
    for attempt in range(tries):
        for name, text, new in pending:
            target.write(text, name, new=new and attempt == 0)
        bad = []
        for name, text, new in pending:
            back = target.read(name)
            if back is None or back.strip() != text.strip():
                bad.append((name, text, new))
        if not bad:
            return attempt + 1
        pending = bad
    raise StoreError("the calculator did not keep %s after %d tries; run the sync again"
                     % (", ".join(n for n, _, _ in pending), tries))


def write_vault(target, vault, layout, slot_of=None, log=None, extra=()):
    """Writes the vault in the split layout, sending only the calculators
    whose lines differ from what the calculator holds (layout, from
    read_vault). `slot_of` maps the vault's calculator ids to slots when the
    sync has given calculators new ids. `extra`: more notes to write first,
    [(name, text, new)] (the shared lines). Everything is written, the index
    last, then checked together. Answers the new cache."""
    slot_of = dict(layout["slot"] if slot_of is None else slot_of)
    used = set(slot_of.values()) | set(layout["lines"])
    nxt = max([int(s) for s in used if s.isdigit()] + [0]) + 1
    entries, cache, items = [], {}, []
    for i, c in enumerate(vault["calcs"]):
        slot = slot_of.get(c["id"])
        if slot is None:
            slot = str(nxt)
            nxt += 1
        rev = layout["rev"].get(slot)
        known = layout["lines"].get(slot)
        if layout["format"] != 2 or known is None or not rev or not _same_lines(known, c["lines"]):
            # Unique, not a timestamp: two writes in one second must differ.
            rev = "p" + uuid.uuid4().hex[:10]
            items.append((calc_note(slot), lines_to_text(c["lines"]), known is None))
        entries.append([c["id"], c["folder"], c["name"], "1" if c["locked"] else "0", slot, rev])
        cache[slot] = {"rev": rev, "lines": json.loads(json.dumps(c["lines"]))}
    written = len(items)
    index = format_list([MAGIC2, vault["dev"], vault["next"],
                         [[f["id"], f["parent"], f["name"]] for f in vault["folders"]], entries])
    # The calculators' notes before the index that points at them, then all
    # checked together: on USB that is one backup.
    write_verified_many(target, list(extra) + items + [(NOTE, index, False)])
    if log:
        log("wrote the index and %d of %d calculators" % (written, len(entries)))
    return cache


# ---------------------------------------------------------- where it lives

class UsbTarget:
    """A calculator on USB.

    A sync reads everything at once with a backup (prefetch, about 12 s) and
    serves its reads from that; a read after something was written takes a
    new backup, so a sync's checks after writing cost one backup in all.
    CVREV, which is polled and fits in one report, is always asked for by
    name. See primelink.PrimeLink for why notes are not read one by one."""

    def __init__(self, log=None):
        from .primelink import PrimeLink
        self.link = PrimeLink(log=log)
        self.label = "calculator on USB"
        self.snap = None  # {name: text} from the last backup, or None
        self.snap_complete = False

    def _snapshot(self):
        self.snap, self.snap_complete = self.link.backup_notes()
        if not self.snap_complete:
            from .primelink import LinkError
            raise LinkError("the calculator did not finish sending its notes. Make sure it is on the "
                            "Home screen or in CalcVault 2, then try again.")
        return self.snap

    def prefetch(self):
        """Everything at once, at the start of a sync (store.read_vault)."""
        self._snapshot()

    def present(self, name):
        """True or False when a complete backup says, None when unknown."""
        if self.snap is None or not self.snap_complete:
            return None
        return name in self.snap

    def read(self, name=NOTE):
        if self.snap is None or not self.snap_complete:
            self._snapshot()
        return self.snap.get(name)

    def write(self, text, name=NOTE, new=False):
        # CalcVault's notes need no particular shape, so none is read first.
        self.link.put_note(name, text, new=True)
        # The backup is out of date now: the next read takes a new one.
        self.snap_complete = False

    def read_rev(self):
        # Always asked for, never taken from a backup: this is how a change
        # made on the calculator meanwhile is noticed. It fits in one report,
        # which a G2 has answered every time.
        return self.link.get_note(REV_NOTE)

    def write_rev(self, token):
        self.write(token, REV_NOTE)

    def write_quick(self, name, text):
        """A small note only CalcVault reads (heartbeat, focus): written in
        the plain shape without first reading the old one, which saves a
        round trip, and a request that goes unanswered when it is new."""
        self.link.put_note(name, text, new=True)

    def close_box(self):
        """Closes CalcVault 2's link box, if it is up (its note CVBOX), so the
        app shows at once what was just sent: Esc is pressed only then."""
        if self.link.get_note("CVBOX", patience=5.0) == "up":
            self.link.send_key(self.link.KEY_ESC)
            return True
        return False

    def install(self, name, source):
        self.link.put_program(name, source)

    def close(self):
        self.link.close()


class FolderTarget:
    """A calculator's folder on disk: the Virtual Calculator's (which it
    reads when it starts, so it must be closed while this runs), or any
    folder holding a CVDATA.hpnote."""

    def __init__(self, folder):
        self.folder = folder
        self.label = folder

    def _path(self, name):
        return os.path.join(self.folder, name + ".hpnote")

    def read(self, name=NOTE):
        path = self._path(name)
        if not os.path.exists(path):
            return None
        from .primelink import note_text
        with open(path, "rb") as f:
            return note_text(f.read())

    def write(self, text, name=NOTE, new=False):
        from .primelink import note_bytes
        path = self._path(name)
        existing = None
        if os.path.exists(path):
            with open(path, "rb") as f:
                existing = f.read()
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            # A note the calculator wrote itself has no formatting tail;
            # keep whatever shape is there, plain for a new one.
            f.write(note_bytes(text, existing if existing is not None else b""))
        os.replace(tmp, path)

    def read_rev(self):
        return self.read(REV_NOTE)

    def write_rev(self, token):
        self.write(token, REV_NOTE)

    def write_quick(self, name, text):
        self.write(text, name)

    def close_box(self):
        return False

    def install(self, name, source):
        raise StoreError("installing into a folder is done with hp-prime-kit's hpprime install")

    def close(self):
        pass


def emulator_folder():
    """The Virtual Calculator's first calculator folder, if there is one."""
    docs = os.path.join(os.path.expanduser("~"), "Documents", "HP Prime", "Calculators", "Prime")
    return docs if os.path.isdir(docs) else None
