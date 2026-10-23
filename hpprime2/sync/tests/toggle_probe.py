"""Is every other message to the calculator lost? Sends ready checks one at a
time, draining everything in between, and records which get an answer.

    python tests/toggle_probe.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import primelink as P  # noqa: E402

link = P.PrimeLink()
results = []
for i in range(16):
    end = time.time() + 0.5
    while time.time() < end:          # empty anything still on its way
        link.dev.read(link.report + 1, 50)
    t0 = time.time()
    link._send(bytes([P.CMD_CHECK_READY]))
    answer = None
    while time.time() - t0 < 3:
        rep = link.dev.read(link.report + 1, 100)
        if rep and rep[1] in (0xFF, 0x59):
            answer = time.time() - t0
            break
    results.append("ok" if answer is not None else "--")
print("ready checks, in order:", " ".join(results))

# The same with each ready check sent twice in a row (a "primer" first).
results = []
for i in range(8):
    end = time.time() + 0.5
    while time.time() < end:
        link.dev.read(link.report + 1, 50)
    link._send(bytes([P.CMD_CHECK_READY]))
    link._send(bytes([P.CMD_CHECK_READY]))
    t0 = time.time()
    n = 0
    while time.time() - t0 < 2:
        rep = link.dev.read(link.report + 1, 100)
        if rep and rep[1] in (0xFF, 0x59):
            n += 1
    results.append(str(n))
print("answers to pairs:      ", " ".join(results))
link.close()
