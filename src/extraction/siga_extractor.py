from __future__ import annotations

"""Fluxo principal de busca de contribuintes e extração dos relatórios do SIGA."""

import logging
import re
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from openpyxl import Workbook

from src.auth.siga_login import SigaLoginFlow
from src.config import Settings
from src.extraction.spreadsheet import SpreadsheetRow, close_status_workbook, write_status_to_spreadsheet_cell
from src.utils.browser import BrowserSession
from src.utils.narration import narrate, narrate_error, narrate_success, narrate_warning
from src.utils.selenium_compat import BrowserContext, Download, Error, Locator, Page, TimeoutError
from src.utils.siga_page import SigaPageInspector
from src.utils.text import slugify, strip_accents


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ExtractionResult:
    cnpj: str
    valor_contabil: str
    icms: str
    output_path: Path
    final_url: str


@dataclass(slots=True)
class FiscalDownloadResult:
    document_tab: str
    profile_name: str
    summary_path: Path
    detail_path: Path
    selected_report_name: str
    month_reference: str
    downloaded_at: datetime | None = None


@dataclass(slots=True)
class BatchExtractionResult:
    cnpj: str
    month_reference: str
    taxpayer_folder: Path
    fiscal_results: list[FiscalDownloadResult]
    final_url: str
    status: str
    message: str
    row_number: int = 0
    download_statuses: dict[str, str] = field(default_factory=dict)


class TaxpayerNotFoundError(Exception):
    """Indica que o CNPJ pesquisado nao retornou contribuinte selecionavel no SIGA."""


@dataclass(slots=True)
class PendingDetailRequest:
    request_key: str
    document_tab: str
    profile_name: str
    summary_path: Path
    report_name: str
    tela_aba: str
    requested_after: datetime
    taxpayer_cnpj: str
    taxpayer_document: str
    month_reference: str
    taxpayer_folder_name: str
    row_number: int


@dataclass(slots=True)
class DownloadLookupTarget:
    request: PendingDetailRequest
    normalized_target: str
    match_fragments: dict[str, str]
    taxpayer_base_key: str


@dataclass(slots=True)
class DownloadRowMatch:
    request_key: str
    page_number: int
    requested_at: datetime
    row_text: str
    exact_match: bool
    preferred: bool
    score: float


@dataclass(slots=True)
class IndicatorMetric:
    name: str
    qtd: float
    valor: float


@dataclass(slots=True)
class MonthOpenDecision:
    month_reference: str
    qtd: float
    valor: float
    opened: bool
    reason: str


@dataclass(slots=True)
class FiscalProfileConfig:
    label: str
    summary_basename: str
    display_label: str | None = None
    annual_quantity_label: str | None = None
    annual_value_label: str | None = None


@dataclass(slots=True)
class FiscalTabConfig:
    tab_name: str
    tab_slug: str
    tab_xpath: str
    profiles: tuple[FiscalProfileConfig, ...]
    detail_mode: str
    month_requires_positive_value: bool = True
    detail_label: str | None = "Autorizadas"


