from __future__ import annotations

"""Interface gráfica baseada em Webview (HTML5/Tailwind/JS) para o SIGA Automação."""

import json
import logging
import time
import threading
from pathlib import Path
import webview

from src.auth.siga_login import SigaLoginFlow
from src.config import Settings
from src.extraction.siga_extractor import SigaContributorExtractor
from src.extraction.spreadsheet import SpreadsheetRow, load_cnpjs_from_xlsx
from src.utils.browser import BrowserSession, launch_debug_browser
from src.utils.logging_setup import configure_logging
from src.months import MONTH_OPTIONS

LOGGER = logging.getLogger(__name__)


class WebviewLogHandler(logging.Handler):
    """Redireciona todas as mensagens de logs da aplicação em tempo real
    para a área de console na interface HTML do webview.
    """

    def __init__(self, api: SigaWebviewAPI) -> None:
        super().__init__()
        self.api = api

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            if self.api.window:
                # Garante que caracteres de quebra de linha ou aspas não quebrem a string JS
                js_safe_msg = json.dumps(message)
                self.api.window.evaluate_js(f"window.addConsoleLog('{record.levelname}', {js_safe_msg})")
        except Exception:  # noqa: BLE001
            pass


class SigaWebviewAPI:
    """API de ponte de comunicação (Bridge) entre o Javascript no HTML
    e os serviços Python do SIGA Automação.
    """

    def __init__(
        self,
        settings: Settings,
        initial_month: str | None = None,
        initial_year: str | None = None,
        initial_spreadsheet: str | None = None,
    ) -> None:
        self.settings = settings
        self.initial_month = initial_month
        self.initial_year = initial_year
        self.initial_spreadsheet = initial_spreadsheet
        
        self.window: webview.Window | None = None
        self.rows: list[SpreadsheetRow] = []
        self.selected_file: str = initial_spreadsheet or "cnpj.xlsx"
        self._browser_started = False

    def get_initial_settings(self) -> dict[str, str]:
        """Retorna as configurações e parâmetros padrão para inicializar o formulário no HTML."""
        month = self.initial_month or self._default_current_month()
        year = self.initial_year or str(time.localtime().tm_year)
        output_dir = str(self.settings.output_dir).replace("\\", "/")
        return {
            "month": month,
            "year": year,
            "output_dir": output_dir,
        }

    def load_spreadsheet_from_base64(self, filename: str, b64_data: str) -> None:
        """Processa uma planilha carregada pelo usuário no navegador via Drag and Drop ou Input File.
        
        Args:
            filename: O nome original do arquivo.
            b64_data: O conteúdo do arquivo em Base64 (Data URI ou apenas a string).
        """
        import base64
        import tempfile
        import os

        def _process_file() -> None:
            try:
                # Remove o prefixo do data URI se houver (ex: 'data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,')
                if "," in b64_data:
                    encoded_data = b64_data.split(",", 1)[1]
                else:
                    encoded_data = b64_data

                file_bytes = base64.b64decode(encoded_data)

                # Salva o arquivo em uma pasta temporária para uso da engine openpyxl
                temp_dir = tempfile.gettempdir()
                temp_path = Path(temp_dir) / f"siga_upload_{int(time.time())}_{filename}"
                temp_path.write_bytes(file_bytes)
                
                self.selected_file = str(temp_path)

                # Processa e carrega os CNPJs usando a rotina interna do SIGA
                rows = load_cnpjs_from_xlsx(temp_path)
                self.rows = rows
                
                # Formata os dados em dicionários para enviar ao Javascript
                rows_data = [
                    {
                        "row_number": r.row_number,
                        "cnpj": r.cnpj,
                        "cod": r.cod,
                        "empresa": r.empresa,
                    }
                    for r in rows
                ]
                
                # Injeta os dados na tabela HTML
                self.window.evaluate_js(
                    f"window.updateSpreadsheetRows({json.dumps(rows_data)}, {json.dumps(filename)})"
                )
                LOGGER.info("Planilha carregada via HTML5 Drag/Drop: %s (%d CNPJs encontrados)", filename, len(rows))
                
                # Tenta remover o arquivo temporário por limpeza (opcional)
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

            except Exception as e:  # noqa: BLE001
                LOGGER.exception("Falha ao processar a planilha recebida em Base64")
                if self.window:
                    self.window.evaluate_js(
                        f"window.addConsoleLog('ERROR', 'Erro ao processar planilha: {str(e)}')"
                    )

        threading.Thread(target=_process_file, daemon=True).start()

    def select_output_folder(self) -> None:
        """Abre uma caixa de diálogo nativa do sistema para seleção da pasta de saída."""
        import subprocess

        def _open_folder_dialog() -> None:
            try:
                # Dispara o diálogo de pastas do Windows usando PowerShell em modo STA
                cmd = [
                    "powershell",
                    "-STA",
                    "-NoProfile",
                    "-Command",
                    "Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description = 'Selecionar Pasta de Saída'; if($d.ShowDialog() -eq 'OK'){ $d.SelectedPath }"
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, shell=False)
                folder_path = result.stdout.strip()

                if folder_path:
                    clean_path = folder_path.replace("\\", "/")
                    # Atualiza diretamente o valor do input no HTML
                    self.window.evaluate_js(
                        f"document.getElementById('input-output-dir').value = '{clean_path}';"
                    )
            except Exception as e:  # noqa: BLE001
                LOGGER.exception("Falha ao carregar a pasta de saída")

        threading.Thread(target=_open_folder_dialog, daemon=True).start()

    def start_browser(self) -> None:
        """Inicia um navegador Chrome de debug configurado em segundo plano."""
        if self._browser_started:
            LOGGER.warning("Instância do navegador de debug já está iniciada.")
            return

        def worker() -> None:
            try:
                LOGGER.info("Iniciando instância de debug do navegador...")
                launch_debug_browser(self.settings)
                self._browser_started = True
                LOGGER.info("Navegador de debug iniciado. Certifique-se de realizar o login no SIGA.")
            except Exception as e:  # noqa: BLE001
                LOGGER.exception("Erro ao iniciar navegador de debug")
                if self.window:
                    self.window.evaluate_js(
                        f"window.addConsoleLog('ERROR', 'Não foi possível iniciar o navegador: {str(e)}')"
                    )

        threading.Thread(target=worker, daemon=True).start()

    def run_extraction(self, params: dict) -> bool:
        """Dispara a extração em lote dos CNPJs e abas selecionados na interface web."""
        if not params.get("items"):
            LOGGER.error("Nenhum item selecionado para extração.")
            return False

        def worker() -> None:
            try:
                # Atualiza as configurações com a pasta de saída informada na interface
                self.settings.output_dir = Path(params["output_dir"])

                # Reconstrói os objetos de CNPJs e a matriz de abas ativas
                selected_rows: list[SpreadsheetRow] = []
                selected_tabs_by_row_number: dict[int, list[str]] = {}

                for item in params["items"]:
                    row = SpreadsheetRow(
                        row_number=item["row_number"],
                        cnpj=item["cnpj"],
                        cod=item["cod"],
                        empresa=item["empresa"],
                    )
                    selected_rows.append(row)
                    selected_tabs_by_row_number[row.row_number] = item["selected_docs"]

                # Executa o extrator
                extractor = SigaContributorExtractor(self.settings, allow_manual_login_prompt=False)
                flow = SigaLoginFlow(self.settings)

                LOGGER.info("Iniciando processo de lote na interface gráfica...")
                with BrowserSession(self.settings) as context:
                    authenticated_page = flow.confirm_authenticated_context(context, browser=context.browser)
                    LOGGER.info("Login confirmado no portal SIGA: %s", authenticated_page.title())

                    results = extractor.run_batch_from_spreadsheet_in_context(
                        context,
                        selected_rows,
                        params["month"],
                        str(params["year"]),
                        selected_tabs=None,
                        selected_tabs_by_row_number=selected_tabs_by_row_number,
                    )

                    download_count = sum(len(result.fiscal_results) for result in results)
                    not_found_count = sum(1 for result in results if result.status == "taxpayer_not_found")

                    LOGGER.info("=== Resumo Geral da Extração ===")
                    LOGGER.info("Contribuintes processados: %d de %d", len(results), len(selected_rows))
                    LOGGER.info("Empresas não localizadas: %d", not_found_count)
                    LOGGER.info("Arquivos gerados/baixados: %d", download_count)
                    if results:
                        LOGGER.info("Última pasta de saída: %s", results[-1].taxpayer_folder)

            except Exception as e:  # noqa: BLE001
                LOGGER.exception("Erro crítico no fluxo de extração da GUI")
                if self.window:
                    self.window.evaluate_js(
                        f"window.addConsoleLog('ERROR', 'Erro na extração: {str(e)}')"
                    )

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _default_current_month(self) -> str:
        """Determina o mês atual para servir como referência padrão."""
        current_struct = time.localtime()
        current_idx = current_struct.tm_mon - 1
        return MONTH_OPTIONS[current_idx]


