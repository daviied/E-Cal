import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cvsync.mathconv import (  # noqa: E402
    ConvertError, latex_to_prime, parse_latex, parse_prime, prime_to_latex,
    safe_latex_to_prime)

# LaTeX as MathLive writes it in the web app -> what the calculator stores.
LATEX_TO_PRIME = [
    ("a=5", "a=5"),
    ("b=a\\cdot2", "b=a*2"),
    ("2x+1", "2*x+1"),
    ("ab", "a*b"),
    ("\\frac{V}{I}", "V/I"),
    ("\\frac{a+b}{c-d}", "(a+b)/(c-d)"),
    ("x^2", "x^2"),
    ("x^{2}+3x", "x^2+3*x"),
    ("x^{-1}", "x^-1"),
    ("e^{x+1}", "e^(x+1)"),
    ("\\sqrt{x}", "sqrt(x)"),
    ("\\sqrt[3]{8}", "surd(8,3)"),
    ("\\left|x-3\\right|", "abs(x-3)"),
    ("|x|", "abs(x)"),
    ("\\sin\\left(x\\right)", "sin(x)"),
    ("\\sin x", "sin(x)"),
    ("\\sin^{2}\\left(x\\right)", "sin(x)^2"),
    ("\\ln\\left(x\\right)+\\log\\left(100\\right)", "ln(x)+log(100)"),
    ("\\log_{2}\\left(8\\right)", "logb(8,2)"),
    ("\\pi r^2", "π*r^2"),
    ("2\\pi", "2*π"),
    ("V_{2ab4s}", "V_2ab4s"),
    ("V_2+1", "V_2+1"),
    ("\\theta+\\alpha_{1}", "θ+α_1"),
    ("x\\geq0?x^2:-x", "when(x>=0,x^2,-x)"),
    ("x<0?-1:(x==0?0:1)", "when(x<0,-1,when(x==0,0,1))"),
    ("y=x\\geq0?x^2:-x","y=when(x>=0,x^2,-x)"),
    ("a=b=c", "a=b=c"),
    ("\\det\\begin{pmatrix}2&1\\\\1&3\\end{pmatrix}", "det([[2,1],[1,3]])"),
    ("\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}\\cdot2", "[[1,2],[3,4]]*2"),
    ("f\\left(x\\right)=x^2", "f(x)=x^2"),
    ("f(3)", "f(3)"),
    ("-x^2", "-x^2"),
    ("\\left(-x\\right)^2", "(-x)^2"),
    ("3!", "3!"),
    ("a\\ne b", "a!=b"),
    ("1.5\\times10^{3}", "1.5*10^3"),
    ("\\frac{1}{2}\\div4", "1/2/4"),
    ("a-\\left(b-c\\right)", "a-(b-c)"),
    ("\\operatorname{abs}\\left(x\\right)", "abs(x)"),
    ("\\mathrm{Vin}", "Vin"),
    ("\\exp\\left(2\\right)", "exp(2)"),
    ("\\exponentialE^{2}", "e^2"),
    ("\\infty", "inf"),
    # TeX shorthand found in real data: unbraced one-character arguments
    ("E=\\frac12\\cdot LI^2", "E=1/2*L*I^2"),
    ("R_1=\\frac{1}{\\frac17+\\frac13}+3.9", "R_1=1/(1/7+1/3)+3.9"),
    ("\\frac123", "1/2*3"),
    ("x^23", "x^2*3"),
    ("E=\\frac12\\cdot\\left(330\\cdot10^{-9}\\right)\\cdot V_{c^{}}^2", "E=1/2*(330*10^-9)*V_c^2"),
    # typed in the web app without MathLive's shortcuts kicking in
    ("sqrt\\left(x\\right)", "sqrt(x)"),
    ("sin\\left(x\\right)+ln(x)", "sin(x)+ln(x)"),
    ("abs\\left(x\\right)", "abs(x)"),
    ("2.5e-7", "2.5E-7"),
    ("x>=0?x^2:-x", "when(x>=0,x^2,-x)"),
    ("x!=y", "x!=y"),
    ("\\frac{1}{\\left(1+x\\right)}", "1/(1+x)"),
    ("a\\cdot\\frac{b}{c}", "a*(b/c)"),
    ("", ""),
]

