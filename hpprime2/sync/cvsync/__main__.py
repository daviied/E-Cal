"""CalcVault sync for the HP Prime.

    python -m cvsync sync                 sync the calculator on USB with the web app
    python -m cvsync sync --dry-run       show what a sync would do, change nothing
    python -m cvsync sync --emulator      sync HP's Virtual Calculator instead (close it first)
    python -m cvsync live                 keep syncing while the calculator is plugged in
    python -m cvsync online               live sync for a calculator with CalcVault 2 open on
                                          it: faster, shows "online" there, and opens on the
                                          calculator what you open in the web app
    python -m cvsync restore FILE         put a backed-up CVDATA back on the calculator
    python -m cvsync install              send the CalcVault program to the calculator
    python -m cvsync status               what is configured and what is attached
    python -m cvsync login                log in again (the session lasts 30 days)

Options:
    --server URL        the web app's address; remembered after the first use
    --folder DIR        sync a calculator folder holding CVDATA.hpnote
    --yes               do not ask before deleting anything
    --password-env VAR  read the password from this environment variable

Keep HP's Connectivity Kit closed on the PC (both want the same USB
connection). CalcVault may stay open on the calculator: it reloads when the
PC writes, and will not save over what the PC wrote.
"""
import datetime
import getpass
import json
import os
import subprocess
import sys
import time
import uuid

from . import store, sync
from .api import Api, ApiError

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM_SOURCE = os.path.join(HERE, "..", "..", "calc", "CALCVAULT2.txt")


def config_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "CalcVaultSync")
    os.makedirs(os.path.join(d, "backups"), exist_ok=True)
    return d


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, value):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def opt(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def connect_api(argv, cfg, cfg_path):
    url = opt(argv, "--server") or cfg.get("server")
    if not url:
        url = input("CalcVault web address (for example https://calc.example.com): ").strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if cfg.get("server") != url:
        cfg["server"] = url
        save_json(cfg_path, cfg)
    api = Api(url, os.path.join(config_dir(), "session.cookies"))
    if "login" in argv[:1] or not api.authed():
        env = opt(argv, "--password-env")
        password = os.environ.get(env) if env else None
        if not password:
            password = getpass.getpass("CalcVault password for %s: " % url)
        api.login(password)
        print("Logged in.")
    return api


def emulator_running():
    if not sys.platform.startswith("win"):
        return False
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq HPPrime.exe", "/NH"],
                         capture_output=True, text=True).stdout
    return "HPPrime.exe" in out


def open_target(argv):
    folder = opt(argv, "--folder")
    if "--emulator" in argv:
        folder = store.emulator_folder()
        if not folder:
            raise SystemExit("HP's Virtual Calculator folder was not found.")
        if emulator_running():
            raise SystemExit("Close the Virtual Calculator first: it only reads its files when it starts, "
                             "and writes them back when it closes.")
    if folder:
        return store.FolderTarget(folder)
    return store.UsbTarget(log=lambda m: None)


