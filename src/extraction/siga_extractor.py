from __future__ import annotations

import logging
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from playwright.sync_api import BrowserContext, Download, Error, Locator, Page, TimeoutError

from src.auth.siga_login import SigaLoginFlow
from src.config import Settings
from src.extraction.spreadsheet import SpreadsheetRow
from src.utils.browser import BrowserSession
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
    cgf: str
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


class SigaContributorExtractor:
    def __init__(self, settings: Settings, allow_manual_login_prompt: bool = True) -> None:
        self.settings = settings
        self.allow_manual_login_prompt = allow_manual_login_prompt
        self.page_inspector = SigaPageInspector(settings)

    def run(self, cnpj: str) -> ExtractionResult:
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
            LOGGER.info("Saved extraction screenshot to %s", screenshot_path)

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
    ) -> list[BatchExtractionResult]:
        with BrowserSession(self.settings) as context:
            return self.run_batch_from_spreadsheet_in_context(
                context,
                spreadsheet_rows,
                month_reference,
            )

    def run_batch_from_spreadsheet_in_context(
        self,
        context: BrowserContext,
        spreadsheet_rows: list[SpreadsheetRow],
        month_reference: str,
    ) -> list[BatchExtractionResult]:
        normalized_month = month_reference.strip()
        if not normalized_month:
            raise ValueError("Informe o mes de referencia antes de iniciar a extracao.")

        results: list[BatchExtractionResult] = []
        page = context.pages[0] if context.pages else context.new_page()
        page = self._ensure_authenticated(page, context)

        for spreadsheet_row in spreadsheet_rows:
            LOGGER.info("Processing CGF %s from spreadsheet row %s", spreadsheet_row.cgf, spreadsheet_row.row_number)
            self._return_to_home(page)
            self._search_taxpayer(page, spreadsheet_row.cgf)
            self._open_taxpayer(page, spreadsheet_row.cgf)
            fiscal_results = self._extract_fiscal_tables(page, spreadsheet_row.cgf, normalized_month)

            results.append(
                BatchExtractionResult(
                    cgf=spreadsheet_row.cgf,
                    month_reference=normalized_month,
                    taxpayer_folder=self._build_taxpayer_output_dir(spreadsheet_row.cgf, normalized_month),
                    fiscal_results=fiscal_results,
                    final_url=page.url,
                    status="completed_with_downloads" if fiscal_results else "completed_without_downloads",
                    message=(
                        f"Downloads concluidos para {spreadsheet_row.cgf}."
                        if fiscal_results
                        else f"Nenhum download foi solicitado para {spreadsheet_row.cgf}."
                    ),
                )
            )

        return results

    def _extract_fiscal_tables(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
    ) -> list[FiscalDownloadResult]:
        results: list[FiscalDownloadResult] = []
        for tab_config in self._build_fiscal_tab_configs():
            results.extend(self._extract_fiscal_tab(page, cgf, month_reference, tab_config))
        return results

    def _extract_fiscal_tab(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        tab_config: FiscalTabConfig,
    ) -> list[FiscalDownloadResult]:
        LOGGER.info("Starting fiscal extraction for tab %s", tab_config.tab_name)
        self._open_fiscal_information(page)
        self._open_document_tab(page, tab_config)

        summary_paths: dict[str, Path] = {}
        eligible_profiles: list[FiscalProfileConfig] = []

        for profile in tab_config.profiles:
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
                        summary_paths[profile.label],
                    )
                )
                continue

            tela_aba = self._build_download_screen_name(
                month_reference=month_reference,
                tab_name=tab_config.tab_name,
                view_label=self._display_label(profile.label),
                detail_label="Autorizadas",
                selected_year=self._resolve_selected_year_from_page(page),
            )
            self._request_detail_download(page)
            pending_requests.append(
                PendingDetailRequest(
                    document_tab=tab_config.tab_slug,
                    profile_name=profile.label,
                    summary_path=summary_paths[profile.label],
                    report_name="Autorizadas",
                    tela_aba=tela_aba,
                )
            )

        if not pending_requests:
            return []

        detail_paths = self._download_pending_detail_requests(page, cgf, month_reference, pending_requests)
        results: list[FiscalDownloadResult] = []
        for request in pending_requests:
            results.append(
                FiscalDownloadResult(
                    document_tab=request.document_tab,
                    profile_name=request.profile_name,
                    summary_path=request.summary_path,
                    detail_path=detail_paths[request.tela_aba],
                    selected_report_name=request.report_name,
                    month_reference=month_reference,
                )
            )
        return results

    def _ensure_authenticated(self, page: Page, context: BrowserContext) -> Page:
        LOGGER.info("Opening SIGA to reuse authenticated session")
        page.goto(self.settings.siga_url, wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
        if "siga.sefaz.ce.gov.br/ui" in page.url:
            self.page_inspector.stabilize_after_navigation(page, "extract-open")

        if self._has_taxpayer_search(page):
            LOGGER.info("Authenticated SIGA page detected")
            return page

        LOGGER.info("Authenticated area not detected yet, starting manual login handoff")
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
        try:
            if page.locator("input").count() == 0:
                return False
        except Error:
            return False

        text = page.locator("body").inner_text(timeout=5_000)
        search_signals = ("contribuinte", "cnpj", "cpf", "cgf", "pesquisar", "consulta")
        return any(signal in strip_accents(text).lower() for signal in search_signals)

    def _search_taxpayer(self, page: Page, document_value: str) -> None:
        LOGGER.info("Searching taxpayer %s", document_value)
        search_input = self._find_search_input(page)
        search_input.click()
        search_input.fill("")
        search_input.fill(document_value)
        search_input.press("Enter")
        page.wait_for_timeout(2_000)

    def _find_search_input(self, page: Page) -> Locator:
        xpath_input = self._first_visible_enabled(
            page.locator("xpath=//input[contains(@placeholder,'CGF') or contains(@placeholder,'Raz')]")
        )
        if xpath_input is not None:
            LOGGER.info("Using XPath selector for taxpayer search input")
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
        LOGGER.info("Opening taxpayer row for %s", document_value)
        if self._is_taxpayer_detail_page(page):
            LOGGER.info("Taxpayer detail view already detected; skipping row selection for %s", document_value)
            return

        row = self._find_taxpayer_row(page, document_value)
        if row is None:
            # Visual fallback already clicked the row/card. Wait and validate detail view.
            page.wait_for_timeout(3_000)
            if self._is_taxpayer_detail_page(page):
                return
            self._save_debug_snapshot(page, f"open-taxpayer-not-confirmed-{document_value}")
            raise TimeoutError(
                f"O contribuinte {document_value} foi clicado visualmente, mas a tela de detalhes nao foi confirmada."
            )

        if self._open_detail_from_row(page, row):
            page.wait_for_timeout(3_000)
            return

        row.click()
        page.wait_for_timeout(3_000)
        if self._is_taxpayer_detail_page(page):
            return

        self._save_debug_snapshot(page, f"open-taxpayer-not-confirmed-{document_value}")
        raise TimeoutError(
            f"O contribuinte {document_value} foi clicado, mas a tela de detalhes nao foi confirmada."
        )

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
        )

        for locator in detail_candidates:
            target = self._first_visible_enabled(locator)
            if target is None:
                continue
            LOGGER.info("Opening taxpayer detail using Detalhamento action")
            target.click(timeout=5_000)
            return True

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
                LOGGER.info("Using XPath selector for taxpayer row %s", value)
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

        # Digits-only fallback: match rows/cards where normalized digits contain the target.
        digits = self._normalize_numeric_document(document_value)
        if digits:
            row = self._find_row_by_digits(page, digits)
            if row is not None:
                return row

        self._save_debug_snapshot(page, f"row-not-found-{document_value}")
        raise TimeoutError(f"Nao foi possivel localizar o contribuinte {document_value} na lista.")

    def _open_fiscal_information(self, page: Page) -> None:
        LOGGER.info("Opening Informacoes Fiscais")
        if self._click_xpath(
            page,
            "xpath=//a[contains(@href,'/informacoes-fiscais')]",
            "Informacoes Fiscais side menu",
        ):
            page.wait_for_timeout(2_000)
            return

        self._click_text_action(
            page,
            names=("Informacoes Fiscais", "Informacoes fiscais"),
            artifact_name="informacoes-fiscais",
            fallback_task="Locate and click the section, tab or button labeled Informacoes Fiscais.",
        )
        page.wait_for_timeout(2_000)

    def _build_fiscal_tab_configs(self) -> tuple[FiscalTabConfig, ...]:
        return (
            FiscalTabConfig(
                tab_name="NF-e",
                tab_slug="NF-e",
                tab_xpath="xpath=//a[contains(@href,'/informacoes-fiscais/nfe')]",
                detail_mode="reports",
                profiles=(
                    FiscalProfileConfig(label="Emissor", summary_basename="resumo-saida"),
                    FiscalProfileConfig(label="Destinatario", summary_basename="resumo-entrada"),
                ),
            ),
            FiscalTabConfig(
                tab_name="NFC-e",
                tab_slug="NFC-e",
                tab_xpath="xpath=//a[contains(@href,'/informacoes-fiscais/nfce')]",
                detail_mode="authorized",
                month_requires_positive_value=False,
                profiles=(
                    FiscalProfileConfig(
                        label="Emissor",
                        summary_basename="Emissor-resumo",
                        annual_quantity_label=(
                            "Quantidade Total de Documentos Autorizados e Emitidos pelo Contribuinte no Ano"
                        ),
                        annual_value_label=(
                            "Valor Total de Documentos Autorizados e Emitidos pelo Contribuinte no Ano"
                        ),
                    ),
                    FiscalProfileConfig(
                        label="Destinatario",
                        summary_basename="Destinatario-resumo",
                        annual_quantity_label=(
                            "Quantidade Total de Documentos Autorizados e Emitidos para o Contribuinte no Ano"
                        ),
                        annual_value_label=(
                            "Valor Total de Documentos Autorizados e Emitidos para o Contribuinte no Ano"
                        ),
                    ),
                ),
            ),
        )

    def _open_document_tab(self, page: Page, tab_config: FiscalTabConfig) -> None:
        LOGGER.info("Opening fiscal document tab %s", tab_config.tab_name)
        if self._click_xpath(page, tab_config.tab_xpath, f"{tab_config.tab_name} tab"):
            page.wait_for_timeout(2_000)
            return

        self._click_text_action(
            page,
            names=(tab_config.tab_name,),
            artifact_name=f"tab-{slugify(tab_config.tab_name)}",
            fallback_task=f"Locate and click the fiscal tab labeled {tab_config.tab_name}.",
        )
        page.wait_for_timeout(2_000)

    def _open_named_section(self, page: Page, label: str) -> None:
        LOGGER.info("Opening fiscal section %s", label)
        normalized_label = strip_accents(label).lower()
        if normalized_label == "emissor" and self._click_xpath(
            page,
            "xpath=//*[@role='radio' and contains(@aria-label,'Emissor')]",
            "Emissor radio",
            force=True,
        ):
            page.wait_for_timeout(1_500)
            return
        if normalized_label == "destinatario" and self._click_xpath(
            page,
            "xpath=//*[@role='radio' and contains(@aria-label,'Destinat')]",
            "Destinatario radio",
            force=True,
        ):
            page.wait_for_timeout(1_500)
            return

        self._click_text_action(
            page,
            names=(label,),
            artifact_name=f"section-{slugify(label)}",
            fallback_task=f"Locate and click the fiscal section labeled {label}.",
        )
        page.wait_for_timeout(1_500)

    def open_reference_month_if_positive(
        self,
        page: Page,
        month_reference: str,
        require_positive_value: bool = True,
    ) -> MonthOpenDecision:
        LOGGER.info("Checking month reference %s before opening it", month_reference)
        metric = self._get_indicator_metric(page, month_reference)
        if metric is None:
            raise TimeoutError(f"Nao foi possivel localizar o mes de referencia {month_reference}.")

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
        LOGGER.info("Opening month reference %s", month_reference)
        month_xpath = (
            f"xpath=//tr[.//span[normalize-space()='{month_reference}']]//td[1]//div"
        )
        if self._click_xpath(page, month_xpath, f"month row {month_reference}"):
            page.wait_for_timeout(1_500)
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
                page.wait_for_timeout(1_500)
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
                page.wait_for_timeout(1_500)
                return

        raise TimeoutError(f"Nao foi possivel localizar o mes de referencia {month_reference}.")

    def _select_positive_reports(self, page: Page) -> list[str]:
        LOGGER.info("Selecting reports with QTD and VALOR greater than zero")
        reports = ("Interna", "Interestadual", "Externa")
        metrics = self._collect_indicator_metrics(page, reports)
        selected_reports: list[str] = []
        for report_name in reports:
            metric = metrics.get(report_name.lower())
            if metric and metric["qtd"] > 0 and metric["valor"] > 0:
                selected_reports.append(report_name)

        if selected_reports:
            LOGGER.info("Positive reports selected for detail download: %s", ", ".join(selected_reports))
            return selected_reports

        LOGGER.info("No detail reports with positive QTD and VALOR were found on the page")
        return []

    def _should_download_profile_summary(
        self,
        page: Page,
        tab_config: FiscalTabConfig,
        profile: FiscalProfileConfig,
    ) -> bool:
        if not profile.annual_quantity_label or not profile.annual_value_label:
            return True

        quantity_value = self._parse_decimal_value(self._extract_metric(page, profile.annual_quantity_label))
        total_value = self._parse_decimal_value(self._extract_metric(page, profile.annual_value_label))
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
        selected_year = self._resolve_selected_year_from_page(page)
        for report_name in positive_reports:
            self._click_report_by_name(page, report_name)
            page.wait_for_timeout(1_500)
            tela_aba = self._build_download_screen_name(
                month_reference=month_reference,
                tab_name=tab_config.tab_name,
                view_label=self._display_label(profile.label),
                detail_label=report_name,
                selected_year=selected_year,
            )
            self._request_detail_download(page)
            requests.append(
                PendingDetailRequest(
                    document_tab=tab_config.tab_slug,
                    profile_name=profile.label,
                    summary_path=summary_path,
                    report_name=report_name,
                    tela_aba=tela_aba,
                )
            )
        return requests

    def _display_label(self, label: str) -> str:
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

            for (const row of rows) {
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
            return results;
        }
        """
        try:
            result = page.evaluate(script, list(names))
        except Error:
            return {}
        return result if isinstance(result, dict) else {}

    def _get_indicator_metric(self, page: Page, name: str) -> IndicatorMetric | None:
        metrics = self._collect_indicator_metrics(page, (name,))
        metric = metrics.get(strip_accents(name).lower())
        if not metric:
            return None
        return IndicatorMetric(name=name, qtd=float(metric["qtd"]), valor=float(metric["valor"]))

    def _click_report_by_name(self, page: Page, report_name: str) -> None:
        report_xpath = f"xpath=//tr[./td[1][normalize-space()='{report_name}']]/td[1]"
        if self._click_xpath(page, report_xpath, f"detail row {report_name}"):
            return

        self._click_text_action(
            page,
            names=(report_name,),
            artifact_name=f"report-{slugify(report_name)}",
            fallback_task=f"Locate and click the report named {report_name}.",
        )

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
        LOGGER.info("Clicking Baixar Tabela")
        self._click_text_action(
            page,
            names=("Baixar Tabela",),
            artifact_name="baixar-tabela",
            fallback_task="Locate and click the action button Baixar Tabela.",
        )
        page.wait_for_timeout(1_500)

    def _click_summary_download_button(self, page: Page) -> None:
        target = self._find_download_button(page, expected_index=0)
        if target is not None:
            LOGGER.info("Clicking summary download button")
            target.click()
            page.wait_for_timeout(1_500)
            return
        self._click_download_table_button(page)

    def _request_detail_download(self, page: Page) -> None:
        target = self._find_download_button(page, expected_index=1)
        if target is None:
            raise TimeoutError("Nao foi possivel localizar o botao Baixar Tabela do bloco de detalhamento.")
        LOGGER.info("Requesting detail download using the detail section button")
        target.click()
        page.wait_for_timeout(2_000)

    def _find_download_button(self, page: Page, expected_index: int) -> Locator | None:
        xpath_locator = page.locator(
            f"xpath=(//button[.//span[contains(normalize-space(.),'Baixar Tabela')]])[{expected_index + 1}]"
        )
        xpath_target = self._first_visible_enabled(xpath_locator)
        if xpath_target is not None:
            LOGGER.info("Using XPath selector for Baixar Tabela button index %s", expected_index)
            return xpath_target

        locator = page.get_by_role("button", name="Baixar Tabela")
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

    def _capture_direct_download(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        basename: str,
        document_tab: str,
    ) -> Path:
        try:
            with page.expect_download(timeout=10_000) as download_info:
                self._click_summary_download_button(page)
            download = download_info.value
            return self._save_download(download, cgf, month_reference, basename, document_tab)
        except TimeoutError:
            LOGGER.info("Direct download did not start immediately for %s", basename)
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
        LOGGER.info("Opening Downloads menu to fetch %s pending detail file(s)", len(pending_requests))
        if self._click_xpath(
            page,
            "xpath=//a[contains(@href,'/downloads-assincronos')]",
            "Downloads side menu",
        ):
            page.wait_for_timeout(2_000)
        else:
            self._click_text_action(
                page,
                names=("Downloads",),
                artifact_name="downloads",
                fallback_task="Locate and click the Downloads area in the side menu.",
            )
            page.wait_for_timeout(2_000)

        detail_paths: dict[str, Path] = {}
        for request in pending_requests:
            detail_paths[request.tela_aba] = self._download_requested_file(
                page,
                cgf,
                month_reference,
                request.tela_aba,
                request.document_tab,
            )

        page.goto(origin_url, wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
        page.wait_for_timeout(1_500)
        return detail_paths

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

    def _click_download_action(self, row: Locator) -> None:
        candidates = (
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
        row.click()

    def _build_download_screen_name(
        self,
        month_reference: str,
        tab_name: str,
        view_label: str,
        detail_label: str,
        selected_year: str,
    ) -> str:
        normalized_month = re.sub(r"\s+", " ", month_reference).strip()
        return (
            f"Informacoes Fiscais - {tab_name} - {view_label} - "
            f"Detalhamento {normalized_month} de {selected_year} - {detail_label}"
        )

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

    def _download_requested_file(
        self,
        page: Page,
        cgf: str,
        month_reference: str,
        tela_aba: str,
        document_tab: str,
    ) -> Path:
        LOGGER.info("Downloading requested file for TELA/ABA: %s", tela_aba)
        download_row = self._find_download_row_by_screen_name(page, tela_aba)
        signed_urls: list[str] = []

        def on_response(response) -> None:
            if "/api/v1/solicitacoes/" not in response.url or "/download" not in response.url:
                return
            location = response.headers.get("location")
            if location:
                signed_urls.append(location)

        page.on("response", on_response)
        try:
            self._click_download_action(download_row)
            page.wait_for_timeout(2_500)
        finally:
            page.remove_listener("response", on_response)

        if signed_urls:
            signed_url = signed_urls[-1]
            output_path = self._save_signed_download(cgf, month_reference, tela_aba, signed_url, document_tab)
            LOGGER.info("Saved download center file via signed URL to %s", output_path)
            return output_path

        LOGGER.warning(
            "Signed URL was not captured for %s. Falling back to direct browser download capture.",
            tela_aba,
        )
        output_path = self._capture_download_from_row(
            page=page,
            row=download_row,
            cgf=cgf,
            month_reference=month_reference,
            basename=self._sanitize_filename(tela_aba),
            document_tab=document_tab,
        )
        LOGGER.info("Saved download center file via direct capture to %s", output_path)
        return output_path

    def _find_download_row_by_screen_name(self, page: Page, tela_aba: str) -> Locator:
        normalized_target = strip_accents(self._normalize_spaces(tela_aba)).lower()
        match_fragments = self._extract_download_match_fragments(normalized_target)
        deadline = time.time() + (self.settings.download_wait_timeout_ms / 1000)
        while time.time() < deadline:
            rows = page.locator("tr")
            try:
                row_count = rows.count()
            except Error:
                row_count = 0

            exact_candidates: list[tuple[Locator, datetime, str]] = []
            fuzzy_candidates: list[tuple[Locator, float, datetime, str]] = []
            for index in range(1, row_count):
                row = rows.nth(index)
                try:
                    tela_aba_text = strip_accents(
                        self._normalize_spaces(row.locator("td").nth(2).inner_text(timeout=2_000))
                    ).lower()
                    requested_at_text = self._normalize_spaces(row.locator("td").nth(5).inner_text(timeout=2_000))
                    status_text = strip_accents(
                        self._normalize_spaces(row.locator("td").nth(7).inner_text(timeout=2_000))
                    ).lower()
                except Error:
                    continue

                if tela_aba_text == normalized_target and "concluido" in status_text:
                    exact_candidates.append((row, self._parse_request_datetime(requested_at_text), tela_aba_text))
                    continue
                if "concluido" not in status_text:
                    continue
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
                if score >= 3.0:
                    fuzzy_candidates.append(
                        (row, score, self._parse_request_datetime(requested_at_text), tela_aba_text)
                    )

            if exact_candidates:
                exact_candidates.sort(key=lambda item: item[1], reverse=True)
                best_row, best_dt, best_text = exact_candidates[0]
                LOGGER.info(
                    "Download row match strategy: exact-latest (candidates=%s, requested_at=%s, chosen='%s')",
                    len(exact_candidates),
                    best_dt.isoformat(sep=" ", timespec="seconds"),
                    best_text,
                )
                return best_row

            if fuzzy_candidates:
                fuzzy_candidates.sort(key=lambda item: (item[1], item[2]), reverse=True)
                best_row, best_score, best_dt, best_text = fuzzy_candidates[0]
                LOGGER.info(
                    "Download row match strategy: fuzzy-latest (score=%s, candidates=%s, requested_at=%s, chosen='%s')",
                    best_score,
                    len(fuzzy_candidates),
                    best_dt.isoformat(sep=" ", timespec="seconds"),
                    best_text,
                )
                return best_row

            page.wait_for_timeout(self.settings.download_poll_interval_ms)

        raise TimeoutError(f"Nao foi possivel localizar a solicitacao concluida para {tela_aba}.")

    def _extract_download_match_fragments(self, normalized_target: str) -> dict[str, str]:
        tab = "nfc-e" if "nfc-e" in normalized_target else ("nf-e" if "nf-e" in normalized_target else "")
        view = ""
        if "destinatario" in normalized_target:
            view = "destinatario"
        elif "emissor" in normalized_target:
            view = "emissor"
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
        normalized = self._normalize_spaces(value)
        # Exemplo SIGA: 26/05/2026 às 13:52:43
        match = re.search(r"(\d{2}/\d{2}/\d{4})\s+(?:as|às)\s+(\d{2}:\d{2}:\d{2})", normalized, re.IGNORECASE)
        if not match:
            return datetime.min
        try:
            return datetime.strptime(f"{match.group(1)} {match.group(2)}", "%d/%m/%Y %H:%M:%S")
        except ValueError:
            return datetime.min

    def _capture_download_from_row(
        self,
        page: Page,
        row: Locator,
        cgf: str,
        month_reference: str,
        basename: str,
        document_tab: str,
    ) -> Path:
        with page.expect_download(timeout=self.settings.download_wait_timeout_ms) as download_info:
            self._click_download_action(row)
        download = download_info.value
        return self._save_download(download, cgf, month_reference, basename, document_tab)

    def _save_signed_download(
        self,
        cgf: str,
        month_reference: str,
        tela_aba: str,
        signed_url: str,
        document_tab: str,
    ) -> Path:
        output_dir = self._build_taxpayer_output_dir(cgf, month_reference, document_tab)
        output_path = output_dir / f"{self._sanitize_filename(tela_aba)}.csv"
        with urllib.request.urlopen(signed_url, timeout=60) as response:
            output_path.write_bytes(response.read())
        return output_path

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
            locator = page.locator(f"text=/{re.escape(pattern)}/i")
            try:
                if locator.count():
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
        LOGGER.info("Saved XLSX output to %s", output_path)
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
        extension = self._resolve_download_extension(download)
        output_path = output_dir / f"{basename}{extension}"
        LOGGER.info(
            "Saving download with deterministic name: basename=%s, suggested_filename=%s, final_path=%s",
            basename,
            download.suggested_filename,
            output_path,
        )
        download.save_as(str(output_path))
        LOGGER.info("Saved download to %s", output_path)
        return output_path

    def _resolve_download_extension(self, download: Download) -> str:
        suggested_name = download.suggested_filename or ""
        suffix = Path(suggested_name).suffix.lower().strip()
        if suffix in {".csv", ".txt"}:
            return ".csv"
        # Some SIGA responses expose UUID-like or extensionless names; enforce CSV.
        if re.fullmatch(r"[a-f0-9-]{20,}", suggested_name.lower()):
            return ".csv"
        return ".csv"

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
        LOGGER.info("Clicking %s via XPath: %s", label, xpath)
        target.click(force=force)
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

    def _find_row_by_digits(self, page: Page, target_digits: str) -> Locator | None:
        candidates = page.locator("tr, [role='row'], .p-datatable-row, .card")
        try:
            count = candidates.count()
        except Error:
            return None

        for index in range(count):
            candidate = candidates.nth(index)
            try:
                text = candidate.inner_text(timeout=2_000)
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

