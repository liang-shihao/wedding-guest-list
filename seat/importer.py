"""Parse guest rows pasted from Excel (tab separated) or CSV text."""
import csv
import io

HEADER_MAP = {
    "姓名": "name",
    "桌号": "table",
    "公开说明": "public_note",
    "说明": "public_note",
    "内部备注": "private_note",
    "备注": "private_note",
}
# Column order when there is no header row.
DEFAULT_ORDER = ("name", "table", "private_note", "public_note")


def parse_import(text: str):
    """Return (rows, errors). Any error means rows is empty (all-or-nothing)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    delimiter = "\t" if "\t" in text else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    columns = None
    rows, errors = [], []
    for cells in reader:
        line = reader.line_num
        cells = [c.strip() for c in cells]
        if not any(cells):
            continue
        if columns is None:
            if "姓名" in cells:
                columns = [HEADER_MAP.get(c) for c in cells]
                continue
            columns = list(DEFAULT_ORDER)
        g = {"name": "", "table": "", "public_note": "", "private_note": ""}
        for field, value in zip(columns, cells):
            if field and not g[field]:
                g[field] = value
        if not g["name"]:
            errors.append(f"第 {line} 行：姓名为空")
        elif not g["table"]:
            errors.append(f"第 {line} 行：桌号为空")
        else:
            rows.append(g)
    if errors:
        return [], errors
    if not rows:
        return [], ["没有可导入的数据"]
    return rows, []
