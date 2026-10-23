"""Converting math between the web app's LaTeX and the calculator's text.

The web app stores what MathLive edits: LaTeX, which it turns into
ascii-math and evaluates with math.js. The calculator stores what a person
types on it: infix text in the HP Prime's own spelling (`sqrt(x)`, `x^2`,
`when(c,a,b)`, `[[1,2],[3,4]]`). Both sides are parsed into one small tree
and written out from it, so each direction is a parser plus a printer.

Conventions shared with the web app, so a line means the same on both:
  - `log` is base 10 and `ln` is natural (the calculator app maps `log` to
    the CAS's `log10` when it evaluates).
  - adjacent letters multiply (`ab` is a*b), and a multi-letter name only
    exists as a subscripted name (`V_{in}`, written `V_in` on the
    calculator) or as an Input line's variable name.
  - `c ? a : b` (the web's piecewise) is `when(c,a,b)` on the calculator.
"""
import re

# ---------------------------------------------------------------- the tree


class Node:
    __slots__ = ()

    def __eq__(self, other):
        return type(self) is type(other) and all(
            getattr(self, s) == getattr(other, s) for s in self.__slots__)

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__,
                           ", ".join(repr(getattr(self, s)) for s in self.__slots__))


class Num(Node):
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


class Sym(Node):
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class Const(Node):  # pi, e, i, inf
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class Bin(Node):  # + - * / ^
    __slots__ = ("op", "a", "b")

    def __init__(self, op, a, b):
        self.op, self.a, self.b = op, a, b


class Neg(Node):
    __slots__ = ("a",)

    def __init__(self, a):
        self.a = a


class Cmp(Node):  # = == != < > <= >=
    __slots__ = ("op", "a", "b")

    def __init__(self, op, a, b):
        self.op, self.a, self.b = op, a, b


class Call(Node):
    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name, self.args = name, list(args)


class Mat(Node):  # rows of cells; a plain vector is one row with vector=True
    __slots__ = ("rows", "vector")

    def __init__(self, rows, vector=False):
        self.rows, self.vector = [list(r) for r in rows], vector


class Fact(Node):
    __slots__ = ("a",)

    def __init__(self, a):
        self.a = a


class When(Node):
    __slots__ = ("c", "a", "b")

    def __init__(self, c, a, b):
        self.c, self.a, self.b = c, a, b


class ConvertError(ValueError):
    pass


GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "θ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
GREEK_BACK = {v: k for k, v in GREEK.items() if k not in ("varepsilon", "vartheta", "varphi")}

# Functions both sides know, by the name the tree uses.
FUNCS = {
    "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh",
    "asinh", "acosh", "atanh", "sec", "csc", "cot", "ln", "log", "exp",
    "sqrt", "abs", "det", "surd", "logb", "floor", "ceil", "round", "max",
    "min", "mod",
}
LATEX_FUNCS = {  # \name -> tree name
    "sin": "sin", "cos": "cos", "tan": "tan", "arcsin": "asin",
    "arccos": "acos", "arctan": "atan", "sinh": "sinh", "cosh": "cosh",
    "tanh": "tanh", "sec": "sec", "csc": "csc", "cot": "cot", "ln": "ln",
    "log": "log", "exp": "exp", "det": "det", "max": "max", "min": "min",
    "lg": "log",
}
LATEX_FUNCS_OUT = {"sin": "\\sin", "cos": "\\cos", "tan": "\\tan",
                   "asin": "\\arcsin", "acos": "\\arccos", "atan": "\\arctan",
                   "sinh": "\\sinh", "cosh": "\\cosh", "tanh": "\\tanh",
                   "sec": "\\sec", "csc": "\\csc", "cot": "\\cot",
                   "ln": "\\ln", "log": "\\log", "exp": "\\exp",
                   "det": "\\det", "max": "\\max", "min": "\\min"}
