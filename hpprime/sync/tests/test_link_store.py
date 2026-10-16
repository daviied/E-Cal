import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cvsync import primelink as P  # noqa: E402
from cvsync import store  # noqa: E402


class Crc(unittest.TestCase):
    def test_reference_table_rows(self):
        # Rows of libhpcalcs' ccitt_crc16_table (prime_cmd.c), as transcribed
        # in Prime Connection Kit's tests.
        rows = {0x00: [0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7],
                0x08: [0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF],
                0xF0: [0xEF1F, 0xFF3E, 0xCF5D, 0xDF7C, 0xAF9B, 0xBFBA, 0x8FD9, 0x9FF8]}
        for start, values in rows.items():
            self.assertEqual(P._TABLE[start:start + 8], values)

    def test_xmodem_vector(self):
        self.assertEqual(P.crc16(b"123456789"), 0x31C3)


class Messages(unittest.TestCase):
    def test_names_fill_whole_words(self):
        # an odd number of characters gets a NUL so the field is 4-byte aligned
        self.assertEqual(P.name_bytes("CVC10"), "CVC10".encode("utf-16-le") + b"\x00\x00")
        self.assertEqual(P.name_bytes("CVC1"), "CVC1".encode("utf-16-le"))
        m = P.file_message(P.CMD_FILE, "CVC10", P.TYPE_NOTE, P.note_bytes("x"))
        ftype, name, content = P.parse_file_reply(m)
        self.assertEqual(name, "CVC10")

    def test_request_header(self):
        m = P.file_message(P.CMD_REQUEST_FILE, "Demo", P.TYPE_PROGRAM)
        self.assertEqual(m[0], 0xF8)
        self.assertEqual(m[1], 0x01)
        self.assertEqual(int.from_bytes(m[2:6], "big"), 4 + 8)
        self.assertEqual(m[6], P.TYPE_PROGRAM)
        self.assertEqual(m[7], 8)

    def test_file_round_trip(self):
        content = P.note_bytes("hello")
        m = P.file_message(P.CMD_FILE, "CVDATA", P.TYPE_NOTE, content)
        ftype, name, got = P.parse_file_reply(m)
        self.assertEqual((ftype, name, got), (P.TYPE_NOTE, "CVDATA", content))
        bad = bytearray(m)
        bad[12] ^= 1
        with self.assertRaises(P.LinkError):
            P.parse_file_reply(bytes(bad))

    def test_fragment_sequence_and_terminator(self):
        msg = bytes(range(256)) * 10
        pkts = P.fragment(msg, 1023)
        self.assertEqual([p[0] for p in pkts], [0, 1, 2])
        self.assertEqual(b"".join(p[1:] for p in pkts), msg)
        # A length-prefixed message filling its last report exactly gets no
        # empty terminator; a bare command does.
        exact = P.with_length(0xF7, b"x" * (1023 - 6))
        self.assertEqual(len(P.fragment(exact, 1023, padded=True)), 1)
        # unpadded (Linux, macOS): an empty report closes it, as measured on macOS
        self.assertEqual(len(P.fragment(exact, 1023, padded=False)), 2)
        self.assertEqual(len(P.fragment(b"\xff", 1023)), 1)

    def test_sequence_skips_ff(self):
        pkts = P.fragment(b"\x00" * (63 * 300), 63)
        self.assertNotIn(0xFF, [p[0] for p in pkts])
        self.assertEqual(pkts[255][0], 0)


class Notes(unittest.TestCase):
    def test_plain_note(self):
        b = "abc".encode("utf-16-le") + b"\x00\x00"
        self.assertEqual(P.note_text(b), "abc")

    def test_formatted_note_keeps_tail(self):
        new = P.note_bytes("first")
        self.assertIn("CSWD110".encode("utf-16-le"), new)
        self.assertEqual(P.note_text(new), "first")
        again = P.note_bytes("second", new)
        self.assertEqual(P.note_text(again), "second")
        self.assertTrue(again.endswith(new[new.find("CSWD".encode("utf-16-le")):]))

    def test_plain_stays_plain(self):
        plain = "x".encode("utf-16-le") + b"\x00\x00"
        self.assertEqual(P.note_bytes("yz", plain), "yz".encode("utf-16-le") + b"\x00\x00")