def launch_gui_webview(
    settings: Settings,
    initial_spreadsheet: str | None = None,
    initial_month: str | None = None,
    initial_year: str | None = None,
) -> int:
    """Cria e abre a janela da interface gráfica baseada em Webview (PyWebView)."""
    settings.ensure_runtime_dirs()
    
    # Configura e inicializa a gravação do log em run.log
    if not logging.getLogger().handlers:
        configure_logging(settings.log_dir / "run.log")

    # Define o template HTML
    html_path = Path(__file__).parent / "gui.html"
    if not html_path.exists():
        # Fallback para o caso de empacotamento ou caminhos de build
        html_path = Path(sys.argv[0]).parent / "gui" / "gui.html"

    # Se ainda assim não encontrar, tenta localizar na raiz de execução
    if not html_path.exists():
        html_path = Path("src/gui/gui.html")

    # Inicializa a API da ponte
    api = SigaWebviewAPI(
        settings=settings,
        initial_month=initial_month,
        initial_year=initial_year,
        initial_spreadsheet=initial_spreadsheet,
    )

    # Cria o manipulador de Logs para transferi-los à console da GUI
    log_handler = WebviewLogHandler(api)
    log_handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(log_handler)

    # Cria a janela principal do WebView
    window = webview.create_window(
        title="SIGA Automação",
        url=str(html_path.resolve()),
        js_api=api,
        width=1280,
        height=860,
        min_size=(1080, 720),
    )
    api.window = window

    # Inicia a aplicação com depuração desabilitada para ocultar DevTools
    webview.start(debug=False)

    # Remove o log handler ao encerrar para evitar vazamento
    logging.getLogger().removeHandler(log_handler)
    return 0
