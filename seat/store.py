"""SQLite-backed guest list and settings."""
import csv
import io
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

from .text import normalize_name

SETTING_KEYS = ("title", "date_text", "welcome", "floorplan")
GUEST_FIELDS = ("name", "table", "public_note", "private_note")
FUZZY_LIMIT = 5
BACKUP_KEEP = 50

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guests (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    table_no TEXT NOT NULL,
    public_note TEXT NOT NULL DEFAULT '',
    private_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS guests_name_key ON guests(name_key);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _clean(row: dict) -> dict:
    """Trim fields and validate required ones. Raises ValueError."""
    out = {k: str(row.get(k) or "").strip() for k in GUEST_FIELDS}
    if not normalize_name(out["name"]):
        raise ValueError("姓名不能为空")
    if not out["table"]:
        raise ValueError("桌号不能为空")
    return out


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Store:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.backup_dir = os.path.join(data_dir, "backups")
        os.makedirs(data_dir, exist_ok=True)
        self.db_path = os.path.join(data_dir, "guests.db")
        self._backup_lock = threading.Lock()
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(_SCHEMA)
            # Recompute match keys in case normalize_name changed between versions.
            for r in c.execute("SELECT id, name, name_key FROM guests").fetchall():
                key = normalize_name(r["name"])
                if key != r["name_key"]:
                    c.execute("UPDATE guests SET name_key = ? WHERE id = ?", (key, r["id"]))

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ---- public queries -------------------------------------------------
    def search(self, q: str) -> dict:
        key = normalize_name(q)
        if not key:
            raise ValueError("请输入姓名")
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, name, table_no, public_note FROM guests WHERE name_key = ? ORDER BY id",
                (key,),
            ).fetchall()
            if rows:
                return {
                    "mode": "exact",
                    "results": [
                        {"id": r["id"], "name": r["name"], "table": r["table_no"], "public_note": r["public_note"]}
                        for r in rows
                    ],
                }
            if len(key) < 2:
                return {"mode": "none", "results": []}
            rows = c.execute(
                "SELECT id, name, public_note FROM guests WHERE name_key LIKE ? ESCAPE '\\' ORDER BY id LIMIT ?",
                ("%" + _escape_like(key) + "%", FUZZY_LIMIT),
            ).fetchall()
        if not rows:
            return {"mode": "none", "results": []}
        return {
            "mode": "fuzzy",
            "results": [{"id": r["id"], "name": r["name"], "public_note": r["public_note"]} for r in rows],
        }

    def seat(self, guest_id: int, q: str):
        """Seat for a fuzzy candidate. Requires the same query that produced it,
        so ids cannot be enumerated to dump the list."""
        key = normalize_name(q)
        if len(key) < 2:
            return None
        with self._conn() as c:
            r = c.execute(
                "SELECT name, table_no, public_note FROM guests WHERE id = ? AND name_key LIKE ? ESCAPE '\\'",
                (guest_id, "%" + _escape_like(key) + "%"),
            ).fetchone()
        if r is None:
            return None
        return {"name": r["name"], "table": r["table_no"], "public_note": r["public_note"]}

    # ---- admin ------------------------------------------------------------
    def list_guests(self) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, name, table_no, public_note, private_note FROM guests ORDER BY id"
            ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "table": r["table_no"],
             "public_note": r["public_note"], "private_note": r["private_note"]}
            for r in rows
        ]

    @staticmethod
    def _insert(c, g: dict) -> int:
        cur = c.execute(
            "INSERT INTO guests (name, name_key, table_no, public_note, private_note) VALUES (?, ?, ?, ?, ?)",
            (g["name"], normalize_name(g["name"]), g["table"], g["public_note"], g["private_note"]),
        )
        return cur.lastrowid

    def add_guest(self, name, table, public_note="", private_note="") -> int:
        g = _clean({"name": name, "table": table, "public_note": public_note, "private_note": private_note})
        with self._conn() as c:
            return self._insert(c, g)

    def update_guest(self, guest_id: int, **fields) -> bool:
        unknown = set(fields) - set(GUEST_FIELDS)
        if unknown:
            raise ValueError("未知字段: " + ", ".join(sorted(unknown)))
        with self._conn() as c:
            r = c.execute(
                "SELECT name, table_no, public_note, private_note FROM guests WHERE id = ?", (guest_id,)
            ).fetchone()
            if r is None:
                return False
            current = {"name": r["name"], "table": r["table_no"],
                       "public_note": r["public_note"], "private_note": r["private_note"]}
            current.update(fields)
            g = _clean(current)
            c.execute(
                "UPDATE guests SET name=?, name_key=?, table_no=?, public_note=?, private_note=? WHERE id=?",
                (g["name"], normalize_name(g["name"]), g["table"], g["public_note"], g["private_note"], guest_id),
            )
        return True

    def delete_guest(self, guest_id: int) -> bool:
        with self._conn() as c:
            if c.execute("SELECT 1 FROM guests WHERE id = ?", (guest_id,)).fetchone() is None:
                return False
        self.backup()
        with self._conn() as c:
            return c.execute("DELETE FROM guests WHERE id = ?", (guest_id,)).rowcount > 0

    def replace_all(self, rows: list) -> int:
        cleaned = [_clean(r) for r in rows]
        self.backup()
        with self._conn() as c:
            c.execute("DELETE FROM guests")
            for g in cleaned:
                self._insert(c, g)
        return len(cleaned)

    def append(self, rows: list) -> int:
        cleaned = [_clean(r) for r in rows]
        with self._conn() as c:
            for g in cleaned:
                self._insert(c, g)
        return len(cleaned)

    def duplicate_names_missing_note(self) -> set:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id FROM guests WHERE public_note = '' AND name_key IN "
                "(SELECT name_key FROM guests GROUP BY name_key HAVING COUNT(*) >= 2)"
            ).fetchall()
        return {r["id"] for r in rows}

    # ---- csv ----------------------------------------------------------------
    def export_csv(self) -> bytes:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["姓名", "桌号", "公开说明", "内部备注"])
        for g in self.list_guests():
            w.writerow([g["name"], g["table"], g["public_note"], g["private_note"]])
        return ("﻿" + buf.getvalue()).encode("utf-8")

    def backup(self) -> str:
        with self._backup_lock:
            os.makedirs(self.backup_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = os.path.join(self.backup_dir, f"guests-{stamp}.csv")
            n = 1
            while os.path.exists(path):
                path = os.path.join(self.backup_dir, f"guests-{stamp}-{n}.csv")
                n += 1
            with open(path, "wb") as f:
                f.write(self.export_csv())
            self._prune_backups()
            return path

    def _prune_backups(self):
        entries = []
        for name in os.listdir(self.backup_dir):
            if name.startswith("guests-") and name.endswith(".csv"):
                p = os.path.join(self.backup_dir, name)
                entries.append((os.stat(p).st_mtime_ns, name, p))
        entries.sort()
        for _, _, p in entries[:-BACKUP_KEEP]:
            os.remove(p)

    # ---- settings -------------------------------------------------------------
    def get_settings(self) -> dict:
        out = {k: "" for k in SETTING_KEYS}
        with self._conn() as c:
            for r in c.execute("SELECT key, value FROM settings"):
                if r["key"] in out:
                    out[r["key"]] = r["value"]
        return out

    def set_settings(self, **kv) -> None:
        unknown = set(kv) - set(SETTING_KEYS)
        if unknown:
            raise ValueError("未知设置: " + ", ".join(sorted(unknown)))
        with self._conn() as c:
            for k, v in kv.items():
                c.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, str(v if v is not None else "").strip()),
                )
