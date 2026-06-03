from __future__ import annotations

"""Utilidades pequenas de texto usadas para normalização e nomes de arquivos."""

import re
import unicodedata


def strip_accents(value: str) -> str:
    """Remove acentos para comparações que não dependem da ortografia exata."""
    normalized = unicodedata.normalize("NFD", value)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def slugify(value: str) -> str:
    """Transforma um texto livre em um identificador seguro para nome de pasta."""
    normalized = strip_accents(value).lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
