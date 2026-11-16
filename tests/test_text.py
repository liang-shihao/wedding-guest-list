import unittest
from seat.text import normalize_name, format_table


class TextTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_name("  张 三 "), "张三")
        self.assertEqual(normalize_name("张\u3000三"), "张三")
        self.assertEqual(normalize_name("Ｔｏｍ Lee"), "tomlee")
        self.assertEqual(normalize_name("   "), "")

    def test_normalize_invisible_and_dots(self):
        self.assertEqual(normalize_name("​张三﻿"), "张三")
        base = normalize_name("阿卜杜拉·买买提")
        for dot in ("•", "・", "･", "‧", "."):
            self.assertEqual(normalize_name("阿卜杜拉" + dot + "买买提"), base)
        self.assertEqual(base, normalize_name("阿卜杜拉买买提"))

    def test_format_table(self):
        self.assertEqual(format_table("8"), "第 8 桌")
        self.assertEqual(format_table(" 12 "), "第 12 桌")
        self.assertEqual(format_table("主桌"), "主桌")
        self.assertEqual(format_table("A3"), "A3")


if __name__ == "__main__":
    unittest.main()
