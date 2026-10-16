"""One sync, as run by the web app's own server (backend/app/hp.py).

This is cvsync.__main__.sync_once without the command line: the calculator is
reached through whatever `target` is given (the web app hands it one that asks
the user's browser, which holds the USB connection), the web app's data is
reached through `api` (in-process, no HTTP), and the three-way-merge state
and backups live in `state_dir` instead of the PC's settings folder. The
merge itself is sync.run, unchanged.

Anything the user should see goes through `say(text)`. When the plan would
delete something or resolve a conflict and the sync is not automatic,
`confirm(plan_text)` is asked first; answering False changes nothing.
"""
import datetime
import json
import os
import uuid

from . import store, sync

SERVER_KEY = "calcvault-web"
KEEP_BACKUPS = 30


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, value):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _prune(folder, prefix):
    names = sorted(n for n in os.listdir(folder) if n.startswith(prefix))
    for old in names[:-KEEP_BACKUPS]:
        try:
            os.remove(os.path.join(folder, old))
        except OSError:
            pass


def sync_once(api, target, state_dir, say, confirm, auto=False, _depth=0):
    """Answers {"code": 0 or 1, "changed": bool, "summary": str}. 0 means done
    (or nothing to do), 1 means stopped with nothing harmful changed."""
    backups = os.path.join(state_dir, "backups")
    os.makedirs(backups, exist_ok=True)

    if not auto:
        say("Reading CalcVault from the calculator...")
    rev_read = target.read_rev()

    def cache_for(dev):
        st = _load(os.path.join(state_dir, "state-%s.json" % dev), {}) if dev else {}
        return st.get("cache", {}) if st.get("server") == SERVER_KEY else {}

    try:
        vault, layout = store.read_vault(target, cache_for, log=None if auto else say)
    except store.StoreError as e:
        say("The calculator's CalcVault notes could not be read (%s). Nothing was changed." % e)
        return {"code": 1, "changed": False, "summary": ""}
    fresh = not vault["dev"]
    if fresh:
        vault["dev"] = uuid.uuid4().hex[:12]
    state_path = os.path.join(state_dir, "state-%s.json" % vault["dev"])
    state = _load(state_path, {})
    if state and state.get("server") != SERVER_KEY:
        say("This calculator was last synced by another tool; treating this as a first sync here.")
        state = {}
    base = state.get("base", {})

    plan = sync.Report()
    sync.run(vault, api, base, plan, dry_run=True)
    nothing = not (plan.to_web or plan.to_calc or plan.conflicts)
    if nothing and not fresh and layout["format"] == 2:
        if not auto:
            say(plan.summary())
        return {"code": 0, "changed": False, "summary": plan.summary()}
    say(plan.summary())

    risky = [x for x in plan.to_web + plan.to_calc if "deleted" in x] + plan.conflicts
    if risky and not auto:
        if not confirm(plan.summary()):
            say("Nothing was changed.")
            return {"code": 1, "changed": False, "summary": plan.summary()}

    if vault["calcs"] or vault["folders"]:
        # The whole vault in one file, whichever layout the calculator has.
        with open(os.path.join(backups, "CVDATA-%s-%s.txt" % (vault["dev"], stamp())), "w",
                  encoding="utf-8") as f:
            f.write(store.vault_to_text(vault))
        _prune(backups, "CVDATA-")
    if plan.to_web:
        tree = api.tree()
        snap = {"tree": tree, "calculators": {c["id"]: api.get_calc(c["id"]) for c in tree["calculators"]}}
        _save(os.path.join(backups, "server-%s.json" % stamp()), snap)
        _prune(backups, "server-")

    # The app may have saved while this was planning; start again then.
    if target.read_rev() != rev_read:
        if _depth >= 3:
            say("The calculator keeps changing; try again in a moment.")
            return {"code": 1, "changed": False, "summary": ""}
        say("The calculator changed while syncing; starting again.")
        return sync_once(api, target, state_dir, say, confirm, auto, _depth + 1)

    report = sync.Report()
    new_vault, new_base = sync.run(vault, api, base, report)
    # Ids made on the calculator are on the server now; remember them before
    # touching the calculator, in case the next step fails.
    state.update({"server": SERVER_KEY, "base": dict(base, pending=new_base["pending"])})
    _save(state_path, state)

    # Each calculator keeps its note (slot) when the sync gives it the web
    # app's id in place of one made on the calculator.
    slot_of = {new_base["pending"].get(cid, cid): slot for cid, slot in layout["slot"].items()}
    try:
        cache = store.write_vault(target, new_vault, layout, slot_of, log=None if auto else say)
    except store.StoreError as e:
        say("%s. The web app has been updated; run the sync again." % e)
        return {"code": 1, "changed": True, "summary": report.summary()}
    # Tells CalcVault, if it is open on the calculator, to reload.
    target.write_rev("p" + stamp())
    new_base["pending"] = {}
    state.update({"base": new_base, "cache": cache,
                  "last_sync": datetime.datetime.now().isoformat(timespec="seconds")})
    _save(state_path, state)
    for w in report.warnings:
        say("  " + w)
    say("Done.")
    return {"code": 0, "changed": True, "summary": report.summary()}
