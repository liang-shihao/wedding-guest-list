import unittest

from seat.importer import parse_import


def row(name, table, public_note="", private_note=""):
    return {"name": name, "table": table, "public_note": public_note, "private_note": private_note}


class ImporterTest(unittest.TestCase):
    def test_tab_with_header(self):
        rows, errors = parse_import("姓名\t桌号\t备注\r\n张三\t8\t素食\r\n")
        self.assertEqual(errors, [])
        self.assertEqual(rows, [row("张三", "8", private_note="素食")])

    def test_header_mapping(self):
        rows, errors = parse_import("姓名,桌号,公开说明,内部备注\n张三,8,新郎同学,素食")
        self.assertEqual(rows, [row("张三", "8", "新郎同学", "素食")])

    def test_header_aliases_and_order(self):
        rows, _ = parse_import("桌号\t说明\t姓名\n8\t新郎同学\t张三")
        self.assertEqual(rows, [row("张三", "8", public_note="新郎同学")])

    def test_no_header_order(self):
        rows, errors = parse_import("张三\t8\t素食\t新郎同学")
        self.assertEqual(errors, [])
        self.assertEqual(rows, [row("张三", "8", "新郎同学", "素食")])

    def test_csv_quoted_comma(self):
        rows, _ = parse_import('张三,8,"素食,不吃辣"')
        self.assertEqual(rows, [row("张三", "8", private_note="素食,不吃辣")])

    def test_blank_lines_skipped(self):
        rows, errors = parse_import("张三\t8\n\n\t\t\n李四\t9\n\n")
        self.assertEqual(errors, [])
        self.assertEqual([r["name"] for r in rows], ["张三", "李四"])

    def test_errors_with_line_numbers(self):
        rows, errors = parse_import("姓名\t桌号\n\t8\n李四\t\n")
        self.assertEqual(rows, [])
        self.assertEqual(errors, ["第 2 行：姓名为空", "第 3 行：桌号为空"])

    def test_values_trimmed(self):
        rows, _ = parse_import(" 张三 \t 8 ")
        self.assertEqual(rows, [row("张三", "8")])

    def test_empty_text(self):
        rows, errors = parse_import("  \n ")
        self.assertEqual(rows, [])
        self.assertEqual(errors, ["没有可导入的数据"])


if __name__ == "__main__":
    unittest.main()
