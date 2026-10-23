"""Two-way sync between the calculator's vault and the web app.

A three-way merge against what both sides held after the last sync (the
"base", kept on the PC per calculator):

  changed on one side only     -> copied to the other
  changed on both sides        -> the web app's version wins, and the
                                  calculator's is kept as a new calculator
                                  named "<name> (calculator copy)"
  deleted on one side, unchanged on the other -> deleted on both
  deleted on one side, changed on the other   -> kept, the change wins

Folders and calculators are compared whole; lines carry the web app's line
ids (uid on the calculator), so a line that did not change keeps its exact
LaTeX on the web and its exact text on the calculator, and only lines that
changed are converted.
"""
import copy
import json
import uuid

from . import mathconv, store
from .store import clean

ROLE_TO_CALC = {"none": "0", "input": "1", "output": "2"}
ROLE_TO_WEB = {v: k for k, v in ROLE_TO_CALC.items()}
FIELD = {"none": "latex", "input": "value", "output": "expr"}
GREEK_NAMES = {k: v for k, v in mathconv.GREEK.items() if not k.startswith("var")}
GREEK_SPELLED = {v: k for k, v in GREEK_NAMES.items()}


def web_var(name):
    """An Input's variable name as the web app has to spell it so that its
    math-fields (through MathLive) reach the same variable: θ -> theta,
    Vin -> V_in."""
    name = (name or "").strip()
    if not name:
        return name
    head, sep, rest = name.partition("_")
    if head in GREEK_SPELLED:
        head = GREEK_SPELLED[head]
    elif not sep and len(head) > 1:
        head, sep, rest = head[0], "_", head[1:]
    return head + sep + rest


def calc_var(name):
    name = (name or "").strip()
    head, sep, rest = name.partition("_")
    if head in GREEK_NAMES:
        head = GREEK_NAMES[head]
    return clean(head + sep + rest)


def canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def web_lines(data):
    """The web app's lines, including its pre-lines 'Function' shape."""
    if isinstance(data.get("lines"), list):
        return data["lines"]
    if "formulaLatex" in data or "paramName" in data:
        var = data.get("paramName") or "x"
        return [
            {"id": str(uuid.uuid4()), "role": "input", "hidden": False, "latex": "", "varName": var,
             "label": var, "value": data.get("paramDefault") or "0", "expr": ""},
            {"id": str(uuid.uuid4()), "role": "output", "hidden": False, "latex": "", "varName": "",
             "label": data.get("outputLabel") or "Result", "value": "", "expr": data.get("formulaLatex") or ""},
        ]
    return []


class Report:
    def __init__(self):
        self.to_web, self.to_calc, self.conflicts, self.warnings = [], [], [], []

    def summary(self):
        out = []
        for title, items in (("To the web app", self.to_web), ("To the calculator", self.to_calc),
                             ("Conflicts", self.conflicts), ("Warnings", self.warnings)):
            if items:
                out.append(title + ":")
                out.extend("  " + s for s in items)
        return "\n".join(out) if out else "Everything was already in sync."


class DryApi:
    """Answers reads from the real API and records writes without making
    them, handing out stand-in ids."""

    def __init__(self, api, report):
        self.api, self.report, self.next = api, report, -1

    def __getattr__(self, name):
        return getattr(self.api, name)

    def _fake(self):
        self.next -= 1
        return self.next

    def create_folder(self, name, parent_id):
        return {"id": self._fake(), "name": name, "parent_id": parent_id}

    def update_folder(self, fid, name, parent_id):
        return {"id": fid}

    def delete_folder(self, fid):
        return {"ok": True}

    def create_calc(self, name, folder_id):
        return {"id": self._fake(), "updated_at": "dry-run"}

    def update_calc(self, cid, name, folder_id, data):
        return {"id": cid, "updated_at": "dry-run"}

    def delete_calc(self, cid):
        return {"ok": True}


def server_to_calc(srv, base_entry, report):
    """A web calculator ({name, folder, data}) -> the calculator's form."""
    bs = {l.get("id"): l for l in web_lines(base_entry["server"]["data"])} if base_entry else {}
    bc = {l["uid"]: l for l in base_entry["calc"]["lines"]} if base_entry else {}
    lines = []
    for l in web_lines(srv["data"]):
        role = l.get("role") if l.get("role") in FIELD else "none"
        field = FIELD[role]
        latex = l.get(field) or ""
        old_s, old_c = bs.get(l.get("id")), bc.get(l.get("id"))
        if old_s is not None and old_c is not None and (old_s.get(field) or "") == latex \
                and old_s.get("role") == l.get("role"):
            text = old_c["text"]
        else:
            text, err = mathconv.safe_latex_to_prime(latex)
            if err:
                report.warnings.append('"%s": a line could not be converted for the calculator '
                                       "(%s); it was copied as it is." % (srv["name"], err))
        lines.append({"uid": l.get("id") or str(uuid.uuid4()), "role": ROLE_TO_CALC[role],
                      "hidden": bool(l.get("hidden")), "var": calc_var(l.get("varName")),
                      "label": clean(l.get("label") or ""), "text": clean(text)})
    return {"name": clean(srv["name"]), "folder": srv["folder"],
            "locked": bool(srv["data"].get("locked")), "lines": lines}