class SigaContributorExtractor:
    """Orquestra a navegação no SIGA, a busca do contribuinte e o download dos arquivos."""
    def __init__(self, settings: Settings, allow_manual_login_prompt: bool = True, output_spreadsheet_path: Path | None = None) -> None:
        self.settings = settings
        self.allow_manual_login_prompt = allow_manual_login_prompt
        self.page_inspector = SigaPageInspector(settings)
        self.output_spreadsheet_path = output_spreadsheet_path
        # Cache do indice da opcao "maior valor" no dropdown de linhas por pagina da Central de
        # Downloads, para evitar reler todas as opcoes a cada reload (ver _select_max_downloads_page_size).
        self._downloads_page_size_option_index: int | None = None

    def run(self, cnpj: str) -> ExtractionResult:
        """Executa a extração completa para um único contribuinte."""
        normalized_cnpj = self._normalize_numeric_document(cnpj)

        with BrowserSession(self.settings) as context:
            page = context.pages[0] if context.pages else context.new_page()
            page = self._ensure_authenticated(page, context)
            self._open_taxpayer_from_home(page, normalized_cnpj)

            valor_contabil = self._extract_metric(page, "Valor Contabil")
            icms = self._extract_metric(page, "ICMS")
            output_path = self._save_xlsx(normalized_cnpj, valor_contabil, icms)

            screenshot_path = self.settings.log_dir / f"{normalized_cnpj}.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            LOGGER.info("Captura de extração salva em %s", screenshot_path)

            return ExtractionResult(
                cnpj=normalized_cnpj,
                valor_contabil=valor_contabil,
                icms=icms,
                output_path=output_path,
                final_url=page.url,
            )

    def run_batch_from_spreadsheet(
        self,
        spreadsheet_rows: list[SpreadsheetRow],
        month_reference: str,
        reference_year: str | None = None,
        selected_tabs: list[str] | None = None,
        selected_tabs_by_cnpj: dict[str, list[str]] | None = None,
        selected_tabs_by_row_number: dict[int, list[str]] | None = None,
    ) -> list[BatchExtractionResult]:
        """Abre um contexto próprio de navegador e processa a planilha inteira."""
        with BrowserSession(self.settings) as context:
            return self.run_batch_from_spreadsheet_in_context(
                context,
                spreadsheet_rows,
                month_reference,
                reference_year,
                selected_tabs,
                selected_tabs_by_cnpj,
                selected_tabs_by_row_number,
            )

    def run_batch_from_spreadsheet_in_context(
        self,
        context: BrowserContext,
        spreadsheet_rows: list[SpreadsheetRow],
        month_reference: str,
        reference_year: str | None = None,
        selected_tabs: list[str] | None = None,
        selected_tabs_by_cnpj: dict[str, list[str]] | None = None,
        selected_tabs_by_row_number: dict[int, list[str]] | None = None,
    ) -> list[BatchExtractionResult]:
        """Reaproveita um contexto já autenticado para processar vários documentos em sequência."""
        try:
            return self._run_batch_from_spreadsheet_in_context(
                context,
                spreadsheet_rows,
                month_reference,
                reference_year,
                selected_tabs,
                selected_tabs_by_cnpj,
                selected_tabs_by_row_number,
            )
        finally:
            # Libera o workbook de status mantido em memória durante o lote (ver spreadsheet.py).
            close_status_workbook(self.output_spreadsheet_path)

    def _run_batch_from_spreadsheet_in_context(
        self,
        context: BrowserContext,
        spreadsheet_rows: list[SpreadsheetRow],
        month_reference: str,
        reference_year: str | None = None,
        selected_tabs: list[str] | None = None,
        selected_tabs_by_cnpj: dict[str, list[str]] | None = None,
        selected_tabs_by_row_number: dict[int, list[str]] | None = None,
    ) -> list[BatchExtractionResult]:
        normalized_month = month_reference.strip()
        if not normalized_month:
            raise ValueError("Informe o mes de referencia antes de iniciar a extracao.")
        normalized_year = self._normalize_reference_year(reference_year)

        results: list[BatchExtractionResult] = []
        pending_requests_by_row_number: dict[int, list[PendingDetailRequest]] = {}
        taxpayer_folder_names_by_row_number: dict[int, str] = {}
        all_pending_requests: list[PendingDetailRequest] = []
        not_found_row_numbers: set[int] = set()
        prebuilt_results_by_row_number: dict[int, BatchExtractionResult] = {}
        last_successful_taxpayer_cnpj: str | None = None
        page = context.pages[0] if context.pages else context.new_page()
        page = self._ensure_authenticated(page, context)

        all_possible_tabs = ["NF-e", "NFC-e", "CT-e", "Malha Fiscal", "Débitos Fiscais"]

        queue = list(spreadsheet_rows)
        row_retry_counts: dict[int, int] = {}

        while queue:
            spreadsheet_row = queue.pop(0)
            # Cada linha da planilha vira uma busca independente dentro do SIGA.
            LOGGER.info("Processando o CNPJ %s da linha %s da planilha", spreadsheet_row.cnpj, spreadsheet_row.row_number)
            narrate("Processando o CNPJ %s (linha %s da planilha)...", self._format_cnpj(spreadsheet_row.cnpj), spreadsheet_row.row_number)
            taxpayer_folder_name = self._build_taxpayer_folder_name(spreadsheet_row)
            taxpayer_folder_names_by_row_number[spreadsheet_row.row_number] = taxpayer_folder_name

            # Determinar abas selecionadas para esta linha
            tabs_for_row = selected_tabs
            if selected_tabs_by_row_number is not None:
                tabs_for_row = selected_tabs_by_row_number.get(spreadsheet_row.row_number)
            elif selected_tabs_by_cnpj is not None:
                tabs_for_row = selected_tabs_by_cnpj.get(spreadsheet_row.cnpj)

            if tabs_for_row is not None:
                tabs_for_row = [tab for tab in tabs_for_row if tab in all_possible_tabs]
            else:
                tabs_for_row = all_possible_tabs

            # Gravar imediatamente "Não solicitado" para abas não marcadas nesta linha (apenas no primeiro processamento)
            if spreadsheet_row.row_number not in row_retry_counts:
                for tab in all_possible_tabs:
                    if tab not in tabs_for_row:
                        write_status_to_spreadsheet_cell(self.output_spreadsheet_path, spreadsheet_row.row_number, tab, "Não solicitado")

            try:
                self._open_taxpayer_from_home(page, spreadsheet_row.cnpj)
            except TaxpayerNotFoundError as exc:
                LOGGER.warning("CNPJ %s nao foi encontrado na pesquisa do SIGA; seguindo para o proximo.", spreadsheet_row.cnpj)
                narrate_warning("CNPJ %s não foi encontrado no SIGA; seguindo para o próximo.", self._format_cnpj(spreadsheet_row.cnpj))
                notice_path = self._save_taxpayer_not_found_notice(
                    cgf=spreadsheet_row.cnpj,
                    month_reference=normalized_month,
                    message=str(exc),
                    taxpayer_folder_name=taxpayer_folder_name,
                )
                
                # Gravar erro de contribuinte não encontrado em tempo real
                for tab in tabs_for_row:
                    write_status_to_spreadsheet_cell(self.output_spreadsheet_path, spreadsheet_row.row_number, tab, "Erro: Contribuinte não encontrado")

                prebuilt_results_by_row_number[spreadsheet_row.row_number] = BatchExtractionResult(
                    cnpj=spreadsheet_row.cnpj,
                    month_reference=normalized_month,
                    taxpayer_folder=notice_path.parent,
                    fiscal_results=[],
                    final_url=page.url,
                    status="taxpayer_not_found",
                    message=f"CNPJ {spreadsheet_row.cnpj} nao foi encontrado no SIGA.",
                    row_number=spreadsheet_row.row_number,
                )
                pending_requests_by_row_number[spreadsheet_row.row_number] = []
                not_found_row_numbers.add(spreadsheet_row.row_number)
                continue
            except Exception as exc:  # noqa: BLE001
                # Se for um erro temporário (como TimeoutError, erro de conexão ou página em branco)
                # e ainda houver tentativas para esta linha, coloca no final da fila.
                retry_count = row_retry_counts.get(spreadsheet_row.row_number, 0)
                if retry_count < 2:
                    row_retry_counts[spreadsheet_row.row_number] = retry_count + 1
                    LOGGER.warning(
                        "Falha temporaria ao abrir o contribuinte para o CNPJ %s na linha %s (%s). "
                        "Reenfileirando para tentar no final do lote (tentativa %s/2).",
                        spreadsheet_row.cnpj,
                        spreadsheet_row.row_number,
                        exc,
                        retry_count + 1,
                    )
                    queue.append(spreadsheet_row)
                    narrate_warning(
                        "Tentando novamente o CNPJ %s (tentativa %s de 3)...",
                        self._format_cnpj(spreadsheet_row.cnpj),
                        retry_count + 1,
                    )
                    continue

                # Se esgotou as retentativas, registra o erro definitivo
                LOGGER.exception(
                    "Falha definitiva ao abrir o contribuinte para o CNPJ %s após %s retentativas",
                    spreadsheet_row.cnpj,
                    retry_count,
                )
                narrate_error(
                    "Não foi possível abrir o CNPJ %s após várias tentativas.",
                    self._format_cnpj(spreadsheet_row.cnpj),
                )
                for tab in tabs_for_row:
                    write_status_to_spreadsheet_cell(self.output_spreadsheet_path, spreadsheet_row.row_number, tab, f"Erro: {exc}")

                prebuilt_results_by_row_number[spreadsheet_row.row_number] = BatchExtractionResult(
                    cnpj=spreadsheet_row.cnpj,
                    month_reference=normalized_month,
                    taxpayer_folder=self._build_taxpayer_output_dir(taxpayer_folder_name, normalized_month),
                    fiscal_results=[],
                    final_url=page.url,
                    status="error",
                    message=f"Falha inesperada ao abrir o CNPJ {spreadsheet_row.cnpj}: {exc}",
                    row_number=spreadsheet_row.row_number,
                )
                pending_requests_by_row_number[spreadsheet_row.row_number] = []
                not_found_row_numbers.add(spreadsheet_row.row_number)
                continue

            # A Central de Downloads so fica acessivel dentro de um contribuinte valido.
            last_successful_taxpayer_cnpj = spreadsheet_row.cnpj
            
            try:
                pending_requests = self._extract_fiscal_tables(
                    page,
                    spreadsheet_row.cnpj,
                    normalized_month,
                    normalized_year,
                    taxpayer_folder_name,
                    tabs_for_row,
                    row_number=spreadsheet_row.row_number,
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha ao extrair tabelas fiscais para o CNPJ %s", spreadsheet_row.cnpj)
                # Marcar erro em todas as abas selecionadas que falharam na solicitação
                for tab in tabs_for_row:
                    write_status_to_spreadsheet_cell(self.output_spreadsheet_path, spreadsheet_row.row_number, tab, f"Erro: {exc}")
                pending_requests = []

            pending_requests_by_row_number[spreadsheet_row.row_number] = pending_requests
            all_pending_requests.extend(pending_requests)

        detail_paths: dict[str, Path] = {}
        if all_pending_requests:
            LOGGER.info(
                "Todas as solicitacoes fiscais foram preparadas para %s CNPJ(s); abrindo a Central de Downloads uma unica vez para buscar %s arquivo(s).",
                len(spreadsheet_rows),
                len(all_pending_requests),
            )
            detail_paths = self._download_pending_detail_requests(
                page,
                all_pending_requests,
                context=context,
                fallback_taxpayer_cnpj=last_successful_taxpayer_cnpj,
            )

        for spreadsheet_row in spreadsheet_rows:
            if spreadsheet_row.row_number in not_found_row_numbers:
                results.append(prebuilt_results_by_row_number[spreadsheet_row.row_number])
                continue
            pending_requests = pending_requests_by_row_number.get(spreadsheet_row.row_number, [])
            fiscal_results = []
            
            for request in pending_requests:
                detail_path = detail_paths.get(request.request_key)
                
                downloaded_at = None
                if detail_path is not None:
                    path_str = str(detail_path)
                    if not path_str.startswith("__ERROR__") and detail_path.suffix != ".txt":
                        downloaded_at = datetime.now()

                fiscal_results.append(
                    FiscalDownloadResult(
                        document_tab=request.document_tab,
                        profile_name=request.profile_name,
                        summary_path=request.summary_path,
                        detail_path=detail_path,
                        selected_report_name=request.report_name,
                        month_reference=normalized_month,
                        downloaded_at=downloaded_at,
                    )
                )

            results.append(
                BatchExtractionResult(
                    cnpj=spreadsheet_row.cnpj,
                    month_reference=normalized_month,
                    taxpayer_folder=self._build_taxpayer_output_dir(
                        taxpayer_folder_names_by_row_number[spreadsheet_row.row_number],
                        normalized_month,
                    ),
                    fiscal_results=fiscal_results,
                    final_url=page.url,
                    status="completed_with_downloads" if fiscal_results else "completed_without_downloads",
                    message=(
                        f"Downloads concluidos para {spreadsheet_row.cnpj}."
                        if fiscal_results
                        else f"Nenhum download foi solicitado para {spreadsheet_row.cnpj}."
                    ),
                    row_number=spreadsheet_row.row_number,
                )
            )

        narrate_success("Processo concluído. %s de %s contribuintes processados.", len(results), len(spreadsheet_rows))
        return results

    def _open_taxpayer_from_home(self, page: Page, cgf: str) -> None:
        """Retenta a navegação até a lista do contribuinte abrir de forma confiável."""
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                self._return_to_home(page)
                self._wait_for_taxpayer_list_ready(page)
                self._search_taxpayer(page, cgf)
                self._open_taxpayer(page, cgf)
                return
            except TaxpayerNotFoundError as exc:
                last_error = exc
                LOGGER.warning(
                    "A tentativa %s indicou que o contribuinte %s nao foi encontrado: %s",
                    attempt,
                    cgf,
                    exc,
                )
                if attempt == 3:
                    raise
                if attempt < 3:
                    page.wait_for_timeout(1_000)
            except (TimeoutError, Error) as exc:
                last_error = exc
                LOGGER.warning(
                    "A tentativa %s de pesquisar e abrir o contribuinte %s nao foi concluida: %s",
                    attempt,
                    cgf,
                    exc,
                )
                if attempt < 3:
                    # Se a página estiver em branco ou quebrada, estabilizar imediatamente antes
                    # de retentar — evita desperdiçar uma tentativa digitando em tela inutilizável.
                    try:
                        diagnosis = self.page_inspector.inspect(page)
                        if diagnosis["needs_recovery"]:
                            LOGGER.warning(
                                "Pagina em branco detectada durante a tentativa %s para %s (motivo: %s); "
                                "estabilizando antes de retentar.",
                                attempt,
                                cgf,
                                diagnosis["reason"],
                            )
                            self.page_inspector.stabilize_after_navigation(
                                page, f"retry-before-taxpayer-open-{cgf}"
                            )
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(1_000)

        self._save_debug_snapshot(page, f"taxpayer-open-cycle-failed-{cgf}")
        raise TimeoutError(
            f"Nao foi possivel pesquisar e abrir o contribuinte {cgf} apos retentativas."
        ) from last_error

    def _wait_for_loading_overlays_to_disappear(self, page: Page) -> None:
        """Espera até que qualquer div de bloqueio ou carregamento (PrimeNG blockUI/spinners) desapareça da tela."""
        deadline = time.time() + 15
        script = """
        () => {
            const isVisible = (el) => {
                const style = window.getComputedStyle(el);
                return style && style.display !== 'none' && style.visibility !== 'hidden' && el.offsetWidth > 0;
            };
            const overlays = [...document.querySelectorAll("div")].filter(el => {
                const style = window.getComputedStyle(el);
                if (!style) return false;
                const isFixedOrAbsolute = style.position === 'fixed' || style.position === 'absolute';
                const isFullScreen = (el.offsetWidth >= window.innerWidth * 0.9) && (el.offsetHeight >= window.innerHeight * 0.9);
                const hasLoaderClass = el.className && (
                    el.className.includes('loading') || 
                    el.className.includes('blockui') || 
                    el.className.includes('spinner') || 
                    el.className.includes('overlay')
                );
                const zIndexVal = parseFloat(style.zIndex);
                const isBlockingOverlay = isFixedOrAbsolute && isFullScreen && (!isNaN(zIndexVal) && zIndexVal >= 0);
                return isVisible(el) && (hasLoaderClass || isBlockingOverlay);
            });
            return overlays.length > 0;
        }
        """
        while time.time() < deadline:
            try:
                if not page.evaluate(script):
                    return
            except Error:
                pass
            page.wait_for_timeout(500)

    def _wait_for_taxpayer_list_ready(self, page: Page) -> bool:
        """Espera a lista de contribuintes se estabilizar antes de digitar o CGF."""
        self._wait_for_loading_overlays_to_disappear(page)
        deadline = time.time() + min(max(8, self.settings.timeout_ms / 1000), 12)
        skeleton_selector = ".p-skeleton, .skeleton, [class*='skeleton']"
        row_selector = "tr.p-selectable-row, tr[role='row'] td, .p-datatable-tbody tr"

        while time.time() < deadline:
            try:
                skeletons = page.locator(skeleton_selector)
                visible_skeleton = self._first_visible_enabled(skeletons)
                if visible_skeleton is not None:
                    page.wait_for_timeout(500)
                    continue
            except Error:
                pass

            try:
                rows = page.locator(row_selector)
                if rows.count() > 0:
                    LOGGER.info("A lista de contribuintes está visível antes da pesquisa")
                    return True
            except Error:
                pass

            # A lista vazia também libera a pesquisa; a validação forte acontece após o Enter no CGF.
            try:
                body_text = strip_accents(page.locator("body").inner_text(timeout=2_000)).lower()
                if any(
                    marker in body_text
                    for marker in (
                        "nenhum registro",
                        "nenhum resultado",
                        "nao ha registros",
                        "nao foram encontrados",
                    )
                ):
                    LOGGER.info("A lista de contribuintes indicou estado vazio antes da pesquisa")
                    return True
            except Error:
                pass

            page.wait_for_timeout(500)

        diagnosis = self.page_inspector.inspect(page)
        if diagnosis["needs_recovery"]:
            raise TimeoutError(
                f"A pagina do SIGA permaneceu em branco ou inacessivel (motivo: {diagnosis['reason']})."
            )

        LOGGER.info(
            "A lista de contribuintes não terminou de carregar visualmente; continuando porque a busca agora é feita por paginação direta."
        )
        return False

    def _extract_fiscal_tables(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        reference_year: str,
        taxpayer_folder_name: str,
        selected_tabs: list[str] | None = None,
        row_number: int = 0,
    ) -> list[PendingDetailRequest]:
        """Percorre as abas fiscais selecionadas e agrega as solicitações de download.

        As abas "Malha Fiscal" e "Débitos Fiscais" possuem fluxos próprios e são
        despachadas para métodos dedicados antes do loop de abas fiscais padrão.
        """
        results: list[PendingDetailRequest] = []
        allowed_tabs = self._normalize_selected_tabs(selected_tabs)

        # --- Abas especiais que não seguem o fluxo de Informações Fiscais ---
        if "Malha Fiscal" in allowed_tabs:
            try:
                request = self._request_malha_fiscal(page, cgf, month_reference, taxpayer_folder_name, row_number)
                if request is not None:
                    results.append(request)
                else:
                    write_status_to_spreadsheet_cell(self.output_spreadsheet_path, row_number, "Malha Fiscal", "Sem indícios de irregularidades")
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha ao solicitar Malha Fiscal para o CNPJ %s", cgf)
                write_status_to_spreadsheet_cell(self.output_spreadsheet_path, row_number, "Malha Fiscal", f"Erro: {exc}")
                narrate_warning("Não foi possível solicitar a Malha Fiscal do CNPJ %s.", self._format_cnpj(cgf))

        if "Débitos Fiscais" in allowed_tabs:
            try:
                request = self._request_debitos_fiscais(page, cgf, month_reference, taxpayer_folder_name, row_number)
                if request is not None:
                    results.append(request)
                else:
                    write_status_to_spreadsheet_cell(self.output_spreadsheet_path, row_number, "Débitos Fiscais", "Sem débitos fiscais")
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha ao solicitar Débitos Fiscais para o CNPJ %s", cgf)
                write_status_to_spreadsheet_cell(self.output_spreadsheet_path, row_number, "Débitos Fiscais", f"Erro: {exc}")
                narrate_warning("Não foi possível solicitar os Débitos Fiscais do CNPJ %s.", self._format_cnpj(cgf))

        # --- Abas fiscais padrão (NF-e, NFC-e, CT-e) ---
        for tab_config in self._build_fiscal_tab_configs():
            if tab_config.tab_name not in allowed_tabs:
                LOGGER.info("Ignorando a aba fiscal %s porque ela não foi selecionada", tab_config.tab_name)
                continue
            try:
                narrate("Extraindo dados de %s do contribuinte...", tab_config.tab_name)
                results.extend(
                    self._collect_fiscal_tab_requests(
                        page,
                        cgf,
                        month_reference,
                        reference_year,
                        taxpayer_folder_name,
                        tab_config,
                        row_number,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha ao solicitar %s para o CNPJ %s", tab_config.tab_name, cgf)
                write_status_to_spreadsheet_cell(self.output_spreadsheet_path, row_number, tab_config.tab_name, f"Erro: {exc}")
                narrate_warning("Não foi possível extrair %s do CNPJ %s.", tab_config.tab_name, self._format_cnpj(cgf))
        return results

    def _build_pending_request(
        self,
        *,
        cgf: str,
        month_reference: str,
        document_tab: str,
        profile_name: str,
        summary_path: Path,
        report_name: str,
        tela_aba: str,
        requested_after: datetime,
        taxpayer_document: str,
        taxpayer_folder_name: str,
        row_number: int = 0,
    ) -> PendingDetailRequest:
        """Cria uma solicitacao com chave unica para nao misturar downloads de CNPJs diferentes."""
        request_key = "|".join(
            (
                self._normalize_numeric_document(cgf),
                slugify(month_reference),
                self._sanitize_filename(tela_aba),
            )
        )
        return PendingDetailRequest(
            request_key=request_key,
            document_tab=document_tab,
            profile_name=profile_name,
            summary_path=summary_path,
            report_name=report_name,
            tela_aba=tela_aba,
            requested_after=requested_after,
            taxpayer_cnpj=cgf,
            taxpayer_document=taxpayer_document,
            month_reference=month_reference,
            taxpayer_folder_name=taxpayer_folder_name,
            row_number=row_number,
        )

    def _normalize_selected_tabs(self, selected_tabs: list[str] | None) -> set[str]:
        """Converte a seleção do usuário em um conjunto válido de abas fiscais.

        As abas especiais "Malha Fiscal" e "Débitos Fiscais" são incluídas no
        conjunto disponível mas processadas por métodos dedicados, não pelo
        loop de FiscalTabConfig padrão.
        """
        # Abas do loop padrão (NF-e, NFC-e, CT-e)
        available_tabs = {config.tab_name: config.tab_name for config in self._build_fiscal_tab_configs()}
        # Abas especiais adicionais
        for special_tab in ("Malha Fiscal", "Débitos Fiscais"):
            available_tabs[special_tab] = special_tab

        if not selected_tabs:
            return set(available_tabs.keys())

        normalized_lookup = {strip_accents(name).casefold(): name for name in available_tabs.keys()}
        resolved: set[str] = set()
        for value in selected_tabs:
            normalized = strip_accents(str(value)).strip().casefold()
            if not normalized:
                continue
            if normalized in {"all", "todos", "todas", "*"}:
                return set(available_tabs.keys())
            tab_name = normalized_lookup.get(normalized)
            if not tab_name:
                valid = ", ".join(available_tabs.keys())
                raise ValueError(f"Aba fiscal invalida '{value}'. Valores aceitos: {valid}.")
            resolved.add(tab_name)
        return resolved or set(available_tabs.keys())

    def _collect_fiscal_tab_requests(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        reference_year: str,
        taxpayer_folder_name: str,
        tab_config: FiscalTabConfig,
        row_number: int = 0,
    ) -> list[PendingDetailRequest]:
        """Extrai uma aba fiscal inteira e guarda apenas as solicitações de detalhamento."""
        LOGGER.info("Iniciando a extração fiscal da aba %s", tab_config.tab_name)
        try:
            self._open_fiscal_information(page)
        except TimeoutError:
            LOGGER.info(
                "Informacoes Fiscais did not open on the current view for %s; returning home and retrying once.",
                tab_config.tab_name,
            )
            self._return_to_home(page)
            self._open_fiscal_information(page)
        self._open_document_tab(page, tab_config)

        summary_paths: dict[str, Path] = {}
        eligible_profiles: list[FiscalProfileConfig] = []

        for profile in tab_config.profiles:
            # Primeiro verificamos se o resumo vale a pena baixar; isso evita arquivos vazios.
            self._open_named_section(page, profile.label)
            if not self._should_download_profile_summary(page, tab_config, profile):
                LOGGER.info(
                    "Skipping summary download for %s/%s because annual totals are not positive",
                    tab_config.tab_name,
                    profile.label,
                )
                continue

            summary_paths[profile.label] = self._download_current_table(
                page,
                cgf,
                month_reference,
                taxpayer_folder_name,
                profile.summary_basename,
                tab_config.tab_slug,
            )
            eligible_profiles.append(profile)

        pending_requests: list[PendingDetailRequest] = []
        for profile in eligible_profiles:
            # Só pedimos detalhamento se o mês escolhido tiver movimento suficiente.
            self._open_named_section(page, profile.label)
            month_decision = self.open_reference_month_if_positive(
                page,
                month_reference,
                require_positive_value=tab_config.month_requires_positive_value,
            )
            if not month_decision.opened:
                LOGGER.info(
                    "Skipping month %s for %s/%s because %s (QTD=%s, VALOR=%s)",
                    month_reference,
                    tab_config.tab_name,
                    profile.label,
                    month_decision.reason,
                    month_decision.qtd,
                    month_decision.valor,
                )
                continue

            if tab_config.detail_mode == "reports":
                pending_requests.extend(
                    self._request_report_details_for_profile(
                        page,
                        cgf,
                        tab_config,
                        profile,
                        month_reference,
                        reference_year,
                        summary_paths[profile.label],
                        taxpayer_folder_name,
                        row_number,
                    )
                )
                continue

            tela_aba = self._build_download_screen_name(
                month_reference=month_reference,
                tab_name=tab_config.tab_name,
                view_label=self._display_label(profile.label, profile.display_label),
                detail_label=tab_config.detail_label,
                selected_year=reference_year,
            )
            requested_after = datetime.now() - timedelta(seconds=30)
            self._request_detail_download(page)
            pending_requests.append(
                self._build_pending_request(
                    cgf=cgf,
                    month_reference=month_reference,
                    document_tab=tab_config.tab_slug,
                    profile_name=profile.label,
                    summary_path=summary_paths[profile.label],
                    report_name=tab_config.detail_label or "Detalhamento",
                    tela_aba=tela_aba,
                    requested_after=requested_after,
                    taxpayer_document=self._current_taxpayer_document(page),
                    taxpayer_folder_name=taxpayer_folder_name,
                    row_number=row_number,
                )
            )
        if not pending_requests:
            write_status_to_spreadsheet_cell(
                self.output_spreadsheet_path,
                row_number,
                tab_config.tab_name,
                "Sem movimento",
            )
        return pending_requests

    def _ensure_authenticated(self, page: Page, context: BrowserContext) -> Page:
        """Garante que a sessão esteja autenticada antes de mexer na interface do SIGA."""
        LOGGER.info("Abrindo o SIGA para reutilizar a sessão autenticada")
        page.goto(self.settings.siga_url, wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
        if "siga.sefaz.ce.gov.br/ui" in page.url:
            self.page_inspector.stabilize_after_navigation(page, "extract-open")

        if self._has_taxpayer_search(page):
            LOGGER.info("Página autenticada do SIGA detectada")
            return page

        LOGGER.info("Área autenticada ainda não detectada; iniciando o handoff do login manual")
        login_flow = SigaLoginFlow(self.settings)
        if not self.allow_manual_login_prompt:
            self._save_debug_snapshot(page, "auth-required")
            raise TimeoutError(
                "A sessao autenticada do SIGA nao foi encontrada. Confirme o login manual na interface antes de extrair."
            )
        try:
            authenticated_page = login_flow.wait_for_manual_login(page, context)
        except TimeoutError as exc:
            self._save_debug_snapshot(page, "login-handoff-failed")
            raise TimeoutError(
                "Nao foi possivel confirmar o login manual no SIGA durante a extracao."
            ) from exc

        if not self._has_taxpayer_search(authenticated_page):
            self._save_debug_snapshot(authenticated_page, "auth-timeout")
            raise TimeoutError(
                "O SIGA foi reaberto, mas a area autenticada com a pesquisa de contribuintes nao foi detectada."
            )

        return authenticated_page

    def _has_taxpayer_search(self, page: Page) -> bool:
        """Identifica sinais da área autenticada por meio da presença dos campos de busca."""
        try:
            if page.locator("input").count() == 0:
                return False
        except Error:
            return False

        text = page.locator("body").inner_text(timeout=5_000)
        search_signals = ("contribuinte", "cnpj", "cpf", "cgf", "pesquisar", "consulta")
        return any(signal in strip_accents(text).lower() for signal in search_signals)

    def _search_taxpayer(self, page: Page, document_value: str) -> None:
        """Envia o CGF ou CNPJ para a busca e aguarda o resultado filtrado."""
        LOGGER.info("Pesquisando contribuinte %s", document_value)
        narrate("Digitando o CNPJ %s na busca...", self._format_cnpj(document_value))
        self._wait_for_loading_overlays_to_disappear(page)
        search_input = self._find_search_input(page)
        search_input.click()
        search_input.fill("")
        search_input.fill(document_value)
        search_input.press("Enter")
        self._wait_for_taxpayer_search_result(page, document_value)

    def _wait_for_taxpayer_search_result(self, page: Page, document_value: str) -> None:
        """Espera a tabela responder à busca até surgir uma linha correspondente."""
        target_digits = self._normalize_numeric_document(document_value)
        deadline = time.time() + max(30, self.settings.timeout_ms / 1000)
        script = """
        (targetDigits) => {
            const digits = (value) => String(value || "").replace(/\\D/g, "");
            const normalize = (value) => String(value || "")
                .normalize("NFD")
                .replace(/[\u0300-\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();
            const isVisible = (element) => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                if (!style || style.display === "none" || style.visibility === "hidden") return false;
                return !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
            };

            const skeletonVisible = [...document.querySelectorAll(".p-skeleton, .skeleton, [class*='skeleton']")]
                .some(isVisible);
            const rowSelector = "tr.p-selectable-row, .p-datatable-tbody tr, tr[role='row'], [role='row'], .p-datatable-row, .card";
            const rows = [...document.querySelectorAll(rowSelector)].filter(isVisible);
            const matchingRows = rows.filter((row) => digits(row.innerText || row.textContent).includes(targetDigits));
            const bodyText = normalize(document.body ? document.body.innerText : "");
            
            // Lista expandida de marcadores para identificar a ausência de cadastro de forma instantânea
            const noResult = [
                "nenhum registro",
                "nenhum resultado",
                "nao ha registros",
                "nao foram encontrados",
                "nao foram localizados",
                "nao localizado",
                "sem registros",
                "sem resultados",
                "nenhum item",
                "nenhuma ocorrencia"
            ].some((marker) => bodyText.includes(marker)) || (rows.length === 0 && !skeletonVisible);

            return {
                skeletonVisible,
                rowCount: rows.length,
                matchCount: matchingRows.length,
                noResult,
            };
        }
        """

        empty_result_seen_at: float | None = None
        while time.time() < deadline:
            try:
                state = page.evaluate(script, target_digits)
                if state.get("matchCount", 0) > 0:
                    LOGGER.info(
                        "Resultado da pesquisa do contribuinte pronto para %s com %s linha(s) correspondente(s)",
                        document_value,
                        state.get("matchCount", 0),
                    )
                    narrate_success("Contribuinte %s localizado.", self._format_cnpj(document_value))
                    return
                if state.get("skeletonVisible"):
                    empty_result_seen_at = None
                    page.wait_for_timeout(500)
                    continue
                if state.get("noResult"):
                    if empty_result_seen_at is None:
                        empty_result_seen_at = time.time()
                    if time.time() - empty_result_seen_at >= 3:
                        self._save_debug_snapshot(page, f"taxpayer-search-empty-{document_value}")
                        raise TaxpayerNotFoundError(
                            f"Nenhum contribuinte foi encontrado para {self._format_cnpj(document_value)}."
                        )
                    page.wait_for_timeout(500)
                    continue
                empty_result_seen_at = None
            except TimeoutError:
                raise
            except Error as exc:
                LOGGER.warning("Ainda nao foi possivel inspecionar o resultado da pesquisa do contribuinte: %s", exc)

            page.wait_for_timeout(500)

        self._save_debug_snapshot(page, f"taxpayer-search-timeout-{document_value}")
        raise TaxpayerNotFoundError(
            f"Nenhum contribuinte foi encontrado para {self._format_cnpj(document_value)}."
        )

    def _find_search_input(self, page: Page) -> Locator:
        """Localiza o campo de pesquisa do contribuinte com várias estratégias de fallback."""
        xpath_input = self._first_visible_enabled(
            page.locator("xpath=//input[contains(@placeholder,'CGF') or contains(@placeholder,'Raz')]")
        )
        if xpath_input is not None:
            LOGGER.info("Usando seletor XPath para o campo de pesquisa do contribuinte")
            return xpath_input

        candidate_selectors = (
            page.get_by_placeholder(re.compile(r"(pesquis|busc|cnpj|cpf|cgf|contribuinte)", re.IGNORECASE)),
            page.get_by_role("searchbox"),
            page.get_by_role("textbox", name=re.compile(r"(pesquis|busc|cnpj|cpf|cgf|contribuinte)", re.IGNORECASE)),
            page.locator("input[type='search']"),
            page.locator("input"),
        )

        for locator in candidate_selectors:
            candidate = self._first_visible_enabled(locator)
            if candidate is not None:
                return candidate

        raise TimeoutError("Nao foi possivel localizar a barra de pesquisa de contribuintes.")

    def _open_taxpayer(self, page: Page, document_value: str) -> None:
        """Abre o contribuinte encontrado usando a linha ou célula que melhor bater com o documento."""
        LOGGER.info("Abrindo a linha do contribuinte %s", document_value)
        narrate("Abrindo a ficha do contribuinte %s...", self._format_cnpj(document_value))
        if self._is_taxpayer_detail_page(page):
            LOGGER.info("A visualização de detalhes do contribuinte já foi detectada; ignorando a seleção de linha para %s", document_value)
            return

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                row = self._find_taxpayer_row(page, document_value)
                if row is None:
                    # O fallback por DOM já acionou o clique; aguardamos a navegação confirmar a tela.
                    if self._wait_for_taxpayer_detail_page(page, document_value, attempt):
                        return
                    continue

                if self._open_detail_from_row(page, row):
                    if self._wait_for_taxpayer_detail_page(page, document_value, attempt):
                        return

                if self._click_taxpayer_cgf_cell(row):
                    LOGGER.info("Abrindo os detalhes do contribuinte clicando na célula do CGF (tentativa %s)", attempt)
                    if self._wait_for_taxpayer_detail_page(page, document_value, attempt):
                        return

                LOGGER.info("Abrindo os detalhes do contribuinte clicando na linha encontrada (tentativa %s)", attempt)
                try:
                    row.click(timeout=5_000)
                except Error:
                    row.click(timeout=5_000, force=True)
                if self._wait_for_taxpayer_detail_page(page, document_value, attempt):
                    return
            except Error as exc:
                last_error = exc
                LOGGER.warning(
                    "A tentativa %s de abrir o contribuinte %s falhou antes da confirmação dos detalhes: %s",
                    attempt,
                    document_value,
                    exc,
                )
            page.wait_for_timeout(1_000)

        self._save_debug_snapshot(page, f"open-taxpayer-not-confirmed-{document_value}")
        if last_error is not None:
            LOGGER.warning("Último erro ao abrir o contribuinte %s: %s", document_value, last_error)
        raise TimeoutError(
            f"O contribuinte {document_value} foi clicado, mas a tela de detalhes nao foi confirmada."
        )

    def _wait_for_taxpayer_detail_page(self, page: Page, document_value: str, attempt: int) -> bool:
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                if self._is_taxpayer_detail_page(page):
                    LOGGER.info(
                        "Visualização de detalhes do contribuinte confirmada para %s na tentativa %s",
                        document_value,
                        attempt,
                    )
                    return True
            except Error:
                pass
            page.wait_for_timeout(500)
        return False

    def _open_detail_from_row(self, page: Page, row: Locator) -> bool:
        row_container = row
        try:
            ancestor_row = row.locator("xpath=ancestor::tr[1]")
            if ancestor_row.count():
                row_container = ancestor_row.first
        except Error:
            row_container = row

        detail_candidates = (
            row_container.locator("a:has(i.pi-external-link)"),
            row_container.locator("button:has(i.pi-external-link)"),
            row_container.locator("[role='button']:has(i.pi-external-link)"),
            row_container.locator("i.pi-external-link").locator("xpath=ancestor::a[1]"),
            row_container.locator("i.pi-external-link").locator("xpath=ancestor::*[@role='button'][1]"),
            row_container.get_by_role("button", name=re.compile(r"detalh|visualiz|abrir|selecionar", re.IGNORECASE)),
            row_container.get_by_role("link", name=re.compile(r"detalh|visualiz|abrir|selecionar", re.IGNORECASE)),
            row_container.locator("a[title*='Detalh'], button[title*='Detalh'], [aria-label*='Detalh']"),
        )

        for locator in detail_candidates:
            target = self._first_visible_enabled(locator)
            if target is None:
                continue
            LOGGER.info("Abrindo os detalhes do contribuinte usando a ação Detalhamento")
            target.click(timeout=5_000, force=True)
            return True

        return False

    def _click_taxpayer_cgf_cell(self, row: Locator) -> bool:
        try:
            cells = row.locator("td")
            if cells.count() < 2:
                return False
            # A busca localiza a linha pelo CGF; na tabela do SIGA, a célula do CGF é a
            # segunda coluna e costuma ser o alvo que dispara a navegação para o detalhe.
            target = cells.nth(1)
            if not (target.is_visible() and target.is_enabled()):
                target = self._first_visible_enabled(cells)
            if target is None:
                return False
            target.click(timeout=5_000, force=True)
            return True
        except Error:
            return False

    def _find_taxpayer_row(self, page: Page, document_value: str) -> Locator | None:
        candidate = self._find_taxpayer_row_on_current_page(page, document_value)
        if candidate is not None:
            return candidate
        self._save_debug_snapshot(page, f"row-not-found-{document_value}")
        raise TaxpayerNotFoundError(
            f"Nao foi possivel localizar o contribuinte {self._format_cnpj(document_value)} na lista filtrada."
        )

    def _find_taxpayer_row_on_current_page(self, page: Page, document_value: str) -> Locator | None:
        patterns = (
            document_value,
            self._format_cnpj(document_value),
            self._format_cgf(document_value),
        )

        for value in patterns:
            if not value:
                continue
            xpath_row = page.locator(f"xpath=//tr[.//td[contains(normalize-space(.),'{value}')]]")
            candidate = self._first_visible_enabled(xpath_row)
            if candidate is not None:
                LOGGER.info("Usando seletor XPath para a linha do contribuinte %s", value)
                return candidate

        row_candidates = (
            page.get_by_role("row", name=re.compile(re.escape(document_value))),
            page.get_by_role("link", name=re.compile(re.escape(document_value))),
            page.get_by_role("button", name=re.compile(re.escape(document_value))),
        )

        for locator in row_candidates:
            try:
                if locator.count():
                    return locator.first
            except Error:
                continue

        for value in patterns:
            if not value:
                continue
            text_locator = page.locator(f"text={value}")
            try:
                if text_locator.count():
                    return text_locator.first
            except Error:
                continue

        # Fallback por dígitos: encontra linhas/cards mesmo quando o CGF aparece formatado.
        digits = self._normalize_numeric_document(document_value)
        if digits:
            row = self._find_row_by_digits(page, digits)
            if row is not None:
                return row

        return None

    def _click_taxpayer_row_by_digits(self, page: Page, target_digits: str) -> bool:
        """Usa uma checagem via DOM para clicar na linha do contribuinte quando o Selenium falha."""
        script = """
        (targetDigits) => {
            const digits = (value) => String(value || "").replace(/\\D/g, "");
            const isVisible = (element) => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                if (!style || style.display === "none" || style.visibility === "hidden") return false;
                return !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
            };
            const rowSelector = "tr.p-selectable-row, .p-datatable-tbody tr, tr[role='row'], [role='row'], .p-datatable-row, .card";
            const rows = [...document.querySelectorAll(rowSelector)].filter(isVisible);

            for (const row of rows) {
                const text = row.innerText || row.textContent || "";
                if (!digits(text).includes(targetDigits)) {
                    continue;
                }

                const icon = row.querySelector("i.pi-external-link, .pi-external-link");
                const iconAction = icon ? icon.closest("a, button, [role='button']") : null;
                const cells = row.querySelectorAll("td");
                const cgfCell = cells.length > 1 ? cells[1] : null;
                const actions = [...row.querySelectorAll("a, button, [role='button']")].filter(isVisible);
                const target = cgfCell || iconAction || actions[0] || row;
                target.scrollIntoView({block: "center", inline: "center"});
                target.click();
                return true;
            }
            return false;
        }
        """
        try:
            clicked = bool(page.evaluate(script, target_digits))
        except Error as exc:
            LOGGER.warning("O fallback por DOM não conseguiu clicar na linha do contribuinte %s: %s", target_digits, exc)
            return False
        if clicked:
            LOGGER.info("Abrindo os detalhes do contribuinte usando o fallback por DOM para os dígitos %s", target_digits)
        return clicked

    def _go_to_next_contributor_page(self, page: Page) -> bool:
        candidates = (
            page.locator("button.p-paginator-next:not([disabled]):not(.p-disabled)"),
            page.locator("xpath=//button[contains(@class,'p-paginator-next') and not(@disabled) and not(contains(@class,'p-disabled'))]"),
            page.get_by_role("button", name=re.compile(r"proxima|next", re.IGNORECASE)),
        )
        for locator in candidates:
            target = self._first_visible_enabled(locator)
            if target is None:
                continue
            target.click()
            page.wait_for_timeout(1_000)
            return True
        return False

    def _go_to_first_contributor_page(self, page: Page) -> None:
        candidates = (
            page.locator("button.p-paginator-first:not([disabled]):not(.p-disabled)"),
            page.locator("xpath=//button[contains(@class,'p-paginator-first') and not(@disabled) and not(contains(@class,'p-disabled'))]"),
            page.get_by_role("button", name=re.compile(r"primeira|first", re.IGNORECASE)),
        )
        for locator in candidates:
            target = self._first_visible_enabled(locator)
            if target is None:
                continue
            target.click()
            page.wait_for_timeout(1_000)
            return

    def _open_fiscal_information(self, page: Page) -> None:
        """Entra na área de informações fiscais antes de escolher a aba de documento."""
        LOGGER.info("Abrindo Informações Fiscais")
        self._ensure_side_menu_open(page)
        if self._click_xpath(
            page,
            "xpath=//a[contains(@href,'/informacoes-fiscais')]",
            "Menu lateral Informações Fiscais",
        ):
            page.wait_for_timeout(1_000)
            return

        self._click_text_action(
            page,
            names=("Informacoes Fiscais", "Informacoes fiscais"),
            artifact_name="informacoes-fiscais",
            fallback_task="Localize e clique na seção, aba ou botão chamado Informações Fiscais.",
        )
        page.wait_for_timeout(1_000)

    # ------------------------------------------------------------------
    # Métodos dedicados para Malha Fiscal e Débitos Fiscais
    # ------------------------------------------------------------------

    def _request_malha_fiscal(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        taxpayer_folder_name: str,
        row_number: int = 0,
    ) -> "PendingDetailRequest | None":
        """Navega até Malha Fiscal, solicita o download de indícios e retorna a
        solicitação pendente para ser resgatada na Central de Downloads.

        Fluxo:
            1. Abre o menu lateral e clica em "Malha Fiscal".
            2. Localiza o botão "Baixar todos os indícios (XLSX)" e clica.
            3. Aguarda a mensagem de confirmação de solicitação do download.
            4. Retorna um PendingDetailRequest apontando para a Central de Downloads.
        """
        import time as _time
        LOGGER.info("Iniciando extração de Malha Fiscal para o CNPJ %s", cgf)
        narrate("Solicitando o relatório de Malha Fiscal do CNPJ %s...", self._format_cnpj(cgf))
        self._ensure_side_menu_open(page)

        # --- Navegar até Malha Fiscal ---
        if not self._click_xpath(
            page,
            "xpath=//a[contains(@href,'/malha-fiscal') or contains(normalize-space(.),'Malha Fiscal')]",
            "Menu lateral Malha Fiscal",
        ):
            self._click_text_action(
                page,
                names=("Malha Fiscal",),
                artifact_name="malha-fiscal",
                fallback_task="Localize e clique no item de menu chamado 'Malha Fiscal'.",
            )
        page.wait_for_timeout(1_500)

        # --- Clicar em Baixar todos os indícios (XLSX) ---
        baixar_clicked = self._click_xpath(
            page,
            "xpath=//button[contains(normalize-space(.),'Baixar todos os ind') or contains(@title,'Baixar todos os ind')]",
            "Botão Baixar todos os indícios XLSX",
        )
        if not baixar_clicked:
            self._click_text_action(
                page,
                names=("Baixar todos os indicios",),
                artifact_name="malha-fiscal-baixar-indicios",
                fallback_task=(
                    "Em 'Indícios de irregularidades', localize o botão "
                    "'Baixar todos os indícios (XLSX)' e clique nele."
                ),
            )

        # --- Aguardar a mensagem de confirmação do toast ---
        LOGGER.info("Aguardando confirmação de solicitação de download de Malha Fiscal")
        toast_messages = (
            "solicitacao de download foi realizada",
            "solicitacao de download ja foi realizada",
        )
        requested_after = datetime.now() - timedelta(seconds=30)
        deadline = _time.time() + 30
        while _time.time() < deadline:
            try:
                body_text = strip_accents(page.locator("body").inner_text(timeout=3_000)).lower()
                if any(msg in body_text for msg in toast_messages):
                    LOGGER.info("Confirmação de download de Malha Fiscal recebida")
                    narrate_success("Download de Malha Fiscal solicitado com sucesso.")
                    break
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(500)

        # Normalizar o CNPJ para 14 dígitos (obrigatório para o título do arquivo)
        cnpj_digits = self._normalize_numeric_document(cgf).zfill(14)
        # O título na Central de Downloads segue o padrão:
        # "Malha Fiscal - Visão Geral - Indícios de Irregularidades - <CNPJ14>"
        tela_aba = f"Malha Fiscal - Visão Geral - Indícios de Irregularidades - {cnpj_digits}"

        return self._build_pending_request(
            cgf=cgf,
            month_reference=month_reference,
            document_tab="Malha Fiscal",
            profile_name="Indícios",
            summary_path=None,
            report_name="malha-fiscal-indicios",
            tela_aba=tela_aba,
            requested_after=requested_after,
            taxpayer_document=cgf,
            taxpayer_folder_name=taxpayer_folder_name,
            row_number=row_number,
        )

    def _request_debitos_fiscais(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        taxpayer_folder_name: str,
        row_number: int = 0,
    ) -> "PendingDetailRequest | None":
        """Navega até Débitos Fiscais, solicita o download e retorna a
        solicitação pendente para ser resgatada na Central de Downloads.

        Fluxo:
            1. Abre o menu lateral e clica em "Débitos Fiscais".
            2. Localiza o botão de download (XLSX) e clica.
            3. Aguarda a mensagem de confirmação de solicitação do download.
            4. Retorna um PendingDetailRequest apontando para a Central de Downloads.
        """
        import time as _time
        LOGGER.info("Iniciando extração de Débitos Fiscais para o CNPJ %s", cgf)
        narrate("Solicitando o relatório de Débitos Fiscais do CNPJ %s...", self._format_cnpj(cgf))
        self._ensure_side_menu_open(page)

        # --- Navegar até Débitos Fiscais ---
        if not self._click_xpath(
            page,
            "xpath=//a[contains(@href,'/debitos-fiscais') or contains(normalize-space(.),'Débitos Fiscais') or contains(normalize-space(.),'Debitos Fiscais')]",
            "Menu lateral Débitos Fiscais",
        ):
            self._click_text_action(
                page,
                names=("Débitos Fiscais", "Debitos Fiscais"),
                artifact_name="debitos-fiscais",
                fallback_task="Localize e clique no item de menu chamado 'Débitos Fiscais'.",
            )
        page.wait_for_timeout(1_500)

        # --- Clicar no botão de download (XLSX) ---
        baixar_clicked = self._click_xpath(
            page,
            "xpath=//button[contains(normalize-space(.),'Baixar') and (contains(normalize-space(.),'XLSX') or contains(normalize-space(.),'Excel') or contains(@title,'Baixar'))]",
            "Botão download Débitos Fiscais XLSX",
        )
        if not baixar_clicked:
            self._click_text_action(
                page,
                names=("Baixar XLSX", "Baixar Excel", "Download"),
                artifact_name="debitos-fiscais-baixar",
                fallback_task=(
                    "Na tela de Débitos Fiscais, localize o botão para baixar em XLSX ou Excel e clique nele."
                ),
            )

        # --- Aguardar a mensagem de confirmação do toast ---
        LOGGER.info("Aguardando confirmação de solicitação de download de Débitos Fiscais")
        toast_messages = (
            "solicitacao de download foi realizada",
            "solicitacao de download ja foi realizada",
        )
        requested_after = datetime.now() - timedelta(seconds=30)
        deadline = _time.time() + 30
        while _time.time() < deadline:
            try:
                body_text = strip_accents(page.locator("body").inner_text(timeout=3_000)).lower()
                if any(msg in body_text for msg in toast_messages):
                    LOGGER.info("Confirmação de download de Débitos Fiscais recebida")
                    narrate_success("Download de Débitos Fiscais solicitado com sucesso.")
                    break
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(500)

        # Normalizar o CNPJ para 14 dígitos (obrigatório para o título do arquivo)
        cnpj_digits = self._normalize_numeric_document(cgf).zfill(14)
        # O título na Central de Downloads segue o padrão: "Débitos Fiscais - <CNPJ14>"
        tela_aba = f"Débitos Fiscais - {cnpj_digits}"

        return self._build_pending_request(
            cgf=cgf,
            month_reference=month_reference,
            document_tab="Débitos Fiscais",
            profile_name="Débitos",
            summary_path=None,
            report_name="debitos-fiscais",
            tela_aba=tela_aba,
            requested_after=requested_after,
            taxpayer_document=cgf,
            taxpayer_folder_name=taxpayer_folder_name,
            row_number=row_number,
        )

    def _build_fiscal_tab_configs(self) -> tuple[FiscalTabConfig, ...]:
        return (
            FiscalTabConfig(
                tab_name="NF-e",
                tab_slug="NF-e",
                tab_xpath="xpath=//a[contains(@href,'/informacoes-fiscais/nfe')]",
                detail_mode="reports",
                month_requires_positive_value=False,
                profiles=(
                    FiscalProfileConfig(
                        label="Emissor",
                        summary_basename="resumo-emissor",
                        annual_quantity_label=(
                            "Quantidade Total de Documentos Emitidos pelo Contribuinte no Ano"
                        ),
                        annual_value_label=(
                            "Valor Total de Documentos Emitidos pelo Contribuinte no Ano"
                        ),
                    ),
                    FiscalProfileConfig(
                        label="Destinatario",
                        summary_basename="resumo-destinatario",
                        annual_quantity_label=(
                            "Quantidade Total de Documentos Emitidos para o Contribuinte no Ano"
                        ),
                        annual_value_label=(
                            "Valor Total de Documentos Emitidos para o Contribuinte no Ano"
                        ),
                    ),
                ),
            ),
            FiscalTabConfig(
                tab_name="NFC-e",
                tab_slug="NFC-e",
                tab_xpath="xpath=//a[contains(@href,'/informacoes-fiscais/nfce')]",
                detail_mode="authorized",
                month_requires_positive_value=False,
                detail_label=None,
                profiles=(
                    FiscalProfileConfig(
                        label="Emissor",
                        summary_basename="resumo-emissor",
                        annual_quantity_label=(
                            "Quantidade Total de Documentos Autorizados e Emitidos pelo Contribuinte no Ano"
                        ),
                        annual_value_label=(
                            "Valor Total de Documentos Autorizados e Emitidos pelo Contribuinte no Ano"
                        ),
                    ),
                    FiscalProfileConfig(
                        label="Destinatario",
                        summary_basename="resumo-destinatario",
                        annual_quantity_label=(
                            "Quantidade Total de Documentos Autorizados e Emitidos para o Contribuinte no Ano"
                        ),
                        annual_value_label=(
                            "Valor Total de Documentos Autorizados e Emitidos para o Contribuinte no Ano"
                        ),
                    ),
                ),
            ),
            FiscalTabConfig(
                tab_name="CT-e",
                tab_slug="CT-e",
                tab_xpath="xpath=//a[contains(@href,'/informacoes-fiscais/cte')]",
                detail_mode="authorized",
                month_requires_positive_value=False,
                detail_label=None,
                profiles=(
                    FiscalProfileConfig(
                        label="Emissor",
                        display_label="Emitente",
                        summary_basename="resumo-emissor",
                        annual_quantity_label=(
                            "Quantidade Total de Documentos Emitidos pelo Contribuinte no Ano"
                        ),
                        annual_value_label=(
                            "Valor Total de Documentos Emitidos pelo Contribuinte no Ano"
                        ),
                    ),
                    FiscalProfileConfig(
                        label="Tomador",
                        summary_basename="resumo-tomador",
                        annual_quantity_label=(
                            "Quantidade Total de Documentos Emitidos para o Contribuinte no Ano"
                        ),
                        annual_value_label=(
                            "Valor Total de Documentos Emitidos para o Contribuinte no Ano"
                        ),
                    ),
                ),
            ),
        )

    def _open_document_tab(self, page: Page, tab_config: FiscalTabConfig) -> None:
        """Seleciona a aba fiscal correta, usando XPath primeiro e texto como fallback."""
        LOGGER.info("Abrindo a aba fiscal %s", tab_config.tab_name)
        narrate("Abrindo a aba %s...", tab_config.tab_name)
        if self._click_xpath(page, tab_config.tab_xpath, f"{tab_config.tab_name} tab"):
            page.wait_for_timeout(1_000)
            return

        self._click_text_action(
            page,
            names=(tab_config.tab_name,),
            artifact_name=f"tab-{slugify(tab_config.tab_name)}",
            fallback_task=f"Localize e clique na aba fiscal chamada {tab_config.tab_name}.",
        )
        page.wait_for_timeout(1_000)

    def _open_named_section(self, page: Page, label: str) -> None:
        """Abre uma seção interna como Emissor, Destinatário, Tomador ou Emitente."""
        LOGGER.info("Abrindo a seção fiscal %s", label)
        narrate("Abrindo a seção %s...", label)
        normalized_label = strip_accents(label).lower()
        if normalized_label == "emissor" and self._click_xpath(
            page,
            "xpath=//*[@role='radio' and contains(@aria-label,'Emissor')]",
            "Emissor radio",
            force=True,
        ):
            page.wait_for_timeout(1_000)
            return
        if normalized_label == "destinatario" and self._click_xpath(
            page,
            "xpath=//*[@role='radio' and contains(@aria-label,'Destinat')]",
            "Destinatario radio",
            force=True,
        ):
            page.wait_for_timeout(1_000)
            return
        if normalized_label == "tomador" and self._click_xpath(
            page,
            "xpath=//*[@role='radio' and contains(@aria-label,'Tomador')]",
            "Tomador radio",
            force=True,
        ):
            page.wait_for_timeout(1_000)
            return
        if normalized_label == "emitente" and self._click_xpath(
            page,
            "xpath=//*[@role='radio' and contains(@aria-label,'Emitente')]",
            "Emitente radio",
            force=True,
        ):
            page.wait_for_timeout(1_000)
            return

        self._click_text_action(
            page,
            names=(label,),
            artifact_name=f"section-{slugify(label)}",
            fallback_task=f"Localize e clique na seção fiscal chamada {label}.",
        )
        page.wait_for_timeout(1_000)

    def open_reference_month_if_positive(
        self,
        page: Page,
        month_reference: str,
        require_positive_value: bool = True,
    ) -> MonthOpenDecision:
        LOGGER.info("Verificando o mês de referência %s antes de abri-lo", month_reference)
        self._wait_for_month_reference_table(page, month_reference)
        metric = None
        last_error: TimeoutError | None = None
        for attempt in range(1, 7):
            try:
                metric = self._get_indicator_metric(page, month_reference)
            except TimeoutError as exc:
                last_error = exc
                metric = None

            if metric is not None:
                break

            if attempt < 6:
                LOGGER.info(
                    "O mês de referência %s ainda não está pronto (tentativa %s/6); aguardando antes de tentar novamente.",
                    month_reference,
                    attempt,
                )
                self._wait_for_month_reference_table(page, month_reference, timeout_seconds=5)
                page.wait_for_timeout(1_000)

        if metric is None:
            raise TimeoutError(f"Nao foi possivel localizar o mes de referencia {month_reference}.") from last_error

        if metric.qtd <= 0 or (require_positive_value and metric.valor <= 0):
            return MonthOpenDecision(
                month_reference=month_reference,
                qtd=metric.qtd,
                valor=metric.valor,
                opened=False,
                reason=(
                    "QTD nao e positivo"
                    if not require_positive_value
                    else "QTD e VALOR R$ nao sao positivos"
                ),
            )

        self._open_reference_month(page, month_reference)
        return MonthOpenDecision(
            month_reference=month_reference,
            qtd=metric.qtd,
            valor=metric.valor,
            opened=True,
            reason="Mes aberto com sucesso",
        )

    def _wait_for_month_reference_table(
        self,
        page: Page,
        month_reference: str,
        timeout_seconds: int = 12,
    ) -> None:
        """Espera a tabela do mes aparecer antes de tentar ler os indicadores."""
        normalized_month = strip_accents(month_reference).lower()
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                body_text = strip_accents(page.locator("body").inner_text(timeout=3_000)).lower()
                if normalized_month in body_text:
                    return
            except Error:
                pass

            rows = page.locator("tr, [role='row'], .p-datatable-row, .card, .p-accordion-header")
            try:
                row_count = rows.count()
            except Error:
                row_count = 0

            for index in range(row_count):
                row = rows.nth(index)
                try:
                    if not row.is_visible():
                        continue
                    text = strip_accents(row.inner_text(timeout=1_500)).lower()
                except Error:
                    continue
                if normalized_month in text:
                    return

            page.wait_for_timeout(500)

    def _open_reference_month(self, page: Page, month_reference: str) -> None:
        LOGGER.info("Abrindo o mês de referência %s", month_reference)
        page.wait_for_timeout(750)
        month_xpath = (
            f"xpath=//tr[.//span[normalize-space()='{month_reference}']]//td[1]//div"
        )
        if self._click_xpath(page, month_xpath, f"month row {month_reference}"):
            page.wait_for_timeout(1_000)
            return

        normalized_month = strip_accents(month_reference).lower()

        candidates = (
            page.get_by_role("button", name=re.compile(re.escape(month_reference), re.IGNORECASE)),
            page.get_by_role("link", name=re.compile(re.escape(month_reference), re.IGNORECASE)),
            page.get_by_text(re.compile(re.escape(month_reference), re.IGNORECASE)),
        )
        for locator in candidates:
            target = self._first_visible_enabled(locator)
            if target is not None:
                target.click()
                page.wait_for_timeout(1_000)
                return

        rows = page.locator("tr, [role='row'], .p-datatable-row, .card, .p-accordion-header")
        try:
            row_count = rows.count()
        except Error:
            row_count = 0
        for index in range(row_count):
            row = rows.nth(index)
            try:
                text = strip_accents(row.inner_text(timeout=2_000)).lower()
            except Error:
                continue
            if normalized_month in text:
                row.click()
                page.wait_for_timeout(1_000)
                return

        page.wait_for_timeout(750)
        rows = page.locator("tr, [role='row'], .p-datatable-row, .card, .p-accordion-header")
        try:
            row_count = rows.count()
        except Error:
            row_count = 0
        for index in range(row_count):
            row = rows.nth(index)
            try:
                text = strip_accents(row.inner_text(timeout=2_000)).lower()
            except Error:
                continue
            if normalized_month in text:
                row.click()
                page.wait_for_timeout(1_000)
                return

        script = """
        (targetMonth) => {
            const normalize = (value) => String(value || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();

            const wanted = normalize(targetMonth);
            const candidates = [...document.querySelectorAll("tr, [role='row'], .p-datatable-row, .card")];

            for (const row of candidates) {
                const rowText = normalize(row.innerText || row.textContent || "");
                if (!rowText || !rowText.includes(wanted)) {
                    continue;
                }

                const clickableElements = [
                    ...row.querySelectorAll("td, button, a, span, div"),
                ];
                for (const element of clickableElements) {
                    const elementText = normalize(
                        element.innerText || element.textContent || element.getAttribute("aria-label") || element.getAttribute("title")
                    );
                    if (elementText === wanted || elementText.includes(wanted)) {
                        element.scrollIntoView({block: "center", inline: "center"});
                        element.click();
                        return true;
                    }
                }

                row.scrollIntoView({block: "center", inline: "center"});
                row.click();
                return true;
            }

            return false;
        }
        """
        try:
            if bool(page.evaluate(script, month_reference)):
                page.wait_for_timeout(1_000)
                return
        except Error:
            pass

        raise TimeoutError(f"Nao foi possivel localizar o mes de referencia {month_reference}.")

    def _wait_for_detail_xlsx_button_ready(self, page: Page) -> Locator:
        """Espera o splitbutton de detalhamento renderizar e ficar clicavel antes do clique."""
        LOGGER.info("Aguardando o botão de detalhamento Baixar Tabela (XLSX) ficar pronto")
        deadline = time.time() + 35
        candidates = (
            page.locator(
                "button.p-element.p-splitbutton-defaultbutton.p-button.p-component.ng-star-inserted"
            ),
            page.locator("xpath=//button[contains(@class,'p-splitbutton-defaultbutton')]"),
            page.get_by_role("button", name=re.compile(r"Baixar Tabela\s*\(XLSX\)", re.IGNORECASE)),
        )

        last_error: Error | None = None
        last_status: str | None = None
        while time.time() < deadline:
            status = self._describe_detail_xlsx_button_state(page)
            status_text = status.get("summary", "")
            if status_text and status_text != last_status:
                LOGGER.info("Estado do botão de detalhamento: %s", status_text)
                last_status = status_text
            if status.get("ready"):
                for locator in candidates:
                    try:
                        count = locator.count()
                    except Error as exc:
                        last_error = exc
                        continue

                    for index in range(count):
                        candidate = locator.nth(index)
                        try:
                            if candidate.is_visible() and candidate.is_enabled():
                                LOGGER.info("Botão Baixar Tabela (XLSX) pronto para clique")
                                return candidate
                        except Error as exc:
                            last_error = exc
                            continue

            for locator in candidates:
                try:
                    count = locator.count()
                except Error as exc:
                    last_error = exc
                    continue

                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        if candidate.is_visible() and candidate.is_enabled():
                            return candidate
                    except Error as exc:
                        last_error = exc
                        continue

            page.wait_for_timeout(500)

        raise TimeoutError(
            "Não foi possível aguardar o botão Baixar Tabela (XLSX) ficar visível e clicável."
        ) from last_error

    def _describe_detail_xlsx_button_state(self, page: Page) -> dict[str, object]:
        """Lê o estado atual do splitbutton para ajudar no aguardo e no debug do layout novo."""
        script = """
        () => {
            const normalize = (value) => String(value || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();

            const candidates = [...document.querySelectorAll(
                "button.p-element.p-splitbutton-defaultbutton.p-button.p-component.ng-star-inserted, button.p-splitbutton-defaultbutton, button, a, [role='button']"
            )];
            const matches = [];
            const wantedFragments = ["baixar tabela", "xlsx"];

            for (const element of candidates) {
                const text = normalize(
                    element.innerText ||
                    element.textContent ||
                    element.getAttribute("aria-label") ||
                    element.getAttribute("title")
                );
                if (!text) {
                    continue;
                }
                if (!wantedFragments.every((fragment) => text.includes(fragment))) {
                    continue;
                }

                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                const ready = !!rect.width
                    && !!rect.height
                    && style.display !== "none"
                    && style.visibility !== "hidden"
                    && style.pointerEvents !== "none"
                    && !element.disabled
                    && element.getAttribute("aria-disabled") !== "true";

                matches.push({
                    text,
                    className: element.className || "",
                    ready,
                    visible: !!rect.width && !!rect.height,
                    enabled: !element.disabled && element.getAttribute("aria-disabled") !== "true",
                });
            }

            const readyCount = matches.filter((item) => item.ready).length;
            return {
                count: matches.length,
                ready: readyCount > 0,
                readyCount,
                summary: matches.length
                    ? `${matches.length} candidato(s), ${readyCount} pronto(s)`
                    : "nenhum candidato localizado ainda",
                matches,
            };
        }
        """
        try:
            result = page.evaluate(script)
        except Error as exc:
            return {"count": 0, "ready": False, "readyCount": 0, "summary": f"erro ao inspecionar o botao: {exc}"}
        return result if isinstance(result, dict) else {"count": 0, "ready": False, "readyCount": 0, "summary": "estado desconhecido"}

    def _select_positive_reports(self, page: Page) -> list[str]:
        LOGGER.info("Selecionando relatórios com QTD maior que zero")
        reports = ("Interna", "Interestadual", "Externa")
        metrics = self._collect_indicator_metrics(page, reports)
        selected_reports: list[str] = []
        for report_name in reports:
            metric = metrics.get(report_name.lower())
            # O documento pede liberar o detalhamento quando a quantidade do recorte for positiva.
            if metric and metric["qtd"] > 0:
                selected_reports.append(report_name)

        if selected_reports:
            LOGGER.info("Relatórios positivos selecionados para o download do detalhamento: %s", ", ".join(selected_reports))
            return selected_reports

        LOGGER.info("Nenhuma linha de detalhamento com QTD positiva foi encontrada na página")
        return []

    def _should_download_profile_summary(
        self,
        page: Page,
        tab_config: FiscalTabConfig,
        profile: FiscalProfileConfig,
    ) -> bool:
        if not profile.annual_quantity_label or not profile.annual_value_label:
            return True

        # A tela pode terminar de renderizar os campos em etapas; por isso
        # damos algumas tentativas curtas antes de desistir da métrica anual.
        quantity_value = self._parse_decimal_value(
            self._extract_metric_with_retry(page, profile.annual_quantity_label)
        )
        total_value = self._parse_decimal_value(
            self._extract_metric_with_retry(page, profile.annual_value_label)
        )
        LOGGER.info(
            "Annual totals for %s/%s: quantidade=%s valor=%s",
            tab_config.tab_name,
            profile.label,
            quantity_value,
            total_value,
        )
        return quantity_value > 0 and total_value > 0

    def _request_report_details_for_profile(
        self,
        page: Page,
        cgf: str,
        tab_config: FiscalTabConfig,
        profile: FiscalProfileConfig,
        month_reference: str,
        reference_year: str,
        summary_path: Path,
        taxpayer_folder_name: str,
        row_number: int = 0,
    ) -> list[PendingDetailRequest]:
        positive_reports = self._select_positive_reports(page)
        if not positive_reports:
            LOGGER.info(
                "No positive report rows found for %s/%s in month %s",
                tab_config.tab_name,
                profile.label,
                month_reference,
            )
            return []

        requests: list[PendingDetailRequest] = []
        for report_name in positive_reports:
            self._click_report_by_name(page, report_name)
            page.wait_for_timeout(500)
            tela_aba = self._build_download_screen_name(
                month_reference=month_reference,
                tab_name=tab_config.tab_name,
                view_label=self._display_label(profile.label, profile.display_label),
                detail_label=report_name,
                selected_year=reference_year,
            )
            requested_after = datetime.now() - timedelta(seconds=30)
            self._request_detail_download(page)
            requests.append(
                self._build_pending_request(
                    cgf=cgf,
                    month_reference=month_reference,
                    document_tab=tab_config.tab_slug,
                    profile_name=profile.label,
                    summary_path=summary_path,
                    report_name=report_name,
                    tela_aba=tela_aba,
                    requested_after=requested_after,
                    taxpayer_document=self._current_taxpayer_document(page),
                    taxpayer_folder_name=taxpayer_folder_name,
                    row_number=row_number,
                )
            )
        return requests

    def _display_label(self, label: str, display_label: str | None = None) -> str:
        if display_label:
            return display_label
        if strip_accents(label).lower() == "destinatario":
            return "Destinatario"
        return label

    def _collect_indicator_metrics(self, page: Page, names: tuple[str, ...]) -> dict[str, dict[str, float]]:
        script = """
        (targetNames) => {
            const normalize = (value) => (value || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();
            const parseNumber = (value) => {
                const cleaned = (value || "")
                    .replace(/\\./g, "")
                    .replace(",", ".")
                    .replace(/[^0-9.-]/g, "");
                const parsed = Number(cleaned);
                return Number.isFinite(parsed) ? parsed : 0;
            };
            const wanted = new Set((targetNames || []).map((item) => normalize(item)));
            const results = {};
            const rows = [...document.querySelectorAll("tr")];
            const isVisible = (element) => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                if (!style || style.visibility === "hidden" || style.display === "none") return false;
                return !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
            };

            const parseRows = (rowList) => {
                for (const row of rowList) {
                    const cells = [...row.querySelectorAll("td, th")]
                        .map((cell) => (cell.innerText || cell.textContent || "").trim())
                        .filter(Boolean);
                    if (cells.length < 3) {
                        continue;
                    }
                    const name = normalize(cells[0]);
                    if (!wanted.has(name)) {
                        continue;
                    }
                    results[name] = {
                        qtd: parseNumber(cells[1]),
                        valor: parseNumber(cells[2]),
                    };
                    if (results[name].qtd === 0 && results[name].valor === 0) {
                        const flatText = normalize(row.innerText || row.textContent || "");
                        const currencyMatches = [...flatText.matchAll(/r\\$\\s*([\\d\\.,]+)/gi)];
                        const numberMatches = [...flatText.matchAll(/-?\\d+[\\d\\.,]*/g)].map((match) => match[0]);
                        if (numberMatches.length) {
                            results[name].qtd = parseNumber(numberMatches[0]);
                        }
                        if (currencyMatches.length) {
                            results[name].valor = parseNumber(currencyMatches[0][1]);
                        }
                    }
                }
            };

            parseRows(rows.filter((row) => isVisible(row)));
            if (Object.keys(results).length === 0) {
                parseRows(rows);
            }
            return results;
        }
        """
        try:
            result = page.evaluate(script, list(names))
        except Error:
            result = {}

        if isinstance(result, dict) and result:
            return result

        fallback = self._collect_indicator_metrics_from_rows(page, names)
        if fallback:
            LOGGER.info(
                "Indicator metrics recovered directly from the table rows for %s",
                ", ".join(names),
            )
        return fallback

    def _collect_indicator_metrics_from_rows(self, page: Page, names: tuple[str, ...]) -> dict[str, dict[str, float]]:
        """Lê a tabela visível diretamente quando a varredura em JavaScript nao encontra os dados."""
        wanted = {strip_accents(name).lower() for name in names if name}
        if not wanted:
            return {}

        results: dict[str, dict[str, float]] = {}
        rows = page.locator("tr")
        try:
            row_count = rows.count()
        except Error:
            return {}

        for index in range(row_count):
            row = rows.nth(index)
            try:
                if not row.is_visible():
                    continue
                row_cells = self._row_cell_texts(row)
            except Error:
                continue

            if len(row_cells) < 3:
                continue

            row_name = strip_accents(self._normalize_spaces(row_cells[0])).lower()
            if row_name not in wanted:
                continue

            results[row_name] = {
                "qtd": self._parse_decimal_value(row_cells[1]),
                "valor": self._parse_decimal_value(row_cells[2]),
            }

        return results

    def _get_indicator_metric(self, page: Page, name: str) -> IndicatorMetric | None:
        metrics = self._collect_indicator_metrics(page, (name,))
        metric = metrics.get(strip_accents(name).lower())
        if not metric:
            return None
        return IndicatorMetric(name=name, qtd=float(metric["qtd"]), valor=float(metric["valor"]))

    def _click_report_by_name(self, page: Page, report_name: str) -> None:
        report_xpath = f"xpath=//tr[./td[1][normalize-space()='{report_name}']]/td[1]"
        if self._click_xpath(page, report_xpath, f"detail row {report_name}"):
            page.wait_for_timeout(750)
            self._wait_for_detail_xlsx_button_ready(page)
            return

        try:
            self._click_text_action(
                page,
                names=(report_name,),
                artifact_name=f"report-{slugify(report_name)}",
            fallback_task=f"Localize e clique no relatório chamado {report_name}.",
            )
            page.wait_for_timeout(750)
            self._wait_for_detail_xlsx_button_ready(page)
            return
        except TimeoutError:
            pass

        script = """
        (targetReport) => {
            const normalize = (value) => String(value || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();

            const wanted = normalize(targetReport);
            const candidates = [...document.querySelectorAll("tr, td, span, div, button, a")];

            for (const element of candidates) {
                const text = normalize(
                    element.innerText ||
                    element.textContent ||
                    element.getAttribute("aria-label") ||
                    element.getAttribute("title")
                );
                if (!text || text !== wanted) {
                    continue;
                }
                element.scrollIntoView({block: "center", inline: "center"});
                element.click();
                return true;
            }
            return false;
        }
        """
        try:
            if bool(page.evaluate(script, report_name)):
                page.wait_for_timeout(750)
                self._wait_for_detail_xlsx_button_ready(page)
                return
        except Error:
            pass

        raise TimeoutError(f"Nao foi possivel clicar no detalhamento {report_name}.")

    def _download_current_table(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        taxpayer_folder_name: str,
        basename: str,
        document_tab: str,
    ) -> Path:
        return self._capture_direct_download(page, cgf, month_reference, taxpayer_folder_name, basename, document_tab)

    def _click_download_table_button(self, page: Page) -> None:
        LOGGER.info("Clicando em Baixar Tabela")
        self._click_text_action(
            page,
            names=("Baixar Tabela",),
            artifact_name="baixar-tabela",
            fallback_task="Localize e clique no botão de ação Baixar Tabela.",
        )
        page.wait_for_timeout(750)

    def _click_summary_download_button(self, page: Page) -> None:
        target = self._find_download_button(page, expected_index=0)
        if target is not None:
            LOGGER.info("Clicando no botão de download do resumo")
            target.click()
            page.wait_for_timeout(750)
            return
        self._click_download_table_button(page)

    def _request_detail_download(self, page: Page) -> None:
        target = self._wait_for_detail_xlsx_button_ready(page)
        LOGGER.info("Solicitando o download do detalhamento usando o botão XLSX")
        if not self._click_detail_xlsx_button(page):
            target.click(force=True)
        page.wait_for_timeout(750)

    def _find_download_button(self, page: Page, expected_index: int = 0, button_text: str = "Baixar Tabela") -> Locator | None:
        xpath_locator = page.locator(
            f"xpath=(//button[contains(normalize-space(.),'{button_text}')])[{expected_index + 1}]"
        )
        xpath_target = self._first_visible_enabled(xpath_locator)
        if xpath_target is not None:
            LOGGER.info("Usando seletor XPath para o botão %s no índice %s", button_text, expected_index)
            return xpath_target

        locator = page.get_by_role("button", name=button_text)
        try:
            count = locator.count()
        except Error:
            return None

        visible_buttons: list[Locator] = []
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible() and candidate.is_enabled():
                    visible_buttons.append(candidate)
            except Error:
                continue

        if len(visible_buttons) > expected_index:
            return visible_buttons[expected_index]
        if visible_buttons:
            return visible_buttons[-1]
        return None

    def _click_detail_xlsx_button(self, page: Page) -> bool:
        """Clica diretamente no splitbutton principal do detalhamento."""
        script = """
        () => {
            const normalize = (value) => String(value || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();

            const buttons = [...document.querySelectorAll(
                "button.p-element.p-splitbutton-defaultbutton.p-button.p-component.ng-star-inserted, button.p-splitbutton-defaultbutton"
            )];
            for (const button of buttons) {
                const text = normalize(
                    button.innerText || button.textContent || button.getAttribute("aria-label") || button.getAttribute("title")
                );
                const style = window.getComputedStyle(button);
                const rect = button.getBoundingClientRect();
                const ready = !!rect.width
                    && !!rect.height
                    && style.display !== "none"
                    && style.visibility !== "hidden"
                    && style.pointerEvents !== "none"
                    && !button.disabled
                    && button.getAttribute("aria-disabled") !== "true";

                if (text.includes("baixar tabela") && text.includes("xlsx") && ready) {
                    button.scrollIntoView({block: "center", inline: "center"});
                    button.click();
                    return true;
                }
            }
            return false;
        }
        """
        try:
            return bool(page.evaluate(script))
        except Error:
            return False

    def _capture_direct_download(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        taxpayer_folder_name: str,
        basename: str,
        document_tab: str,
    ) -> Path:
        attempts = max(1, self.settings.download_retry_count)
        last_error: TimeoutError | None = None

        # O download direto recebe uma segunda chance antes de cair para a Central de Downloads.
        for attempt in range(1, attempts + 1):
            try:
                with page.expect_download(timeout=self.settings.download_wait_timeout_ms) as download_info:
                    self._click_summary_download_button(page)
                download = download_info.value
                return self._save_download(download, taxpayer_folder_name, month_reference, basename, document_tab)
            except TimeoutError as exc:
                last_error = exc
                if attempt < attempts:
                    LOGGER.warning(
                        "O download direto para %s nao iniciou na tentativa %s/%s; tentando novamente em %s ms.",
                        basename,
                        attempt,
                        attempts,
                        self.settings.download_retry_delay_ms,
                    )
                    page.wait_for_timeout(self.settings.download_retry_delay_ms)
                    continue

        LOGGER.info("O download direto nao iniciou apos %s tentativa(s) para %s", attempts, basename)
        if last_error is not None:
            LOGGER.debug("Ultimo erro do download direto para %s: %s", basename, last_error)
        return self._download_from_download_center(page, cgf, month_reference, taxpayer_folder_name, basename, document_tab)

    def _download_from_download_center(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        taxpayer_folder_name: str,
        basename: str,
        document_tab: str,
    ) -> Path:
        request = self._build_pending_request(
            cgf=cgf,
            month_reference=month_reference,
            document_tab=document_tab,
            profile_name="unknown",
            summary_path=Path("."),
            report_name=basename,
            tela_aba=basename,
            requested_after=datetime.min,
            taxpayer_document=self._current_taxpayer_document(page),
            taxpayer_folder_name=taxpayer_folder_name,
        )
        detail_paths = self._download_pending_detail_requests(page, [request])
        return detail_paths[request.request_key]

    def _download_pending_detail_requests(
        self,
        page: Page,
        pending_requests: list[PendingDetailRequest],
        context: BrowserContext | None = None,
        fallback_taxpayer_cnpj: str | None = None,
    ) -> dict[str, Path]:
        origin_url = page.url
        LOGGER.info("Abrindo o menu de Downloads para buscar %s arquivo(s) de detalhamento pendente(s)", len(pending_requests))
        narrate("Abrindo a Central de Downloads para buscar %s arquivo(s)...", len(pending_requests))
        page = self._prepare_downloads_context(page, context, fallback_taxpayer_cnpj)
        self._ensure_side_menu_open(page)
        if self._click_xpath(
            page,
            "xpath=//a[contains(@href,'/downloads-assincronos')]",
            "Menu lateral Downloads",
        ):
            page.wait_for_timeout(1_000)
        else:
            self._click_text_action(
                page,
                names=("Downloads",),
                artifact_name="downloads",
                fallback_task="Localize e clique na área Downloads no menu lateral.",
            )
            page.wait_for_timeout(1_000)

        # Reduz o numero de paginas a percorrer na varredura (ver PLANO_CORRECOES.md item 27).
        self._select_max_downloads_page_size(page)

        targets = self._build_download_lookup_targets(pending_requests)
        matches = self._find_pending_download_matches(page, targets)
        detail_paths = self._download_found_pending_requests(
            page,
            targets,
            matches,
        )

        page.goto(origin_url, wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
        page.wait_for_timeout(1_000)
        return detail_paths

    def _prepare_downloads_context(
        self,
        page: Page,
        context: BrowserContext | None,
        fallback_taxpayer_cnpj: str | None,
    ) -> Page:
        """Garante um contexto autenticado com menu lateral valido antes de abrir Downloads."""
        page_state = self._describe_authenticated_page_state(page)
        LOGGER.info("Validando o contexto atual antes de abrir Downloads: %s", page_state)

        self._ensure_side_menu_open(page)
        if self._has_downloads_menu_entry(page):
            return page

        if context is not None:
            page = self._ensure_authenticated(page, context)
            self._ensure_side_menu_open(page)
            if self._has_downloads_menu_entry(page):
                return page

        if context is not None and fallback_taxpayer_cnpj:
            # Se a ultima pesquisa terminou fora de um contribuinte, reabrimos um CNPJ
            # valido apenas para recuperar o menu lateral autenticado de Downloads.
            LOGGER.info(
                "O menu de Downloads nao ficou disponivel no estado '%s'; reabrindo o ultimo CNPJ localizado com sucesso (%s).",
                page_state,
                fallback_taxpayer_cnpj,
            )
            self._open_taxpayer_from_home(page, fallback_taxpayer_cnpj)
            self._ensure_side_menu_open(page)
            if self._has_downloads_menu_entry(page):
                return page

        self._save_debug_snapshot(page, "downloads-context-unavailable")
        raise TimeoutError(
            "Nao foi possivel preparar um contexto valido com o menu Downloads Assincronos disponivel."
        )

    def _has_downloads_menu_entry(self, page: Page) -> bool:
        """Confirma se o item Downloads ja esta visivel no menu lateral atual."""
        candidates = (
            page.locator("xpath=//a[contains(@href,'/downloads-assincronos')]"),
            page.get_by_role("link", name=re.compile(r"downloads", re.IGNORECASE)),
            page.get_by_role("button", name=re.compile(r"downloads", re.IGNORECASE)),
        )
        for locator in candidates:
            if self._first_visible_enabled(locator) is not None:
                return True
        return False

    def _describe_authenticated_page_state(self, page: Page) -> str:
        """Resume o estado visivel da pagina para orientar o fallback de navegacao."""
        if "/contribuinte/" in page.url:
            return "dentro-de-contribuinte"
        if self._has_taxpayer_search(page):
            try:
                body_text = strip_accents(page.locator("body").inner_text(timeout=2_000)).lower()
            except Error:
                body_text = ""
            if any(
                marker in body_text
                for marker in (
                    "nenhum registro",
                    "nenhum resultado",
                    "nao ha registros",
                    "nao foram encontrados",
                )
            ):
                return "pesquisa-sem-resultado"
            return "lista-de-contribuintes"
        return "rota-autenticada-sem-contexto-de-contribuinte"

    def _build_download_lookup_targets(
        self,
        pending_requests: list[PendingDetailRequest],
    ) -> list[DownloadLookupTarget]:
        """Prepara os filtros uma unica vez antes de varrer a Central de Downloads."""
        targets: list[DownloadLookupTarget] = []
        for request in pending_requests:
            targets.append(
                DownloadLookupTarget(
                    request=request,
                    normalized_target=self._normalize_download_target(request.tela_aba),
                    match_fragments=self._extract_download_match_fragments_from_title(request.tela_aba),
                    taxpayer_base_key=self._taxpayer_base_key(request.taxpayer_document),
                )
            )
        return targets

    def _pending_request_labels(self, targets: list[DownloadLookupTarget], request_keys: list[str]) -> list[str]:
        """Traduz as chaves internas em labels legiveis para os logs do lote."""
        labels_by_key = {
            target.request.request_key: f"{self._normalize_numeric_document(target.request.taxpayer_cnpj)} - {target.request.tela_aba}"
            for target in targets
        }
        return [labels_by_key.get(request_key, request_key) for request_key in request_keys]

    def _find_pending_download_matches(
        self,
        page: Page,
        targets: list[DownloadLookupTarget],
    ) -> dict[str, DownloadRowMatch]:
        """Varre todas as paginas e escolhe o melhor match por solicitacao."""
        deadline = time.time() + (self.settings.download_wait_timeout_ms / 1000)
        target_keys = {target.request.request_key for target in targets}
        # Acumula os matches ja confirmados (preferidos) entre ciclos: uma vez resolvida, uma
        # solicitacao nao precisa ser reprocurada nos ciclos de espera seguintes, entao os ciclos
        # seguintes varrem menos alvos (e param de paginar mais cedo) enquanto o restante ainda
        # esta em processamento no SIGA.
        resolved_matches: dict[str, DownloadRowMatch] = {}
        latest_matches: dict[str, DownloadRowMatch] = {}
        all_settled = False

        while time.time() < deadline:
            pending_targets = [
                target for target in targets
                if target.request.request_key not in resolved_matches
            ]
            if not pending_targets:
                all_settled = True
                break

            # Varredura intermediaria: pode parar cedo assim que todas as solicitacoes pendentes
            # forem avistadas, pois aqui so precisamos saber se algo ainda esta em processamento.
            cycle_matches, processing_counts = self._scan_downloads_table_once(page, pending_targets)
            for request_key, match in cycle_matches.items():
                if match.preferred:
                    resolved_matches[request_key] = match
            latest_matches = {**resolved_matches, **cycle_matches}

            waiting_keys = [
                key
                for key in self._download_keys_still_processing(pending_targets, cycle_matches, processing_counts)
                if key not in resolved_matches
            ]
            if not waiting_keys:
                all_settled = True
                break

            delay_ms = 1_500 if len(waiting_keys) <= 2 else 2_000
            LOGGER.info(
                "Downloads ainda em processamento para %s; nova varredura em %s ms.",
                ", ".join(self._pending_request_labels(targets, waiting_keys)),
                delay_ms,
            )
            self._nudge_session_activity(page)
            page.wait_for_timeout(delay_ms)
            page.reload(wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
            page.wait_for_timeout(750)
            # O reload da SPA reseta o paginador para o tamanho padrao; reaplica o maximo.
            self._select_max_downloads_page_size(page)

        if all_settled:
            # Antes de retornar, faz uma varredura completa (sem parada antecipada) com todos os
            # alvos originais, para garantir a resolucao de duplicatas em paginas posteriores,
            # independentemente da ordenacao da Central de Downloads.
            latest_matches, _ = self._scan_downloads_table_once(page, targets, full_scan=True)
            missing_keys = sorted(target_keys - set(latest_matches.keys()))
            if missing_keys:
                LOGGER.warning(
                    "Downloads nao localizados apos a varredura completa: %s",
                    ", ".join(self._pending_request_labels(targets, missing_keys)),
                )
        elif latest_matches:
            LOGGER.warning(
                "A Central de Downloads expirou antes de concluir todas as linhas pendentes; usando os matches encontrados ate agora."
            )

        return latest_matches

    def _nudge_session_activity(self, page: Page) -> None:
        """Simula uma pequena interacao do usuario (Page Down/Page Up) para evitar que a sessao
        do SIGA seja encerrada por inatividade durante as esperas prolongadas na Central de
        Downloads (o reload por si so e trafego de rede, mas pode nao contar como interacao para
        o detector de inatividade client-side do portal)."""
        with suppress(Error):
            page.keyboard.press("PageDown")
            page.wait_for_timeout(150)
            page.keyboard.press("PageUp")

    def _scan_downloads_table_once(
        self,
        page: Page,
        targets: list[DownloadLookupTarget],
        full_scan: bool = False,
    ) -> tuple[dict[str, DownloadRowMatch], dict[str, int]]:
        """Le as paginas necessarias e monta o melhor match por TELA/ABA.

        A paginacao da Central de Downloads e estavel durante a espera: todas as solicitacoes
        deste lote ja foram feitas antes de abrir a tela, entao nenhuma linha nova aparece e cada
        solicitacao ocupa exatamente uma linha; apenas o status muda de "processando" para
        "concluido" no lugar. Por isso, nas varreduras intermediarias, assim que todas as
        solicitacoes tiverem sido localizadas (como concluidas ou ainda em processamento), as
        paginas seguintes nao contem nada de interesse e a varredura pode parar, evitando o custo
        quadratico de reler paginas finais vazias a cada ciclo de espera (ver PLANO_CORRECOES.md
        item 16). Com `full_scan=True`, a parada antecipada e desativada e todas as paginas sao
        lidas, garantindo a resolucao de duplicatas antes de retornar o resultado final.

        Adicionalmente, como a Central de Downloads e ordenada por data de solicitacao decrescente
        (mais recente primeiro), quando a data de uma linha for anterior ao inicio do lote atual
        (com 60s de margem), nenhuma linha subsequente pode pertencer a este lote — a paginacao
        para imediatamente. Isso reduz em ~90% o numero de paginas varridas por ciclo quando o
        historico de downloads acumulado e grande.
        """
        matches: dict[str, DownloadRowMatch] = {}
        processing_counts: dict[str, int] = {}
        # Garante que uma mesma linha fisica da tabela nao seja usada como resultado de
        # duas solicitacoes diferentes nesta passada (ver PLANO_CORRECOES.md item 15).
        claimed_rows: dict[tuple[int, int], str] = {}
        # Solicitacoes ja avistadas nesta passada (concluidas ou em processamento).
        located_keys: set[str] = set()
        target_keys = {target.request.request_key for target in targets}

        # Limite inferior de data: linhas mais antigas que este corte nao podem pertencer ao lote
        # atual (a tabela e ordenada do mais novo para o mais antigo). Margem de 60s para absorver
        # pequenas diferencas de relogio e atrasos de exibicao.
        cutoff_dt: datetime | None = None
        if not full_scan and targets:
            from datetime import timedelta
            earliest = min(target.request.requested_after for target in targets)
            cutoff_dt = earliest - timedelta(seconds=60)

        self._go_to_first_downloads_page(page)
        page_number = 1

        while True:
            # Log de progresso a cada pagina: sem isso, uma varredura de muitas linhas fica
            # em silencio por minutos e e indistinguivel de um travamento real (ver
            # PLANO_CORRECOES.md item 29 - motivado por um caso real onde o usuario encerrou
            # o processo pensando que tinha travado).
            LOGGER.info(
                "Varrendo pagina %s da Central de Downloads (full_scan=%s, %s/%s solicitacoes localizadas ate agora)...",
                page_number,
                full_scan,
                len(located_keys),
                len(target_keys),
            )
            narrate(
                "Procurando os arquivos na Central de Downloads (página %s, %s de %s já localizados)...",
                page_number,
                len(located_keys),
                len(target_keys),
            )
            past_cutoff = self._scan_downloads_current_page_for_targets(
                page,
                targets,
                page_number,
                matches,
                processing_counts,
                claimed_rows,
                located_keys,
                cutoff_dt=cutoff_dt,
            )
            # Todas as solicitacoes ja foram encontradas: nao ha motivo para paginar adiante.
            # Como a Central de Downloads e ordenada do mais novo para o mais antigo, qualquer 
            # item nas paginas subsequentes seria mais antigo do que os que ja encontramos.
            if target_keys and located_keys >= target_keys:
                break
            # Corte por timestamp: linha mais antiga que o inicio do lote foi encontrada;
            # nao ha arquivos do lote atual nas paginas seguintes (ordem DESC por data).
            if past_cutoff:
                LOGGER.info(
                    "Corte por timestamp ativado na pagina %s: linhas anteriores ao inicio do lote "
                    "detectadas; interrompendo a varredura (full_scan=%s).",
                    page_number,
                    full_scan,
                )
                break
            if not self._go_to_next_downloads_page(page):
                break
            page_number += 1

        LOGGER.info(
            "Varredura da Central de Downloads concluida: %s/%s solicitacoes localizadas em %s pagina(s).",
            len(located_keys),
            len(target_keys),
            page_number,
        )
        return matches, processing_counts

    def _iter_downloads_table_rows(self, page: Page) -> Iterator[tuple[int, list[str]]]:
        """Itera as linhas visiveis da tabela atual da Central de Downloads como (indice, celulas).

        Tenta uma leitura em lote via JavaScript (uma unica chamada, sem round-trip Selenium por
        linha/celula); recorre a leitura linha a linha via Selenium se o `evaluate` falhar,
        preservando o comportamento original como rede de seguranca (ver
        `_read_downloads_table_rows_js`).
        """
        js_rows = self._read_downloads_table_rows_js(page)
        if js_rows is not None:
            for index, row_cells in enumerate(js_rows, start=1):
                if row_cells is None:
                    continue
                yield index, row_cells
            return

        rows = page.locator("tr")
        try:
            row_count = rows.count()
        except Error:
            row_count = 0

        for index in range(1, row_count):
            row = rows.nth(index)
            try:
                if not row.is_visible():
                    continue
                # Timeout curto por celula: numa varredura em lote (potencialmente dezenas de
                # linhas), uma linha obsoleta apos um re-render nao pode custar o timeout
                # padrao de 2s por celula, senao a espera silenciosa some minutos sem log.
                row_cells = self._row_cell_texts(row, cell_timeout_ms=400)
            except Error:
                continue
            yield index, row_cells

    def _read_downloads_table_rows_js(self, page: Page) -> list[list[str] | None] | None:
        """Le todas as linhas da tabela atual em uma unica chamada JS (uma unica ida ao browser),
        no lugar de um round-trip Selenium por linha/celula (`.is_visible()`, `.inner_text()`).

        Retorna uma lista alinhada com as linhas a partir do indice 1 (pula o cabecalho, igual ao
        loop original), com `None` no lugar de linhas nao visiveis. Retorna `None` (nao uma lista
        vazia) se o `evaluate` falhar, sinalizando ao chamador para usar o fallback linha a linha.
        """
        script = r"""
        () => {
            const isVisible = (el) => {
                if (!el || !el.isConnected) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                    return false;
                }
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            const rows = Array.from(document.querySelectorAll('tr'));
            const result = [];
            for (let i = 1; i < rows.length; i++) {
                const row = rows[i];
                if (!isVisible(row)) {
                    result.push(null);
                    continue;
                }
                const cells = Array.from(row.querySelectorAll('td'));
                result.push(cells.map((cell) => (cell.innerText || cell.textContent || '').replace(/\s+/g, ' ').trim()));
            }
            return result;
        }
        """
        try:
            result = page.evaluate(script)
        except Error:
            return None
        if not isinstance(result, list):
            return None
        return result

    def _scan_downloads_current_page_for_targets(
        self,
        page: Page,
        targets: list[DownloadLookupTarget],
        page_number: int,
        matches: dict[str, DownloadRowMatch],
        processing_counts: dict[str, int],
        claimed_rows: dict[tuple[int, int], str],
        located_keys: set[str],
        cutoff_dt: datetime | None = None,
    ) -> bool:
        """Varre uma pagina da Central de Downloads e atualiza os dicionarios de resultados.

        Retorna True se encontrou alguma linha com data de solicitacao anterior ao corte
        (cutoff_dt), sinalizando que as paginas seguintes tambem so contem historico antigo
        e a varredura pode ser interrompida.
        """
        past_cutoff = False

        for index, row_cells in self._iter_downloads_table_rows(page):
            row_text = self._normalize_download_target(" ".join(row_cells))
            status_text = self._row_status_text(row_cells)
            requested_at = self._row_request_datetime(row_cells)
            row_id = (page_number, index)

            # Corte por timestamp: se a linha for mais antiga que o inicio do lote, sinaliza
            # ao chamador para interromper a paginacao. Continua processando as demais linhas
            # desta pagina (podem existir arquivos do lote antes do corte nesta mesma pagina).
            if cutoff_dt is not None and requested_at != datetime.min and requested_at < cutoff_dt:
                past_cutoff = True

            for target in targets:
                request_key = target.request.request_key

                # Linha ja reivindicada por outra solicitacao nesta passada: nao pode ser
                # reaproveitada, mesmo que os fragmentos de titulo tambem batam com este alvo.
                claimed_by = claimed_rows.get(row_id)
                if claimed_by is not None and claimed_by != request_key:
                    continue

                if not self._row_matches_download_target(
                    row_cells,
                    target.normalized_target,
                    target.match_fragments,
                ):
                    continue
                if target.taxpayer_base_key and not self._row_matches_taxpayer_document(
                    row_cells,
                    target.taxpayer_base_key,
                ):
                    continue

                if any(status_key in status_text for status_key in ("processando", "aguardando", "gerando")):
                    processing_counts[request_key] = processing_counts.get(request_key, 0) + 1
                    located_keys.add(request_key)
                    continue
                if "concluido" not in status_text:
                    continue

                candidate = DownloadRowMatch(
                    request_key=request_key,
                    page_number=page_number,
                    requested_at=requested_at,
                    row_text=row_text,
                    exact_match=self._row_matches_download_target(
                        row_cells,
                        target.normalized_target,
                        target.match_fragments,
                        exact_only=True,
                    ),
                    preferred=requested_at >= target.request.requested_after,
                    score=self._download_match_score(
                        row_text,
                        target.normalized_target,
                        target.match_fragments,
                    ),
                )
                claimed_rows[row_id] = request_key
                located_keys.add(request_key)
                self._store_best_download_match(matches, candidate)

        return past_cutoff

    def _store_best_download_match(
        self,
        matches: dict[str, DownloadRowMatch],
        candidate: DownloadRowMatch,
    ) -> None:
        current = matches.get(candidate.request_key)
        if current is None or self._is_better_download_match(candidate, current):
            matches[candidate.request_key] = candidate

    def _is_better_download_match(
        self,
        candidate: DownloadRowMatch,
        current: DownloadRowMatch,
    ) -> bool:
        candidate_rank = (
            1 if candidate.exact_match else 0,
            1 if candidate.preferred else 0,
            candidate.score,
            candidate.requested_at,
        )
        current_rank = (
            1 if current.exact_match else 0,
            1 if current.preferred else 0,
            current.score,
            current.requested_at,
        )
        return candidate_rank > current_rank

    def _download_keys_still_processing(
        self,
        targets: list[DownloadLookupTarget],
        matches: dict[str, DownloadRowMatch],
        processing_counts: dict[str, int],
    ) -> list[str]:
        """Se houver linha mais nova em processamento, evitamos cair cedo no fallback antigo."""
        waiting_keys: list[str] = []
        for target in targets:
            request_key = target.request.request_key
            if processing_counts.get(request_key, 0) <= 0:
                continue
            current_match = matches.get(request_key)
            if current_match is None or not current_match.preferred:
                waiting_keys.append(request_key)
        return sorted(waiting_keys)

    def _download_found_pending_requests(
        self,
        page: Page,
        targets: list[DownloadLookupTarget],
        matches: dict[str, DownloadRowMatch],
    ) -> dict[str, Path]:
        """Baixa os itens encontrados em lote, paginando apenas por pagina com match."""
        detail_paths: dict[str, Path] = {}
        page_targets: dict[int, list[DownloadLookupTarget]] = {}

        for target in targets:
            request_key = target.request.request_key
            basename = self._build_download_output_basename(target.request.tela_aba)
            match = matches.get(request_key)
            if match is None:
                detail_paths[request_key] = self._save_unavailable_download_notice(
                    cgf=target.request.taxpayer_cnpj,
                    month_reference=target.request.month_reference,
                    basename=basename,
                    document_tab=target.request.document_tab,
                    tela_aba=target.request.tela_aba,
                    taxpayer_folder_name=target.request.taxpayer_folder_name,
                )
                write_status_to_spreadsheet_cell(
                    self.output_spreadsheet_path,
                    target.request.row_number,
                    target.request.document_tab,
                    "Erro: Não localizado na Central de Downloads",
                )
                narrate_warning("Não foi possível localizar o arquivo de %s na Central de Downloads.", target.request.tela_aba)
                continue

            LOGGER.info(
                "Arquivo localizado na Central de Downloads: %s para o CNPJ %s (Solicitado em %s, Página %s)",
                target.request.tela_aba,
                target.request.taxpayer_cnpj,
                match.requested_at.strftime("%d/%m/%Y %H:%M:%S") if match.requested_at else "desconhecido",
                match.page_number,
            )
            narrate(
                "Arquivo localizado na Central: %s (CNPJ: %s)",
                target.request.tela_aba,
                self._normalize_numeric_document(target.request.taxpayer_cnpj),
            )
            page_targets.setdefault(match.page_number, []).append(target)

        if not page_targets:
            return detail_paths

        self._go_to_first_downloads_page(page)
        current_page = 1
        max_page = max(page_targets.keys())

        while current_page <= max_page:
            for target in page_targets.get(current_page, []):
                match = matches[target.request.request_key]
                try:
                    path = self._capture_download_for_match(
                        page=page,
                        target=target,
                        match=match,
                    )
                    detail_paths[target.request.request_key] = path
                    status_str = match.requested_at.strftime("%d/%m/%Y %H:%M:%S") if match.requested_at else datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    write_status_to_spreadsheet_cell(
                        self.output_spreadsheet_path,
                        target.request.row_number,
                        target.request.document_tab,
                        status_str,
                    )
                except Exception as exc:  # noqa: BLE001
                    LOGGER.error("Falha ao baixar %s: %s", target.request.tela_aba, exc)
                    detail_paths[target.request.request_key] = Path(f"__ERROR__:{exc}")
                    write_status_to_spreadsheet_cell(
                        self.output_spreadsheet_path,
                        target.request.row_number,
                        target.request.document_tab,
                        f"Erro: {exc}",
                    )

            if current_page == max_page:
                break
            if not self._advance_to_next_downloads_page_with_retry(page, current_page):
                # A paginacao da Central de Downloads quebrou no meio do lote e a tentativa
                # de recuperacao tambem falhou. Em vez de abortar tudo (perdendo os downloads
                # ja concluidos ate aqui), marca os itens das paginas ainda nao alcancadas como
                # nao localizados e encerra o lote de forma graciosa.
                LOGGER.warning(
                    "Nao foi possivel avancar da pagina %s para a proxima na Central de Downloads "
                    "apos tentativa de recuperacao; marcando os itens restantes como nao localizados.",
                    current_page,
                )
                self._mark_unreached_download_pages_as_unavailable(page_targets, current_page, detail_paths)
                break
            current_page += 1

        return detail_paths

    def _advance_to_next_downloads_page_with_retry(self, page: Page, current_page: int) -> bool:
        """Tenta avancar para a proxima pagina; se falhar, recarrega e reavanca do zero uma vez.

        A Central de Downloads pode ficar momentaneamente instavel (overlay preso, hiccup de
        carregamento) no meio de um lote longo. Uma unica tentativa de recuperacao evita abortar
        o restante do lote por uma falha pontual de paginacao.
        """
        if self._go_to_next_downloads_page(page):
            return True

        LOGGER.warning(
            "Falha ao avancar da pagina %s na Central de Downloads; tentando recuperar com reload.",
            current_page,
        )
        try:
            page.reload(wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
            page.wait_for_timeout(1_000)
        except Error:
            return False

        # O reload da SPA reseta o paginador para o tamanho padrao; reaplica o maximo antes
        # de reavancar, senao o numero de cliques de "proxima pagina" abaixo fica incorreto.
        self._select_max_downloads_page_size(page)

        self._go_to_first_downloads_page(page)
        for _ in range(current_page):
            if not self._go_to_next_downloads_page(page):
                return False
        return True

    def _mark_unreached_download_pages_as_unavailable(
        self,
        page_targets: dict[int, list[DownloadLookupTarget]],
        current_page: int,
        detail_paths: dict[str, Path],
    ) -> None:
        """Registra aviso e status de erro para itens cujas paginas nao puderam ser alcancadas."""
        remaining_pages = sorted(page_number for page_number in page_targets if page_number > current_page)
        for remaining_page in remaining_pages:
            for target in page_targets[remaining_page]:
                request_key = target.request.request_key
                if request_key in detail_paths:
                    continue
                basename = self._build_download_output_basename(target.request.tela_aba)
                detail_paths[request_key] = self._save_unavailable_download_notice(
                    cgf=target.request.taxpayer_cnpj,
                    month_reference=target.request.month_reference,
                    basename=basename,
                    document_tab=target.request.document_tab,
                    tela_aba=target.request.tela_aba,
                    taxpayer_folder_name=target.request.taxpayer_folder_name,
                )
                write_status_to_spreadsheet_cell(
                    self.output_spreadsheet_path,
                    target.request.row_number,
                    target.request.document_tab,
                    "Erro: Falha ao navegar na Central de Downloads",
                )

    def _capture_download_for_match(
        self,
        page: Page,
        target: DownloadLookupTarget,
        match: DownloadRowMatch,
    ) -> Path:
        attempts = max(1, self.settings.download_retry_count)
        last_error: TimeoutError | None = None

        for attempt in range(1, attempts + 1):
            row = self._find_download_row_for_match_on_current_page(page, target, match)
            if row is None:
                raise TimeoutError(
                    f"Nao foi possivel reencontrar a linha '{target.request.tela_aba}' na pagina {match.page_number}."
                )

            basename = self._build_download_output_basename(target.request.tela_aba)
            try:
                with page.expect_download(timeout=self.settings.download_wait_timeout_ms) as download_info:
                    self._click_download_action(row, page=page, tela_aba=target.request.tela_aba)
                download = download_info.value
                output_path = self._save_download(
                    download,
                    target.request.taxpayer_folder_name,
                    target.request.month_reference,
                    basename,
                    target.request.document_tab,
                )
                LOGGER.info(
                    "Download salvo para %s na pagina %s em %s",
                    target.request.tela_aba,
                    match.page_number,
                    output_path,
                )
                narrate_success("Arquivo de %s baixado com sucesso.", target.request.tela_aba)
                return output_path
            except TimeoutError as exc:
                last_error = exc
                if attempt < attempts:
                    LOGGER.warning(
                        "O download de %s nao iniciou na tentativa %s/%s; tentando novamente em %s ms.",
                        target.request.tela_aba,
                        attempt,
                        attempts,
                        self.settings.download_retry_delay_ms,
                    )
                    narrate_warning("O download de %s não iniciou; tentando novamente...", target.request.tela_aba)
                    page.wait_for_timeout(self.settings.download_retry_delay_ms)
                    continue

        if last_error is not None:
            raise last_error
        raise TimeoutError(f"Nao foi possivel baixar '{target.request.tela_aba}'.")

    def _find_download_row_for_match_on_current_page(
        self,
        page: Page,
        target: DownloadLookupTarget,
        match: DownloadRowMatch,
    ) -> Locator | None:
        # Usa a mesma leitura em lote via JS do loop de espera (ver _iter_downloads_table_rows):
        # apenas o indice da melhor linha e resolvido para um Locator real ao final, evitando um
        # round-trip Selenium por linha/celula so para reencontrar a linha antes do clique.
        candidates: list[tuple[int, tuple[int, int, float, datetime, str]]] = []
        for index, row_cells in self._iter_downloads_table_rows(page):
            if not self._row_matches_download_target(
                row_cells,
                target.normalized_target,
                target.match_fragments,
            ):
                continue
            if target.taxpayer_base_key and not self._row_matches_taxpayer_document(
                row_cells,
                target.taxpayer_base_key,
            ):
                continue

            status_text = self._row_status_text(row_cells)
            if "concluido" not in status_text:
                continue

            row_text = self._normalize_download_target(" ".join(row_cells))
            requested_at = self._row_request_datetime(row_cells)
            exact_match = int(
                target.normalized_target in row_text
                or self._normalize_download_target(row_text, strip_marks=True)
                .find(self._normalize_download_target(target.normalized_target, strip_marks=True))
                >= 0
            )
            preferred = int(requested_at >= target.request.requested_after)
            score = self._download_match_score(
                row_text,
                target.normalized_target,
                target.match_fragments,
            )
            candidates.append(
                (
                    index,
                    (
                        exact_match,
                        preferred,
                        score,
                        requested_at,
                        row_text,
                    ),
                )
            )

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[1], reverse=True)
        best_index = candidates[0][0]
        return page.locator("tr").nth(best_index)

    def _click_download_action(self, row: Locator, page: Page | None = None, tela_aba: str | None = None) -> None:
        candidates = (
            row.locator("xpath=.//td[last()]//*[contains(normalize-space(.),'Download')]"),
            row.locator("xpath=.//td[last()]"),
            row.get_by_role("button", name=re.compile(r"download|baixar", re.IGNORECASE)),
            row.get_by_role("link", name=re.compile(r"download|baixar", re.IGNORECASE)),
            row.locator("button"),
            row.locator("a"),
        )
        for locator in candidates:
            target = self._first_visible_enabled(locator)
            if target is not None:
                target.click()
                return

        if page is not None and tela_aba:
            normalized_target = strip_accents(self._normalize_spaces(tela_aba)).lower()
            rows = page.locator("tr")
            try:
                row_count = rows.count()
            except Error:
                row_count = 0

            for index in range(1, row_count):
                candidate_row = rows.nth(index)
                try:
                    row_text = strip_accents(self._normalize_spaces(candidate_row.inner_text(timeout=2_000))).lower()
                except Error:
                    continue

                if normalized_target not in row_text:
                    continue

                retry_candidates = (
                    candidate_row.locator("xpath=.//td[last()]//*[contains(normalize-space(.),'Download')]"),
                    candidate_row.locator("xpath=.//td[last()]"),
                    candidate_row.get_by_role("button", name=re.compile(r"download|baixar", re.IGNORECASE)),
                    candidate_row.get_by_role("link", name=re.compile(r"download|baixar", re.IGNORECASE)),
                    candidate_row.locator("button"),
                    candidate_row.locator("a"),
                )
                for locator in retry_candidates:
                    target = self._first_visible_enabled(locator)
                    if target is not None:
                        target.click()
                        return

        raise TimeoutError(
            "Nao foi possivel clicar no item de download da linha encontrada; a linha pode ter sido atualizada no DOM."
        )

    def _build_download_screen_name(
        self,
        month_reference: str,
        tab_name: str,
        view_label: str,
        detail_label: str | None,
        selected_year: str,
    ) -> str:
        normalized_month = re.sub(r"\s+", " ", month_reference).strip()
        base_name = f"Informacoes Fiscais - {tab_name} - {view_label} - Detalhamento {normalized_month} de {selected_year}"
        if detail_label:
            return f"{base_name} - {detail_label}"
        return base_name

    def _resolve_selected_year_from_page(self, page: Page) -> str:
        try:
            locator = page.locator("input[role='combobox'], .p-dropdown-label, [aria-label='Selecione um Período']")
            count = locator.count()
            for index in range(count):
                text = self._normalize_spaces(locator.nth(index).inner_text(timeout=2_000))
                if re.fullmatch(r"\d{4}", text):
                    return text
        except Error:
            pass
        return str(time.localtime().tm_year)

    def _normalize_reference_year(self, reference_year: str | None) -> str:
        if reference_year is None:
            return str(time.localtime().tm_year)
        normalized_year = self._normalize_spaces(str(reference_year))
        if not re.fullmatch(r"\d{4}", normalized_year):
            raise ValueError("Informe o ano de referencia no formato YYYY, por exemplo 2026.")
        return normalized_year

    def _download_requested_file(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        tela_aba: str,
        document_tab: str,
        requested_after: datetime,
        taxpayer_document: str,
    ) -> Path:
        LOGGER.info("Baixando o arquivo solicitado para TELA/ABA: %s", tela_aba)
        row_match = self._find_download_row_by_screen_name(
            page,
            tela_aba,
            requested_after,
            taxpayer_document,
        )
        basename = self._build_download_output_basename(tela_aba)
        if row_match is None:
            return self._save_unavailable_download_notice(
                cgf=cgf,
                month_reference=month_reference,
                basename=basename,
                document_tab=document_tab,
                tela_aba=tela_aba,
                taxpayer_folder_name=taxpayer_folder_name,
            )
        download_row, unidentified_client = row_match
        if unidentified_client:
            basename = f"{basename} - cliente-nao-identificado"
            LOGGER.warning(
                "Download selecionado com CNPJ nao identificado para %s; adicionando sufixo '%s'.",
                tela_aba,
                "cliente-nao-identificado",
            )
        output_path = self._capture_download_from_row(
            page=page,
            row=download_row,
            tela_aba=tela_aba,
            cgf=cgf,
            month_reference=month_reference,
            taxpayer_folder_name=taxpayer_folder_name,
            basename=basename,
            document_tab=document_tab,
            taxpayer_document=taxpayer_document,
        )
        LOGGER.info("Arquivo da Central de Downloads salvo via captura de download do Selenium em %s", output_path)
        return output_path

    def _build_download_output_basename(self, tela_aba: str) -> str:
        """Normaliza o nome final do arquivo sem repetir sufixos internos da fila do SIGA."""
        basename = self._sanitize_filename(tela_aba)
        if self._normalize_download_target(tela_aba).endswith(" - autorizadas"):
            basename = basename[: -len(" - Autorizadas")]
        return basename

    def _find_visible_download_row_on_current_page(
        self,
        page: Page,
        tela_aba: str,
        taxpayer_document: str = "",
    ) -> Locator | None:
        """Reencontra a linha visível da fila para clicar com um locator fresco no DOM atual."""
        self._go_to_first_downloads_page(page)
        normalized_target = self._normalize_download_target(tela_aba)
        match_fragments = self._extract_download_match_fragments_from_title(tela_aba)
        taxpayer_base_key = self._taxpayer_base_key(taxpayer_document)

        rows = page.locator("tr")
        try:
            row_count = rows.count()
        except Error:
            row_count = 0

        for index in range(1, row_count):
            candidate_row = rows.nth(index)
            try:
                if not candidate_row.is_visible():
                    continue
                row_cells = self._row_cell_texts(candidate_row)
            except Error:
                continue

            if not self._row_matches_download_target(row_cells, normalized_target, match_fragments):
                continue

            status_text = self._row_status_text(row_cells)
            if "concluido" not in status_text:
                continue
            if taxpayer_base_key and not self._row_matches_taxpayer_document(row_cells, taxpayer_base_key):
                continue

            return candidate_row

        return None

    def _find_download_row_by_screen_name(
        self,
        page: Page,
        tela_aba: str,
        requested_after: datetime | None = None,
        taxpayer_document: str = "",
    ) -> tuple[Locator, bool] | None:
        normalized_target = self._normalize_download_target(tela_aba)
        match_fragments = self._extract_download_match_fragments_from_title(tela_aba)
        taxpayer_base_key = self._taxpayer_base_key(taxpayer_document)
        deadline = time.time() + (self.settings.download_wait_timeout_ms / 1000)
        processing_streak = 0
        empty_streak = 0
        while time.time() < deadline:
            self._go_to_first_downloads_page(page)
            preferred_exact_candidates: list[tuple[Locator, datetime, str]] = []
            preferred_fuzzy_candidates: list[tuple[Locator, float, datetime, str]] = []
            fallback_exact_candidates: list[tuple[Locator, datetime, str]] = []
            fallback_fuzzy_candidates: list[tuple[Locator, float, datetime, str]] = []
            while True:
                page_result = self._scan_downloads_current_page(
                    page=page,
                    normalized_target=normalized_target,
                    match_fragments=match_fragments,
                    taxpayer_base_key=taxpayer_base_key,
                    requested_after=requested_after,
                )

                if page_result["exact"]:
                    preferred_exact_candidates.extend(page_result["exact"]["preferred"])
                    fallback_exact_candidates.extend(page_result["exact"]["fallback"])

                if page_result["fuzzy"]:
                    preferred_fuzzy_candidates.extend(page_result["fuzzy"]["preferred"])
                    fallback_fuzzy_candidates.extend(page_result["fuzzy"]["fallback"])

                if page_result["processing"] > 0:
                    processing_streak += 1
                    empty_streak = 0
                    delay_ms = 1_500 if processing_streak == 1 else 2_000
                    LOGGER.info(
                        "Download ainda em processamento para %s (%s linha(s) correspondente(s)); aguardando %s ms antes de atualizar.",
                        tela_aba,
                        page_result["processing"],
                        delay_ms,
                    )
                    page.wait_for_timeout(delay_ms)
                    if processing_streak >= 2:
                        page.reload(wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
                        page.wait_for_timeout(750)
                        processing_streak = 0
                    continue

                if not self._go_to_next_downloads_page(page):
                    break

            if preferred_exact_candidates:
                preferred_exact_candidates.sort(key=lambda item: item[1], reverse=True)
                best_row, best_dt, best_text = preferred_exact_candidates[0]
                LOGGER.info(
                    "Estratégia de correspondência da linha de download: exata e mais recente por título (candidatos=%s, solicitado_em=%s, escolhido='%s')",
                    len(preferred_exact_candidates),
                    best_dt.isoformat(sep=" ", timespec="seconds"),
                    best_text,
                )
                return best_row, False
            if fallback_exact_candidates:
                fallback_exact_candidates.sort(key=lambda item: item[1], reverse=True)
                best_row, best_dt, best_text = fallback_exact_candidates[0]
                LOGGER.info(
                    "Estratégia de correspondência da linha de download: exata e mais recente por título no fallback (candidatos=%s, solicitado_em=%s, escolhido='%s')",
                    len(fallback_exact_candidates),
                    best_dt.isoformat(sep=" ", timespec="seconds"),
                    best_text,
                )
                return best_row, False
            if preferred_fuzzy_candidates:
                preferred_fuzzy_candidates.sort(key=lambda item: (item[1], item[2]), reverse=True)
                best_row, best_score, best_dt, best_text = preferred_fuzzy_candidates[0]
                LOGGER.info(
                    "Estratégia de correspondência da linha de download: aproximada e mais recente por título (pontuacao=%s, candidatos=%s, solicitado_em=%s, escolhido='%s')",
                    best_score,
                    len(preferred_fuzzy_candidates),
                    best_dt.isoformat(sep=" ", timespec="seconds"),
                    best_text,
                )
                return best_row, False
            if fallback_fuzzy_candidates:
                fallback_fuzzy_candidates.sort(key=lambda item: (item[1], item[2]), reverse=True)
                best_row, best_score, best_dt, best_text = fallback_fuzzy_candidates[0]
                LOGGER.info(
                    "Estratégia de correspondência da linha de download: aproximada e mais recente por título no fallback (pontuacao=%s, candidatos=%s, solicitado_em=%s, escolhido='%s')",
                    best_score,
                    len(fallback_fuzzy_candidates),
                    best_dt.isoformat(sep=" ", timespec="seconds"),
                    best_text,
                )
                return best_row, False
            empty_streak += 1
            processing_streak = 0
            page.wait_for_timeout(max(500, self.settings.download_poll_interval_ms // 2))
            if empty_streak >= 2:
                page.reload(wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
                page.wait_for_timeout(750)
                empty_streak = 0

        LOGGER.warning(
            "Nao foi possivel localizar a solicitacao concluida para %s. "
            "Nenhum download sera feito; sera gerado arquivo de aviso.",
            tela_aba,
        )
        return None

    def _save_unavailable_download_notice(
        self,
        cgf: str,
        month_reference: str,
        basename: str,
        document_tab: str,
        tela_aba: str,
        taxpayer_folder_name: str,
    ) -> Path:
        output_dir = self._build_taxpayer_output_dir(taxpayer_folder_name, month_reference, document_tab)
        output_path = output_dir / f"{basename}.txt"
        message = (
            "Download nao foi realizado porque a informacao fiscal nao foi localizada na Central de Downloads.\n"
            f"TELA/ABA: {tela_aba}\n"
            "Criterios tentados: correspondencia de TELA/ABA, CNPJ na mesma linha e status Concluido.\n"
        )
        output_path.write_text(message, encoding="utf-8")
        LOGGER.warning("Aviso de download indisponivel salvo em %s", output_path)
        return output_path

    def _save_taxpayer_not_found_notice(
        self,
        cgf: str,
        month_reference: str,
        message: str,
        taxpayer_folder_name: str,
    ) -> Path:
        output_dir = self._build_taxpayer_output_dir(taxpayer_folder_name, month_reference)
        output_path = output_dir / "CNPJ nao encontrado.txt"
        formatted_cnpj = self._format_cnpj(cgf)
        content = (
            "O CNPJ informado nao foi encontrado na barra de pesquisa do SIGA.\n"
            f"CNPJ pesquisado: {formatted_cnpj}\n"
            f"Detalhe: {message}\n"
        )
        output_path.write_text(content, encoding="utf-8")
        LOGGER.warning("Aviso de CNPJ nao encontrado salvo em %s", output_path)
        return output_path

    def _scan_downloads_current_page(
        self,
        page: Page,
        normalized_target: str,
        match_fragments: dict[str, str],
        taxpayer_base_key: str,
        requested_after: datetime | None,
    ) -> dict[str, object]:
        rows = page.locator("tr")
        try:
            row_count = rows.count()
        except Error:
            row_count = 0

        exact_candidates: list[tuple[Locator, datetime, str]] = []
        fuzzy_candidates: list[tuple[Locator, float, datetime, str]] = []
        processing_candidates = 0
        preferred_exact_candidates: list[tuple[Locator, datetime, str]] = []
        preferred_fuzzy_candidates: list[tuple[Locator, float, datetime, str]] = []
        fallback_exact_candidates: list[tuple[Locator, datetime, str]] = []
        fallback_fuzzy_candidates: list[tuple[Locator, float, datetime, str]] = []

        for index in range(1, row_count):
            row = rows.nth(index)
            try:
                if not row.is_visible():
                    continue
                row_cells = self._row_cell_texts(row)
            except Error:
                continue

            row_text = self._normalize_download_target(" ".join(row_cells))
            score = self._download_match_score(row_text, normalized_target, match_fragments)
            matches_target = self._row_matches_download_target(row_cells, normalized_target, match_fragments)
            if not matches_target:
                continue

            requested_at = self._row_request_datetime(row_cells)
            status_text = self._row_status_text(row_cells)
            if any(status_key in status_text for status_key in ("processando", "aguardando", "gerando")):
                processing_candidates += 1
                continue
            if "concluido" not in status_text:
                continue
            if taxpayer_base_key and not self._row_matches_taxpayer_document(row_cells, taxpayer_base_key):
                continue

            is_preferred = requested_after is None or requested_at >= requested_after
            if self._row_matches_download_target(row_cells, normalized_target, match_fragments, exact_only=True):
                target_bucket = preferred_exact_candidates if is_preferred else fallback_exact_candidates
                target_bucket.append((row, requested_at, row_text))
            else:
                target_bucket = preferred_fuzzy_candidates if is_preferred else fallback_fuzzy_candidates
                target_bucket.append((row, score, requested_at, row_text))

        return {
            "exact": {
                "preferred": preferred_exact_candidates,
                "fallback": fallback_exact_candidates,
            },
            "fuzzy": {
                "preferred": preferred_fuzzy_candidates,
                "fallback": fallback_fuzzy_candidates,
            },
            "processing": processing_candidates,
        }

    def _go_to_next_downloads_page(self, page: Page) -> bool:
        candidates = (
            page.locator("button.p-paginator-next:not([disabled]):not(.p-disabled)"),
            page.locator("xpath=//button[contains(@class,'p-paginator-next') and not(@disabled) and not(contains(@class,'p-disabled'))]"),
            page.get_by_role("button", name=re.compile(r"proxima|next", re.IGNORECASE)),
        )
        for locator in candidates:
            target = self._first_visible_enabled(locator)
            if target is None:
                continue
            target.click()
            page.wait_for_timeout(1_000)
            return True
        return False

    def _go_to_first_downloads_page(self, page: Page) -> None:
        candidates = (
            page.locator("button.p-paginator-first:not([disabled]):not(.p-disabled)"),
            page.locator("xpath=//button[contains(@class,'p-paginator-first') and not(@disabled) and not(contains(@class,'p-disabled'))]"),
            page.get_by_role("button", name=re.compile(r"primeira|first", re.IGNORECASE)),
        )
        for locator in candidates:
            target = self._first_visible_enabled(locator)
            if target is None:
                continue
            target.click()
            page.wait_for_timeout(1_000)
            return

    def _select_max_downloads_page_size(self, page: Page) -> bool:
        """Seleciona o maior numero de linhas por pagina no paginador da Central de Downloads.

        Reduz drasticamente o total de paginas a percorrer numa varredura (ex.: de 100 paginas
        de 10 linhas para 10 paginas de 100), sem alterar o comportamento caso o seletor nao
        esteja disponivel na tela (fallback silencioso, mantendo o tamanho de pagina padrao).
        """
        dropdown_candidates = (
            page.locator("[aria-label='Rows per page']"),
            page.locator(".p-paginator-rpp-options .p-dropdown-label"),
            page.locator(".p-paginator-rpp-options"),
        )
        trigger = None
        for locator in dropdown_candidates:
            trigger = self._first_visible_enabled(locator)
            if trigger is not None:
                break

        if trigger is None:
            LOGGER.info(
                "Seletor de linhas por pagina nao encontrado na Central de Downloads; mantendo o padrao."
            )
            return False

        try:
            trigger.click()
            page.wait_for_timeout(300)

            options = page.locator("li[role='option'], [role='listbox'] li")
            option_count = options.count()

            # Com o indice ja descoberto numa chamada anterior (mesma execucao do extrator),
            # evita reler o texto de todas as opcoes a cada reload: a lista de opcoes do
            # paginador nao muda entre reloads da mesma tela de Downloads.
            cached_index = self._downloads_page_size_option_index
            if cached_index is not None and cached_index < option_count:
                options.nth(cached_index).click()
                page.wait_for_timeout(1_500)
                narrate("Ajustando a Central de Downloads para mostrar mais itens por página...")
                return True

            best_index = -1
            best_value = -1
            for index in range(option_count):
                try:
                    option_text = options.nth(index).inner_text(timeout=1_000)
                except Error:
                    continue
                digits = re.sub(r"[^0-9]", "", option_text)
                if not digits:
                    continue
                value = int(digits)
                if value > best_value:
                    best_value = value
                    best_index = index

            if best_index == -1:
                LOGGER.warning(
                    "Nao foi possivel identificar as opcoes de linhas por pagina da Central de Downloads; mantendo o padrao."
                )
                page.keyboard.press("Escape")
                return False

            options.nth(best_index).click()
            # Espera mais generosa que a usada em outras interacoes de paginador: aumentar o
            # tamanho da pagina pode multiplicar por 10x a quantidade de linhas renderizadas
            # pelo Angular de uma vez, e a varredura que vem em seguida precisa encontrar o
            # DOM ja estavel (ver PLANO_CORRECOES.md item 27 e correcao de selenium_compat.py).
            page.wait_for_timeout(1_500)
            self._downloads_page_size_option_index = best_index
            LOGGER.info("Linhas por pagina da Central de Downloads ajustadas para %s.", best_value)
            narrate("Ajustando a Central de Downloads para mostrar mais itens por página...")
            return True
        except Error:
            LOGGER.warning(
                "Falha ao tentar ajustar as linhas por pagina da Central de Downloads; mantendo o padrao.",
                exc_info=True,
            )
            return False

    def _download_match_score(self, tela_aba_text: str, normalized_target: str, match_fragments: dict[str, str]) -> float:
        score = 0.0
        if match_fragments["tab"] and match_fragments["tab"] in tela_aba_text:
            score += 1.0
        if match_fragments["view"] and match_fragments["view"] in tela_aba_text:
            score += 1.0
        if match_fragments["month"] and match_fragments["month"] in tela_aba_text:
            score += 1.0
        if match_fragments["year"] and match_fragments["year"] in tela_aba_text:
            score += 1.0
        if "detalhamento" in tela_aba_text:
            score += 0.5
        if "informacoes fiscais" in tela_aba_text:
            score += 0.25
        return score

    def _row_cell_texts(self, row: Locator, cell_timeout_ms: int = 2_000) -> list[str]:
        """Le o texto de cada celula da linha.

        `cell_timeout_ms` controla quanto tempo esperar por cada celula individual antes de
        desistir dela. Varreduras em lote (muitas linhas de uma vez, ex. apos aumentar o
        tamanho de pagina no item 27) devem usar um valor bem menor que o padrao, pois uma
        linha obsoleta/desalinhada apos um re-render grande do Angular pode fazer cada celula
        dela gastar o timeout inteiro antes de cair no fallback, somando minutos de espera
        silenciosa em uma tabela com muitas linhas (ver PLANO_CORRECOES.md item 29).
        """
        cells = row.locator("td")
        try:
            cell_count = cells.count()
        except Error:
            return []

        values: list[str] = []
        for index in range(cell_count):
            try:
                values.append(self._normalize_spaces(cells.nth(index).inner_text(timeout=cell_timeout_ms)))
            except Error:
                values.append("")
        return values

    def _row_matches_download_target(
        self,
        row_cells: list[str],
        normalized_target: str,
        match_fragments: dict[str, str],
        exact_only: bool = False,
    ) -> bool:
        row_text = self._normalize_download_target(" ".join(row_cells))
        row_text_ascii = self._normalize_download_target(" ".join(row_cells), strip_marks=True)
        normalized_target_ascii = self._normalize_download_target(normalized_target, strip_marks=True)
        if normalized_target in row_text or normalized_target_ascii in row_text_ascii:
            return True
        if exact_only:
            # Sem correspondência literal do título completo, a linha não é uma correspondência exata.
            return False
        return self._row_contains_signature_fragments(row_text, row_text_ascii, match_fragments)

    def _row_contains_signature_fragments(self, row_text: str, row_text_ascii: str, match_fragments: dict[str, str]) -> bool:
        """Verifica se uma linha da Central de Downloads corresponde aos fragmentos esperados.

        Para abas especiais (malha fiscal, debitos fiscais) os requisitos de
        "informacoes fiscais" e "detalhamento" são ignorados, pois elas possuem
        títulos próprios na Central de Downloads.
        """
        special_tabs = ("malha fiscal", "malha-fiscal", "debitos fiscais", "debitos-fiscais")
        is_special_tab = match_fragments.get("tab") in special_tabs or any(
            s in row_text_ascii for s in ("malha fiscal", "malha-fiscal", "debitos fiscais", "debitos-fiscais")
        )

        if not is_special_tab:
            # Validações estritas apenas para abas do fluxo padrão
            if "informacoes fiscais" not in row_text_ascii:
                return False
            if "detalhamento" not in row_text_ascii:
                return False

        if match_fragments["tab"] and match_fragments["tab"] not in row_text_ascii:
            return False
        if match_fragments["view"] and match_fragments["view"] not in row_text_ascii:
            return False
        if match_fragments["month"] and match_fragments["month"] not in row_text:
            return False
        if match_fragments["year"] and match_fragments["year"] not in row_text_ascii:
            return False
        if match_fragments.get("detail") and match_fragments["detail"] not in row_text_ascii:
            return False
        return True

    def _row_status_text(self, row_cells: list[str]) -> str:
        for cell_text in row_cells:
            normalized = strip_accents(self._normalize_spaces(cell_text)).lower()
            if any(keyword in normalized for keyword in ("processando", "aguardando", "gerando", "concluido")):
                return normalized
        return ""

    def _row_request_datetime(self, row_cells: list[str]) -> datetime:
        for cell_text in row_cells:
            parsed = self._parse_request_datetime(cell_text)
            if parsed != datetime.min:
                return parsed
        return datetime.min

    def _row_matches_taxpayer_document(self, row_cells: list[str], taxpayer_base_key: str) -> bool:
        if not taxpayer_base_key:
            return True
        for cell_text in row_cells:
            cell_digits = self._normalize_numeric_document(cell_text)
            if not cell_digits:
                continue
            # Igualdade exata evita que um numero mais longo que apenas comeca com os mesmos
            # digitos do CNPJ-alvo (ex.: um numero de processo interno da SEFAZ) seja aceito
            # como pertencente ao contribuinte errado.
            if cell_digits == taxpayer_base_key:
                return True
        return False

    def _normalize_download_target(self, value: str, strip_marks: bool = False) -> str:
        normalized = self._normalize_spaces(value)
        if strip_marks:
            normalized = strip_accents(normalized)
        return normalized.casefold()

    def _extract_download_match_fragments_from_title(self, tela_aba: str) -> dict[str, str]:
        """Extrai fragmentos de identificação a partir do título da aba de download.

        Para Malha Fiscal e Débitos Fiscais o campo "tab" é preenchido com o tipo
        especial, permitindo que _row_contains_signature_fragments valide a linha
        sem os requisitos do fluxo padrão (informacoes fiscais / detalhamento).
        """
        normalized_target = self._normalize_download_target(tela_aba)
        target_clean = strip_accents(normalized_target)
        tab = ""
        # Verificar abas especiais antes das abas padrão
        if "malha fiscal" in target_clean or "malha-fiscal" in target_clean:
            tab = "malha fiscal"
        elif "debitos fiscais" in target_clean or "debitos-fiscais" in target_clean:
            tab = "debitos fiscais"
        elif "nfc-e" in target_clean:
            tab = "nfc-e"
        elif "ct-e" in target_clean:
            tab = "ct-e"
        elif "nf-e" in target_clean:
            tab = "nf-e"

        view = ""
        if "destinatario" in normalized_target:
            view = "destinatario"
        elif "emissor" in normalized_target:
            view = "emissor"
        elif "emitente" in normalized_target:
            view = "emitente"
        elif "tomador" in normalized_target:
            view = "tomador"

        month = ""
        year = ""
        detail = ""
        detail_match = re.search(r"detalhamento\s+(.+?)\s+de\s+(\d{4})(?:\s*-\s*(.+))?$", normalized_target, re.IGNORECASE)
        if detail_match:
            month = detail_match.group(1).strip()
            year = detail_match.group(2).strip()
            if detail_match.lastindex and detail_match.group(3):
                detail = detail_match.group(3).strip()

        return {
            "tab": tab,
            "view": view,
            "month": month,
            "year": year,
            "detail": detail,
        }

    def _taxpayer_base_key(self, taxpayer_document: str) -> str:
        # Retorna o documento completo para fins de comparação direta e precisa dos arquivos na central de downloads.
        # Impede que filiais distintas misturem seus relatórios no disco.
        digits = self._normalize_numeric_document(taxpayer_document)
        if not digits:
            return ""
        return digits

    def _parse_request_datetime(self, value: str) -> datetime:
        normalized = strip_accents(self._normalize_spaces(value)).lower()
        normalized = normalized.replace("Ã s", "as")
        # Exemplo SIGA: 26/05/2026 as 13:52:43
        match = re.search(r"(\d{2}/\d{2}/\d{4})\s+as\s+(\d{2}:\d{2}:\d{2})", normalized, re.IGNORECASE)
        if not match:
            return datetime.min
        try:
            return datetime.strptime(f"{match.group(1)} {match.group(2)}", "%d/%m/%Y %H:%M:%S")
        except ValueError:
            return datetime.min

    def _current_taxpayer_document(self, page: Page) -> str:
        match = re.search(r"/contribuinte/([^/?#]+)", page.url)
        if not match:
            return ""
        return self._normalize_numeric_document(match.group(1))

    def _capture_download_from_row(
        self,
        page: Page,
        row: Locator,
        tela_aba: str,
        cgf: str,
        month_reference: str,
        taxpayer_folder_name: str,
        basename: str,
        document_tab: str,
        taxpayer_document: str,
    ) -> Path:
        refreshed_row = self._find_visible_download_row_on_current_page(
            page,
            tela_aba,
            taxpayer_document=taxpayer_document,
        )
        if refreshed_row is not None:
            row = refreshed_row

        with page.expect_download(timeout=self.settings.download_wait_timeout_ms) as download_info:
            self._click_download_action(row, page=page, tela_aba=tela_aba)
        download = download_info.value
        return self._save_download(download, taxpayer_folder_name, month_reference, basename, document_tab)

    def _sanitize_filename(self, value: str) -> str:
        compact = self._normalize_spaces(value)
        return "".join("-" if character in '<>:"/\\|?*' else character for character in compact)

    def _normalize_spaces(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    def _parse_decimal_value(self, value: str) -> float:
        cleaned = (value or "").strip()
        cleaned = cleaned.replace(".", "").replace(",", ".")
        cleaned = re.sub(r"[^0-9.-]", "", cleaned)
        if not cleaned:
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def _return_to_home(self, page: Page) -> None:
        try:
            page.goto(self.settings.siga_url, wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
            if "siga.sefaz.ce.gov.br/ui" in page.url:
                self.page_inspector.stabilize_after_navigation(page, "return-home")
        except Error:
            page.reload(wait_until="domcontentloaded", timeout=self.settings.timeout_ms)

    def _extract_metric(self, page: Page, label: str, aliases: tuple[str, ...] = ()) -> str:
        LOGGER.info("Extracting metric %s", label)
        patterns: list[str] = []
        for value in (label, *aliases):
            for candidate in (value, strip_accents(value)):
                if candidate not in patterns:
                    patterns.append(candidate)
        for pattern in patterns:
            try:
                value = self._extract_value_near_label(page, pattern)
                if value:
                    return value
            except Error:
                continue

        text = page.locator("body").inner_text(timeout=10_000)
        for pattern in patterns:
            regex = re.compile(rf"{re.escape(pattern)}\s*[:\-]?\s*([^\n]+)", re.IGNORECASE)
            match = regex.search(text)
            if match:
                return match.group(1).strip()

        normalized_text = strip_accents(text)
        for pattern in patterns:
            normalized_pattern = strip_accents(pattern)
            regex = re.compile(rf"{re.escape(normalized_pattern)}\s*[:\-]?\s*([^\n]+)", re.IGNORECASE)
            match = regex.search(normalized_text)
            if match:
                return match.group(1).strip()

        self._save_debug_snapshot(page, f"metric-not-found-{slugify(label)}")
        raise TimeoutError(f"Nao foi possivel extrair o campo {label}.")

    def _extract_metric_with_retry(
        self,
        page: Page,
        label: str,
        aliases: tuple[str, ...] = (),
        attempts: int = 4,
        delay_ms: int = 750,
    ) -> str:
        for attempt in range(1, attempts + 1):
            try:
                return self._extract_metric(page, label, aliases)
            except TimeoutError:
                if attempt < attempts:
                    page.wait_for_timeout(delay_ms)
                    continue
                raise
            except Error as exc:
                if attempt < attempts:
                    page.wait_for_timeout(delay_ms)
                    continue
                raise TimeoutError(f"Nao foi possivel extrair o campo {label}.") from exc

    def _extract_value_near_label(self, page: Page, label: str) -> str | None:
        script = """
        (targetLabel) => {
            const normalize = (value) => value
                .normalize('NFD')
                .replace(/[\\u0300-\\u036f]/g, '')
                .replace(/\\s+/g, ' ')
                .trim()
                .toLowerCase();

            const wanted = normalize(targetLabel);
            const elements = [...document.querySelectorAll('body *')];

            const collectTexts = (element) => {
                const values = [];
                const children = [...element.children];
                for (const child of children) {
                    const text = (child.innerText || child.textContent || '').trim();
                    if (text) {
                        values.push(text);
                    }
                }
                return values;
            };

            for (const element of elements) {
                const text = (element.innerText || element.textContent || '').trim();
                if (!text) {
                    continue;
                }

                if (normalize(text) === wanted) {
                    const sibling = element.nextElementSibling;
                    if (sibling) {
                        const siblingText = (sibling.innerText || sibling.textContent || '').trim();
                        if (siblingText) {
                            return siblingText.split('\\n')[0].trim();
                        }
                    }

                    const parent = element.parentElement;
                    if (parent) {
                        const childTexts = collectTexts(parent).filter((value) => normalize(value) !== wanted);
                        if (childTexts.length) {
                            return childTexts[0].split('\\n')[0].trim();
                        }

                        const parentLines = (parent.innerText || parent.textContent || '')
                            .split('\\n')
                            .map((value) => value.trim())
                            .filter(Boolean);
                        for (let index = 0; index < parentLines.length; index += 1) {
                            if (normalize(parentLines[index]) === wanted && parentLines[index + 1]) {
                                return parentLines[index + 1].trim();
                            }
                        }
                    }
                }
            }

            return null;
        }
        """
        value = page.evaluate(script, label)
        if value:
            return str(value).strip()
        return None

    def _save_xlsx(self, cnpj: str, valor_contabil: str, icms: str) -> Path:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "dados"
        sheet.append(["CNPJ", "Valor Contabil", "ICMS"])
        sheet.append([cnpj, valor_contabil, icms])

        output_path = self.settings.output_dir / f"{cnpj}.xlsx"
        workbook.save(output_path)
        LOGGER.info("Saida XLSX salva em %s", output_path)
        return output_path

    def _build_taxpayer_output_dir(self, taxpayer_folder_name: str, month_reference: str, document_tab: str | None = None) -> Path:
        output_dir = self.settings.output_dir / self._sanitize_filename(taxpayer_folder_name) / slugify(month_reference)
        if document_tab:
            output_dir = output_dir / document_tab
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _save_download(
        self,
        download: Download,
        taxpayer_folder_name: str,
        month_reference: str,
        basename: str,
        document_tab: str,
    ) -> Path:
        output_dir = self._build_taxpayer_output_dir(taxpayer_folder_name, month_reference, document_tab)
        final_suffix = self._download_output_suffix(download.suggested_filename)
        final_name = f"{self._sanitize_filename(basename)}{final_suffix}"
        output_path = output_dir / final_name
        LOGGER.info(
            "Salvando download com nome deterministico: nome_base=%s, nome_sugerido=%s, caminho_final=%s",
            basename,
            download.suggested_filename,
            output_path,
        )
        download.save_as(str(output_path))
        LOGGER.info("Download salvo em %s", output_path)
        return output_path

    def _download_output_suffix(self, suggested_filename: str) -> str:
        """Preserva a extensão original informada pelo navegador, com fallback seguro para CSV."""
        suffix = "".join(Path(suggested_filename).suffixes).strip()
        if not suffix:
            return ".csv"
        return suffix

    def _save_debug_snapshot(self, page: Page, name: str) -> None:
        self.page_inspector.save_debug_artifacts(page, name)

    def _normalize_numeric_document(self, value: str) -> str:
        # Retém tanto letras quanto números para suportar o novo padrão de CNPJ alfanumérico.
        # Remove apenas pontuações, traços, barras e espaços.
        return re.sub(r"[^a-zA-Z0-9]", "", value)

    def _format_cnpj(self, value: str) -> str:
        digits = self._normalize_numeric_document(value)
        if len(digits) != 14:
            return digits
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"

    def _format_cgf(self, value: str) -> str:
        digits = self._normalize_numeric_document(value)
        if len(digits) != 9:
            return digits
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}-{digits[8:]}"

    def _build_taxpayer_folder_name(self, spreadsheet_row: SpreadsheetRow) -> str:
        """Monta o nome da pasta usando COD, EMPRESA e CNPJ no padrão operacional."""
        cod = self._sanitize_filename((spreadsheet_row.cod or "SEM-COD").strip() or "SEM-COD")
        empresa = self._sanitize_filename((spreadsheet_row.empresa or "SEM-EMPRESA").strip() or "SEM-EMPRESA")
        cnpj = self._normalize_numeric_document(spreadsheet_row.cnpj) or "SEM-CNPJ"
        return f"{cod} - {empresa} - {cnpj}"

    def _click_text_action(
        self,
        page: Page,
        names: tuple[str, ...],
        artifact_name: str,
        fallback_task: str,
    ) -> None:
        normalized_names = [strip_accents(name) for name in names]
        candidates = []
        for name in normalized_names:
            candidates.extend(
                [
                    page.get_by_role("button", name=re.compile(re.escape(name), re.IGNORECASE)),
                    page.get_by_role("link", name=re.compile(re.escape(name), re.IGNORECASE)),
                    page.get_by_role("tab", name=re.compile(re.escape(name), re.IGNORECASE)),
                    page.get_by_text(re.compile(re.escape(name), re.IGNORECASE)),
                ]
            )

        for locator in candidates:
            target = self._first_visible_enabled(locator)
            if target is not None:
                target.click()
                narrate("Clicando em %s...", names[0])
                return

        raise TimeoutError(f"Nao foi possivel clicar em: {', '.join(names)}.")

    def _click_xpath(self, page: Page, xpath: str, label: str, force: bool = False) -> bool:
        target = self._first_visible_enabled(page.locator(xpath))
        if target is None:
            return False
        LOGGER.info("Clicando em %s via XPath: %s", label, xpath)
        narrate("Clicando em %s...", label)
        target.click(force=force)
        return True

    def _ensure_side_menu_open(self, page: Page) -> bool:
        """Expande o menu lateral quando ele estiver recolhido, evitando bloqueio de navegação.

        Tenta os seletores em ordem de preferência semântica, usando o XPath posicional apenas
        como último recurso — se cair no fallback, registra WARNING como sinal de possível
        mudança no layout do SIGA.
        """
        # Seletores em ordem de robustez: semântico > componente > posicional
        toggle_selectors = [
            # 1ª tentativa: atributo ARIA ou classe de toggle de menu
            "[aria-label*='menu' i], [aria-label*='toggle' i], button.menu-toggle, [class*='menu-toggle']",
            # 2ª tentativa: ícone dentro do componente de cabeçalho Angular do SIGA
            "ed-header-v2-track-one i, #main-structure-header-id i",
            # 3ª tentativa (fallback posicional) — frágil a mudanças de layout
            "//*[@id='main-structure-header-id']/div/div[1]/ed-header-v2-track-one/div/div/div/div[1]/div/i",
        ]

        menu_toggle = None
        used_fallback = False
        for idx, selector in enumerate(toggle_selectors):
            # XPath só funciona com o prefixo correto no locator
            loc = page.locator(f"xpath={selector}") if selector.startswith("/") else page.locator(selector)
            menu_toggle = self._first_visible_enabled(loc)
            if menu_toggle is not None:
                if idx == len(toggle_selectors) - 1:
                    used_fallback = True
                break

        if menu_toggle is None:
            return False

        if used_fallback:
            LOGGER.warning(
                "Toggle do menu lateral localizado apenas pelo XPath posicional (fallback). "
                "Isso pode indicar uma mudança no layout do SIGA — verifique se os seletores semanticos precisam ser atualizados."
            )

        try:
            body_text = strip_accents(page.locator("body").inner_text(timeout=2_000)).lower()
        except Error:
            body_text = ""

        if "informacoes fiscais" in body_text and "downloads" in body_text:
            return False

        LOGGER.info("Abrindo o menu lateral pelo alternador do cabecalho")
        menu_toggle.click(force=True)
        page.wait_for_timeout(750)
        return True

    def _first_visible_enabled(self, locator: Locator) -> Locator | None:
        try:
            count = locator.count()
        except Error:
            return None

        for index in range(count):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible() and candidate.is_enabled():
                    return candidate
            except Error:
                continue
        return None

    def _find_row_by_digits(self, page: Page, target_digits: str, max_candidates: int = 80) -> Locator | None:
        candidates = page.locator("tr, [role='row'], .p-datatable-row, .card")
        try:
            count = candidates.count()
        except Error:
            return None

        limited = count > max_candidates
        if limited:
            LOGGER.info(
                "Limitando a varredura de digitos do contribuinte a %s de %s elementos candidatos de linha/cartao",
                max_candidates,
                count,
            )

        for index in range(min(count, max_candidates)):
            candidate = candidates.nth(index)
            try:
                if not candidate.is_visible():
                    continue
                text = candidate.inner_text(timeout=500)
            except Error:
                continue
            normalized = re.sub(r"\D", "", text)
            if target_digits and target_digits in normalized:
                return candidate

        # Emite aviso explícito quando o limite foi atingido sem encontrar o alvo —
        # sinal de que a tabela cresceu além do limite padrão de varredura.
        if limited:
            LOGGER.warning(
                "Alvo '%s' nao encontrado dentro do limite de %s candidatos (total na pagina: %s). "
                "Considere aumentar max_candidates se a tabela cresceu significativamente.",
                target_digits,
                max_candidates,
                count,
            )
        return None

    def _is_taxpayer_detail_page(self, page: Page) -> bool:
        try:
            body_text = strip_accents(page.locator("body").inner_text(timeout=4_000)).lower()
        except Error:
            return False

        detail_signals = (
            "informacoes fiscais",
            "informacoes do contribuinte",
            "resumo",
            "emissor",
            "destinatario",
        )
        return any(signal in body_text for signal in detail_signals)

