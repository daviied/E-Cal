"""CVSHR, the web app's shared lines as the calculator reads them.

    python -m unittest tests.test_shared
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cvsync import store, sync  # noqa: E402


def line(role, lid, **kw):
    out = {"id": lid, "role": role, "hidden": False, "latex": "", "varName": "", "label": "",
           "value": "", "expr": ""}
    out.update(kw)
    return out


TREE = {
    "globals": {"lines": [line("none", "g1", latex=r"g=9.81")]},
    "folders": [
        {"id": 7, "name": "Physics", "parent_id": None,
         "data": {"lines": [line("input", "f1", varName="m", label="mass", value="2"),
                            line("none", "f2", latex=r"F=m\cdot g")]}},
        {"id": 3, "name": "Empty", "parent_id": None, "data": {}},
    ],
    "calculators": [],
}


class SharedText(unittest.TestCase):
    def test_shape(self):
        d = store.parse_list(sync.shared_text(TREE))
        self.assertEqual(d[0], "CVSH1")
        self.assertEqual(d[1], [["g1", "0", "0", "", "", "g=9.81"]])
        # Only folders that have shared lines, by id, as strings.
        self.assertEqual([f[0] for f in d[2]], ["7"])
        self.assertEqual(d[2][0][1][0], ["f1", "1", "0", "m", "mass", "2"])
        self.assertEqual(d[2][0][1][1][5], "F=m*g")

    def test_empty(self):
        d = store.parse_list(sync.shared_text({"folders": [], "calculators": []}))
        self.assertEqual(d, ["CVSH1", [], []])

    def test_stable(self):
        # Rewritten only when it differs, so the same tree gives the same text.
        self.assertEqual(sync.shared_text(TREE), sync.shared_text(dict(TREE)))


if __name__ == "__main__":
    unittest.main()
