"""Logs every raw report the calculator sends after a request, with no
interpretation, to see what a "missing" answer really is.

    python tests/raw_probe.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import primelink as P  # noqa: E402

link = P.PrimeLink()
print("report size", link.report)


def listen(label, seconds):
    t0 = time.time()
    seen = []
    while time.time() - t0 < seconds:
        rep = link.dev.read(link.report + 1, 100)
        if rep:
            rep = bytes(rep)
            seen.append("%.2fs seq=%02x %s.. (%d bytes)" % (time.time() - t0, rep[0], rep[1:9].hex(), len(rep)))
    print("%-28s %s" % (label, " | ".join(seen[:6]) or "nothing"), "(+%d more)" % (len(seen) - 6) if len(seen) > 6 else "")


listen("idle, before anything", 1.5)
for i in range(6):
    link._send(P.file_message(P.CMD_REQUEST_FILE, "CVDATA", P.TYPE_NOTE))
    listen("CVDATA request %d" % i, 4)
link._send(bytes([P.CMD_CHECK_READY]))
listen("ready check", 2)
for i in range(3):
    link._send(P.file_message(P.CMD_REQUEST_FILE, "CVDATA", P.TYPE_NOTE))
    listen("CVDATA request %d" % (i + 6), 4)
link.close()