class FakeCalculator:
    """A hidapi device that answers like a G2: 1024-byte reports, padded to
    full size as Windows delivers them, no acknowledgement for a write."""

    def __init__(self):
        self.objects = {}
        self.inbox = bytearray()
        self.out = []

    def write(self, data):
        data = bytes(data)
        assert data[0] == 0  # report id
        self.inbox += data[2:]  # drop report id and sequence
        msg = bytes(self.inbox)
        if msg[:1] == b"\xff":
            self.inbox.clear()
            self._reply(b"\x59")
        elif len(msg) >= 6 and msg[1] == 1 and len(msg) >= 6 + int.from_bytes(msg[2:6], "big"):
            msg = msg[:6 + int.from_bytes(msg[2:6], "big")]
            self.inbox.clear()
            ftype, name, content = msg[6], msg[10:10 + msg[7]].decode("utf-16-le"), msg[10 + msg[7]:]
            if msg[0] == 0xF8:
                if (name, ftype) in self.objects:
                    self._reply(P.file_message(0xF7, name, ftype, self.objects[(name, ftype)]))
                else:
                    self._reply(b"\xf9")
            elif msg[0] == 0xF7:
                self.objects[(name, ftype)] = content
        return len(data)

    def _reply(self, msg):
        for p in P.fragment(msg, 1023):
            self.out.append(p + b"\x00" * (1024 - len(p)))

    def read(self, n, timeout=0):
        return list(self.out.pop(0)) if self.out else []

    def close(self):
        pass


class Link(unittest.TestCase):
    def link(self, fake):
        link = P.PrimeLink.__new__(P.PrimeLink)
        link.dev, link.report, link.log = fake, 1024, (lambda *_: None)
        link.WRITE_ACK_WINDOW = 0.05
        link.REOPEN_AFTER_WRITE = False
        link.GET_ATTEMPTS = 2
        link.FIRST_REPLY = 0.2
        link.REPLY_TIMEOUT = 0.2
        return link

    def test_ready_and_notes(self):
        fake = FakeCalculator()
        link = self.link(fake)
        self.assertTrue(link.check_ready())
        self.assertIsNone(link.get_note("CVDATA"))
        big = '{"CVDB1","","1",{},{' + ",".join('{"%d","0","calc %d","0",{}}' % (i, i) for i in range(300)) + "}}"
        link.put_note("CVDATA", big)
        self.assertEqual(link.get_note("CVDATA"), big)
        link.put_note("CVDATA", "short")
        self.assertEqual(link.get_note("CVDATA"), "short")


class Store(unittest.TestCase):
    def test_round_trip(self):
        v = {"dev": "d1", "next": "4",
             "folders": [{"id": "3", "parent": "0", "name": 'say "hi"'}],
             "calcs": [{"id": "n1", "folder": "3", "name": "Ohm", "locked": True,
                        "lines": [{"uid": "u", "role": "1", "hidden": False, "var": "V",
                                   "label": "Volts", "text": "12"}]}]}
        text = store.vault_to_text(v)
        back = store.vault_from_text(text)
        v["folders"][0]["name"] = "say 'hi'"
        self.assertEqual(back, v)

    def test_decimal_comma_and_numbers(self):
        # STRING() on a calculator set to a decimal comma separates with ;
        self.assertEqual(store.parse_list('{"a";{"b";2};−3}'), ["a", ["b", "2"], "-3"])

    def test_empty_and_bad(self):
        self.assertEqual(store.vault_from_text(None)["calcs"], [])
        with self.assertRaises(store.StoreError):
            store.vault_from_text('{"other"}')

    def test_what_the_emulator_wrote(self):
        # Copied from CVDATA.hpnote after a session in the Virtual Calculator.
        text = ('{"CVDB1","","2",{},{{"n1","0","UntitlOhm law","1",{{"","1","0","V","Voltage","24"},'
                '{"","1","0","I","Current"," 2"},{"","2","0","","Power"," V*I"},'
                '{"","0","0","","","R=V/I"},{"","0","0","","","1/I"}}}}} ')
        v = store.vault_from_text(text)
        self.assertEqual(v["calcs"][0]["lines"][2]["text"], " V*I")
        self.assertTrue(v["calcs"][0]["locked"])