def sync_once(api, target, cfg, argv, interactive=True, quiet=False):
    """One sync. Answers 0 when done or nothing to do, 1 when stopped."""
    dry = "--dry-run" in argv
    say = (lambda *a: None) if quiet else print
    say("Reading CalcVault from the %s..." % target.label)
    rev_read = target.read_rev()

    def cache_for(dev):
        st = load_json(os.path.join(config_dir(), "state-%s.json" % dev), {}) if dev else {}
        return st.get("cache", {}) if st.get("server") == cfg["server"] else {}

    try:
        vault, layout = store.read_vault(target, cache_for, log=None if quiet else say)
    except store.StoreError as e:
        print("The calculator's CalcVault notes could not be read (%s). Nothing was changed." % e)
        return 1
    fresh = not vault["dev"]
    if fresh:
        vault["dev"] = uuid.uuid4().hex[:12]
    state_path = os.path.join(config_dir(), "state-%s.json" % vault["dev"])
    state = load_json(state_path, {})
    if state and state.get("server") != cfg["server"]:
        print("This calculator was last synced with %s; treating this as a first sync with %s."
              % (state.get("server"), cfg["server"]))
        state = {}
    base = state.get("base", {})
    # The web app's global and folder lines, which the calculator only reads.
    shared = sync.shared_text(api.tree())
    shared_changed = shared != state.get("shared")

    plan = sync.Report()
    sync.run(vault, api, base, plan, dry_run=True)
    nothing = not (plan.to_web or plan.to_calc or plan.conflicts)
    if not (quiet and nothing):
        say(plan.summary())
        if shared_changed:
            say("Shared lines (global and folder lines) will be copied to the calculator.")
    if dry:
        print("\n(dry run: nothing was changed)")
        return 0
    if nothing and not fresh and layout["format"] == 2 and not shared_changed:
        return 0
    risky = [x for x in plan.to_web + plan.to_calc if "deleted" in x] + plan.conflicts
    if risky and interactive and "--yes" not in argv:
        if input("\nApply these changes? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing was changed.")
            return 1

    backups = os.path.join(config_dir(), "backups")
    if vault["calcs"] or vault["folders"]:
        # The whole vault in one file, whichever layout the calculator has.
        with open(os.path.join(backups, "CVDATA-%s-%s.txt" % (vault["dev"], stamp())), "w",
                  encoding="utf-8") as f:
            f.write(store.vault_to_text(vault))
    if plan.to_web:
        tree = api.tree()
        snap = {"tree": tree, "calculators": {c["id"]: api.get_calc(c["id"]) for c in tree["calculators"]}}
        save_json(os.path.join(backups, "server-%s.json" % stamp()), snap)

    # The app may have saved while this was planning; start again then.
    if target.read_rev() != rev_read:
        say("The calculator changed while syncing; starting again.")
        return sync_once(api, target, cfg, argv, interactive, quiet)

    report = sync.Report()
    new_vault, new_base = sync.run(vault, api, base, report)
    # Ids made on the calculator are on the server now; remember them
    # before touching the calculator, in case the next step fails.
    state.update({"server": cfg["server"], "base": dict(base, pending=new_base["pending"])})
    save_json(state_path, state)

    # Each calculator keeps its note (slot) when the sync gives it the web
    # app's id in place of one made on the calculator.
    slot_of = {new_base["pending"].get(cid, cid): slot for cid, slot in layout["slot"].items()}
    try:
        cache = store.write_vault(target, new_vault, layout, slot_of, log=None if quiet else say)
    except store.StoreError as e:
        print("%s. The web app has been updated; run the sync again." % e)
        return 1
    if shared_changed:
        try:
            store.write_verified(target, store.SHARED_NOTE, shared, new="shared" not in state)
            state["shared"] = shared
        except store.StoreError as e:
            print("Shared lines: %s." % e)
    # Tells CalcVault, if it is open, to reload.
    target.write_rev("p" + stamp())
    new_base["pending"] = {}
    state.update({"base": new_base, "cache": cache,
                  "last_sync": datetime.datetime.now().isoformat(timespec="seconds")})
    save_json(state_path, state)
    if quiet:
        done = report.to_web + report.to_calc + report.conflicts
        if shared_changed:
            done.append("shared lines")
        print("%s  synced: %s" % (now(), "; ".join(done) if done else "ids updated"))
        for w in report.warnings:
            print("    " + w)
    else:
        print("\nDone." if report.summary() == plan.summary() else "\nDone:\n" + report.summary())
    return 0


def now():
    return datetime.datetime.now().strftime("%H:%M:%S")


def cmd_sync(argv):
    cfg_path = os.path.join(config_dir(), "config.json")
    cfg = load_json(cfg_path, {})
    api = connect_api(argv, cfg, cfg_path)
    target = open_target(argv)
    try:
        return sync_once(api, target, cfg, argv)
    finally:
        target.close()


def web_signature(api):
    """Changes whenever anything on the web app does."""
    t = api.tree()
    # Shared lines change no calculator's updated_at, so they count here too.
    shared = json.dumps({"g": t.get("globals"), "f": {str(f["id"]): f.get("data") for f in t["folders"]}},
                        sort_keys=True)
    return (tuple(sorted((f["id"], f["parent_id"] or 0, f["name"]) for f in t["folders"])),
            tuple(sorted((c["id"], c["folder_id"] or 0, c["name"], c.get("updated_at") or "")
                         for c in t["calculators"])), shared)


