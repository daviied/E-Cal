"""Why does reading stop after the first one or two notes? Read-only.

    python tests/stall_probe.py [rounds]       default 8 reads per strategy

Leave the calculator on its Home screen with CalcVault closed, HP's
Connectivity Kit closed. It reads CalcVault's own notes (CVDATA, CVREV and
the calculators' CVC notes) over and over, each strategy in turn, and prints
one mark per read: ok (with seconds), -- for no answer in 8 s, ! for an
error. After every answer it keeps listening for 0.4 s and counts reports
that arrive after the reply's declared end ("tail"), which would show the
calculator sending more than the reply it declares.

Strategies:
  plain        request, wait                (no ready check)
  ready        ready check, request, wait   (what the sync does)
  ready+pause  ready check, 0.3 s, request
  pause        1 s pause, request
  reopen       close and reopen the USB connection, request
  drainlong    listen 1 s for stray reports, then ready check, request
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import primelink as P  # noqa: E402
from cvsync import store  # noqa: E402


def one(link, name, how):
    if how == "reopen":
        link._reopen()
    if how == "pause":
        time.sleep(1.0)
    if how == "drainlong":
        end = time.time() + 1.0
        stray = 0
        while time.time() < end:
            if link.dev.read(link.report + 1, 100):
                stray += 1
        if stray:
            print("    (%d stray reports before %s)" % (stray, name))
    if how in ("ready", "ready+pause", "drainlong"):
        if not link.check_ready(timeout=2.0):
            print("    (no answer to the ready check before %s)" % name)
    if how == "ready+pause":
        time.sleep(0.3)
    link._drain()
    t0 = time.time()
    link._send(P.file_message(P.CMD_REQUEST_FILE, name, P.TYPE_NOTE))
    try:
        reply = link._reply(P.CMD_FILE, 60.0, first=8.0)
    except TimeoutError:
        return "--", None
    except P.LinkError as e:
        return "!", str(e)
    dt = time.time() - t0
    got = P.parse_file_reply(reply)
    tail = []
    end = time.time() + 0.4
    while time.time() < end:
        rep = link.dev.read(link.report + 1, 50)
        if rep:
            tail.append(bytes(rep[:8]).hex())
    if got is None:
        return "none", None
    mark = "ok%.1f" % dt if got[1] == name else "other(%s)" % got[1]
    return mark, ("tail %d: %s" % (len(tail), tail[:3])) if tail else None


def main(rounds):
    link = P.PrimeLink(log=print)
    try:
        text = link.get_note(store.NOTE)
        if text is None:
            raise SystemExit("CVDATA did not arrive even with retries; is CalcVault data on the calculator?")
        d = store.parse_list(text)
        slots = [c[4] for c in d[4]] if d and d[0] == store.MAGIC2 else []
        names = [store.NOTE, store.REV_NOTE] + [store.calc_note(s) for s in slots[:6]]
        print("notes used: %s" % ", ".join(names))
        for how in ("plain", "ready", "ready+pause", "pause", "reopen", "drainlong"):
            link._reopen()
            marks, notes = [], []
            for i in range(rounds):
                name = names[i % len(names)]
                m, extra = one(link, name, how)
                marks.append(m)
                if extra:
                    notes.append("%s: %s" % (name, extra))
            ok = sum(1 for m in marks if m.startswith("ok"))
            print("%-12s %d/%d  %s" % (how, ok, rounds, " ".join(marks)))
            for n in notes[:4]:
                print("             " + n)
    finally:
        link.close()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8)