class CountingFolder(store.FolderTarget):
    """A folder target that counts what is read and written."""

    def __init__(self, folder):
        super().__init__(folder)
        self.reads, self.writes = [], []

    def read(self, name=store.NOTE):
        self.reads.append(name)
        return super().read(name)

    def write(self, text, name=store.NOTE, new=False):
        self.writes.append(name)
        return super().write(text, name, new)


def line(uid, text, role="0"):
    return {"uid": uid, "role": role, "hidden": False, "var": "", "label": "", "text": text}


class SplitLayout(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def vault(self):
        return {"dev": "d", "next": "3", "folders": [{"id": "7", "parent": "0", "name": "F"}],
                "calcs": [{"id": "1", "folder": "7", "name": "A", "locked": False, "lines": [line("a", "x=1")]},
                          {"id": "n2", "folder": "0", "name": "B", "locked": True, "lines": [line("b", "y=2")]}]}

    def test_round_trip_and_notes(self):
        t = CountingFolder(self.dir)
        empty, layout = store.read_vault(t)
        cache = store.write_vault(t, self.vault(), layout)
        self.assertEqual(sorted(n for n in os.listdir(self.dir)), ["CVC1.hpnote", "CVC2.hpnote", "CVDATA.hpnote"])
        back, layout = store.read_vault(t)
        self.assertEqual(back, self.vault())
        self.assertEqual(layout["slot"], {"1": "1", "n2": "2"})
        self.assertEqual(set(cache), {"1", "2"})

    def test_only_changed_calculators_move(self):
        t = CountingFolder(self.dir)
        cache = store.write_vault(t, self.vault(), store.read_vault(t)[1])
        t.reads.clear()
        v, layout = store.read_vault(t, cache)
        self.assertNotIn("CVC1", t.reads)                  # known from the cache
        t.writes.clear()
        v["calcs"][1]["lines"][0]["text"] = "y=3"
        store.write_vault(t, v, layout)
        self.assertEqual(t.writes, ["CVC2", "CVDATA"])     # A is not sent again

    def test_slot_survives_new_id(self):
        t = CountingFolder(self.dir)
        store.write_vault(t, self.vault(), store.read_vault(t)[1])
        v, layout = store.read_vault(t)
        v["calcs"][1]["id"] = "126"                        # the sync gave n2 the web app's id
        t.writes.clear()
        store.write_vault(t, v, layout, {"1": "1", "126": "2"})
        self.assertEqual(t.writes, ["CVDATA"])
        self.assertEqual(store.read_vault(t)[1]["slot"], {"1": "1", "126": "2"})

    def test_old_single_note_is_read_and_converted(self):
        t = CountingFolder(self.dir)
        t.write(store.vault_to_text(self.vault()))
        v, layout = store.read_vault(t)
        self.assertEqual(layout["format"], 1)
        self.assertEqual(v, self.vault())
        store.write_vault(t, v, layout)
        v2, layout2 = store.read_vault(t)
        self.assertEqual((layout2["format"], v2), (2, self.vault()))

    def test_missing_calculator_note_is_an_error(self):
        t = CountingFolder(self.dir)
        store.write_vault(t, self.vault(), store.read_vault(t)[1])
        os.remove(os.path.join(self.dir, "CVC2.hpnote"))
        with self.assertRaises(store.StoreError):
            store.read_vault(t)

    def test_resend_when_read_back_differs(self):
        t = CountingFolder(self.dir)
        real_write = store.FolderTarget.write
        calls = {"n": 0}

        def flaky(self_, text, name=store.NOTE, new=False):
            calls["n"] += 1
            real_write(self_, text[:-3] if calls["n"] == 1 else text, name, new)   # first send arrives cut short
        t.write = flaky.__get__(t)
        self.assertEqual(store.write_verified(t, "CVC9", '{{"a","0","0","","","x"}}'), 2)


if __name__ == "__main__":
    unittest.main()
