"""Which note names survive a write and read back over USB?

    python tests/name_probe.py

Writes a tiny note under names of different lengths (all starting CVZ, so
nothing of CalcVault's is touched), reads each back, and prints which ones
worked and how long they took.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync.primelink import PrimeLink  # noqa: E402

NAMES = ["CVZ", "CVZ1", "CVZ12", "CVZ123", "CVZ1234", "CVZ12345", "CVZAB", "CVZABC", "CVZ10", "CVZ010"]


def main():
    link = PrimeLink()
    for name in NAMES:
        text = "probe " + name
        t0 = time.time()
        try:
            link.put_note(name, text, new=True)
            back = link.get_note(name)
            ok = back == text
            print("%-9s %d chars  %-4s  %.1fs%s" % (name, len(name), "ok" if ok else "FAIL", time.time() - t0,
                                                    "" if ok else "  (read back %r)" % back))
        except Exception as e:  # noqa: BLE001
            print("%-9s %d chars  ERROR %.1fs  %r" % (name, len(name), time.time() - t0, e))
            link._reopen()
    link.close()


if __name__ == "__main__":
    main()
