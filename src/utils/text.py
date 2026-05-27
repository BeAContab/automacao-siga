from __future__ import annotations

import re
import unicodedata


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def slugify(value: str) -> str:
    normalized = strip_accents(value).lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
