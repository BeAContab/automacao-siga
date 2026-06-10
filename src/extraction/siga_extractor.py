from __future__ import annotations

"""Fluxo principal de busca de contribuintes e extração dos relatórios do SIGA."""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook

from src.auth.siga_login import SigaLoginFlow
from src.config import Settings
from src.extraction.spreadsheet import SpreadsheetRow
from src.utils.browser import BrowserSession
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


@dataclass(slots=True)
class BatchExtractionResult:
    cnpj: str
    month_reference: str
    taxpayer_folder: Path
    fiscal_results: list[FiscalDownloadResult]
    final_url: str
    status: str
    message: str


@dataclass(slots=True)
class PendingDetailRequest:
    document_tab: str
    profile_name: str
    summary_path: Path
    report_name: str
    tela_aba: str
    requested_after: datetime
    taxpayer_document: str


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
    def __init__(self, settings: Settings, allow_manual_login_prompt: bool = True) -> None:
        self.settings = settings
        self.allow_manual_login_prompt = allow_manual_login_prompt
        self.page_inspector = SigaPageInspector(settings)

    def run(self, cnpj: str) -> ExtractionResult:
        """Executa a extração completa para um único contribuinte."""
        normalized_cnpj = self._normalize_numeric_document(cnpj)

        with BrowserSession(self.settings) as context:
            page = context.pages[0] if context.pages else context.new_page()
            page = self._ensure_authenticated(page, context)
            self._search_taxpayer(page, normalized_cnpj)
            self._open_taxpayer(page, normalized_cnpj)

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
        normalized_month = month_reference.strip()
        if not normalized_month:
            raise ValueError("Informe o mes de referencia antes de iniciar a extracao.")
        normalized_year = self._normalize_reference_year(reference_year)

        results: list[BatchExtractionResult] = []
        page = context.pages[0] if context.pages else context.new_page()
        page = self._ensure_authenticated(page, context)

        for spreadsheet_row in spreadsheet_rows:
            # Cada linha da planilha vira uma busca independente dentro do SIGA.
            LOGGER.info("Processando o CNPJ %s da linha %s da planilha", spreadsheet_row.cnpj, spreadsheet_row.row_number)
            self._open_taxpayer_from_home(page, spreadsheet_row.cnpj)
            tabs_for_row = selected_tabs
            if selected_tabs_by_row_number is not None:
                tabs_for_row = selected_tabs_by_row_number.get(spreadsheet_row.row_number)
            elif selected_tabs_by_cnpj is not None:
                tabs_for_row = selected_tabs_by_cnpj.get(spreadsheet_row.cnpj)
            if tabs_for_row is not None:
                tabs_for_row = [tab for tab in tabs_for_row if tab in {"NF-e", "NFC-e", "CT-e"}]
            pending_requests = self._extract_fiscal_tables(
                page,
                spreadsheet_row.cnpj,
                normalized_month,
                normalized_year,
                tabs_for_row,
            )
            detail_paths: dict[str, Path] = {}
            if pending_requests:
                LOGGER.info(
                    "All fiscal requests for %s were prepared; now opening Downloads to fetch %s file(s).",
                    spreadsheet_row.cnpj,
                    len(pending_requests),
                )
                detail_paths = self._download_pending_detail_requests(
                    page,
                    spreadsheet_row.cnpj,
                    normalized_month,
                    pending_requests,
                )
            fiscal_results = [
                FiscalDownloadResult(
                    document_tab=request.document_tab,
                    profile_name=request.profile_name,
                    summary_path=request.summary_path,
                    detail_path=detail_paths[request.tela_aba],
                    selected_report_name=request.report_name,
                    month_reference=normalized_month,
                )
                for request in pending_requests
            ]

            results.append(
                BatchExtractionResult(
                    cnpj=spreadsheet_row.cnpj,
                    month_reference=normalized_month,
                    taxpayer_folder=self._build_taxpayer_output_dir(spreadsheet_row.cnpj, normalized_month),
                    fiscal_results=fiscal_results,
                    final_url=page.url,
                    status="completed_with_downloads" if fiscal_results else "completed_without_downloads",
                    message=(
                        f"Downloads concluidos para {spreadsheet_row.cnpj}."
                        if fiscal_results
                        else f"Nenhum download foi solicitado para {spreadsheet_row.cnpj}."
                    ),
                )
            )

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
            except (TimeoutError, Error) as exc:
                last_error = exc
                LOGGER.warning(
                    "A tentativa %s de pesquisar e abrir o contribuinte %s nao foi concluida: %s",
                    attempt,
                    cgf,
                    exc,
                )
                if attempt < 3:
                    page.wait_for_timeout(1_000)

        self._save_debug_snapshot(page, f"taxpayer-open-cycle-failed-{cgf}")
        raise TimeoutError(
            f"Nao foi possivel pesquisar e abrir o contribuinte {cgf} apos retentativas."
        ) from last_error

    def _wait_for_taxpayer_list_ready(self, page: Page) -> bool:
        """Espera a lista de contribuintes se estabilizar antes de digitar o CGF."""
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

        LOGGER.info(
            "A lista de contribuintes não terminou de carregar visualmente antes da pesquisa; continuando porque o campo de busca é a fonte da verdade."
        )
        return False

    def _extract_fiscal_tables(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        reference_year: str,
        selected_tabs: list[str] | None = None,
    ) -> list[PendingDetailRequest]:
        """Percorre as abas fiscais selecionadas e agrega as solicitações de download."""
        results: list[PendingDetailRequest] = []
        allowed_tabs = self._normalize_selected_tabs(selected_tabs)
        for tab_config in self._build_fiscal_tab_configs():
            if tab_config.tab_name not in allowed_tabs:
                LOGGER.info("Ignorando a aba fiscal %s porque ela não foi selecionada", tab_config.tab_name)
                continue
            results.extend(self._collect_fiscal_tab_requests(page, cgf, month_reference, reference_year, tab_config))
        return results

    def _normalize_selected_tabs(self, selected_tabs: list[str] | None) -> set[str]:
        """Converte a seleção do usuário em um conjunto válido de abas fiscais."""
        available_tabs = {config.tab_name: config.tab_name for config in self._build_fiscal_tab_configs()}
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
        tab_config: FiscalTabConfig,
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
                        tab_config,
                        profile,
                        month_reference,
                        reference_year,
                        summary_paths[profile.label],
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
                PendingDetailRequest(
                    document_tab=tab_config.tab_slug,
                    profile_name=profile.label,
                    summary_path=summary_paths[profile.label],
                    report_name=tab_config.detail_label or "Detalhamento",
                    tela_aba=tela_aba,
                    requested_after=requested_after,
                    taxpayer_document=self._current_taxpayer_document(page),
                )
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
            const noResult = [
                "nenhum registro",
                "nenhum resultado",
                "nao ha registros",
                "nao foram encontrados",
            ].some((marker) => bodyText.includes(marker));

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
                        raise TimeoutError(f"Nenhum contribuinte foi encontrado para {document_value}.")
                    page.wait_for_timeout(500)
                    continue
                empty_result_seen_at = None
            except TimeoutError:
                raise
            except Error as exc:
                LOGGER.warning("Ainda nao foi possivel inspecionar o resultado da pesquisa do contribuinte: %s", exc)

            page.wait_for_timeout(500)

        self._save_debug_snapshot(page, f"taxpayer-search-timeout-{document_value}")
        raise TimeoutError(f"A pesquisa do contribuinte {document_value} nao retornou uma linha clicavel.")

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
            if self._click_taxpayer_row_by_digits(page, digits):
                return None
            row = self._find_row_by_digits(page, digits)
            if row is not None:
                return row

        self._save_debug_snapshot(page, f"row-not-found-{document_value}")
        raise TimeoutError(f"Nao foi possivel localizar o contribuinte {document_value} na lista.")

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
        metric = None
        last_error: TimeoutError | None = None
        for attempt in range(1, 5):
            try:
                metric = self._get_indicator_metric(page, month_reference)
            except TimeoutError as exc:
                last_error = exc
                metric = None

            if metric is not None:
                break

            if attempt < 4:
                LOGGER.info(
                    "O mês de referência %s ainda não está pronto (tentativa %s/4); aguardando antes de tentar novamente.",
                    month_reference,
                    attempt,
                )
                page.wait_for_timeout(750)
                page.reload(wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
                page.wait_for_timeout(750)

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
        tab_config: FiscalTabConfig,
        profile: FiscalProfileConfig,
        month_reference: str,
        reference_year: str,
        summary_path: Path,
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
                PendingDetailRequest(
                    document_tab=tab_config.tab_slug,
                    profile_name=profile.label,
                    summary_path=summary_path,
                    report_name=report_name,
                    tela_aba=tela_aba,
                    requested_after=requested_after,
                    taxpayer_document=self._current_taxpayer_document(page),
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
        basename: str,
        document_tab: str,
    ) -> Path:
        return self._capture_direct_download(page, cgf, month_reference, basename, document_tab)

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

    def _find_xlsx_detail_download_button(self, page: Page) -> Locator | None:
        """Localiza diretamente o botao novo do detalhamento, sem depender de indice."""
        candidates = (
            page.locator("xpath=//button[contains(normalize-space(.), 'Baixar Tabela (XLSX)')]"),
            page.get_by_role("button", name=re.compile(r"Baixar Tabela\s*\(XLSX\)", re.IGNORECASE)),
        )
        for locator in candidates:
            try:
                count = locator.count()
            except Error:
                continue
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    if candidate.is_enabled():
                        return candidate
                except Error:
                    continue
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
                return self._save_download(download, cgf, month_reference, basename, document_tab)
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
        return self._download_from_download_center(page, cgf, month_reference, basename, document_tab)

    def _download_from_download_center(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        basename: str,
        document_tab: str,
    ) -> Path:
        request = PendingDetailRequest(
            document_tab=document_tab,
            profile_name="unknown",
            summary_path=Path("."),
            report_name=basename,
            tela_aba=basename,
            requested_after=datetime.min,
            taxpayer_document=self._current_taxpayer_document(page),
        )
        detail_paths = self._download_pending_detail_requests(page, cgf, month_reference, [request])
        return detail_paths[request.tela_aba]

    def _download_pending_detail_requests(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        pending_requests: list[PendingDetailRequest],
    ) -> dict[str, Path]:
        origin_url = page.url
        LOGGER.info("Abrindo o menu de Downloads para buscar %s arquivo(s) de detalhamento pendente(s)", len(pending_requests))
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

        targets = self._build_download_lookup_targets(pending_requests)
        matches = self._find_pending_download_matches(page, targets)
        detail_paths = self._download_found_pending_requests(
            page,
            cgf,
            month_reference,
            targets,
            matches,
        )

        page.goto(origin_url, wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
        page.wait_for_timeout(1_000)
        return detail_paths

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

    def _find_pending_download_matches(
        self,
        page: Page,
        targets: list[DownloadLookupTarget],
    ) -> dict[str, DownloadRowMatch]:
        """Varre todas as paginas e escolhe o melhor match por solicitacao."""
        deadline = time.time() + (self.settings.download_wait_timeout_ms / 1000)
        latest_matches: dict[str, DownloadRowMatch] = {}
        target_keys = {target.request.tela_aba for target in targets}

        while time.time() < deadline:
            latest_matches, processing_counts = self._scan_downloads_table_once(page, targets)
            waiting_keys = self._download_keys_still_processing(targets, latest_matches, processing_counts)
            missing_keys = sorted(target_keys - set(latest_matches.keys()))

            if not waiting_keys:
                if missing_keys:
                    LOGGER.warning(
                        "Downloads nao localizados apos a varredura completa: %s",
                        ", ".join(missing_keys),
                    )
                return latest_matches

            delay_ms = 1_500 if len(waiting_keys) <= 2 else 2_000
            LOGGER.info(
                "Downloads ainda em processamento para %s; nova varredura completa em %s ms.",
                ", ".join(waiting_keys),
                delay_ms,
            )
            page.wait_for_timeout(delay_ms)
            page.reload(wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
            page.wait_for_timeout(750)

        if latest_matches:
            LOGGER.warning(
                "A Central de Downloads expirou antes de concluir todas as linhas pendentes; usando os matches encontrados ate agora."
            )
        return latest_matches

    def _scan_downloads_table_once(
        self,
        page: Page,
        targets: list[DownloadLookupTarget],
    ) -> tuple[dict[str, DownloadRowMatch], dict[str, int]]:
        """Le todas as paginas uma vez e monta o melhor match por TELA/ABA."""
        matches: dict[str, DownloadRowMatch] = {}
        processing_counts: dict[str, int] = {}
        self._go_to_first_downloads_page(page)
        page_number = 1

        while True:
            self._scan_downloads_current_page_for_targets(
                page,
                targets,
                page_number,
                matches,
                processing_counts,
            )
            if not self._go_to_next_downloads_page(page):
                break
            page_number += 1

        return matches, processing_counts

    def _scan_downloads_current_page_for_targets(
        self,
        page: Page,
        targets: list[DownloadLookupTarget],
        page_number: int,
        matches: dict[str, DownloadRowMatch],
        processing_counts: dict[str, int],
    ) -> None:
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
                row_cells = self._row_cell_texts(row)
            except Error:
                continue

            row_text = self._normalize_download_target(" ".join(row_cells))
            status_text = self._row_status_text(row_cells)
            requested_at = self._row_request_datetime(row_cells)

            for target in targets:
                request_key = target.request.tela_aba
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
                self._store_best_download_match(matches, candidate)

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
            request_key = target.request.tela_aba
            if processing_counts.get(request_key, 0) <= 0:
                continue
            current_match = matches.get(request_key)
            if current_match is None or not current_match.preferred:
                waiting_keys.append(request_key)
        return sorted(waiting_keys)

    def _download_found_pending_requests(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        targets: list[DownloadLookupTarget],
        matches: dict[str, DownloadRowMatch],
    ) -> dict[str, Path]:
        """Baixa os itens encontrados em lote, paginando apenas por pagina com match."""
        detail_paths: dict[str, Path] = {}
        page_targets: dict[int, list[DownloadLookupTarget]] = {}

        for target in targets:
            request_key = target.request.tela_aba
            basename = self._build_download_output_basename(request_key)
            match = matches.get(request_key)
            if match is None:
                detail_paths[request_key] = self._save_unavailable_download_notice(
                    cgf=cgf,
                    month_reference=month_reference,
                    basename=basename,
                    document_tab=target.request.document_tab,
                    tela_aba=request_key,
                )
                continue
            page_targets.setdefault(match.page_number, []).append(target)

        if not page_targets:
            return detail_paths

        self._go_to_first_downloads_page(page)
        current_page = 1
        max_page = max(page_targets.keys())

        while current_page <= max_page:
            for target in page_targets.get(current_page, []):
                match = matches[target.request.tela_aba]
                detail_paths[target.request.tela_aba] = self._capture_download_for_match(
                    page=page,
                    target=target,
                    match=match,
                    cgf=cgf,
                    month_reference=month_reference,
                )

            if current_page == max_page:
                break
            if not self._go_to_next_downloads_page(page):
                raise TimeoutError(
                    "Nao foi possivel navegar ate a pagina esperada da Central de Downloads durante o lote."
                )
            current_page += 1

        return detail_paths

    def _capture_download_for_match(
        self,
        page: Page,
        target: DownloadLookupTarget,
        match: DownloadRowMatch,
        cgf: str,
        month_reference: str,
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
                    cgf,
                    month_reference,
                    basename,
                    target.request.document_tab,
                )
                LOGGER.info(
                    "Download salvo para %s na pagina %s em %s",
                    target.request.tela_aba,
                    match.page_number,
                    output_path,
                )
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
        rows = page.locator("tr")
        try:
            row_count = rows.count()
        except Error:
            row_count = 0

        candidates: list[tuple[Locator, tuple[int, int, float, datetime, str]]] = []
        for index in range(1, row_count):
            row = rows.nth(index)
            try:
                if not row.is_visible():
                    continue
                row_cells = self._row_cell_texts(row)
            except Error:
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
                    row,
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
        return candidates[0][0]

    def _find_latest_download_row(self, page: Page) -> Locator:
        deadline = time.time() + (self.settings.download_wait_timeout_ms / 1000)
        while time.time() < deadline:
            rows = page.locator("tr, [role='row'], .p-datatable-row, .card")
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
                if "csv" in text or "download" in text or "gerado" in text:
                    return row
            page.wait_for_timeout(self.settings.download_poll_interval_ms)

        raise TimeoutError("Nao foi possivel localizar a linha do arquivo solicitado na central de Downloads.")

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
    ) -> Path:
        output_dir = self._build_taxpayer_output_dir(cgf, month_reference, document_tab)
        output_path = output_dir / f"{basename}.txt"
        message = (
            "Download nao foi realizado porque a informacao fiscal nao foi localizada na Central de Downloads.\n"
            f"TELA/ABA: {tela_aba}\n"
            "Criterios tentados: correspondencia de TELA/ABA, CNPJ na mesma linha e status Concluido.\n"
        )
        output_path.write_text(message, encoding="utf-8")
        LOGGER.warning("Aviso de download indisponivel salvo em %s", output_path)
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

    def _row_cell_texts(self, row: Locator) -> list[str]:
        cells = row.locator("td")
        try:
            cell_count = cells.count()
        except Error:
            return []

        values: list[str] = []
        for index in range(cell_count):
            try:
                values.append(self._normalize_spaces(cells.nth(index).inner_text(timeout=2_000)))
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
            return self._row_contains_signature_fragments(row_text, row_text_ascii, match_fragments)
        return self._row_contains_signature_fragments(row_text, row_text_ascii, match_fragments)

    def _row_contains_signature_fragments(self, row_text: str, row_text_ascii: str, match_fragments: dict[str, str]) -> bool:
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
            if cell_digits == taxpayer_base_key or cell_digits.startswith(taxpayer_base_key):
                return True
        return False

    def _normalize_download_target(self, value: str, strip_marks: bool = False) -> str:
        normalized = self._normalize_spaces(value)
        if strip_marks:
            normalized = strip_accents(normalized)
        return normalized.casefold()

    def _extract_download_match_fragments_from_title(self, tela_aba: str) -> dict[str, str]:
        normalized_target = self._normalize_download_target(tela_aba)
        tab = ""
        if "nfc-e" in normalized_target:
            tab = "nfc-e"
        elif "ct-e" in normalized_target:
            tab = "ct-e"
        elif "nf-e" in normalized_target:
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

    def _is_zero_cnpj_base_row(self, row: Locator) -> bool:
        return self._row_cnpj_base_key(row) == "0"

    def _row_cnpj_base_key(self, row: Locator) -> str:
        try:
            cnpj_base_text = self._normalize_spaces(row.locator("td").nth(0).inner_text(timeout=2_000))
        except Error:
            return ""
        digits = self._normalize_numeric_document(cnpj_base_text)
        if not digits:
            return ""
        return digits[:8]

    def _taxpayer_base_key(self, taxpayer_document: str) -> str:
        digits = self._normalize_numeric_document(taxpayer_document)
        if not digits:
            return ""
        if len(digits) >= 8:
            digits = digits[:8]
        return digits

    def _extract_download_match_fragments(self, normalized_target: str) -> dict[str, str]:
        tab = ""
        if "nfc-e" in normalized_target:
            tab = "nfc-e"
        elif "ct-e" in normalized_target:
            tab = "ct-e"
        elif "nf-e" in normalized_target:
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
        month_match = re.search(
            r"detalhamento\s+([a-zçãõáéíóúâêîôû]+)\s+de\s+(\d{4})",
            normalized_target,
            re.IGNORECASE,
        )
        month = month_match.group(1) if month_match else ""
        year = month_match.group(2) if month_match else ""
        return {
            "tab": tab,
            "view": view,
            "month": month,
            "year": year,
        }

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

    def _download_row_matches_taxpayer(self, row: Locator, taxpayer_key: str) -> bool:
        cells = row.locator("td")
        row_documents: list[str] = []
        for cell_index in (0, 1):
            try:
                cell_text = cells.nth(cell_index).inner_text(timeout=2_000)
            except Error:
                continue
            document_key = self._document_key(cell_text)
            if document_key:
                row_documents.append(document_key)
        return taxpayer_key in row_documents

    def _document_key(self, value: str) -> str:
        return self._normalize_numeric_document(value)

    def _capture_download_from_row(
        self,
        page: Page,
        row: Locator,
        tela_aba: str,
        cgf: str,
        month_reference: str,
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
        return self._save_download(download, cgf, month_reference, basename, document_tab)

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

    def _return_from_detail_to_fiscal_menu(self, page: Page) -> None:
        back_candidates = (
            page.get_by_role("button", name=re.compile(r"voltar|retornar|fechar", re.IGNORECASE)),
            page.get_by_role("link", name=re.compile(r"voltar|retornar|fechar", re.IGNORECASE)),
        )
        for locator in back_candidates:
            target = self._first_visible_enabled(locator)
            if target is not None:
                target.click()
                page.wait_for_timeout(1_000)
                return

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

    def _build_taxpayer_output_dir(self, cgf: str, month_reference: str, document_tab: str | None = None) -> Path:
        output_dir = self.settings.output_dir / cgf / slugify(month_reference)
        if document_tab:
            output_dir = output_dir / document_tab
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _save_download(
        self,
        download: Download,
        cgf: str,
        month_reference: str,
        basename: str,
        document_tab: str,
    ) -> Path:
        output_dir = self._build_taxpayer_output_dir(cgf, month_reference, document_tab)
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
        return re.sub(r"\D", "", value)

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
                return

        raise TimeoutError(f"Nao foi possivel clicar em: {', '.join(names)}.")

    def _click_xpath(self, page: Page, xpath: str, label: str, force: bool = False) -> bool:
        target = self._first_visible_enabled(page.locator(xpath))
        if target is None:
            return False
        LOGGER.info("Clicando em %s via XPath: %s", label, xpath)
        target.click(force=force)
        return True

    def _ensure_side_menu_open(self, page: Page) -> bool:
        """Expande o menu lateral quando ele estiver recolhido, evitando bloqueio de navegação."""
        menu_toggle_xpath = (
            "xpath=//*[@id='main-structure-header-id']/div/div[1]/ed-header-v2-track-one/"
            "div/div/div/div[1]/div/i"
        )
        menu_toggle = self._first_visible_enabled(page.locator(menu_toggle_xpath))
        if menu_toggle is None:
            return False

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

    def _click_xlsx_detail_download_button(self, page: Page) -> bool:
        """Clica no botao XLSX por locator ou, se preciso, direto pelo DOM."""
        target = self._find_xlsx_detail_download_button(page)
        if target is not None:
            target.click(force=True)
            return True

        script = """
        (buttonText) => {
            const normalize = (value) => String(value || "")
                .normalize("NFD")
                .replace(/[\\u0300-\\u036f]/g, "")
                .replace(/\\s+/g, " ")
                .trim()
                .toLowerCase();
            const wanted = normalize(buttonText);
            const candidates = [...document.querySelectorAll("button, a, [role='button']")];

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
                if (text === wanted || (text.includes("baixar tabela") && text.includes("xlsx"))) {
                    element.scrollIntoView({block: "center", inline: "center"});
                    element.click();
                    return true;
                }
            }
            return false;
        }
        """
        try:
            return bool(page.evaluate(script, "Baixar Tabela (XLSX)"))
        except Error:
            return False

    def _find_row_by_digits(self, page: Page, target_digits: str, max_candidates: int = 80) -> Locator | None:
        candidates = page.locator("tr, [role='row'], .p-datatable-row, .card")
        try:
            count = candidates.count()
        except Error:
            return None

        if count > max_candidates:
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

