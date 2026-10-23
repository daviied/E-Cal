"""A small test vault for HP's Virtual Calculator: a folder with shared
lines, a calculator that uses them, and global lines.

    python seed_emu.py            write the notes into the emulator's folder
    python seed_emu.py --program  write probes/CVSEED.txt, a program that
                                  makes the same notes when run on the
                                  calculator (the 2.4 emulator does not load
                                  .hpnote files from its folder at start)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sync"))
from cvsync import store, sync  # noqa: E402


def line(role, lid, **kw):
    out = {"id": lid, "role": role, "hidden": False, "latex": "", "varName": "", "label": "",
           "value": "", "expr": ""}
    out.update(kw)
    return out


TREE = {
    "globals": {"lines": [line("none", "g1", latex=r"g=9.81")]},
    "folders": [{"id": 7, "name": "Physics", "parent_id": None,
                 "data": {"lines": [line("input", "f1", varName="m", label="mass", value="2")]}}],
    "calculators": [],
}


def calc_line(uid, role, hidden, var, label, text):
    return {"uid": uid, "role": role, "hidden": hidden, "var": var, "label": label, "text": text}


VAULT = {
    "dev": "emutest", "next": "1",
    "folders": [{"id": "7", "parent": "0", "name": "Physics"}],
    "calcs": [{
        "id": "21", "folder": "7", "name": "Weight", "locked": False,
        "lines": [
            calc_line("a1", "1", False, "h", "height", "3"),
            calc_line("a2", "0", True, "", "", "W=m*g"),
            calc_line("a3", "2", False, "", "Energy", "W*h"),
        ],
    }],
}

def notes():
    """Every note of the test vault: {name: text}."""
    t = MemTarget()
    store.write_vault(t, VAULT, {"format": 2, "slot": {}, "rev": {}, "lines": {}})
    t.write(sync.shared_text(TREE), store.SHARED_NOTE)
    t.write_rev("pseed")
    return t.notes


class MemTarget:
    def __init__(self):
        self.notes = {}

    def read(self, name=store.NOTE):
        return self.notes.get(name)

    def write(self, text, name=store.NOTE, new=False):
        self.notes[name] = text

    def write_rev(self, token):
        self.write(token, store.REV_NOTE)


def program():
    out = ["// Made by seed_emu.py: the test vault's notes, written on the calculator.",
           "EXPORT CVSEED()", "BEGIN", "  LOCAL q;", "  q := CHAR(34);"]
    for name, text in notes().items():
        assert "~" not in text
        out.append('  Notes("%s") := REPLACE("%s", "~", q);' % (name, text.replace('"', "~")))
    for name in ("CVSET", store.LINK_NOTE, store.FOCUS_NOTE):
        out.append('  IFERR Notes("%s") := ""; THEN END;' % name)
    out += ['  RETURN "seeded";', "END;", ""]
    return "\n".join(out)


if __name__ == "__main__":
    if "--program" in sys.argv:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probes", "CVSEED.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(program())
        print("wrote", path)
        sys.exit(0)
    folder = store.emulator_folder()
    if not folder:
        raise SystemExit("Virtual Calculator folder not found")
    t = store.FolderTarget(folder)
    store.write_vault(t, VAULT, {"format": 2, "slot": {}, "rev": {}, "lines": {}})
    t.write(sync.shared_text(TREE), store.SHARED_NOTE)
    t.write_rev("pseed")
    for name in ("CVSET", store.LINK_NOTE, store.FOCUS_NOTE):
        path = os.path.join(folder, name + ".hpnote")
        if os.path.exists(path):
            os.remove(path)
    print("seeded", folder)
