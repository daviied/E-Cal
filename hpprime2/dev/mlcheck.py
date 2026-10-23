"""Check the sync tool's converter against the web app's real math path.

    python mlcheck.py cases          # writes mlcases.json next to mlcheck.html
    (open /hpprime/dev/mlcheck.html from a server at the repo root, copy the
     JSON it prints into mlresults.json)
    python mlcheck.py compare        # evaluates each case's calculator text
                                     # here and compares with math.js

Each case is a line of calculator text. It is converted to LaTeX the way the
sync tool sends it to the web app; the page runs that LaTeX through MathLive
and math.js exactly as the app does; this script evaluates the calculator
text numerically with the same variable values. Agreement means the line
computes the same number on both sides.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sync"))
from cvsync import mathconv as M  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCOPE = {"x": 2.0, "y": 3.0, "a": 5.0, "b": 7.0, "c": 11.0, "d": 13.0,
         "r": 1.5, "V": 12.0, "I": 2.0, "t": 0.7, "k": 4.0, "n": 3.0,
         "V_2ab": 6.0, "V_in": 9.0, "α_1": 0.25, "θ": 0.5}
# math.js spells Greek names out (MathLive writes 	heta as theta).
WEB_NAMES = {"θ": "theta", "α_1": "alpha_1"}
# Functions the web app cannot evaluate at all, whatever the LaTeX: math.js
# has no arcsin/arctan, which is what MathLive writes for them.
WEB_GAPS = {"atan(1)*4", "asin(0.5)"}

CASES = [
    "V*I", "V/I", "x^2+3*x", "sqrt(x)", "surd(8,3)", "abs(x-3)", "sin(x)",
    "ln(x)+log(100)", "π*r^2", "V_2ab*2", "V_in+1", "when(x>=0,x^2,-x)",
    "when(x<0,-1,when(x==0,0,1))", "det([[2,1],[1,3]])", "-x^2", "(-x)^2",
    "3!", "(a+b)/(c-d)", "e^(x+1)", "2*π", "θ+α_1", "x^-1", "a-(b-c)",
    "3*x^2*sin(x)+x^3*cos(x)", "logb(8,2)", "2.5E-7*x", "a/b/c",
    "a^b^0.5", "2^-1", "x*y/(a*b)", "1/(1+x)", "cos(x)^2+sin(x)^2",
    "exp(1)", "abs(-3)+sqrt(16)", "atan(1)*4", "x!", "-(a-b)", "2*(x+1)",
    "2.5E-7", "surd(27,3)+logb(8,2)",
    "10^3", "x^(1/3)", "asin(0.5)", "max(a,b)", "a*-b", "x/-y",
]


def ev(n, env):
    if isinstance(n, M.Num):
        return float(n.text)
    if isinstance(n, M.Sym):
        return env[n.name]
    if isinstance(n, M.Const):
        return {"pi": math.pi, "e": math.e, "inf": math.inf}[n.name]
    if isinstance(n, M.Neg):
        return -ev(n.a, env)
    if isinstance(n, M.Bin):
        a, b = ev(n.a, env), ev(n.b, env)
        return {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else math.nan,
                "^": a ** b}[n.op]
    if isinstance(n, M.Cmp):
        a, b = ev(n.a, env), ev(n.b, env)
        return float({"==": a == b, "=": a == b, "!=": a != b, "<": a < b,
                      ">": a > b, "<=": a <= b, ">=": a >= b}[n.op])
    if isinstance(n, M.Fact):
        return float(math.gamma(ev(n.a, env) + 1))
    if isinstance(n, M.When):
        return ev(n.a, env) if ev(n.c, env) else ev(n.b, env)
    if isinstance(n, M.Call):
        if n.name == "det":
            rows = [[ev(c, env) for c in r] for r in n.args[0].rows]
            return rows[0][0] * rows[1][1] - rows[0][1] * rows[1][0]
        args = [ev(a, env) for a in n.args]
        f = {"sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin,
             "acos": math.acos, "atan": math.atan, "ln": math.log, "log": math.log10,
             "exp": math.exp, "sqrt": math.sqrt, "abs": abs, "max": max, "min": min,
             "surd": lambda x, k: x ** (1.0 / k), "logb": lambda x, b: math.log(x) / math.log(b)}
        return float(f[n.name](*args))
    raise ValueError(repr(n))


def cases():
    out = []
    for i, text in enumerate(CASES):
        latex = M.prime_to_latex(text)
        scope = {WEB_NAMES.get(k, k): v for k, v in SCOPE.items()}
        out.append({"id": i, "text": text, "latex": latex, "scope": scope})
    with open(os.path.join(HERE, "mlcases.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("wrote %d cases" % len(out))


def compare(path):
    with open(path, encoding="utf-8") as f:
        results = {r["id"]: r for r in json.load(f)}
    bad = 0
    for i, text in enumerate(CASES):
        r = results[i]
        want = ev(M.parse_prime(text), SCOPE)
        got = r["value"]
        ok = isinstance(got, (int, float)) and math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-12)
        gap = not ok and text in WEB_GAPS
        bad += not ok and not gap
        print("%s %-28s %-34s ascii=%-26s web=%s here=%s%s" % (
            "ok " if ok else ("gap" if gap else "BAD"), text, r["latex"], r["ascii"], got, want,
            "  " + r["error"] if r["error"] else ""))
    print("%d cases, %d disagree" % (len(CASES), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "cases":
        cases()
    else:
        sys.exit(compare(sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "mlresults.json")))
