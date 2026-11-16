"""Name normalization and table display helpers."""
import unicodedata


def normalize_name(s: str) -> str:
    """Key used for matching: NFKC, all whitespace removed, lower-cased."""
    s = unicodedata.normalize("NFKC", s or "")
    return "".join(ch for ch in s if not ch.isspace()).lower()


def format_table(t: str) -> str:
    t = (t or "").strip()
    return f"第 {t} 桌" if t.isdigit() else t
