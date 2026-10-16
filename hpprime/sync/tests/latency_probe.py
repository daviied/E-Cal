"""How long does the calculator take to answer? Asks once and waits long.

    python tests/latency_probe.py

Times the ready check, then a request for a small note (CVDATA) and a
missing one, each waiting up to 60 s and logging every report that comes
back, so late or stray replies show up instead of being taken for answers.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import primelink as P  # noqa: E402


def ask(link, what, message, wait=60.0):
    link._drain()
    t0 = time.time()
    link._send(message)
    got = []
    end = t0 + wait
    while time.time() < end:
        rep = link.dev.read(link.report + 1, 200)
        if rep:
            rep = bytes(rep)
            got.append((time.time() - t0, rep[0], rep[1:7].hex()))
            if len(got) == 1 and rep[1] == 0xF7:
                size = int.from_bytes(rep[3:7], "big") + 6
                need = (size + link.report - 2) // (link.report - 1)
                while len(got) < need and time.time() < end:
                    r2 = link.dev.read(link.report + 1, 200)
                    if r2:
                        got.append((time.time() - t0, r2[0], bytes(r2[1:7]).hex()))
                break
            if rep[1] in (0xFF, 0x59) and what == "ready":
                break
    print("%-18s %s" % (what, ", ".join("%.2fs seq%d %s" % g for g in got[:4]) or "no reply in %ds" % wait),
          "(%d reports)" % len(got) if len(got) > 4 else "")


link = P.PrimeLink()
for i in range(3):
    ask(link, "ready", bytes([P.CMD_CHECK_READY]), 20)
ask(link, "CVDATA", P.file_message(P.CMD_REQUEST_FILE, "CVDATA", P.TYPE_NOTE))
ask(link, "missing note", P.file_message(P.CMD_REQUEST_FILE, "CVZNONE", P.TYPE_NOTE), 20)
ask(link, "CVDATA again", P.file_message(P.CMD_REQUEST_FILE, "CVDATA", P.TYPE_NOTE))
link.close()
