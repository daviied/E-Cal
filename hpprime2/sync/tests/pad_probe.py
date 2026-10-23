"""Can an odd-length name be written if the name is padded? Tries a NUL
terminator after the name, counted in the name length, for writing and
reading.

    python tests/pad_probe.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import primelink as P  # noqa: E402


def message(cmd, name, ftype, content=None, pad=False):
    nb = name.encode("utf-16-le") + (b"\x00\x00" if pad else b"")
    body = bytes([ftype, len(nb), 0, 0]) + nb + (bytes(content) if content is not None else b"")
    msg = bytearray(P.with_length(cmd, body))
    covered = bytearray(msg[:len(msg) - 6])
    for off in (8, 9):
        if off < len(covered):
            covered[off] = 0
    crc = P.crc16(covered)
    msg[8], msg[9] = crc & 0xFF, crc >> 8
    return bytes(msg)


def read(link, name, pad):
    for _ in range(3):
        link.check_ready(timeout=2)
        link._drain()
        link._send(message(P.CMD_REQUEST_FILE, name, P.TYPE_NOTE, pad=pad))
        try:
            got = P.parse_file_reply(link._reply(P.CMD_FILE, 20, first=2.5))
            return got[1] if got else "(no object)"
        except TimeoutError:
            continue
    return None


link = P.PrimeLink()
link.REOPEN_AFTER_WRITE = True
for name in ("CVPAD", "CVPADDD"):
    link.check_ready(timeout=2)
    link._drain()
    link._send(message(P.CMD_FILE, name, P.TYPE_NOTE, P.note_bytes("padded " + name), pad=True))
    time.sleep(1.5)
    link._reopen()
    print("%-8s written with a padded name -> read plain: %r, read padded: %r"
          % (name, read(link, name, False), read(link, name, True)))
link.close()
