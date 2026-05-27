from __future__ import annotations

import logging
from pathlib import Path

from playwright.sync_api import Error, Page, TimeoutError

from src.config import Settings


LOGGER = logging.getLogger(__name__)


class SigaPageInspector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def stabilize_after_navigation(self, page: Page, reason: str) -> None:
        for attempt in range(self.settings.blank_page_retry_count + 1):
            self._wait_for_settle(page)
            diagnosis = self.inspect(page)
            if not diagnosis["needs_recovery"]:
                if attempt > 0:
                    LOGGER.info("Recovered SIGA page after %s reload(s)", attempt)
                return

            artifact_name = f"{reason}-blank-{attempt + 1}"
            self.save_debug_artifacts(page, artifact_name)

            if attempt >= self.settings.blank_page_retry_count:
                raise TimeoutError(
                    "A pagina do SIGA nao renderizou corretamente apos as tentativas de recarga."
                )

            LOGGER.warning(
                "Detected problematic SIGA render state (%s). Reloading page (%s/%s).",
                diagnosis["reason"],
                attempt + 1,
                self.settings.blank_page_retry_count,
            )
            page.reload(wait_until="domcontentloaded", timeout=self.settings.timeout_ms)

    def inspect(self, page: Page) -> dict[str, object]:
        url = page.url
        body_text = ""
        app_root_count = 0
        app_root_text = ""

        try:
            body_text = page.locator("body").inner_text(timeout=5_000).strip()
        except Error:
            body_text = ""

        try:
            app_root = page.locator(self.settings.siga_app_root_selector)
            app_root_count = app_root.count()
            if app_root_count:
                app_root_text = app_root.first.inner_text(timeout=5_000).strip()
        except Error:
            app_root_count = 0
            app_root_text = ""

        normalized_body = " ".join(body_text.split())
        normalized_root = " ".join(app_root_text.split())
        body_too_empty = len(normalized_body) < 30
        missing_app_root = "siga.sefaz.ce.gov.br/ui" in url and app_root_count == 0
        empty_app_root = app_root_count > 0 and len(normalized_root) == 0 and len(normalized_body) < 80

        needs_recovery = body_too_empty or missing_app_root or empty_app_root
        reason = "healthy"
        if missing_app_root:
            reason = "missing-app-root"
        elif empty_app_root:
            reason = "empty-app-root"
        elif body_too_empty:
            reason = "nearly-empty-body"

        return {
            "needs_recovery": needs_recovery,
            "reason": reason,
            "body_length": len(normalized_body),
            "app_root_count": app_root_count,
            "app_root_length": len(normalized_root),
        }

    def save_debug_artifacts(self, page: Page, name: str) -> tuple[Path, Path]:
        screenshot_path = self.settings.log_dir / f"{name}.png"
        html_path = self.settings.log_dir / f"{name}.html"
        page.screenshot(path=str(screenshot_path), full_page=True)
        html_path.write_text(page.content(), encoding="utf-8")
        LOGGER.info("Saved debug snapshot to %s and %s", screenshot_path, html_path)
        return screenshot_path, html_path

    def _wait_for_settle(self, page: Page) -> None:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=self.settings.timeout_ms)
        except TimeoutError:
            pass

        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except TimeoutError:
            page.wait_for_timeout(2_000)
