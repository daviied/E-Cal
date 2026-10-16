"""Runs the real get_note several times while logging every report read and
written, to find where the sync's own request handling goes wrong.

    python tests/trace_probe.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import primelink as P  # noqa: E402

link = P.PrimeLink()
T0 = time.time()


class Traced:
    def __init__(self, dev):
        self.dev = dev

    def __getattr__(self, name):
        return getattr(self.dev, name)

    def read(self, n, timeout=0):
        r = self.dev.read(n, timeout)
        if r:
            r2 = bytes(r)
            print("   %6.3f  in  seq=%02x %s" % (time.time() - T0, r2[0], r2[1:9].hex()))
        return r

    def write(self, data):
        d = bytes(data)
        print("   %6.3f  out seq=%02x %s (%d bytes)" % (time.time() - T0, d[1], d[2:10].hex(), len(d)))
        return self.dev.write(data)


link.dev = Traced(link.dev)
real_reopen = link._reopen


def reopen(*a, **k):
    print("   %6.3f  -- reconnect" % (time.time() - T0))
    real_reopen(*a, **k)
    link.dev = Traced(link.dev)


link._reopen = reopen
mode = sys.argv[1] if len(sys.argv) > 1 else "read"
for i in range(4):
    t = time.time()
    if mode == "write":
        name = "CVZW%d" % i
        link.put_note(name, "trace %d" % i, new=True)
        print("put_note %s done in %.2fs" % (name, time.time() - t))
        t = time.time()
        text = link.get_note(name)
        print("read back %s -> %r in %.2fs\n" % (name, text, time.time() - t))
    else:
        text = link.get_note("CVDATA")
        print("get_note %d -> %s in %.2fs\n" % (i, "None" if text is None else "%d chars" % len(text), time.time() - t))
link.close()
