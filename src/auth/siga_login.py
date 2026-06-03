from __future__ import annotations

"""Fluxo de autenticação manual e validação da sessão autenticada do SIGA."""

import logging
import re
import time
from dataclasses import dataclass

from src.config import Settings
from src.utils.selenium_compat import Browser, BrowserContext, Error, Page, TimeoutError
from src.utils.browser import BrowserSession
from src.utils.siga_page import SigaPageInspector


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class FlowResult:
    final_url: str
    page_title: str
    manual_login_confirmed: bool


class SigaLoginFlow:
    """Encapsula a abertura do SIGA, a espera pelo login manual e a validação final."""
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.page_inspector = SigaPageInspector(settings)

    def run(self) -> FlowResult:
        """Executa o fluxo completo de login e devolve o estado da sessão."""
        with BrowserSession(self.settings) as context:
            page = self.attach_to_existing_authenticated_page(context, browser=context.browser)
            if page is None:
                page = context.pages[0] if context.pages else context.new_page()
                self._open_siga(page)
                page = self.wait_for_manual_login(page, context, browser=context.browser)
            page.screenshot(path=str(self.settings.screenshot_path), full_page=True)
            LOGGER.info("Screenshot saved to %s", self.settings.screenshot_path)

            return FlowResult(
                final_url=page.url,
                page_title=page.title(),
                manual_login_confirmed=True,
            )

    def wait_for_manual_login(
        self,
        page: Page,
        context: BrowserContext,
        browser: Browser | None = None,
    ) -> Page:
        """Pausa o fluxo para que o usuário conclua a autenticação manual no navegador."""
        if self.settings.prefer_existing_siga_session:
            attached_page = self.attach_to_existing_authenticated_page(context, browser=browser)
            if attached_page is not None:
                return attached_page

        if self.settings.headless:
            raise TimeoutError("Login manual exige navegador visivel. Execute sem --headless.")

        LOGGER.info("Browser opened for manual login at %s", page.url)
        input("Faca o login manualmente no navegador aberto e pressione Enter para continuar...")
        LOGGER.info("User confirmed manual login, waiting for authenticated SIGA page")
        return self.confirm_authenticated_context(context, browser=browser)

    def confirm_authenticated_context(self, context: BrowserContext, browser: Browser | None = None) -> Page:
        """Espera até localizar uma página do SIGA já autenticada."""
        LOGGER.info("Validating authenticated SIGA page")
        return self._wait_for_authenticated_page(context, browser=browser)

    def attach_to_existing_authenticated_page(
        self,
        context: BrowserContext,
        browser: Browser | None = None,
    ) -> Page | None:
        """Tenta reaproveitar uma aba autenticada já aberta no navegador."""
        LOGGER.info("Trying to attach to an existing authenticated SIGA page")
        for active_context in self._iter_contexts(context, browser):
            for candidate in active_context.pages:
                try:
                    if not self._is_authenticated_siga_page(candidate):
                        continue
                    candidate.bring_to_front()
                    LOGGER.info("Attached to existing authenticated SIGA page at %s", candidate.url)
                    return candidate
                except Error:
                    continue
        LOGGER.info("No authenticated SIGA page was available for attach")
        return None

    def _open_siga(self, page: Page) -> None:
        """Abre a URL principal do SIGA e aguarda a estabilização inicial da tela."""
        LOGGER.info("Opening SIGA at %s", self.settings.siga_url)
        page.goto(self.settings.siga_url, wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
        if "siga.sefaz.ce.gov.br/ui" in page.url:
            self.page_inspector.stabilize_after_navigation(page, "siga-open")
        try:
            page.wait_for_url(
                re.compile(r"(sso\.sefaz\.ce\.gov\.br|gov\.br|acesso\.gov\.br)"),
                timeout=10_000,
            )
        except TimeoutError:
            pass
        page.wait_for_timeout(3_000)

    def _wait_for_authenticated_page(self, context: BrowserContext, browser: Browser | None = None) -> Page:
        """Varre as abas até encontrar a área autenticada do SIGA."""
        deadline = time.time() + (self.settings.manual_login_timeout_ms / 1000)
        while time.time() < deadline:
            for active_context in self._iter_contexts(context, browser):
                for candidate in active_context.pages:
                    try:
                        if not self._is_authenticated_siga_page(candidate):
                            continue
                        return candidate
                    except Error:
                        continue
            time.sleep(1)

        raise TimeoutError("Pagina autenticada do SIGA nao foi detectada apos a confirmacao do login manual.")

    def _iter_contexts(self, context: BrowserContext, browser: Browser | None) -> list[BrowserContext]:
        """Monta a lista de contextos de navegador que precisam ser inspecionados."""
        contexts: list[BrowserContext] = [context]
        if browser is not None:
            for candidate_context in browser.contexts:
                if candidate_context not in contexts:
                    contexts.append(candidate_context)
        return contexts

    def _is_authenticated_siga_page(self, page: Page) -> bool:
        """Valida se a página aberta realmente pertence à área autenticada do SIGA."""
        if page.is_closed():
            return False
        if "siga.sefaz.ce.gov.br/ui" not in page.url:
            return False

        page.wait_for_load_state("domcontentloaded", timeout=5_000)
        self.page_inspector.stabilize_after_navigation(page, "authenticated-check")
        diagnosis = self.page_inspector.inspect(page)
        return bool(diagnosis["app_root_count"]) and not bool(diagnosis["needs_recovery"])
