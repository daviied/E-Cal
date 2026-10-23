"""Exercises `python -m cvsync live` end to end against a throwaway backend,
with a folder standing in for the calculator.

    python tests/live_check.py http://127.0.0.1:8767 testpw

It starts live mode, then plays both sides: edits on the web app must reach
the folder, and a save the way the app makes one (CVDATA, then a new "c..."
token in CVREV) must reach the web app. Never point it at a real backend.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import store  # noqa: E402
from cvsync.api import Api  # noqa: E402


def wait_for(cond, what, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            print("ok   " + what)
            return
        time.sleep(0.5)
    raise SystemExit("FAIL " + what)


def main(url, password):
    tmp = tempfile.mkdtemp()
    calc = os.path.join(tmp, "calc")
    os.makedirs(calc)
    env = dict(os.environ, APPDATA=os.path.join(tmp, "appdata"), CVTEST_PW=password)
    api = Api(url, os.path.join(tmp, "cookies"))
    api.login(password)
    c = api.create_calc("Live one", None)
    api.update_calc(c["id"], "Live one", None, {"locked": False, "lines": [
        {"id": "a1", "role": "input", "hidden": False, "latex": "", "varName": "x", "label": "x",
         "value": "1", "expr": ""}]})
    proc = subprocess.Popen([sys.executable, "-m", "cvsync", "live", "--server", url, "--folder", calc,
                             "--password-env", "CVTEST_PW", "--every", "0.5", "--web-every", "1"],
                            cwd=os.path.join(os.path.dirname(__file__), ".."), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    target = store.FolderTarget(calc)
    try:
        def mine(v):
            return next((x for x in v["calcs"] if x["id"] == str(c["id"])), None)

        def calc_value():
            c = mine(store.read_vault(target)[0])
            return c["lines"][0]["text"] if c else None

        wait_for(lambda: calc_value() == "1", "first sync reaches the calculator")
        wait_for(lambda: (target.read_rev() or "").startswith("p"), "PC marks its write in CVREV")

        data = api.get_calc(c["id"])["data"]
        data["lines"][0]["value"] = "2"
        api.update_calc(c["id"], "Live one", None, data)
        wait_for(lambda: calc_value() == "2", "a web edit reaches the calculator")

        v, layout = store.read_vault(target)
        mine(v)["lines"][0]["text"] = "3"
        store.write_vault(target, v, layout)
        target.write_rev("c12345")
        wait_for(lambda: api.get_calc(c["id"])["data"]["lines"][0]["value"] == "3",
                 "a calculator save reaches the web app")
    finally:
        proc.terminate()
        out = proc.communicate(timeout=10)[0]
        print("--- live output ---\n" + out)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
