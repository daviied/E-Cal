"""Reads notes one at a time with a pause between, logging every report, to
tell "not on the calculator" apart from "answer lost or late".

    python tests/slow_read_probe.py [names...]
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import primelink as P  # noqa: E402

names = sys.argv[1:] or ["CVDATA", "CVZ", "CVZ1", "CVZ12", "CVZ123", "CVZ1234", "CVZ12345",
                         "CVZAB", "CVZABC", "CVZ10", "CVZ010", "CVDATA"]
link = P.PrimeLink()
for name in names:
    time.sleep(2)
    ready = link.check_ready(timeout=3)
    link._drain()
    t0 = time.time()
    link._send(P.file_message(P.CMD_REQUEST_FILE, name, P.TYPE_NOTE))
    seen = []
    while time.time() - t0 < 10:
        try:
            r = link._reply(P.CMD_FILE, 30, first=10 - (time.time() - t0))
        except TimeoutError:
            break
        except P.LinkError as e:
            seen.append("error %s" % e)
            break
        got = P.parse_file_reply(r)
        seen.append("%.2fs %s" % (time.time() - t0, got[1] + "=" + repr(P.note_text(got[2])[:20]) if got else "none"))
        if got and got[1] == name:
            break
    print("%-9s ready=%s  %s" % (name, ready, "; ".join(seen) or "no answer in 10 s"))
link.close()