def shared_text(tree, report=None):
    """CVSHR's text for the web app's tree, which carries the global lines
    and each folder's shared lines: all of them converted for the
    calculator. The app only reads it, so it is simply rewritten whenever
    it differs from what was last written."""
    report = report or Report()

    def conv(lines, where):
        srv = {"name": where, "folder": "0", "data": {"lines": lines}}
        return server_to_calc(srv, None, report)["lines"]

    glines = conv((tree.get("globals") or {}).get("lines") or [], "Global lines")
    folders = []
    for f in sorted(tree.get("folders", []), key=lambda f: f["id"]):
        lines = (f.get("data") or {}).get("lines") or []
        if lines:
            folders.append((str(f["id"]), conv(lines, 'shared lines of folder "%s"' % f["name"])))
    return store.shared_to_text(glines, folders)


def calc_to_server(calc, base_entry, report):
    """The calculator's form -> (web data, the calculator's form with every
    line given an id)."""
    bs = {l.get("id"): l for l in web_lines(base_entry["server"]["data"])} if base_entry else {}
    bc = {l["uid"]: l for l in base_entry["calc"]["lines"]} if base_entry else {}
    out, lines = [], []
    seen = set()
    for ln in calc["lines"]:
        uid = ln["uid"] if ln["uid"] and ln["uid"] not in seen else str(uuid.uuid4())
        seen.add(uid)
        role = ROLE_TO_WEB.get(ln["role"], "none")
        field = FIELD[role]
        old_s, old_c = bs.get(uid), bc.get(uid)
        if old_s is not None and old_c is not None and old_c["text"] == ln["text"] \
                and old_c["role"] == ln["role"]:
            latex = old_s.get(field) or ""
        else:
            latex, err = mathconv.safe_prime_to_latex(ln["text"])
            if err:
                report.warnings.append('"%s": %r could not be converted for the web app (%s); '
                                       "it was copied as it is." % (calc["name"], ln["text"], err))
        line = dict(old_s) if old_s else {}
        line.update({"id": uid, "role": role, "hidden": bool(ln["hidden"]),
                     "varName": web_var(ln["var"]) if not (old_c and old_c["var"] == ln["var"] and old_s)
                     else old_s.get("varName", ""),
                     "label": ln["label"]})
        for f in ("latex", "value", "expr"):
            line.setdefault(f, "")
        line[field] = latex
        out.append(line)
        lines.append(dict(ln, uid=uid))
    data = dict(base_entry["server"]["data"]) if base_entry else {}
    data["locked"] = bool(calc["locked"])
    data["lines"] = out
    return data, dict(calc, lines=lines)


