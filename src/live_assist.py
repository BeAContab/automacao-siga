from __future__ import annotations

"""Modo assistido para executar ações manuais no mesmo navegador da automação."""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from contextlib import suppress

from src.auth.siga_login import FlowResult, SigaLoginFlow
from src.config import PROJECT_ROOT, Settings
from src.extraction.siga_extractor import SigaContributorExtractor
from src.utils.browser import BrowserSession, get_connect_browser_url, launch_debug_browser
from src.utils.browser import get_debug_browser_pid_path
from src.utils.selenium_compat import BrowserContext, Download, Page
from src.utils.siga_page import SigaPageInspector


LOGGER = logging.getLogger(__name__)

SESSION_STATE_PATH = PROJECT_ROOT / "brain" / "live_assist_session.json"
ACTIONS_LOG_PATH = PROJECT_ROOT / "brain" / "live_assist_actions.jsonl"


@dataclass(slots=True)
class LiveCommandResult:
    description: str
    current_url: str
    page_title: str


class LiveAssistRecorder:
    """Persistência simples do contexto da sessão assistida e do histórico de ações."""
    def __init__(self) -> None:
        self.session_state_path = SESSION_STATE_PATH
        self.actions_log_path = ACTIONS_LOG_PATH
        self.session_state_path.parent.mkdir(parents=True, exist_ok=True)

    def save_session_state(self, payload: dict[str, object]) -> None:
        """Grava o estado atual da sessão para retomada e auditoria."""
        self.session_state_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def append_action(self, payload: dict[str, object]) -> None:
        """Acrescenta uma linha no histórico de ações realizadas no navegador."""
        with self.actions_log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=True) + "\n")


