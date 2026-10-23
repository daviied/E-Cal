"""Do notes with an odd number of characters in their name fail to be
written? Same content under odd and even names, then read back.

    python tests/parity_probe.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync.primelink import PrimeLink  # noqa: E402

PAIRS = [("CVQ", "CVQQ"), ("CVQ12", "CVQ123"), ("CVQAB", "CVQABC"), ("CVQ1234", "CVQ12345"), ("CVQ7", "CVQ77")]
link = PrimeLink()
for odd, even in PAIRS:
    for name in (odd, even):
        link.put_note(name, "same content", new=True)
for odd, even in PAIRS:
    row = []
    for name in (odd, even):
        t = time.time()
        got = link.get_note(name)
        row.append("%-9s(%d) %-7s" % (name, len(name), "ok" if got == "same content" else "MISSING"))
    print("   ".join(row))
link.close()
