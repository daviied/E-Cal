"""After a request for a missing note goes unanswered, what brings the link
back? Tries: waiting, a ready check, reconnecting.

    python tests/recover_probe.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import primelink as P  # noqa: E402


def ask(link, name, wait=8.0):
    link._drain()
    t0 = time.time()
    link._send(P.file_message(P.CMD_REQUEST_FILE, name, P.TYPE_NOTE))
    try:
        r = link._reply(P.CMD_FILE, wait)
        got = P.parse_file_reply(r)
        return "ok %.2fs %s" % (time.time() - t0, "%d bytes" % len(got[2]) if got else "no object")
    except Exception as e:  # noqa: BLE001
        return "%.2fs %r" % (time.time() - t0, e)


link = P.PrimeLink()
print("before:            ", ask(link, "CVDATA"))
print("missing note:      ", ask(link, "CVZNONE", 5))
print("right after:       ", ask(link, "CVDATA"))
time.sleep(3)
print("after 3 s:         ", ask(link, "CVDATA"))
print("ready check:       ", link.check_ready(timeout=3))
print("after ready check: ", ask(link, "CVDATA"))
link._reopen()
print("after reconnect:   ", ask(link, "CVDATA"))
print("again:             ", ask(link, "CVDATA"))
link.close()
