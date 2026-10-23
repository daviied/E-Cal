"""How long must the PC wait after an answer before the calculator takes the
next request? Sends requests at fixed gaps after each answer.

    python tests/gap_probe.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import primelink as P  # noqa: E402

link = P.PrimeLink()
REQ = P.file_message(P.CMD_REQUEST_FILE, "CVDATA", P.TYPE_NOTE)


def answered(wait=3.0):
    t0 = time.time()
    while time.time() - t0 < wait:
        rep = link.dev.read(link.report + 1, 50)
        if rep and rep[1] == P.CMD_FILE:
            return True
    return False


def settle():
    end = time.time() + 2.0
    while time.time() < end:
        link.dev.read(link.report + 1, 50)


for gap in (0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0):
    settle()
    link._send(REQ)
    answered()
    ok = 0
    for _ in range(6):
        time.sleep(gap)
        link._send(REQ)
        ok += answered()
    print("gap %.2fs after an answer: %d of 6 answered" % (gap, ok))

# A ready check, then a request after various gaps.
for gap in (0.0, 0.1, 0.3, 0.5, 1.0):
    ok = 0
    for _ in range(4):
        settle()
        link._send(bytes([P.CMD_CHECK_READY]))
        time.sleep(0.05)
        time.sleep(gap)
        link._send(REQ)
        ok += answered()
    print("request %.2fs after a ready check: %d of 4 answered" % (gap, ok))
link.close()
