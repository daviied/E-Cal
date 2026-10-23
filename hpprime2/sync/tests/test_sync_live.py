"""End-to-end sync against a running CalcVault backend.

Start a throwaway backend first (never your real one: this creates and
deletes folders and calculators):

    cd backend
    APP_PASSWORD=testpw SESSION_SECRET=x HTTPS_ONLY=false DB_PATH=/tmp/cvtest.db \
        python -m uvicorn app.main:app --port 8766

then

    CALCVAULT_TEST_URL=http://127.0.0.1:8766 CALCVAULT_TEST_PASSWORD=testpw \
        python -m unittest tests.test_sync_live

The calculator side is a temporary folder holding CVDATA.hpnote, which is
what the Virtual Calculator's folder looks like.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cvsync import store, sync  # noqa: E402
from cvsync.__main__ import main  # noqa: E402
from cvsync.api import Api  # noqa: E402

URL = os.environ.get("CALCVAULT_TEST_URL")
PASSWORD = os.environ.get("CALCVAULT_TEST_PASSWORD")


def line(role, lid, **kw):
    out = {"id": lid, "role": role, "hidden": False, "latex": "", "varName": "", "label": "",
           "value": "", "expr": ""}
    out.update(kw)
    return out


@unittest.skipUnless(URL and PASSWORD, "set CALCVAULT_TEST_URL and CALCVAULT_TEST_PASSWORD")
class LiveSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calc_dir = os.path.join(self.tmp, "calc")
        os.makedirs(self.calc_dir)
        os.environ["APPDATA"] = os.path.join(self.tmp, "appdata")
        os.environ["CVTEST_PW"] = PASSWORD
        self.api = Api(URL, os.path.join(self.tmp, "cookies"))
        self.api.login(PASSWORD)
        # Start from an empty server.
        tree = self.api.tree()
        for c in tree["calculators"]:
            self.api.delete_calc(c["id"])
        for f in tree["folders"]:
            try:
                self.api.delete_folder(f["id"])
            except Exception:  # noqa: BLE001 - already gone with its parent
                pass
        phys = self.api.create_folder("Physics", None)
        self.phys = phys["id"]
        ohm = self.api.create_calc("Ohm", self.phys)
        self.ohm = ohm["id"]
        self.api.update_calc(self.ohm, "Ohm", self.phys, {"locked": True, "lines": [
            line("input", "L1", varName="V", label="Voltage", value="12"),
            line("input", "L2", varName="I", label="Current", value="2"),
            line("output", "L3", label="Power", expr="V\\cdot I"),
            line("none", "L4", latex="R=\\frac{V}{I}", hidden=True),
        ]})
        quad = self.api.create_calc("Quad", None)
        self.quad = quad["id"]
        self.api.update_calc(self.quad, "Quad", None, {"locked": False, "lines": [
            line("none", "Q1", latex="a=1"),
            line("none", "Q2", latex="x=\\frac{-b+\\sqrt{b^2-4ac}}{2a}"),
        ]})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sync(self, *extra):
        rc = main(["sync", "--server", URL, "--folder", self.calc_dir, "--yes",
                   "--password-env", "CVTEST_PW"] + list(extra))
        self.assertEqual(rc, 0)
        return store.read_vault(store.FolderTarget(self.calc_dir))[0]

    def save_like_app(self, v):
        """Writes the vault the way CalcVault does: each calculator keeps its
        note, and a changed one gets a new rev."""
        target = store.FolderTarget(self.calc_dir)
        _, layout = store.read_vault(target)
        store.write_vault(target, v, layout)
        target.write_rev("c-test")

    def calc_notes(self):
        return sorted(n for n in os.listdir(self.calc_dir) if n.startswith("CVC"))

    def calc_named(self, vault, name):
        return next(c for c in vault["calcs"] if c["name"] == name)

    def test_round_trip(self):
        # 1. An empty calculator gets everything.
        v = self.sync()
        self.assertEqual([f["name"] for f in v["folders"]], ["Physics"])
        ohm = self.calc_named(v, "Ohm")
        self.assertTrue(ohm["locked"])
        self.assertEqual([ln["text"] for ln in ohm["lines"]], ["12", "2", "V*I", "R=V/I"])
        self.assertEqual(ohm["lines"][3]["hidden"], True)
        self.assertEqual(ohm["folder"], str(self.phys))
        self.assertEqual(self.calc_named(v, "Quad")["lines"][1]["text"], "x=(-b+sqrt(b^2-4*a*c))/(2*a)")

        # 2. Nothing changed: nothing to do, and the calculator text is identical.
        def snapshot():
            return {n: os.path.getmtime(os.path.join(self.calc_dir, n)) for n in os.listdir(self.calc_dir)}
        before = snapshot()
        self.sync()
        self.assertEqual(snapshot(), before)

        # 3. Edits on the calculator: a value, a new line, a new calculator in
        #    a new folder, as the app writes them (ids n1, n2, empty uids).
        ohm["lines"][0]["text"] = "24"
        ohm["lines"].append({"uid": "", "role": "2", "hidden": False, "var": "", "label": "Twice",
                             "text": "2*V^2"})
        v["folders"].append({"id": "n1", "parent": str(self.phys), "name": "Circuits"})
        v["calcs"].append({"id": "n2", "folder": "n1", "name": "Divider", "locked": False, "lines": [
            {"uid": "", "role": "0", "hidden": False, "var": "", "label": "", "text": "Vout=Vin*R2/(R1+R2)"}]})
        v["next"] = "3"
        self.save_like_app(v)
        v = self.sync()
        srv = self.api.get_calc(self.ohm)["data"]
        self.assertEqual(srv["lines"][0]["value"], "24")
        self.assertEqual(srv["lines"][2]["expr"], "V\\cdot I")  # unchanged: original LaTeX kept
        self.assertEqual(srv["lines"][3]["latex"], "R=\\frac{V}{I}")
        self.assertEqual(srv["lines"][4]["expr"], "2V^{2}")
        self.assertTrue(srv["lines"][4]["id"])
        tree = self.api.tree()
        circuits = next(f for f in tree["folders"] if f["name"] == "Circuits")
        self.assertEqual(circuits["parent_id"], self.phys)
        div = next(c for c in tree["calculators"] if c["name"] == "Divider")
        self.assertEqual(div["folder_id"], circuits["id"])
        self.assertEqual(self.api.get_calc(div["id"])["data"]["lines"][0]["latex"],
                         "V_{out}=\\frac{V_{in}\\cdot R_{2}}{R_{1}+R_{2}}")
        # The calculator now holds server ids and line ids.
        self.assertFalse(any(c["id"].startswith("n") for c in v["calcs"]))
        self.assertTrue(all(ln["uid"] for c in v["calcs"] for ln in c["lines"]))
        # and the calculator's own spelling survived
        self.assertEqual(self.calc_named(v, "Divider")["lines"][0]["text"], "Vout=Vin*R2/(R1+R2)")

        # 4. Edits on the web app reach the calculator; untouched lines keep
        #    the calculator's text.
        data = self.api.get_calc(self.quad)["data"]
        data["lines"][0]["latex"] = "a=3"
        self.api.update_calc(self.quad, "Quadratic", None, data)
        v = self.sync()
        quad = self.calc_named(v, "Quadratic")
        self.assertEqual(quad["lines"][0]["text"], "a=3")
        self.assertEqual(quad["lines"][1]["text"], "x=(-b+sqrt(b^2-4*a*c))/(2*a)")

        # 5. The same calculator changed on both sides: the web app's version
        #    stays, the calculator's becomes a copy.
        self.calc_named(v, "Quadratic")["lines"][0]["text"] = "a=99"
        self.save_like_app(v)
        data = self.api.get_calc(self.quad)["data"]
        data["lines"][0]["latex"] = "a=7"
        self.api.update_calc(self.quad, "Quadratic", None, data)
        v = self.sync()
        self.assertEqual(self.calc_named(v, "Quadratic")["lines"][0]["text"], "a=7")
        self.assertEqual(self.calc_named(v, "Quadratic (calculator copy)")["lines"][0]["text"], "a=99")
        names = sorted(c["name"] for c in self.api.tree()["calculators"])
        self.assertIn("Quadratic (calculator copy)", names)

        # 6. Deleted on the calculator -> deleted on the web app; a folder
        #    deleted on the web app -> gone from the calculator with its
        #    contents.
        v["calcs"] = [c for c in v["calcs"] if c["name"] != "Quadratic (calculator copy)"]
        self.save_like_app(v)
        self.api.delete_folder(circuits["id"])
        v = self.sync()
        names = sorted(c["name"] for c in self.api.tree()["calculators"])
        self.assertEqual(names, ["Ohm", "Quadratic"])
        self.assertEqual(sorted(c["name"] for c in v["calcs"]), ["Ohm", "Quadratic"])
        self.assertEqual([f["name"] for f in v["folders"]], ["Physics"])

    def test_dry_run_changes_nothing(self):
        main(["sync", "--server", URL, "--folder", self.calc_dir, "--dry-run",
              "--password-env", "CVTEST_PW"])
        self.assertIsNone(store.FolderTarget(self.calc_dir).read())

    def test_interrupted_sync_does_not_duplicate(self):
        v = self.sync()
        v["calcs"].append({"id": "n1", "folder": "0", "name": "New one", "locked": False, "lines": []})
        self.save_like_app(v)
        # The server step runs, then the calculator is never written.
        state_path = os.path.join(os.environ["APPDATA"], "CalcVaultSync", "state-%s.json" % v["dev"])
        import json
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
        new_vault, new_base = sync.run(v, self.api, state["base"], sync.Report())
        state["base"]["pending"] = new_base["pending"]
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        # The next sync links the calculator's n1 to what was created.
        self.sync()
        names = [c["name"] for c in self.api.tree()["calculators"]]
        self.assertEqual(names.count("New one"), 1)


if __name__ == "__main__":
    unittest.main()