class LiveAssistSession:
    """Mantém o navegador aberto para que comandos pontuais possam ser disparados depois."""
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not self.settings.connect_browser_url:
            self.settings.connect_browser_url = get_connect_browser_url(self.settings)
        self.recorder = LiveAssistRecorder()
        self.page_inspector = SigaPageInspector(settings)
        self.extractor = SigaContributorExtractor(settings, allow_manual_login_prompt=False)

    def start(self) -> FlowResult:
        """Abre o SIGA, aguarda login manual e persiste a sessão pronta para uso."""
        process = launch_debug_browser(self.settings)
        if process is None:
            LOGGER.info("Reutilizando a sessão de navegador existente para o modo assistido")
        else:
            LOGGER.info("Navegador aberto para o modo assistido com PID %s", process.pid)

        input(
            "Conclua o login manual no navegador aberto e pressione Enter "
            "somente quando o SIGA estiver autenticado..."
        )

        flow = SigaLoginFlow(self.settings)
        with BrowserSession(self.settings) as context:
            page = flow.confirm_authenticated_context(context, browser=context.browser)
            self._persist_session_state(page)
            return FlowResult(
                final_url=page.url,
                page_title=page.title(),
                manual_login_confirmed=True,
            )

    def execute_command(
        self,
        command: str,
        target: str | None = None,
        value: str | None = None,
    ) -> LiveCommandResult:
        """Executa um comando assistido e registra o estado antes e depois da ação."""
        with BrowserSession(self.settings) as context:
            page = self._select_active_page(context)
            url_before = page.url

            # Cada comando é mapeado explicitamente para manter o fluxo previsível e auditável.
            if command == "click-text":
                self._require_target(command, target)
                page.get_by_text(target, exact=False).first.click(timeout=self.settings.timeout_ms)
                description = f"Cliquei no texto '{target}'."
            elif command == "click-selector":
                self._require_target(command, target)
                page.locator(target).first.click(timeout=self.settings.timeout_ms)
                description = f"Cliquei no seletor '{target}'."
            elif command == "click-label":
                self._require_target(command, target)
                page.get_by_label(target, exact=False).first.click(timeout=self.settings.timeout_ms)
                description = f"Cliquei no campo/controle com label '{target}'."
            elif command == "fill-selector":
                self._require_target(command, target)
                page.locator(target).first.fill(value or "", timeout=self.settings.timeout_ms)
                description = f"Preenchi o seletor '{target}'."
            elif command == "fill-label":
                self._require_target(command, target)
                page.get_by_label(target, exact=False).first.fill(value or "", timeout=self.settings.timeout_ms)
                description = f"Preenchi o campo com label '{target}'."
            elif command == "press":
                self._require_target(command, target)
                page.keyboard.press(target)
                description = f"Pressionei '{target}'."
            elif command == "wait-text":
                self._require_target(command, target)
                page.get_by_text(target, exact=False).first.wait_for(
                    state="visible",
                    timeout=self.settings.timeout_ms,
                )
                description = f"Esperei o texto '{target}' ficar visivel."
            elif command == "click-coordinates":
                self._require_target(command, target)
                x_pos, y_pos = self._parse_coordinates(target)
                page.mouse.click(x_pos, y_pos)
                description = f"Cliquei nas coordenadas ({x_pos}, {y_pos})."
            elif command == "screenshot":
                screenshot_path = self._save_screenshot(page)
                description = f"Screenshot salva em {screenshot_path}."
            elif command == "download-table":
                self._require_target(command, target)
                output_path = self._download_table(page, target)
                description = f"Tabela baixada com nome controlado em {output_path}."
            elif command == "open-month-if-positive":
                self._require_target(command, target)
                decision = self.extractor.open_reference_month_if_positive(page, target)
                if decision.opened:
                    description = f"Mes '{target}' aberto com sucesso."
                else:
                    description = f"Mes '{target}' nao foi aberto. Motivo: {decision.reason}."
            elif command == "request-positive-details":
                reports = self.extractor._select_positive_reports(page)
                if not reports:
                    description = "Nenhum detalhamento com QTD positiva foi encontrado."
                else:
                    for report_name in reports:
                        self.extractor._click_report_by_name(page, report_name)
                        page.wait_for_timeout(750)
                        self.extractor._request_detail_download(page)
                    description = f"Solicitei os detalhamentos com QTD positiva: {', '.join(reports)}."
            elif command == "close-browser":
                closed = False
                if context.browser is not None:
                    context.browser.close()
                    closed = True
                with suppress(OSError):
                    get_debug_browser_pid_path(self.settings).unlink()
                description = (
                    "Navegador encerrado com sucesso."
                    if closed
                    else "Nao foi possivel confirmar o encerramento do navegador."
                )
            elif command == "show-url":
                description = "Consultei a URL atual."
            elif command == "list-pages":
                description = self._list_pages(context)
            else:
                raise ValueError(
                "Comando inválido. Use um dos comandos suportados: "
                    "click-text, click-selector, click-label, fill-selector, fill-label, "
                    "press, wait-text, click-coordinates, screenshot, "
                    "download-table, open-month-if-positive, request-positive-details, "
                    "close-browser, show-url, list-pages."
                )

            if command == "close-browser":
                self.recorder.append_action(
                    {
                        "timestamp": self._timestamp(),
                        "command": command,
                        "target": target,
                        "value": value,
                        "url_before": url_before,
                        "url_after": "",
                        "page_title": "",
                        "description": description,
                    }
                )
                return LiveCommandResult(
                    description=description,
                    current_url="",
                    page_title="Navegador encerrado",
                )

            page.wait_for_timeout(1_000)
            current_page = self._select_active_page(context)
            self.recorder.append_action(
                {
                    "timestamp": self._timestamp(),
                    "command": command,
                    "target": target,
                    "value": value,
                    "url_before": url_before,
                    "url_after": current_page.url,
                    "page_title": current_page.title(),
                    "description": description,
                }
            )
            self._persist_session_state(current_page)
            return LiveCommandResult(
                description=description,
                current_url=current_page.url,
                page_title=current_page.title(),
            )

    def _ensure_page(self, context: BrowserContext) -> Page:
        """Garante que exista uma aba útil do SIGA antes de aceitar comandos."""
        page = self._select_active_page(context)
        if page.url == "about:blank":
            LOGGER.info("Abrindo a página do SIGA para o modo assistido")
            page.goto(
                self.settings.siga_url,
                wait_until="domcontentloaded",
                timeout=self.settings.timeout_ms,
            )
        if "siga.sefaz.ce.gov.br/ui" in page.url:
            self.page_inspector.stabilize_after_navigation(page, "live-assist-open")
        return page

    def _select_active_page(self, context: BrowserContext) -> Page:
        """Escolhe a aba mais provável de conter a interface do SIGA."""
        pages = [page for page in context.pages if not page.is_closed()]
        if not pages:
            return context.new_page()

        for page in reversed(pages):
            if "siga.sefaz.ce.gov.br" in page.url:
                page.bring_to_front()
                return page

        page = pages[-1]
        page.bring_to_front()
        return page

    def _persist_session_state(self, page: Page) -> None:
        """Armazena URL e título atuais para facilitar retomada do contexto."""
        self.recorder.save_session_state(
            {
                "updated_at": self._timestamp(),
                "connect_browser_url": get_connect_browser_url(self.settings),
                "page_title": page.title(),
                "page_url": page.url,
            }
        )

    def _save_screenshot(self, page: Page) -> Path:
        """Salva uma captura rápida do estado atual do navegador assistido."""
        screenshot_path = self.settings.log_dir / f"{self._artifact_name('live-assist')}.png"
        page.screenshot(path=str(screenshot_path), full_page=False)
        return screenshot_path

    def _download_table(self, page: Page, basename: str) -> Path:
        """Baixa a tabela visível e renomeia o arquivo de forma determinística."""
        attempts = max(1, self.settings.download_retry_count)
        for attempt in range(1, attempts + 1):
            try:
                with page.expect_download(timeout=self.settings.download_wait_timeout_ms) as download_info:
                    page.get_by_role("button", name="Baixar Tabela").click(timeout=self.settings.timeout_ms)
                download = download_info.value
                return self._save_download(download, basename)
            except TimeoutError:
                if attempt < attempts:
                    page.wait_for_timeout(self.settings.download_retry_delay_ms)
                    continue
                raise

    def _save_download(self, download: Download, basename: str) -> Path:
        """Move o arquivo baixado para a pasta do modo assistido."""
        output_dir = self.settings.output_dir / "live-assist"
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = "".join(Path(download.suggested_filename).suffixes).strip() or ".csv"
        output_path = output_dir / f"{basename}{suffix}"
        LOGGER.info(
            "Salvando download do modo assistido: nome_base=%s nome_sugerido=%s caminho_final=%s",
            basename,
            download.suggested_filename,
            output_path,
        )
        download.save_as(str(output_path))
        return output_path

    def _list_pages(self, context: BrowserContext) -> str:
        """Produz uma visão textual das páginas abertas para diagnóstico rápido."""
        open_pages = [page for page in context.pages if not page.is_closed()]
        lines = []
        for index, page in enumerate(open_pages, start=1):
            lines.append(f"[{index}] {page.title()} -> {page.url}")
        return "\n".join(lines) if lines else "Nenhuma página aberta."

    def _artifact_name(self, prefix: str) -> str:
        """Gera um nome curto baseado em data e hora para artefatos temporários."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{prefix}-{stamp}"

    def _parse_coordinates(self, target: str) -> tuple[int, int]:
        """Converte a entrada `x,y` em coordenadas inteiras."""
        values = [part.strip() for part in target.split(",", maxsplit=1)]
        if len(values) != 2:
            raise ValueError("Use coordenadas no formato 'x,y'.")
        return int(values[0]), int(values[1])

    def _require_target(self, command: str, target: str | None) -> None:
        """Valida se o comando recebeu o alvo obrigatório."""
        if not target:
            raise ValueError(f"O comando '{command}' exige --target.")

    def _timestamp(self) -> str:
        """Cria uma marca temporal simples para registrar ações."""
        return datetime.now().isoformat(timespec="seconds")
