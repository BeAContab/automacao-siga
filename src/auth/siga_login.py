from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from playwright.sync_api import Browser, BrowserContext, Error, Page, TimeoutError

from src.config import Settings
from src.utils.browser import BrowserSession
from src.utils.siga_page import SigaPageInspector


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class FlowResult:
    final_url: str
    page_title: str
    manual_login_confirmed: bool


class SigaLoginFlow:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.page_inspector = SigaPageInspector(settings)

    def run(self) -> FlowResult:
        with BrowserSession(self.settings) as context:
            page = context.pages[0] if context.pages else context.new_page()
            self._open_siga(page)
            page = self.wait_for_manual_login(page, context)
            page.screenshot(path=str(self.settings.screenshot_path), full_page=True)
            LOGGER.info("Screenshot saved to %s", self.settings.screenshot_path)

            return FlowResult(
                final_url=page.url,
                page_title=page.title(),
                manual_login_confirmed=True,
            )

    def wait_for_manual_login(self, page: Page, context: BrowserContext) -> Page:
        if self.settings.headless:
            raise TimeoutError("Login manual exige navegador visivel. Execute sem --headless.")

        LOGGER.info("Browser opened for manual login at %s", page.url)
        input("Faca o login manualmente no navegador aberto e pressione Enter para continuar...")
        LOGGER.info("User confirmed manual login, waiting for authenticated SIGA page")
        return self.confirm_authenticated_context(context)

    def confirm_authenticated_context(self, context: BrowserContext, browser: Browser | None = None) -> Page:
        LOGGER.info("Validating authenticated SIGA page")
        return self._wait_for_authenticated_page(context, browser=browser)

    def _open_siga(self, page: Page) -> None:
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
        deadline = time.time() + (self.settings.manual_login_timeout_ms / 1000)
        while time.time() < deadline:
            contexts: list[BrowserContext] = [context]
            if browser is not None:
                with_contexts = [ctx for ctx in browser.contexts if ctx not in contexts]
                contexts.extend(with_contexts)

            for active_context in contexts:
                for candidate in active_context.pages:
                    try:
                        if "siga.sefaz.ce.gov.br" not in candidate.url:
                            continue
                        candidate.wait_for_load_state("domcontentloaded", timeout=5_000)
                        if "siga.sefaz.ce.gov.br/ui" in candidate.url:
                            self.page_inspector.stabilize_after_navigation(candidate, "post-login")
                        return candidate
                    except Error:
                        continue
            time.sleep(1)

        raise TimeoutError("Pagina autenticada do SIGA nao foi detectada apos a confirmacao do login manual.")