# Spellings the calculator may produce for the same functions.
PRIME_ALIASES = {"log10": "log", "√": "sqrt", "ifte": "when", "nthroot": "surd",
                 "ceiling": "ceil", "arcsin": "asin", "arccos": "acos",
                 "arctan": "atan", "ABS": "abs"}

# ======================================================= the calculator side

_PRIME_TOKEN = re.compile(r"""
    (?P<num>(?:\d+\.?\d*|\.\d+)(?:[Eeᴇ][+\-−]?\d+)?)
  | (?P<id>[A-Za-z_Ͱ-ορ-Ͽ][A-Za-z0-9_Ͱ-ορ-Ͽ]*)
  | (?P<op>:=|==|!=|<=|>=|≠|≤|≥|[-−+*×·/÷^()\[\],=<>!√π∞?:;])
  | (?P<ws>\s+)
""", re.VERBOSE)


def _prime_tokens(text):
    out, pos = [], 0
    while pos < len(text):
        m = _PRIME_TOKEN.match(text, pos)
        if not m:
            raise ConvertError("cannot read %r in %r" % (text[pos], text))
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        val = m.group(kind)
        if kind == "op":
            val = {"−": "-", "×": "*", "·": "*", "÷": "/", "≠": "!=", "≤": "<=",
                   "≥": ">=", ":=": "=", ";": ","}.get(val, val)
        if kind == "num":
            val = val.replace("ᴇ", "E").replace("e", "E").replace("−", "-")
        out.append((kind, val))
    out.append(("end", None))
    return out


class _PrimeParser:
    def __init__(self, text):
        self.toks = _prime_tokens(text)
        self.i = 0
        self.text = text

    def peek(self, k=0):
        return self.toks[self.i + k]

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def isop(self, *ops):
        t = self.peek()
        return t[0] == "op" and t[1] in ops

    def expect(self, op):
        if not self.isop(op):
            raise ConvertError("expected %r in %r" % (op, self.text))
        self.take()

    def parse(self):
        e = self.ternary()
        if self.peek()[0] != "end":
            raise ConvertError("unexpected %r in %r" % (self.peek()[1], self.text))
        return e

    def ternary(self):
        c = self.cmp()
        if self.isop("?"):
            self.take()
            a = self.ternary()
            self.expect(":")
            b = self.ternary()
            return When(c, a, b)
        return c

    def cmp(self):
        a = self.add()
        if self.isop("=", "==", "!=", "<", ">", "<=", ">="):
            op = self.take()[1]
            if op == "=" and isinstance(a, (Sym, Call)):
                return Cmp(op, a, self.ternary())
            b = self.add()
            return Cmp(op, a, b)
        return a

    def add(self):
        a = self.mul()
        while self.isop("+", "-"):
            op = self.take()[1]
            a = Bin(op, a, self.mul())
        return a

    def starts_primary(self):
        t = self.peek()
        return t[0] in ("num", "id") or (t[0] == "op" and t[1] in ("(", "[", "√", "π", "∞"))

    def mul(self):
        a = self.unary()
        while True:
            if self.isop("*", "/"):
                op = self.take()[1]
                a = Bin(op, a, self.unary())
            elif self.starts_primary():
                a = Bin("*", a, self.power())
            else:
                return a

    def unary(self):
        if self.isop("-"):
            self.take()
            return Neg(self.unary())
        if self.isop("+"):
            self.take()
            return self.unary()
        return self.power()

    def power(self):
        base = self.postfix()
        if self.isop("^"):
            self.take()
            return Bin("^", base, self.unary())
        return base

    def postfix(self):
        a = self.primary()
        while self.isop("!") and not (self.peek(1)[0] == "op" and self.peek(1)[1] == "="):
            self.take()
            a = Fact(a)
        return a

    def args(self, close):
        out = []
        if self.isop(close):
            self.take()
            return out
        while True:
            out.append(self.ternary())
            if self.isop(","):
                self.take()
                continue
            self.expect(close)
            return out

    def primary(self):
        kind, val = self.take()
        if kind == "num":
            return Num(val)
        if kind == "id":
            if self.isop("("):
                self.take()
                args = self.args(")")
                name = PRIME_ALIASES.get(val, val)
                low = name.lower()
                if low in FUNCS or low in ("when", "log10", "ifte", "integrate", "diff"):
                    name = PRIME_ALIASES.get(low, low)
                if name == "when":
                    if len(args) != 3:
                        raise ConvertError("when needs three arguments")
                    return When(*args)
                return Call(name, args)
            if val in ("pi",):
                return Const("pi")
            if val in ("e", "i"):
                return Const(val)
            if val in ("inf", "infinity"):
                return Const("inf")
            return Sym(val)
        if kind == "op":
            if val == "(":
                e = self.ternary()
                self.expect(")")
                return e
            if val == "[":
                items = self.args("]")
                if items and all(isinstance(x, Mat) and x.vector for x in items):
                    return Mat([x.rows[0] for x in items])
                return Mat([items], vector=True)
            if val == "√":
                return Call("sqrt", [self.power()])
            if val == "π":
                return Const("pi")
            if val == "∞":
                return Const("inf")
        raise ConvertError("unexpected %r in %r" % (val, self.text))


