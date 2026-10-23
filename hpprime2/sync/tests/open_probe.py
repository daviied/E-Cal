"""Does the calculator answer USB while CalcVault 2 is open on it?

    python tests/open_probe.py [seconds]      default 60

Online mode depends on this. Open CalcVault 2 on the calculator, plug it in,
close HP's Connectivity Kit, then run this. Once a second it asks for the
note CVREV and prints whether an answer came and how long it took. Midway,
switch the app's Settings > "Let the PC sync while open" off and on again
and watch the answers change. For comparison, also run it with CalcVault
closed (on Home), where the calculator always answers. It only reads.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import primelink as P  # noqa: E402


def main(seconds):
    link = P.PrimeLink()
    end = time.time() + seconds
    ok = total = 0
    try:
        while time.time() < end:
            total += 1
            t0 = time.time()
            try:
                got = link.get_note("CVREV")
                dt = time.time() - t0
                if got is None:
                    print("%5.1fs  no answer (or no CVREV note)" % dt)
                else:
                    ok += 1
                    print("%5.1fs  answered %r" % (dt, got[:20]))
            except (P.LinkError, OSError, TimeoutError) as e:
                print("%5.1fs  link error: %s; reconnecting" % (time.time() - t0, e))
                try:
                    link._reopen()
                except P.LinkError as e2:
                    print("        could not reconnect: %s" % e2)
            time.sleep(max(0.0, 1.0 - (time.time() - t0)))
    finally:
        link.close()
    print("\n%d of %d requests answered." % (ok, total))


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 60)