# Calculator text -> LaTeX, and back to the same calculator text.
PRIME_ROUND_TRIP = [
    "a=5", "V*I", "R=V/I", "x^2+3*x", "sqrt(x)", "abs(x-3)",
    "sin(x)", "ln(x)+log(100)", "π*r^2", "V_2ab4s", "when(x>=0,x^2,-x)",
    "det([[2,1],[1,3]])", "f(x)=x^2", "y=when(x>=0,x^2,-x)", "x+1=y", "-x^2", "(-x)^2", "3!", "a!=b",
    "(a+b)/(c-d)", "e^(x+1)", "2*π", "θ+α_1", "x^-1", "a-(b-c)", "1/I",
    "3*x^2*sin(x)+x^3*cos(x)", "V_in*2",
]


class LatexToPrime(unittest.TestCase):
    def test_table(self):
        for latex, want in LATEX_TO_PRIME:
            with self.subTest(latex=latex):
                self.assertEqual(latex_to_prime(latex), want)

    def test_cases_refused(self):
        with self.assertRaises(ConvertError):
            latex_to_prime("\\begin{cases}1&x>0\\\\0&x\\le0\\end{cases}")

    def test_safe_passes_through(self):
        text, err = safe_latex_to_prime("\\begin{cases}1\\end{cases}")
        self.assertIsNotNone(err)
        self.assertIn("cases", text)


class PrimeRoundTrip(unittest.TestCase):
    def test_round_trip(self):
        for text in PRIME_ROUND_TRIP:
            with self.subTest(text=text):
                latex = prime_to_latex(text)
                self.assertEqual(parse_latex(latex), parse_prime(text), latex)

    def test_calculator_spellings(self):
        # What the calculator's own keys and CAS write.
        self.assertEqual(parse_prime("√(x)"), parse_prime("sqrt(x)"))
        self.assertEqual(parse_prime("2−3"), parse_prime("2-3"))
        self.assertEqual(parse_prime("2.5ᴇ−7"), parse_prime("2.5E-7"))
        self.assertEqual(parse_prime("LOG(x)"), parse_prime("log(x)"))
        self.assertEqual(parse_prime("log10(x)"), parse_prime("log(x)"))
        self.assertEqual(parse_prime("IFTE(x>0,1,2)"), parse_prime("when(x>0,1,2)"))
        self.assertEqual(parse_prime("a:=2"), parse_prime("a=2"))
        self.assertEqual(parse_prime("x≥2"), parse_prime("x>=2"))
        self.assertEqual(parse_prime("2x"), parse_prime("2*x"))

    def test_equivalent_not_identical(self):
        # Forms the web app can evaluate, where its own spelling cannot.
        self.assertEqual(latex_to_prime(prime_to_latex("surd(8,3)")), "8^(1/3)")
        self.assertEqual(latex_to_prime(prime_to_latex("logb(8,2)")), "ln(8)/ln(2)")
        # Multi-letter names become subscripted ones.
        self.assertEqual(latex_to_prime(prime_to_latex("Vin*2")), "V_in*2")
        # A vector goes to the web as a one-row matrix, which is what
        # MathLive can show; scientific notation goes as a power of ten.
        self.assertEqual(latex_to_prime(prime_to_latex("[1,2]")), "[[1,2]]")
        self.assertEqual(latex_to_prime(prime_to_latex("2.5E-7*x")), "2.5*10^-7*x")

    def test_latex_shapes(self):
        self.assertEqual(prime_to_latex("V/I"), "\\frac{V}{I}")
        self.assertEqual(prime_to_latex("2*x"), "2x")
        self.assertEqual(prime_to_latex("V_2ab"), "V_{2ab}")
        self.assertEqual(prime_to_latex("abs(x)"), "\\left|x\\right|")
        self.assertEqual(prime_to_latex("x>=0"), "x\\ge 0")


if __name__ == "__main__":
    unittest.main()