def parse_prime(text):
    return _PrimeParser(text).parse()


# precedence used by both printers
_PREC = {"when": 0, "cmp": 1, "+": 2, "-": 2, "*": 3, "/": 3, "neg": 4, "^": 5, "fact": 6, "atom": 7}


def _prec(n):
    if isinstance(n, When):
        return _PREC["when"]
    if isinstance(n, Cmp):
        return _PREC["cmp"]
    if isinstance(n, Bin):
        return _PREC[n.op]
    if isinstance(n, Neg):
        return _PREC["neg"]
    if isinstance(n, Fact):
        return _PREC["fact"]
    if isinstance(n, Num) and n.text.startswith("-"):
        return _PREC["neg"]
    return _PREC["atom"]


def to_prime(n):
    """Tree -> calculator text."""
    def wrap(child, need):
        s = to_prime(child)
        return "(" + s + ")" if _prec(child) < need else s

    if isinstance(n, Num):
        return n.text
    if isinstance(n, Sym):
        return n.name
    if isinstance(n, Const):
        return {"pi": "π", "e": "e", "i": "i", "inf": "inf"}[n.name]
    if isinstance(n, Neg):
        return "-" + wrap(n.a, _PREC["neg"] + 1 if isinstance(n.a, Neg) else _PREC["neg"])
    if isinstance(n, Bin):
        p = _PREC[n.op]
        if n.op == "^":
            return wrap(n.a, p + 1) + "^" + wrap(n.b, p if not isinstance(n.b, Neg) else p - 1)
        left = wrap(n.a, p)
        right = wrap(n.b, p + 1)
        return left + n.op + right
    if isinstance(n, Cmp):
        if n.op == "=" and isinstance(n.a, (Sym, Call)):
            return to_prime(n.a) + "=" + to_prime(n.b)
        return wrap(n.a, 2) + n.op + wrap(n.b, 2)
    if isinstance(n, Fact):
        return wrap(n.a, _PREC["atom"]) + "!"
    if isinstance(n, Call):
        return n.name + "(" + ",".join(to_prime(a) for a in n.args) + ")"
    if isinstance(n, When):
        return "when(" + to_prime(n.c) + "," + to_prime(n.a) + "," + to_prime(n.b) + ")"
    if isinstance(n, Mat):
        rows = ["[" + ",".join(to_prime(c) for c in r) + "]" for r in n.rows]
        return rows[0] if n.vector else "[" + ",".join(rows) + "]"
    raise ConvertError("cannot write %r" % (n,))


# ============================================================ the LaTeX side

_LATEX_TOKEN = re.compile(r"""
    (?P<cmd>\\[A-Za-z]+|\\[,;:!\ {}|\\%])
  | (?P<num>(?:\d+(?:\.\d*)?|\.\d+)(?:e[+\-]?\d+)?)
  | (?P<letter>[A-Za-z])
  | (?P<ws>\s+)
  | (?P<ch>.)
""", re.VERBOSE)

