"""Checks the USB link with a real HP Prime, writing only a note named CVTEST.

    python tests/usb_probe.py [sizes...]      default sizes: 100 2000 20000 100000

For each size it writes CVTEST with that many characters, reads it back and
compares, and reports how long each step took. Runs every step in a thread
with a time limit, so a stuck transfer is reported instead of hanging.
"""
import sys
import threading
import time
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync.primelink import PrimeLink  # noqa: E402


def timed(what, fn, limit=60):
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001
            box["error"] = e

    t0 = time.time()
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(limit)
    dt = time.time() - t0
    if th.is_alive():
        print("STUCK %-28s after %.0fs" % (what, dt))
        os._exit(2)
    if "error" in box:
        print("FAIL  %-28s %.2fs  %r" % (what, dt, box["error"]))
        return None
    print("ok    %-28s %.2fs" % (what, dt))
    return box.get("value")


def main():
    sizes = [int(a) for a in sys.argv[1:]] or [100, 2000, 20000, 100000]
    link = timed("open + ready check", lambda: PrimeLink(log=print))
    if link is None:
        return 1
    print("report size", link.report)
    cv = timed("read CVDATA", lambda: link.get_note("CVDATA"))
    print("      CVDATA is %s characters" % (None if cv is None else len(cv)))
    for n in sizes:
        text = ("0123456789abcdefghij" * (n // 20 + 1))[:n]
        timed("write CVTEST %d chars" % n, lambda: link.put_note("CVTEST", text), limit=120)
        back = timed("read CVTEST", lambda: link.get_note("CVTEST"), limit=120)
        if back != text:
            print("      MISMATCH: read back %s characters" % (None if back is None else len(back)))
            return 1
        print("      matches")
    link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
