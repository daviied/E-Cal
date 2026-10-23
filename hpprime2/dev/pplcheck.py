"""Run CALCVAULT2.txt's pure functions in hp-prime-kit's PC interpreter.

The interpreter does not read forward declarations (`cvLoad();` at the top
of the file), which the calculator needs, so they are stripped from a copy
before it is loaded. Everything that draws, asks or touches the CAS is left
in place: the interpreter only objects to it if a call reaches it.

    python pplcheck.py            # runs the checks below, exits 1 on a mismatch
"""
import os
import re
import sys

HPK = os.environ.get("HPK", r"C:\Users\nyg4\ref\hpk")
sys.path.insert(0, HPK)
from hpkit import interp  # noqa: E402

# Stand-ins for string and list commands the interpreter does not cover.
# Their calculator behaviour was checked on the emulator (probe 4: REPLACE
# with CHAR(34), UPPER, POS on a list of strings).
interp.BUILTINS.setdefault("REPLACE", lambda m, a: a[0].replace(a[1], a[2]))
interp.BUILTINS.setdefault("UPPER", lambda m, a: a[0].upper())
interp.BUILTINS.setdefault("LOWER", lambda m, a: a[0].lower())
interp.BUILTINS.setdefault("RIGHT", interp.BUILTINS.get("RIGHT"))
interp.BUILTINS.setdefault("CHAR", lambda m, a: chr(int(a[0])))
interp.BUILTINS.setdefault(
    "POS", lambda m, a: float(next((i + 1 for i, v in enumerate(a[0]) if v == a[1]), 0)))

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "calc", "CALCVAULT2.txt")


def machine():
    with open(SRC, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r"(?m)^cv\w+\([^)]*\);\s*$", "", text)
    # File-scope LOCALs (private globals) are not read either; as exported
    # globals they behave the same for these checks.
    text = re.sub(r"(?m)^LOCAL (\w+ :=[^;]*;)", r"EXPORT \1", text)
    m = interp.Machine()
    m.load(text, "CALCVAULT2.txt")
    return m


def evaluate(m, expr):
    p = interp.Parser(interp.lex(expr), "<check>")
    return m.evaluate(p.expr(), {})


CHECKS = [
    ('cvSplit("a = 5*b")', [1, "a", "", "5*b"]),
    ('cvSplit("f(x, y)=x^2+y")', [2, "f", "x,y", "x^2+y"]),
    ('cvSplit("x>=3")', [0, "", "", "x>=3"]),
    ('cvSplit("a:=2")', [1, "a", "", "2"]),
    ('cvSplit("x^2=4")', [0, "", "", "x^2=4"]),
    ('cvSplit("a==b")', [0, "", "", "a==b"]),
    ('cvSplit("V_2ab=3")', [1, "V_2ab", "", "3"]),
    ('cvMangle("V*I+2E5+log(x)+sin(θ)+π*r", {"V","I"})',
     "zcvV*zcvI+2E5+log10(zcsx)+sin(zcsθ)+π*zcsr"),
    ('cvMangle("f(3)+x_2b", {"f"})', "zcvf(3)+zcsxZqZ2b"),
    ('cvMangle("X_1*2+V_s", {"X_1","V_s"})', "zcvXZqZ1*2+zcvVZqZs"),
    ('cvClean("zcvXZqZ1+zcsy")', "X_1+y"),
    ('cvGuessVar("x_1^2")', "x_1"),
    ('cvHead("abc", 0)', ""),
    ('cvHead("abc", 2)', "ab"),
    ('cvHead("", 3)', ""),
    ('cvTail("abc", 4)', ""),
    ('cvTail("abc", 2)', "bc"),
    ('cvKeyText(16, 0, 0)', "_"),
    ('cvKeyText(42, 0, 0)', "1"),
    ('cvKeyText(21, 0, 1)', "asin("),
    ('cvKeyText(14, 1, 0)', "A"),
    ('cvKeyText(43, 2, 0)', "z"),
    ('cvKeyText(49, 0, 1)', "_"),
    ('cvKbText("sin")', "sin("),
    ('cvKbText("≥")', ">="),
    ('cvKbText("q")', "q"),
    ('cvNumStr(0)', "0"),
    ('cvNumStr(127)', "127"),
    ('cvStrNum("127")', 127),
    ('cvStrNum("n5")', 0),
    ('cvMangle("2x+LOG(100)+e^i", {})', "2*zcsx+log10(100)+e^i"),
    ('cvMangle("(a+b)c+2π", {"a"})', "(zcva+zcsb)*zcsc+2*π"),
    ('cvMangle("1.5E-3*a", {"a"})', "1.5E-3*zcva"),
    ('cvMangle("when(x>=0,x^2,-x)", {})', "when(zcsx>=0,zcsx^2,-zcsx)"),
    ('cvGuessVar("3*sin(t)+k")', "t"),
    ('cvGuessVar("42")', "x"),
    ('cvTrim("  ab c ")', "ab c"),
    ('cvIsIdent("V_2ab")', 1),
    ('cvIsIdent("2a")', 0),
    ('cvIsIdent("_a")', 0),
    ('cvClean("zcva+zcsb")', "a+b"),
    ('cvTidy("12.0")', "12"),
    ('cvTidy("[[2.0,4.5],[6.0,8.0]]")', "[[2,4.5],[6,8]]"),
    ('cvTidy("10.05")', "10.05"),
    ('cvTidy("0.5")', "0.5"),
    ('cvTidy("3.0+y")', "3+y"),
    ('cvTidy("2.0*x^3.0")', "2*x^3"),
    ('cvTidy("1.05E-7")', "1.05E-7"),
    ('cvTidy("x.0")', "x.0"),
    ('cvSanitize("say \\"hi\\"")', None),
    ('cvRemoveAt({1,2,3}, 2)', [1, 3]),
    ('cvInsertAt({1,3}, 2, {9})', [1, [9], 3]),
    ('cvInsertAt({1,3}, 3, 4)', [1, 3, 4]),
    ('cvNames({{"", "1", "0", "V", "Volts", "5"}, {"", "0", "0", "", "", "f(x)=x^2"}, {"", "0", "0", "", "", "a=2"}, {"", "2", "0", "", "P", "V*a"}})',
     ["V", "f", "a"]),
    # CalcVault 2
    ('cvSetVal("kb=1;nap=0;follow=1;open=42;", "open")', "42"),
    ('cvSetVal("kb=1;nap=0;follow=1;open=;", "open")', ""),
    ('cvSetVal("kb=0", "open")', ""),
    ('cvSetVal("kb=0;open=n3", "open")', "n3"),
    ('cvJoin({{1,2}}, {{3,4},{5,6}})', [[1, 2], [3, 4], [5, 6]]),
    ('cvJoin({}, {{3,4}})', [[3, 4]]),
    ('cvJoin({{1,2}}, {})', [[1, 2]]),
]


def norm(v):
    if isinstance(v, (list, tuple)):
        return [norm(x) for x in v]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if hasattr(v, "items") and not isinstance(v, str):
        return [norm(x) for x in v.items]
    return v


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    m = machine()
    bad = 0
    for call, want in CHECKS:
        if want is None:
            continue
        try:
            got = norm(evaluate(m, call))
        except Exception as e:  # noqa: BLE001
            got = "RAISED " + str(e)
        ok = got == want
        bad += not ok
        print(("ok  " if ok else "BAD ") + call + " -> " + repr(got) + ("" if ok else "   want " + repr(want)))
    print("%d checks, %d failed" % (len([c for c in CHECKS if c[1] is not None]), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
