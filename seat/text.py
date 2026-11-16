"""Name normalization and table display helpers."""
import unicodedata


# Name separators that people type inconsistently (e.g. 阿卜杜拉·买买提); dropped from the key.
_DOTS = set("·•‧∙⋅・･.")


def normalize_name(s: str) -> str:
    """Key used for matching: NFKC; whitespace, invisible format chars and name dots removed; lower-cased."""
    s = unicodedata.normalize("NFKC", s or "")
    return "".join(
        ch for ch in s
        if not ch.isspace() and ch not in _DOTS and unicodedata.category(ch) != "Cf"
    ).lower()


def format_table(t: str) -> str:
    t = (t or "").strip()
    return f"第 {t} 桌" if t.isdigit() else t