def run(vault, api, base, report, dry_run=False, log=print):
    """Merges. Answers (new vault, new base). `vault` is the calculator's,
    `base` the saved state for this calculator (or {})."""
    if dry_run:
        api = DryApi(api, report)
    base = copy.deepcopy(base or {})
    b_f = base.get("folders", {})
    b_c = base.get("calcs", {})
    idmap = dict(base.get("pending", {}))  # calculator-made id -> server id

    def mapped(i):
        return idmap.get(i, i)

    # --- the calculator's side, with ids made here that an interrupted sync
    # already created on the server put back to those server ids.
    c_f = {}
    for f in vault["folders"]:
        c_f[mapped(f["id"])] = {"name": f["name"], "parent": mapped(f["parent"])}
    c_c = {}
    for c in vault["calcs"]:
        cc = {k: v for k, v in c.items() if k != "id"}
        cc["folder"] = mapped(c["folder"])
        c_c[mapped(c["id"])] = cc

    # --- the server's side
    tree = api.tree()
    s_f = {str(f["id"]): {"name": f["name"], "parent": str(f["parent_id"] or 0)} for f in tree["folders"]}
    s_meta = {str(c["id"]): c for c in tree["calculators"]}
    s_cache = {}

    def server_calc(cid):
        if cid in s_cache:
            return s_cache[cid]
        meta = s_meta[cid]
        b = b_c.get(cid)
        if b and b.get("updated_at") == meta.get("updated_at"):
            srv = b["server"]
        else:
            full = api.get_calc(cid)
            srv = {"name": full["name"], "folder": str(full["folder_id"] or 0), "data": full["data"]}
        s_cache[cid] = srv
        return srv

    def new_id(i):
        return not i.isdigit()

    # --------------------------------------------------------- folders
    def s_subtree(fid):
        kids = {fid}
        grew = True
        while grew:
            grew = False
            for k, v in s_f.items():
                if v["parent"] in kids and k not in kids:
                    kids.add(k)
                    grew = True
        return kids

    def c_subtree(fid):
        kids = {fid}
        grew = True
        while grew:
            grew = False
            for k, v in c_f.items():
                if v["parent"] in kids and k not in kids:
                    kids.add(k)
                    grew = True
        return kids

    def server_changed_under(fid):
        sub = s_subtree(fid)
        if any(k not in b_f or s_f[k] != b_f[k] for k in sub if k != fid):
            return True
        return any(m["folder_id"] is not None and str(m["folder_id"]) in sub and
                   (str(cid) not in b_c or b_c[str(cid)].get("updated_at") != m.get("updated_at"))
                   for cid, m in s_meta.items())

    def calc_changed_under(fid):
        sub = c_subtree(fid)
        if any(k not in b_f or c_f[k] != b_f[k] for k in sub if k != fid):
            return True
        return any(c["folder"] in sub and (cid not in b_c or canon(c) != canon(b_c[cid]["calc"]))
                   for cid, c in c_c.items())

    final_f = {}
    create_f = []          # calculator folders to create on the server
    delete_f = []          # server folders to delete, last
    for fid in sorted(set(b_f) | set(s_f) | {k for k in c_f if not new_id(k)}, key=str):
        b, c, s = b_f.get(fid), c_f.get(fid), s_f.get(fid)
        name = (s or c or b)["name"]
        if b is None:
            if c is not None and s is not None:
                if c != s:
                    report.conflicts.append('folder "%s": changed on both sides; kept the web '
                                            "app's version" % name)
                final_f[fid] = s
            elif s is not None:
                final_f[fid] = s
                report.to_calc.append('new folder "%s"' % name)
            else:
                create_f.append(fid)
        elif c is not None and s is not None:
            if c != b and s == b:
                final_f[fid] = c
                report.to_web.append('folder "%s" renamed or moved' % c["name"])
            elif s != b and c != b and c != s:
                final_f[fid] = s
                report.conflicts.append('folder "%s": changed on both sides; kept the web '
                                        "app's version" % name)
            else:
                if s != b:
                    report.to_calc.append('folder "%s" renamed or moved' % s["name"])
                final_f[fid] = s
        elif s is not None:  # deleted on the calculator
            if s == b and not server_changed_under(fid):
                delete_f.append(fid)
            else:
                final_f[fid] = s
                report.conflicts.append('folder "%s": deleted on the calculator but changed on '
                                        "the web app; kept" % name)
        elif c is not None:  # deleted on the web app
            if c == b and not calc_changed_under(fid):
                report.to_calc.append('folder "%s" deleted' % name)
            else:
                create_f.append(fid)
                report.conflicts.append('folder "%s": deleted on the web app but changed on the '
                                        "calculator; put back" % name)
    create_f += [k for k in c_f if new_id(k)]

    # Parents before children; a parent that no longer exists means the top.
    def resolve_parent(p, done=()):
        p = mapped(p)
        if p == "0":
            return "0"
        if p in final_f:
            return p
        if p in create_f and p not in done:
            return make_folder(p, done + (p,))
        return "0"

    def make_folder(fid, done=()):
        if fid in idmap and idmap[fid] in final_f:
            return idmap[fid]
        f = c_f[fid]
        parent = resolve_parent(f["parent"], done + (fid,))
        made = api.create_folder(f["name"], None if parent == "0" else int(parent))
        sid = str(made["id"])
        idmap[fid] = sid
        final_f[sid] = {"name": f["name"], "parent": parent}
        report.to_web.append('new folder "%s"' % f["name"])
        return sid

    for fid in list(create_f):
        if fid not in idmap or idmap[fid] not in final_f:
            make_folder(fid)
    for fid, f in list(final_f.items()):
        parent = mapped(f["parent"])
        if parent != "0" and parent not in final_f:
            parent = "0"
        final_f[fid] = dict(f, parent=parent)
    for fid in final_f:
        if fid in c_f and fid in b_f and c_f[fid] != b_f.get(fid) and s_f.get(fid) == b_f.get(fid):
            f = final_f[fid]
            api.update_folder(int(fid), f["name"], None if f["parent"] == "0" else int(f["parent"]))

    # --------------------------------------------------------- calculators
    final_c = {}   # server id -> {"calc": calculator form, "server": web form, "updated_at"}

    def folder_for(calc):
        f = mapped(calc["folder"])
        return f if f in final_f else "0"

    def push(cid, calc, b_entry, label):
        calc = dict(calc, folder=folder_for(calc))
        data, calc2 = calc_to_server(calc, b_entry, report)
        fid = None if calc2["folder"] == "0" else int(calc2["folder"])
        if cid is None:
            made = api.create_calc(calc2["name"], fid)
            cid = str(made["id"])
        res = api.update_calc(int(cid), calc2["name"], fid, data)
        final_c[cid] = {"calc": calc2, "updated_at": res.get("updated_at"),
                        "server": {"name": calc2["name"], "folder": calc2["folder"], "data": data}}
        report.to_web.append('%s "%s"' % (label, calc2["name"]))
        return cid

    def pull(cid, b_entry, label):
        srv = server_calc(cid)
        srv = dict(srv, folder=srv["folder"] if srv["folder"] in final_f else "0")
        final_c[cid] = {"calc": server_to_calc(srv, b_entry, report), "server": srv,
                        "updated_at": s_meta[cid].get("updated_at")}
        if label:
            report.to_calc.append('%s "%s"' % (label, srv["name"]))

    for cid in sorted(set(b_c) | set(s_meta) | {k for k in c_c if not new_id(k)}, key=str):
        b, c, m = b_c.get(cid), c_c.get(cid), s_meta.get(cid)
        if b is None:
            if c is not None and m is not None:
                srv_as_calc = server_to_calc(server_calc(cid), None, Report())
                same = canon(dict(srv_as_calc, lines=[dict(l, uid="") for l in srv_as_calc["lines"]])) == \
                    canon(dict(c, lines=[dict(l, uid="") for l in c["lines"]]))
                pull(cid, None, None if same else "replaced by the web app's version:")
                if not same:
                    push(None, dict(c, name=c["name"] + " (calculator copy)"), None, "new")
                    report.conflicts.append('"%s": differed on the two sides; the calculator\'s '
                                            "version was kept as a copy" % c["name"])
            elif m is not None:
                pull(cid, None, "new")
            elif c is not None:
                idmap[cid] = push(None, c, None, "new")
            continue
        changed_c = c is not None and canon(c) != canon(b["calc"])
        changed_s = m is not None and m.get("updated_at") != b.get("updated_at")
        if c is not None and m is not None:
            if changed_c and not changed_s:
                push(cid, c, b, "changed")
            elif changed_s and not changed_c:
                pull(cid, b, "changed")
            elif changed_c and changed_s:
                pull(cid, b, "changed")
                push(None, dict(c, name=c["name"] + " (calculator copy)"), None, "new")
                report.conflicts.append('"%s": changed on both sides; the web app\'s version '
                                        "kept, the calculator's saved as a copy" % c["name"])
            else:
                srv = dict(b["server"])
                final_c[cid] = {"calc": dict(b["calc"], folder=folder_for(b["calc"])), "server": srv,
                                "updated_at": b.get("updated_at")}
        elif m is not None:  # deleted on the calculator
            if not changed_s:
                api.delete_calc(int(cid))
                report.to_web.append('deleted "%s"' % b["calc"]["name"])
            else:
                pull(cid, b, "kept (deleted on the calculator, changed on the web app):")
        elif c is not None:  # deleted on the web app
            if changed_c:
                idmap[cid] = push(None, c, None, "put back (deleted on the web app, changed on the calculator):")
            else:
                report.to_calc.append('deleted "%s"' % c["name"])

    for cid, c in c_c.items():
        if new_id(cid):
            idmap[cid] = push(None, c, None, "new")

    for fid in delete_f:
        api.delete_folder(int(fid))
        report.to_web.append('deleted folder "%s"' % b_f[fid]["name"])

    # --------------------------------------------------------- results
    order = [mapped(mapped(c["id"])) for c in vault["calcs"]]
    ids = [i for i in order if i in final_c] + sorted((i for i in final_c if i not in order), key=str)
    new_vault = {
        "dev": vault["dev"], "next": vault["next"],
        "folders": [{"id": fid, "parent": f["parent"], "name": f["name"]} for fid, f in final_f.items()],
        "calcs": [dict(final_c[i]["calc"], id=i) for i in ids],
    }
    new_base = {
        "folders": final_f,
        "calcs": {i: {"updated_at": e["updated_at"], "server": e["server"],
                      "calc": {k: v for k, v in e["calc"].items() if k != "id"}}
                  for i, e in final_c.items()},
        # Calculator-side ids that now exist on the server under another id:
        # kept until the calculator has been written, so an interrupted sync
        # does not create them twice.
        "pending": {k: v for k, v in idmap.items() if k != v},
    }
    for e in new_base["calcs"].values():
        e["calc"].pop("id", None)
    return new_vault, new_base