def cmd_live(argv):
    """Syncs whenever the calculator or the web app changes, for as long as
    the calculator stays plugged in, and waits for it when it is not."""
    from .primelink import LinkError
    cfg_path = os.path.join(config_dir(), "config.json")
    cfg = load_json(cfg_path, {})
    api = connect_api(argv, cfg, cfg_path)
    every = float(opt(argv, "--every", "2"))
    web_every = float(opt(argv, "--web-every", "5"))
    print("Live sync with %s. Leave this window open; Ctrl+C stops it." % cfg["server"])
    target, last_rev, last_sig, last_web, waiting = None, None, None, 0.0, False
    while True:
        try:
            if target is None:
                target = open_target(argv)
                print("%s  calculator connected" % now())
                waiting, last_rev = False, None
            rev = target.read_rev()
            sig = last_sig
            if time.time() - last_web >= web_every:
                sig = web_signature(api)
                last_web = time.time()
            if last_rev is None or rev != last_rev or sig != last_sig:
                sync_once(api, target, cfg, argv, interactive=False, quiet=True)
                last_rev = target.read_rev()
                last_sig = web_signature(api)
                last_web = time.time()
            time.sleep(every)
        except (LinkError, TimeoutError, OSError) as e:
            if target is not None:
                target.close()
                target = None
                print("%s  calculator disconnected or busy (%s); waiting for it" % (now(), e))
            elif not waiting:
                print("Waiting for the calculator: plug it in and turn it on.")
            waiting = True
            time.sleep(3)
        except ApiError as e:
            print("%s  web app: %s; trying again shortly" % (now(), e))
            if e.status == 401:
                api = connect_api(argv, cfg, cfg_path)
            time.sleep(10)


def cmd_online(argv):
    """Online mode: CalcVault 2 on the calculator works as a remote for the
    web app. The same two-way sync as `live`, but checked every second, and
    meant to run while CalcVault is open on the calculator (it naps between
    key polls so the calculator can answer USB). It also

      - writes a heartbeat note (CVLINK) every few seconds, which the app
        shows as "online" in its title bar, and
      - when a calculator is opened in the web app, writes its id to CVFOCUS
        and the app opens it too (Settings > Follow the web app).

    While the calculator does not answer (unplugged, or a firmware that does
    not answer while a program runs) it waits, like `live`, and syncs
    whenever it can: the app then works offline, on what it last got."""
    from .primelink import LinkError
    cfg_path = os.path.join(config_dir(), "config.json")
    cfg = load_json(cfg_path, {})
    api = connect_api(argv, cfg, cfg_path)
    every = float(opt(argv, "--every", "1"))
    web_every = float(opt(argv, "--web-every", "1.5"))
    beat_every = float(opt(argv, "--beat-every", "4"))
    print("Online with %s. Leave this window open; Ctrl+C stops it." % cfg["server"])
    target, waiting = None, False
    last_rev, last_sig, sig = None, None, None
    focus, last_focus, has_focus = None, None, True
    t_web = t_beat = 0.0
    while True:
        try:
            if target is None:
                target = open_target(argv)
                print("%s  calculator connected" % now())
                waiting, last_rev, t_beat = False, None, 0.0
            rev = target.read_rev()
            if sig is None or time.time() - t_web >= web_every:
                sig = web_signature(api)
                if has_focus:
                    focus = api.get_focus()
                    has_focus = focus is not None
                t_web = time.time()
            if last_rev is None or rev != last_rev or sig != last_sig:
                sync_once(api, target, cfg, argv, interactive=False, quiet=True)
                last_rev = target.read_rev()
                sig = last_sig = web_signature(api)
            if focus and focus.get("calc_id") and focus.get("token") != last_focus:
                # A calculator opened before this started is old news,
                # unless it was opened just now.
                if last_focus is not None or (focus.get("age") or 99) < 20:
                    target.write_quick(store.FOCUS_NOTE, "%s;%s" % (focus["calc_id"], focus["token"]))
                    print("%s  opened calculator %s on the calculator" % (now(), focus["calc_id"]))
                last_focus = focus.get("token")
            if time.time() - t_beat >= beat_every:
                target.write_quick(store.LINK_NOTE, "b" + uuid.uuid4().hex[:8])
                t_beat = time.time()
            time.sleep(every)
        except (LinkError, TimeoutError, OSError) as e:
            if target is not None:
                target.close()
                target = None
                print("%s  calculator not answering (%s). Waiting for it; if CalcVault is open on it, "
                      "check its Settings > Let the PC sync while open." % (now(), e))
            elif not waiting:
                print("Waiting for the calculator: plug it in and turn it on.")
            waiting = True
            time.sleep(3)
        except ApiError as e:
            print("%s  web app: %s; trying again shortly" % (now(), e))
            if e.status == 401:
                api = connect_api(argv, cfg, cfg_path)
            time.sleep(5)


