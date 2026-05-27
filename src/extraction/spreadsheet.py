from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

from src.utils.text import strip_accents


@dataclass(slots=True)
class SpreadsheetRow:
    row_number: int
    cgf: str


def load_cgfs_from_xlsx(path: Path) -> list[SpreadsheetRow]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active

    header_map: dict[str, int] = {}
    header_row_number = 0
    for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        normalized_cells = [_normalize_header(cell) for cell in row]
        if "cgf" in normalized_cells:
            header_row_number = row_number
            for index, value in enumerate(normalized_cells):
                if value:
                    header_map[value] = index
            break

    if "cgf" not in header_map:
        workbook.close()
        raise ValueError("A planilha precisa conter uma coluna chamada 'cgf'.")

    cgf_index = header_map["cgf"]
    rows: list[SpreadsheetRow] = []
    for row_number, row in enumerate(
        sheet.iter_rows(min_row=header_row_number + 1, values_only=True),
        start=header_row_number + 1,
    ):
        value = row[cgf_index] if cgf_index < len(row) else None
        digits = _normalize_cgf(value)
        if not digits:
            continue
        rows.append(SpreadsheetRow(row_number=row_number, cgf=digits))

    workbook.close()

    if not rows:
        raise ValueError("Nenhum CGF valido foi encontrado na planilha informada.")

    return rows


def _normalize_header(value: object) -> str:
    if value is None:
        return ""
    return strip_accents(str(value)).strip().lower()


def _normalize_cgf(value: object) -> str:
    if value is None:
        return ""
    text = "".join(char for char in str(value) if char.isdigit())
    return text.strip()
