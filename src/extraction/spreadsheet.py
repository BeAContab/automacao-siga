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
    cod: str = ""
    empresa: str = ""


def load_cnpjs_from_xlsx(path: Path) -> list[SpreadsheetRow]:
    """Localiza as colunas da planilha, normaliza os valores e devolve apenas linhas válidas."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active

    header_map: dict[str, int] = {}
    header_row_number = 0
    required_document_headers = {"cnpj", "cgf"}
    cod_headers = {"cod", "codigo", "código"}
    company_headers = {"empresa", "nome empresa", "razao social", "razão social", "razao social completa"}
    # A busca do cabeçalho aceita acentos e variações simples de caixa.
    for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        normalized_cells = [_normalize_header(cell) for cell in row]
        if any(cell in normalized_cells for cell in required_document_headers | cod_headers | company_headers):
            header_row_number = row_number
            for index, value in enumerate(normalized_cells):
                if value:
                    header_map[value] = index
            break

    if "cnpj" not in header_map and "cgf" not in header_map:
        workbook.close()
        raise ValueError("A planilha precisa conter uma coluna chamada 'cnpj'.")

    document_index = header_map.get("cnpj", header_map.get("cgf"))
    cod_index = _find_header_index(header_map, cod_headers)
    company_index = _find_header_index(header_map, company_headers)
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
        cod_value = _normalize_free_text(row[cod_index]) if cod_index is not None and cod_index < len(row) else ""
        company_value = _normalize_free_text(row[company_index]) if company_index is not None and company_index < len(row) else ""
        rows.append(
            SpreadsheetRow(
                row_number=row_number,
                cnpj=digits,
                cod=cod_value,
                empresa=company_value,
            )
        )

    workbook.close()

    if not rows:
        raise ValueError("Nenhum CNPJ valido foi encontrado na planilha informada.")

    return rows


def load_cnpjs_from_text(text: str) -> list[SpreadsheetRow]:
    """Lê CNPJs informados manualmente, um por linha ou separados por pontuação."""
    rows: list[SpreadsheetRow] = []
    seen: set[str] = set()

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        # A interface permite colar CNPJs em vários formatos; tudo é normalizado para 14 dígitos.
        normalized_values = _extract_documents_from_text(raw_line)
        for value in normalized_values:
            if value in seen:
                continue
            seen.add(value)
            rows.append(SpreadsheetRow(row_number=line_number, cnpj=value))

    if not rows:
        raise ValueError("Nenhum CNPJ valido foi informado manualmente.")

    return rows


def _normalize_header(value: object) -> str:
    """Remove acentos e padroniza o cabeçalho para comparação segura."""
    if value is None:
        return ""
    return strip_accents(str(value)).strip().lower()


def _normalize_document(value: object) -> str:
    # Normaliza o documento preservando letras e números para dar suporte ao CNPJ alfanumérico.
    if value is None:
        return ""
    text = "".join(char for char in str(value) if char.isalnum())
    # O CNPJ precisa permanecer com 14 caracteres, inclusive os zeros à esquerda se for numérico.
    if not text:
        return ""
    return text.zfill(14) if len(text) <= 14 else text


def _normalize_free_text(value: object) -> str:
    """Preserva o texto útil da célula e remove apenas espaços excedentes."""
    if value is None:
        return ""
    return str(value).strip()


def _find_header_index(header_map: dict[str, int], aliases: set[str]) -> int | None:
    """Localiza o primeiro índice disponível para um grupo de aliases equivalentes."""
    for alias in aliases:
        index = header_map.get(alias)
        if index is not None:
            return index
    return None


def _extract_documents_from_text(value: object) -> list[str]:
    """Extrai todos os blocos alfanuméricos de 14 caracteres presentes em um texto livre."""
    if value is None:
        return []

    text = str(value)
    matches = []
    for token in text.replace("\t", " ").replace(";", " ").replace(",", " ").split():
        digits = _normalize_document(token)
        if len(digits) == 14:
            matches.append(digits)

    if matches:
        return matches

    digits = _normalize_document(text)
    return [digits] if len(digits) == 14 else []


def write_status_to_spreadsheet_cell(
    spreadsheet_path: Path,
    row_number: int,
    document_tab: str,
    status_str: str,
) -> None:
    """Escreve em tempo real o status do download na coluna correspondente na planilha de resultados."""
    if not spreadsheet_path or not row_number:
        return

    # Usar data_only=False para preservar as fórmulas originais da planilha
    workbook = load_workbook(spreadsheet_path, read_only=False, data_only=False)
    sheet = workbook["SIGA EMPS"] if "SIGA EMPS" in workbook.sheetnames else workbook.active

    # Localizar a linha de cabeçalho (a mesma lógica do carregamento)
    required_document_headers = {"cnpj", "cgf"}
    cod_headers = {"cod", "codigo", "código"}
    company_headers = {"empresa", "nome empresa", "razao social", "razão social", "razao social completa"}
    
    header_map: dict[str, int] = {}
    for r_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        normalized_cells = [_normalize_header(cell) for cell in row]
        if any(cell in normalized_cells for cell in required_document_headers | cod_headers | company_headers):
            for index, value in enumerate(normalized_cells):
                if value:
                    header_map[value] = index + 1  # 1-based para openpyxl
            break

    # Normalizar o nome da aba fiscal para fazer a correspondência com a coluna
    norm_tab = _normalize_header(document_tab)
    col_index = None

    # Mapear a coluna que contém o nome da aba fiscal (ex: "nf-e" ou "debitos fiscais")
    for key, val in header_map.items():
        if norm_tab in key or key in norm_tab:
            col_index = val
            break

    if col_index is not None:
        sheet.cell(row=row_number, column=col_index, value=status_str)
        workbook.save(spreadsheet_path)

    workbook.close()

