from __future__ import annotations

"""Leitura da planilha XLSX com os CNPJs usados pela automação."""

from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

from src.utils.text import strip_accents


@dataclass(slots=True)
class SpreadsheetRow:
    """Representa uma linha válida da planilha já normalizada para processamento."""
    row_number: int
    cnpj: str


def load_cnpjs_from_xlsx(path: Path) -> list[SpreadsheetRow]:
    """Localiza a coluna `cnpj`, normaliza os valores e devolve apenas linhas válidas."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active

    header_map: dict[str, int] = {}
    header_row_number = 0
    # A busca do cabeçalho aceita acentos e variações simples de caixa.
    for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        normalized_cells = [_normalize_header(cell) for cell in row]
        if "cnpj" in normalized_cells or "cgf" in normalized_cells:
            header_row_number = row_number
            for index, value in enumerate(normalized_cells):
                if value:
                    header_map[value] = index
            break

    if "cnpj" not in header_map and "cgf" not in header_map:
        workbook.close()
        raise ValueError("A planilha precisa conter uma coluna chamada 'cnpj'.")

    document_index = header_map.get("cnpj", header_map.get("cgf"))
    rows: list[SpreadsheetRow] = []
    # Cada CNPJ é lido já sem caracteres de formatação para bater com a forma canônica usada no SIGA.
    for row_number, row in enumerate(
        sheet.iter_rows(min_row=header_row_number + 1, values_only=True),
        start=header_row_number + 1,
    ):
        value = row[document_index] if document_index is not None and document_index < len(row) else None
        digits = _normalize_document(value)
        if not digits:
            continue
        rows.append(SpreadsheetRow(row_number=row_number, cnpj=digits))

    workbook.close()

    if not rows:
        raise ValueError("Nenhum CNPJ valido foi encontrado na planilha informada.")

    return rows


def _normalize_header(value: object) -> str:
    """Remove acentos e padroniza o cabeçalho para comparação segura."""
    if value is None:
        return ""
    return strip_accents(str(value)).strip().lower()


def _normalize_document(value: object) -> str:
    if value is None:
        return ""
    text = "".join(char for char in str(value) if char.isdigit())
    # O CNPJ precisa permanecer com 14 dígitos, inclusive os zeros à esquerda.
    if not text:
        return ""
    return text.zfill(14) if len(text) <= 14 else text