_SPACING = {"\\,", "\\;", "\\:", "\\!", "\\ ", "\\quad", "\\qquad", "\\displaystyle",
            "\\textstyle", "\\limits", "\\nolimits", "\\mathstrut"}


def _latex_tokens(text):
    out = []
    for m in _LATEX_TOKEN.finditer(text):
        kind = m.lastgroup
        val = m.group(kind)
        if kind == "ws" or val in _SPACING or val == "~":
            continue
        out.append((kind, val))
    out.append(("end", None))
    return out


class _LatexParser:
    def __init__(self, text):
        self.text = text
        self.toks = _latex_tokens(text)
        self.i = 0

    def peek(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def isch(self, *chs):
        t = self.peek()
        return t[0] == "ch" and t[1] in chs

    def iscmd(self, *cmds):
        t = self.peek()
        return t[0] == "cmd" and t[1] in cmds

    def expect_ch(self, ch):
        if not self.isch(ch):
            raise ConvertError("expected %r in %r" % (ch, self.text))
        self.take()

    def group_text(self):
        """Raw text of a {...} group (or one token), for names and subscripts."""
        if self.isch("{"):
            self.take()
            depth, parts = 1, []
            while True:
                kind, val = self.take()
                if kind == "end":
                    raise ConvertError("unclosed { in %r" % self.text)
                if kind == "ch" and val == "{":
                    depth += 1
                elif kind == "ch" and val == "}":
                    depth -= 1
                    if depth == 0:
                        return "".join(parts)
                if kind == "cmd" and val[1:] in GREEK:
                    parts.append(GREEK[val[1:]])
                elif kind == "cmd" and val in ("\\mathrm", "\\text", "\\mathit", "\\operatorname"):
                    continue
                elif kind == "cmd":
                    parts.append(val[1:])
                elif kind in ("letter", "num"):
                    parts.append(val)
                # anything else -- ^, an empty {} -- is not part of a name
                # (V_{c^{}} is V_c)
        if self.peek()[0] == "num":
            return self.first_digit()
        kind, val = self.take()
        if kind == "cmd" and val[1:] in GREEK:
            return GREEK[val[1:]]
        return val or ""

    def first_digit(self):
        """An unbraced argument is one character, as in TeX: \frac12 is
        1/2 and x_12 is x_1 times 2. Takes the first digit of the number
        token ahead and leaves the rest of it in place."""
        kind, val = self.toks[self.i]
        if len(val) > 1 and val[0].isdigit() and val[1].isdigit():
            self.toks[self.i] = ("num", val[1:])
            return val[0]
        self.i += 1
        return val

    def group(self):
        """A {...} argument parsed as an expression, or a single token."""
        if self.isch("{"):
            self.take()
            if self.isch("}"):
                self.take()
                return None
            e = self.ternary(("}",))
            self.expect_ch("}")
            return e
        if self.peek()[0] == "num":
            return Num(self.first_digit().replace("e", "E"))
        return self.single()

    def single(self):
        kind, val = self.take()
        if kind == "num":
            # x^23 is x^{23} as MathLive writes it, so a bare run of digits
            # after ^ is read as one number.
            return Num(val.replace("e", "E"))
        if kind == "letter":
            return self.name_from(val)
        if kind == "cmd":
            self.i -= 1
            return self.primary(())
        raise ConvertError("unexpected %r in %r" % (val, self.text))

    def parse(self):
        e = self.ternary(())
        if self.peek()[0] != "end":
            raise ConvertError("unexpected %r in %r" % (self.peek()[1], self.text))
        return e

    def at_stop(self, stops):
        t = self.peek()
        if t[0] == "end":
            return True
        if t[0] == "ch" and t[1] in stops:
            return True
        if t[0] == "cmd" and t[1] in stops:
            return True
        return False

    def ternary(self, stops):
        c = self.cmp(stops + ("?", ":"))
        if self.isch("?"):
            self.take()
            a = self.ternary(stops + (":",))
            if self.isch(":") or self.iscmd("\\colon"):
                self.take()
            else:
                raise ConvertError("missing : in %r" % self.text)
            b = self.ternary(stops)
            return When(c, a, b)
        return c

    CMP_CMDS = {"\\ge": ">=", "\\geq": ">=", "\\le": "<=", "\\leq": "<=",
                "\\ne": "!=", "\\neq": "!=", "\\gt": ">", "\\lt": "<"}

    def cmp(self, stops):
        a = self.add(stops)
        op = None
        if self.isch("=", "<", ">", "!"):
            ch = self.take()[1]
            if ch == "!" and self.isch("="):
                self.take()
                op = "!="
            elif ch in "<>" and self.isch("="):
                self.take()
                op = ch + "="
            elif ch == "=" and self.isch("="):
                self.take()
                op = "=="
            elif ch == ":" and self.isch("="):
                self.take()
                op = "="
            else:
                op = ch
        elif self.peek()[0] == "cmd" and self.peek()[1] in self.CMP_CMDS:
            op = self.CMP_CMDS[self.take()[1]]
        elif self.isch(":") and self.peek(1) == ("ch", "="):
            self.take()
            self.take()
            op = "="
        if op is None:
            return a
        if op == "=" and isinstance(a, (Sym, Call)):
            # An assignment takes everything to its right, as in math.js:
            # y=x\geq0?x^2:-x is y = (x>=0 ? x^2 : -x).
            return Cmp(op, a, self.ternary(stops))
        b = self.add(stops)
        return Cmp(op, a, b)

    def add(self, stops):
        a = self.mul(stops)
        while self.isch("+", "-") or self.iscmd("\\pm"):
            op = self.take()[1]
            if op == "\\pm":
                raise ConvertError("± has no single value")
            a = Bin(op, a, self.mul(stops))
        return a

    def starts_factor(self, stops):
        if self.at_stop(stops):
            return False
        t = self.peek()
        if t[0] in ("num", "letter"):
            return True
        if t[0] == "ch":
            return t[1] in ("(", "|", "[") and not (t[1] == "|" and "|" in stops)
        if t[0] == "cmd":
            v = t[1]
            return v not in self.CMP_CMDS and v not in (
                "\\cdot", "\\times", "\\div", "\\right", "\\end", "\\pm", "\\colon", "\\\\", "\\}")
        return False

    def mul(self, stops):
        a = self.unary(stops)
        while True:
            if self.iscmd("\\cdot", "\\times", "\\ast") or self.isch("*"):
                self.take()
                a = Bin("*", a, self.unary(stops))
            elif self.iscmd("\\div") or self.isch("/"):
                self.take()
                a = Bin("/", a, self.unary(stops))
            elif self.starts_factor(stops):
                a = Bin("*", a, self.power(stops))
            else:
                return a

    def unary(self, stops):
        if self.isch("-"):
            self.take()
            return Neg(self.unary(stops))
        if self.isch("+"):
            self.take()
            return self.unary(stops)
        return self.power(stops)

    def power(self, stops):
        base = self.postfix(stops)
        while self.isch("^"):
            self.take()
            exp = self.group()
            if exp is None:
                raise ConvertError("empty exponent in %r" % self.text)
            base = Bin("^", base, exp)
        return base

    def postfix(self, stops):
        a = self.primary(stops)
        while self.isch("!") and self.peek(1) != ("ch", "="):
            self.take()
            a = Fact(a)
        return a

    def letter_run(self, first):
        j = self.i
        word = first
        while self.toks[j][0] == "letter":
            word += self.toks[j][1]
            j += 1
        nxt = self.toks[j]
        opens = nxt == ("ch", "(") or (nxt == ("cmd", "\\left") and self.toks[j + 1] == ("ch", "("))
        name = {"arcsin": "asin", "arccos": "acos", "arctan": "atan", "nthroot": "surd"}.get(word, word)
        if len(word) > 1 and opens and name in FUNCS:
            self.i = j
            return name
        return None

    def name_from(self, letter):
        name = letter
        if self.isch("_"):
            self.take()
            sub = self.group_text().replace(" ", "")
            name = letter + "_" + sub
        return Sym(name)

    def call_args(self):
        """Arguments of a function written with ( ) or \\left( \\right)."""
        if self.iscmd("\\left"):
            self.take()
            self.expect_ch("(")
            args = self.arglist(("\\right",))
            self.take()  # \right
            self.expect_ch(")")
            return args
        self.expect_ch("(")
        args = self.arglist((")",))
        self.expect_ch(")")
        return args

    def arglist(self, stops):
        args = [self.ternary(stops + (",",))]
        while self.isch(","):
            self.take()
            args.append(self.ternary(stops + (",",)))
        return args

    def opens_paren(self):
        return self.isch("(") or (self.iscmd("\\left") and self.peek(1) == ("ch", "("))

    def func(self, name):
        # \sin^{2}x is sin(x)^2
        power = None
        if self.isch("^"):
            self.take()
            power = self.group()
        if name == "log" and self.isch("_"):
            self.take()
            base = self.group()
            arg = self.call_args()[0] if self.opens_paren() else self.power(())
            out = Call("logb", [arg, base])
        elif self.opens_paren():
            out = Call(name, self.call_args())
        else:
            # \sin x: the argument is the next factor, as MathLive reads it.
            out = Call(name, [self.power(())])
        return Bin("^", out, power) if power is not None else out

    def matrix(self, env):
        rows, row = [], []
        while True:
            if self.iscmd("\\end"):
                self.take()
                self.group_text()
                break
            cell = self.ternary(("&", "\\\\", "\\end"))
            row.append(cell)
            if self.isch("&"):
                self.take()
                continue
            if self.iscmd("\\\\"):
                self.take()
                rows.append(row)
                row = []
                continue
        if row:
            rows.append(row)
        return Mat(rows)

    def primary(self, stops):
        kind, val = self.take()
        if kind == "num":
            return Num(val.replace("e", "E"))
        if kind == "letter":
            # sin(x) typed without MathLive turning it into \sin: a run of
            # letters spelling a known function, then a parenthesis.
            word = self.letter_run(val)
            if word:
                return self.func(word)
            sym = self.name_from(val)
            # f(x): a single name followed by parentheses is a call, as
            # math.js reads MathLive's f(x).
            if self.isch("(") and not isinstance(sym, Const):
                self.take()
                args = self.arglist((")",))
                self.expect_ch(")")
                return Call(sym.name, args)
            if self.iscmd("\\left") and self.peek(1) == ("ch", "("):
                args = self.call_args()
                return Call(sym.name, args)
            if sym.name == "e":
                return Const("e")
            if sym.name == "i":
                return Const("i")
            return sym
        if kind == "ch":
            if val == "(":
                e = self.ternary((")",))
                self.expect_ch(")")
                return e
            if val == "[":
                e = self.ternary(("]",))
                self.expect_ch("]")
                return e
            if val == "|":
                e = self.ternary(("|",))
                self.expect_ch("|")
                return Call("abs", [e])
            if val == "{":
                e = self.ternary(("}",))
                self.expect_ch("}")
                return e
        if kind == "cmd":
            name = val[1:]
            if val == "\\left":
                k, v = self.take()
                if v == "(" or v == "[":
                    e = self.ternary(("\\right",))
                    self.take()
                    self.take()  # the closing bracket
                    return e
                if v == "|" or v == "\\|":
                    e = self.ternary(("\\right",))
                    self.take()
                    self.take()
                    return Call("abs", [e])
                if v == "\\{":
                    e = self.ternary(("\\right",))
                    self.take()
                    self.take()
                    return e
                if v == ".":
                    e = self.ternary(("\\right",))
                    self.take()
                    self.take()
                    return e
                raise ConvertError("unsupported \\left%s" % v)
            if val in ("\\frac", "\\dfrac", "\\tfrac", "\\cfrac"):
                a = self.group()
                b = self.group()
                if a is None or b is None:
                    raise ConvertError("empty fraction in %r" % self.text)
                return Bin("/", a, b)
            if val == "\\sqrt":
                if self.isch("["):
                    self.take()
                    n = self.ternary(("]",))
                    self.expect_ch("]")
                    return Call("surd", [self.group(), n])
                return Call("sqrt", [self.group()])
            if val == "\\pi":
                return Const("pi")
            if val in ("\\infty",):
                return Const("inf")
            if val == "\\exponentialE":
                return Const("e")
            if val == "\\imaginaryI":
                return Const("i")
            if name in GREEK:
                return self.name_from(GREEK[name])
            if name in LATEX_FUNCS:
                return self.func(LATEX_FUNCS[name])
            if val in ("\\operatorname", "\\mathrm", "\\mathit", "\\text", "\\mathbf"):
                word = self.group_text().replace(" ", "")
                if self.opens_paren() or word in FUNCS:
                    if word in ("arcsin", "arccos", "arctan"):
                        word = {"arcsin": "asin", "arccos": "acos", "arctan": "atan"}[word]
                    return self.func(word)
                if word in ("e",):
                    return Const("e")
                return Sym(word)
            if val == "\\begin":
                env = self.group_text()
                if env in ("pmatrix", "bmatrix", "matrix", "vmatrix", "Bmatrix", "smallmatrix"):
                    m = self.matrix(env)
                    return Call("det", [m]) if env == "vmatrix" else m
                if env == "cases":
                    raise ConvertError("cases do not evaluate in the web app either")
                raise ConvertError("unsupported environment %s" % env)
            if val in ("\\placeholder",):
                self.group()
                raise ConvertError("an empty box")
            if val == "\\mleft":
                self.i -= 1
                self.toks[self.i] = ("cmd", "\\left")
                return self.primary(stops)
        raise ConvertError("unexpected %r in %r" % (val, self.text))


def parse_latex(text):
    text = (text or "").replace("\\mleft", "\\left").replace("\\mright", "\\right")
    return _LatexParser(text).parse()


def _latex_name(name):
    """A name as MathLive should write it: V_2ab -> V_{2ab}."""
    def piece(s):
        if s in GREEK_BACK:
            return "\\" + GREEK_BACK[s]
        return "".join("\\" + GREEK_BACK[c] + " " if c in GREEK_BACK else c for c in s).strip()

    # MathLive has no multi-letter name except a subscripted one, so Vin
    # goes to the web app as V_{in}, which stays one variable there.
    if "_" not in name and len(name) > 1 and name not in GREEK_BACK:
        name = name[0] + "_" + name[1:]
    if "_" in name:
        head, sub = name.split("_", 1)
        if len(head) > 1 and head not in GREEK_BACK:
            head, sub = head[0], head[1:] + sub
        return piece(head) + "_{" + piece(sub.replace("_", "")) + "}"
    return piece(name)


def to_latex(n):
    """Tree -> LaTeX for MathLive."""
    def wrap(child, need):
        s = to_latex(child)
        return "\\left(" + s + "\\right)" if _prec(child) < need else s

    if isinstance(n, Num):
        t = n.text
        m = re.match(r"^(-?[\d.]+)E([+\-]?\d+)$", t)
        if m:
            return m.group(1) + "\\cdot10^{" + str(int(m.group(2))) + "}"
        return t
    if isinstance(n, Sym):
        return _latex_name(n.name)
    if isinstance(n, Const):
        return {"pi": "\\pi", "e": "e", "i": "i", "inf": "\\infty"}[n.name]
    if isinstance(n, Neg):
        return "-" + wrap(n.a, _PREC["neg"] + (1 if isinstance(n.a, Neg) else 0))
    if isinstance(n, Bin):
        if n.op == "/":
            return "\\frac{" + to_latex(n.a) + "}{" + to_latex(n.b) + "}"
        if n.op == "^":
            return wrap(n.a, _PREC["^"] + 1) + "^{" + to_latex(n.b) + "}"
        p = _PREC[n.op]
        left = wrap(n.a, p)
        right = wrap(n.b, p + 1)
        if n.op == "*":
            # 2x reads as it is written; anything else gets a visible dot
            b = n.b.a if isinstance(n.b, Bin) and n.b.op == "^" else n.b
            if isinstance(n.a, Num) and isinstance(b, (Sym, Const)) and not n.a.text.startswith("-") \
                    and "E" not in n.a.text:
                return left + right
            return left + "\\cdot " + right
        if n.op == "-" and right.startswith("-"):
            right = "\\left(" + right + "\\right)"
        return left + n.op + right
    if isinstance(n, Cmp):
        op = {"=": "=", "==": "==", "!=": "\\ne ", "<": "<", ">": ">",
              "<=": "\\le ", ">=": "\\ge "}[n.op]
        if n.op == "=" and isinstance(n.a, (Sym, Call)):
            return to_latex(n.a) + "=" + to_latex(n.b)
        return wrap(n.a, 2) + op + wrap(n.b, 2)
    if isinstance(n, Fact):
        return wrap(n.a, _PREC["atom"]) + "!"
    if isinstance(n, When):
        return wrap(n.c, 1) + "?" + wrap(n.a, 1) + ":" + wrap(n.b, 0)
    if isinstance(n, Mat):
        body = "\\\\".join("&".join(to_latex(c) for c in r) for r in n.rows)
        return "\\begin{pmatrix}" + body + "\\end{pmatrix}"
    if isinstance(n, Call):
        args = [to_latex(a) for a in n.args]
        if n.name == "sqrt" and len(args) == 1:
            return "\\sqrt{" + args[0] + "}"
        if n.name == "surd" and len(args) == 2:
            # MathLive's \sqrt[n] reaches no function math.js has; the power
            # evaluates.
            return wrap(n.args[0], _PREC["^"] + 1) + "^{\\frac{1}{" + args[1] + "}}"
        if n.name == "abs" and len(args) == 1:
            return "\\left|" + args[0] + "\\right|"
        if n.name == "logb" and len(args) == 2:
            return "\\frac{\\ln\\left(" + args[0] + "\\right)}{\\ln\\left(" + args[1] + "\\right)}"
        if n.name == "det" and len(n.args) == 1 and isinstance(n.args[0], Mat):
            return "\\det" + args[0]
        if n.name in LATEX_FUNCS_OUT:
            return LATEX_FUNCS_OUT[n.name] + "\\left(" + ",".join(args) + "\\right)"
        if len(n.name) == 1 or "_" in n.name or n.name in GREEK_BACK:
            return _latex_name(n.name) + "\\left(" + ",".join(args) + "\\right)"
        return "\\operatorname{" + n.name + "}\\left(" + ",".join(args) + "\\right)"
    raise ConvertError("cannot write %r" % (n,))


# ============================================================== entry points


def latex_to_prime(latex):
    """Web LaTeX -> calculator text. Empty stays empty."""
    if not (latex or "").strip():
        return ""
    return to_prime(parse_latex(latex))


def prime_to_latex(text):
    """Calculator text -> web LaTeX. Empty stays empty."""
    if not (text or "").strip():
        return ""
    return to_latex(parse_prime(text))


def safe_latex_to_prime(latex):
    """Like latex_to_prime, but never raises: what cannot be converted is
    passed through so it is visible (and fails to evaluate) rather than lost.
    Answers (text, error-or-None)."""
    try:
        return latex_to_prime(latex), None
    except (ConvertError, IndexError, RecursionError) as e:
        return (latex or "").replace('"', "'"), str(e)


def safe_prime_to_latex(text):
    try:
        return prime_to_latex(text), None
    except (ConvertError, IndexError, RecursionError) as e:
        return text or "", str(e)