def cmd_restore(argv):
    """Puts a saved CVDATA (one of the backups) back on the calculator."""
    path = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else None
    if not path or not os.path.exists(path):
        raise SystemExit("usage: python -m cvsync restore BACKUP.txt   (backups are in %s)"
                         % os.path.join(config_dir(), "backups"))
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    vault = store.vault_from_text(text)  # refuses anything that is not a vault
    target = open_target(argv)
    try:
        current, _ = store.read_vault(target)
        if current["calcs"] or current["folders"]:
            with open(os.path.join(config_dir(), "backups", "CVDATA-before-restore-%s.txt" % stamp()),
                      "w", encoding="utf-8") as f:
                f.write(store.vault_to_text(current))
        store.write_vault(target, vault, {"format": 1, "slot": {}, "rev": {}, "lines": {}})
        target.write_rev("p" + stamp())
    finally:
        target.close()
    print("Restored %d folders and %d calculators to the calculator." % (len(vault["folders"]), len(vault["calcs"])))
    return 0


def cmd_install(argv):
    with open(PROGRAM_SOURCE, encoding="utf-8") as f:
        source = f.read()
    target = open_target(argv)
    try:
        target.install("CALCVAULT2", source)
    finally:
        target.close()
    print("Sent CALCVAULT2. On the calculator, press Home and type CALCVAULT2 then Enter.")
    return 0


def cmd_status(argv):
    cfg = load_json(os.path.join(config_dir(), "config.json"), {})
    print("Web app:   %s" % (cfg.get("server") or "(not set yet)"))
    print("Settings:  %s" % config_dir())
    try:
        from .primelink import find_calculators
        devs = find_calculators()
        print("USB:       %s" % ("%d HP Prime attached" % len(devs) if devs else "no HP Prime attached"))
    except Exception as e:  # noqa: BLE001
        print("USB:       %s" % e)
    for name in sorted(os.listdir(config_dir())):
        if name.startswith("state-"):
            st = load_json(os.path.join(config_dir(), name), {})
            print("Calculator %s: last synced %s" % (name[6:-5], st.get("last_sync", "never")))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    try:
        if cmd == "sync":
            return cmd_sync(argv)
        if cmd == "live":
            return cmd_live(argv)
        if cmd == "online":
            return cmd_online(argv)
        if cmd == "restore":
            return cmd_restore(argv)
        if cmd == "install":
            return cmd_install(argv)
        if cmd == "status":
            return cmd_status(argv)
        if cmd == "login":
            cfg_path = os.path.join(config_dir(), "config.json")
            connect_api(argv, load_json(cfg_path, {}), cfg_path)
            return 0
    except ApiError as e:
        print("Web app: %s" % e)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 1
    except Exception as e:  # noqa: BLE001
        from .primelink import LinkError
        if isinstance(e, (LinkError, store.StoreError)):
            print(str(e))
            return 1
        raise
    print("unknown command %r\n%s" % (cmd, __doc__))
    return 2


if __name__ == "__main__":
    sys.exit(main())
