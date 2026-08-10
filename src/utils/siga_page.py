from __future__ import annotations

"""Inspeção e estabilização das páginas do SIGA antes das ações de automação."""

import logging
from pathlib import Path

from src.config import Settings
from src.utils.selenium_compat import Error, Page, TimeoutError


LOGGER = logging.getLogger(__name__)


class SigaPageInspector:
    """Detecta telas vazias, falhas de renderização e produz artefatos de diagnóstico."""
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def stabilize_after_navigation(self, page: Page, reason: str) -> None:
        """Aplica tentativas de recuperação quando o SIGA renderiza vazio ou quebrado."""
        for attempt in range(self.settings.blank_page_retry_count + 1):
            self._wait_for_settle(page)
            diagnosis = self.inspect(page)
            if not diagnosis["needs_recovery"]:
                if attempt > 0:
                    LOGGER.info("Pagina do SIGA recuperada apos %s recarga(s)", attempt)
                return

            artifact_name = f"{reason}-blank-{attempt + 1}"
            self.save_debug_artifacts(page, artifact_name)

            if attempt >= self.settings.blank_page_retry_count:
                raise TimeoutError(
                    "A pagina do SIGA nao renderizou corretamente apos as tentativas de recarga."
                )

            LOGGER.warning(
                "Estado problematico de renderizacao do SIGA detectado (%s). Recarregando a pagina (%s/%s).",
                diagnosis["reason"],
                attempt + 1,
                self.settings.blank_page_retry_count,
            )
            page.reload(wait_until="domcontentloaded", timeout=self.settings.timeout_ms)

    def inspect(self, page: Page) -> dict[str, object]:
        """Resume o estado visual da página para decidir se é preciso recuperar a tela."""
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
        """Salva screenshot e HTML quando a página parece estar em estado inválido.

        Os artefatos ficam em uma subpasta "diagnostico" dentro de `settings.output_dir`
        (que a GUI mantém sincronizado com a pasta da planilha selecionada) em vez da pasta
        interna `logs/` do app, para que o operador encontre a evidência junto da planilha
        ao investigar um caso como "contribuinte não encontrado" em outra máquina.
        """
        debug_dir = self.settings.output_dir / "diagnostico"
        debug_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = debug_dir / f"{name}.png"
        html_path = debug_dir / f"{name}.html"
        page.screenshot(path=str(screenshot_path), full_page=True)
        html_path.write_text(page.content(), encoding="utf-8")
        LOGGER.info("Captura de depuracao salva em %s e %s", screenshot_path, html_path)
        return screenshot_path, html_path

    def _wait_for_settle(self, page: Page) -> None:
        """Espera a navegação desacelerar antes de inspecionar a interface."""
        try:
            page.wait_for_load_state("domcontentloaded", timeout=self.settings.timeout_ms)
        except TimeoutError:
            pass

        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except TimeoutError:
            page.wait_for_timeout(2_000)
