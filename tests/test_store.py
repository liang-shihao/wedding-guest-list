import os
import tempfile
import unittest

from seat.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(self.tmp.name)
        self.z1 = self.s.add_guest("张三", "8", "新郎同学", "素食")
        self.z2 = self.s.add_guest("张三", "9", "新娘同事", "")
        self.zf = self.s.add_guest("张三丰", "3")
        self.ls = self.s.add_guest("李四", "主桌")

    def tearDown(self):
        self.tmp.cleanup()

    def backups(self):
        d = os.path.join(self.tmp.name, "backups")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_exact_returns_all_same_name(self):
        r = self.s.search("张 三")
        self.assertEqual(r["mode"], "exact")
        self.assertEqual(len(r["results"]), 2)
        for item in r["results"]:
            self.assertNotIn("private_note", item)
            self.assertEqual(set(item), {"id", "name", "table", "public_note"})
        self.assertEqual({i["table"] for i in r["results"]}, {"8", "9"})

    def test_fuzzy_hides_table(self):
        r = self.s.search("三丰")
        self.assertEqual(r["mode"], "fuzzy")
        self.assertEqual(len(r["results"]), 1)
        self.assertEqual(set(r["results"][0]), {"id", "name", "public_note"})

    def test_fuzzy_needs_two_chars(self):
        r = self.s.search("丰")
        self.assertEqual(r["mode"], "none")
        self.assertEqual(r["results"], [])

    def test_fuzzy_limit_5(self):
        for i in range(7):
            self.s.add_guest(f"王小{i}", "1")
        r = self.s.search("王小")
        self.assertEqual(r["mode"], "fuzzy")
        self.assertEqual(len(r["results"]), 5)

    def test_fuzzy_escapes_like_wildcards(self):
        self.assertEqual(self.s.search("%%")["mode"], "none")
        self.assertEqual(self.s.search("__")["mode"], "none")

    def test_empty_query_raises(self):
        with self.assertRaises(ValueError):
            self.s.search("  ")

    def test_seat(self):
        self.assertEqual(self.s.seat(self.zf, "三丰"), {"name": "张三丰", "table": "3", "public_note": ""})
        self.assertIsNone(self.s.seat(9999, "三丰"))

    def test_seat_requires_matching_query(self):
        self.assertIsNone(self.s.seat(self.zf, ""))
        self.assertIsNone(self.s.seat(self.zf, "丰"))
        self.assertIsNone(self.s.seat(self.zf, "李四"))
        self.assertIsNone(self.s.seat(self.zf, "%%"))

    def test_add_requires_name_and_table(self):
        with self.assertRaises(ValueError):
            self.s.add_guest("", "1")
        with self.assertRaises(ValueError):
            self.s.add_guest("王五", " ")

    def test_update_and_delete(self):
        self.assertTrue(self.s.update_guest(self.ls, table="10", name=" 李 四 "))
        self.assertEqual(self.s.search("李四")["results"][0]["table"], "10")
        with self.assertRaises(ValueError):
            self.s.update_guest(self.ls, table="")
        self.assertFalse(self.s.update_guest(9999, table="1"))
        self.assertTrue(self.s.delete_guest(self.ls))
        self.assertEqual(len(self.backups()), 1)
        self.assertFalse(self.s.delete_guest(self.ls))

    def test_replace_all_backs_up(self):
        self.s.replace_all([{"name": "赵六", "table": "2", "public_note": "", "private_note": ""}])
        files = self.backups()
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.tmp.name, "backups", files[0]), encoding="utf-8-sig") as f:
            self.assertIn("张三丰", f.read())
        self.assertEqual([g["name"] for g in self.s.list_guests()], ["赵六"])

    def test_append(self):
        self.s.append([{"name": "赵六", "table": "2", "public_note": "", "private_note": ""}])
        self.assertEqual(len(self.s.list_guests()), 5)

    def test_backup_keeps_50(self):
        for _ in range(55):
            self.s.backup()
        self.assertEqual(len(self.backups()), 50)

    def test_export_bom(self):
        data = self.s.export_csv()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        text = data.decode("utf-8-sig")
        self.assertIn("内部备注", text.splitlines()[0])
        self.assertIn("素食", text)

    def test_duplicates_missing_note(self):
        a = self.s.add_guest("王五", "1")
        b = self.s.add_guest("王 五", "2")
        dups = self.s.duplicate_names_missing_note()
        self.assertIn(a, dups)
        self.assertIn(b, dups)
        self.assertNotIn(self.z1, dups)
        self.assertNotIn(self.zf, dups)

    def test_rekeys_stale_name_keys_on_open(self):
        import sqlite3
        c = sqlite3.connect(os.path.join(self.tmp.name, "guests.db"))
        c.execute("UPDATE guests SET name_key = 'stale' WHERE id = ?", (self.ls,))
        c.commit(); c.close()
        s2 = Store(self.tmp.name)
        self.assertEqual(s2.search("李四")["mode"], "exact")

    def test_settings_roundtrip(self):
        self.assertEqual(self.s.get_settings(), {"title": "", "date_text": "", "welcome": "", "floorplan": ""})
        self.s.set_settings(title="A & B 的婚礼", welcome="欢迎")
        st = self.s.get_settings()
        self.assertEqual(st["title"], "A & B 的婚礼")
        self.assertEqual(st["welcome"], "欢迎")


if __name__ == "__main__":
    unittest.main()
