"""Puts a 'Showcase' calculator on a throwaway CalcVault backend, covering
the constructs the converter handles, for checking on the emulator.

    python seed_showcase.py http://127.0.0.1:8766 testpw
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sync"))
from cvsync.api import Api  # noqa: E402


def line(role, lid, **kw):
    out = {"id": lid, "role": role, "hidden": False, "latex": "", "varName": "", "label": "",
           "value": "", "expr": ""}
    out.update(kw)
    return out


LINES = [
    line("input", "s1", varName="x", label="x", value="-2"),
    line("none", "s2", latex=r"y=x\geq0?x^2:-x"),
    line("none", "s3", latex=r"\det\begin{pmatrix}2&1\\1&3\end{pmatrix}"),
    line("none", "s4", latex=r"\sqrt{16}+\left|x\right|+\log\left(1000\right)"),
    line("none", "s5", latex=r"f\left(t\right)=t^2+1"),
    line("output", "s6", label="f(3)", expr=r"f\left(3\right)"),
    line("none", "s7", latex=r"\frac{\pi}{4}"),
    line("none", "s8", latex=r"V_{in}=5"),
    line("output", "s9", label="Twice Vin", expr=r"2V_{in}"),
]

if __name__ == "__main__":
    api = Api(sys.argv[1], os.path.join(os.path.dirname(__file__), ".seed-cookies"))
    api.login(sys.argv[2])
    tree = api.tree()
    calc = next((c for c in tree["calculators"] if c["name"] == "Showcase"), None)
    if calc is None:
        folder = api.create_folder("Math", None)
        calc = api.create_calc("Showcase", folder["id"])
    api.update_calc(calc["id"], "Showcase", calc.get("folder_id"), {"locked": False, "lines": LINES})
    print("Showcase is calculator", calc["id"])
