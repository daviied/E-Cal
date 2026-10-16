"""Does a ready check before every request make the link reliable?

    python tests/ready_probe.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import primelink as P  # noqa: E402


def ask(link, name, wait=8.0, ready=True):
    if ready:
        link.check_ready(timeout=3)
    link._drain()
    t0 = time.time()
    link._send(P.file_message(P.CMD_REQUEST_FILE, name, P.TYPE_NOTE))
    try:
        got = P.parse_file_reply(link._reply(P.CMD_FILE, wait))
        return "ok %.2fs" % (time.time() - t0) if got else "no object"
    except Exception as e:  # noqa: BLE001
        return "%.2fs %r" % (time.time() - t0, e)


link = P.PrimeLink()
print("without ready checks:", [ask(link, "CVDATA", 4, ready=False) for _ in range(4)])
print("with ready checks:   ", [ask(link, "CVDATA") for _ in range(10)])
print("missing note:        ", ask(link, "CVZNONE", 4))
print("then, with ready:    ", [ask(link, "CVDATA") for _ in range(4)])
link.close()
