"""Is it the name or the order? Writes a batch of even-length names, then a
batch of odd-length ones, then reads every one back.

    python tests/parity_probe2.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync.primelink import PrimeLink  # noqa: E402

EVEN = ["CVEA", "CVEB", "CVEC", "CVED", "CVEE", "CVEF"]
ODD = ["CVOAA", "CVOBB", "CVOCC", "CVODD", "CVOEE", "CVOFF"]
link = PrimeLink()
for name in EVEN + ODD:
    link.put_note(name, "x", new=True)
print("even names:", " ".join("%s=%s" % (n, "ok" if link.get_note(n) == "x" else "--") for n in EVEN))
print("odd names: ", " ".join("%s=%s" % (n, "ok" if link.get_note(n) == "x" else "--") for n in ODD))
link.close()
