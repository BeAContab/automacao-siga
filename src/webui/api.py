from __future__ import annotations

"""Métodos Python expostos ao JavaScript (`js_api` do pywebview).

Este módulo é o equivalente direto dos *event handlers* da antiga GUI Tkinter: recebe
a intenção do usuário vinda da interface, valida, e dispara o backend de extração numa
thread de trabalho. O backend em si (`SigaContributorExtractor`, `NfceBatchExtractor`,
`MeudanfeBatchExtractor`, `SigaLoginFlow`, `BrowserSession`) não sofreu nenhuma
alteração nesta migração.

Duas convenções importantes:

- **Toda validação é refeita aqui**, mesmo que o JavaScript já tenha validado antes de
  chamar. A validação do lado da interface existe só para dar resposta imediata; a
  verdade fica no Python, e os dois lados podem divergir com o tempo.
- **Nenhum método bloqueia.** Os `start_*` devolvem `{"ok": ...}` na hora e o progresso
  real chega pela `JsBridge`, empurrado da thread de trabalho — o mesmo desenho de
  antes, em que a GUI nunca esperava a extração terminar.
"""

import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from src import __version__
from src.config import Settings
from src.extraction.spreadsheet import (
    SpreadsheetRow,
    build_manual_entry_workbook,
    load_cnpjs_from_text,
    load_cnpjs_from_xlsx,
)
from src.months import MONTH_OPTIONS
from src.utils.browser import (
    BrowserSession,
    get_connect_browser_url,
    launch_debug_browser,
)
from src.utils.narration import (
    NARRATION_LOGGER_NAME,
    narrate,
    narrate_error,
    narrate_success,
    narrate_warning,
)
from src.webui.bridge import JsBridge

LOGGER = logging.getLogger(__name__)

# Rótulos e descrições dos modos — o Python é a fonte de verdade, a interface só exibe
# o que vem de `get_initial_state`.
MODE_LABELS = {
    "siga": "Extração SIGA",
    "nfce": "Extração NFC-e",
    "nfe": "Extração NF-e",
    "chain": "Cadeia Completa",
}

MODE_DESCRIPTIONS = {
    "siga": "Extração em lote de NF-e, NFC-e, CT-e, Malha Fiscal e Débitos Fiscais do portal SIGA.",
    "nfce": "Login automático e download de XML de NFC-e no portal da SEFAZ-CE por empresa.",
    "nfe": "Download de XML/PDF de NF-e por chave de acesso, via consulta pública no Meu DANFE.",
    "chain": "Executa SIGA, depois NF-e e depois NFC-e em sequência, reaproveitando a saída do SIGA como entrada das duas etapas seguintes.",
}

# Filtros dos diálogos nativos de arquivo, por tipo de campo.
FILE_DIALOG_FILTERS = {
    "spreadsheet": ("Planilhas Excel (*.xlsx)", "Todos os arquivos (*.*)"),
    "chrome": ("Executáveis (*.exe)", "Todos os arquivos (*.*)"),
}


def _ok(**extra: Any) -> dict[str, Any]:
    return {"ok": True, **extra}


def _fail(message: str, level: str = "error") -> dict[str, Any]:
    return {"ok": False, "error": message, "level": level}


def _is_folder_or_xlsx(path: Path) -> bool:
    """True se `path` é uma pasta OU um arquivo `.xlsx` — os modos NF-e/NFC-e aceitam
    tanto uma pasta de resultado do SIGA quanto um arquivo solto único como entrada."""
    return path.is_dir() or (path.is_file() and path.suffix.lower() == ".xlsx")


def _row_to_dict(row: SpreadsheetRow) -> dict[str, Any]:
    return {
        "row_number": row.row_number,
        "cod": row.cod,
        "empresa": row.empresa,
        "cnpj": row.cnpj,
    }


def _dict_to_row(raw: dict[str, Any]) -> SpreadsheetRow:
    """Reconstrói o `SpreadsheetRow` a partir do que a interface devolveu."""
    return SpreadsheetRow(
        row_number=int(raw["row_number"]),
        cnpj=str(raw.get("cnpj") or ""),
        cod=str(raw.get("cod") or ""),
        empresa=str(raw.get("empresa") or ""),
    )


def _default_previous_month() -> str:
    """Sugere o mês anterior ao atual como referência padrão."""
    current_month = time.localtime().tm_mon
    return MONTH_OPTIONS[(current_month - 2) % len(MONTH_OPTIONS)]


class Api:
    """Objeto passado como `js_api` — cada método público vira uma chamada do JS.

    **Todo atributo que não seja método precisa começar com `_`.** O pywebview percorre
    recursivamente os membros públicos deste objeto para montar a API do lado JS
    (`webview/util.py`, `get_functions`), e isso tem duas consequências sérias:

    1. Um atributo público apontando para a janela (`Window`) faz o percurso descer em
       `window.native` e nos objetos WinForms/WebView2, estourando o limite de recursão
       — o efeito prático é a ponte JS nunca ficar pronta e a interface travar em branco.
    2. `Settings` guarda, em tempo de execução, o CPF e a senha digitados no modo NFC-e.
       Mantê-lo público aqui o colocaria no caminho dessa varredura, sem necessidade
       nenhuma — o JavaScript nunca precisa enxergar o objeto de configuração.
    """

    def __init__(
        self,
        settings: Settings,
        bridge: JsBridge,
        initial_spreadsheet: str | None = None,
        initial_month: str | None = None,
        initial_year: str | None = None,
    ) -> None:
        self._settings = settings
        self._bridge = bridge
        self._window: Any = None

        self._initial_spreadsheet = initial_spreadsheet
        self._initial_month = initial_month
        self._initial_year = initial_year

        self._worker_thread: threading.Thread | None = None
        self._browser_thread: threading.Thread | None = None
        self._browser_started = False

        # Controle cooperativo de pausar/continuar/encerrar (ver src/utils/execution_control.py)
        # — um único par de Event cobre qualquer um dos 3 modos, já que só uma execução roda
        # por vez no processo inteiro (`_reject_if_busy`). `_current_mode` diz qual modo está
        # ativo, para "Encerrar" saber se também deve matar o navegador de depuração (só
        # SIGA/NFC-e o usam) ou não (NF-e gerencia seus próprios Chromes independentes).
        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()
        self._current_mode: str | None = None

    # ---------------------------------------------- estado interno (não exposto ao JS)

    def _attach_window(self, window: Any) -> None:
        """Guarda a janela criada por `app.py` (necessária para os diálogos nativos)."""
        self._window = window

    @property
    def _worker_running(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.is_alive()

    def _join_worker(self, timeout: float) -> None:
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=timeout)

    # ------------------------------------------------------------------ inicialização

    def get_initial_state(self) -> dict[str, Any]:
        """Valores iniciais dos campos — equivale às `tk.StringVar` do construtor antigo."""
        rows: list[dict[str, Any]] = []
        if self._initial_spreadsheet:
            try:
                rows = [_row_to_dict(row) for row in load_cnpjs_from_xlsx(Path(self._initial_spreadsheet))]
            except Exception:  # noqa: BLE001
                LOGGER.exception("Falha ao pré-carregar a planilha informada na linha de comando")

        return {
            "version": __version__,
            "months": list(MONTH_OPTIONS),
            "month": self._initial_month or _default_previous_month(),
            "year": self._initial_year or str(time.localtime().tm_year),
            "nfe_max_workers": self._settings.nf_meudanfe_max_workers,
            "nfce_base_spreadsheet": str(self._settings.nfce_base_spreadsheet_path or ""),
            "mode_labels": MODE_LABELS,
            "mode_descriptions": MODE_DESCRIPTIONS,
            "spreadsheet": self._initial_spreadsheet or "",
            "rows": rows,
        }

    def on_window_ready(self) -> dict[str, Any]:
        """A interface avisa que o contrato JS está registrado; libera o canal direto."""
        self._bridge.mark_ready()
        narrate("Interface pronta.")
        return _ok()

    def report_client_error(self, message: str, detail: str = "") -> dict[str, Any]:
        """Registra no log um erro ocorrido no JavaScript.

        Sem isto, uma falha na camada de interface só apareceria no DevTools — que o
        operador não abre. Assim qualquer erro de interface cai em `logs/run.log` junto
        com o resto do diagnóstico.
        """
        LOGGER.error("Erro na interface (JavaScript): %s | %s", message, detail)
        return _ok()

    # ------------------------------------------------------------------ diálogos nativos

    def pick_file(self, kind: str) -> str | None:
        """Abre o seletor de arquivo. Devolve `None` se o usuário cancelar."""
        file_types = FILE_DIALOG_FILTERS.get(kind, ("Todos os arquivos (*.*)",))
        try:
            import webview

            result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Falha ao abrir o seletor de arquivo")
            return None
        return str(result[0]) if result else None

    def pick_directory(self, kind: str) -> str | None:
        """Abre o seletor de pasta, começando na pasta que já estiver no campo."""
        try:
            import webview

            result = self._window.create_file_dialog(
                webview.FileDialog.FOLDER,
                directory=self._initial_directory_for(kind),
            )
        except Exception:  # noqa: BLE001
            LOGGER.exception("Falha ao abrir o seletor de pasta")
            return None
        return str(result[0]) if result else None

    def _initial_directory_for(self, kind: str) -> str:
        if kind == "siga_output":
            return str(self._settings.output_dir)
        return ""

    # ------------------------------------------------------------------ carga de dados

    def load_spreadsheet(self, path: str) -> dict[str, Any]:
        """Lê os CNPJs de um XLSX para montar a grade de empresas."""
        spreadsheet_path = Path(str(path).strip()).expanduser()
        if not spreadsheet_path.exists():
            return _fail(f"Planilha não encontrada:\n{spreadsheet_path}")
        try:
            rows = load_cnpjs_from_xlsx(spreadsheet_path)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falha ao carregar planilha")
            return _fail(f"Falha ao carregar planilha:\n{exc}")

        narrate_success("Planilha carregada com %s empresa(s).", len(rows))
        return _ok(rows=[_row_to_dict(row) for row in rows])

    def load_manual_cnpjs(self, text: str) -> dict[str, Any]:
        """Interpreta CNPJs digitados manualmente, sem depender de planilha."""
        try:
            rows = load_cnpjs_from_text(str(text))
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falha ao carregar CNPJs manuais")
            return _fail(f"Falha ao carregar CNPJs manuais:\n{exc}")

        if not rows:
            return _fail("Nenhum CNPJ válido foi reconhecido no texto informado.", level="warning")

        narrate_success("Entrada manual com %s CNPJ(s).", len(rows))
        return _ok(rows=[_row_to_dict(row) for row in rows])

    # ------------------------------------------------------------------ navegador

    def start_browser(self, mode: str = "siga") -> dict[str, Any]:
        """Abre o navegador de depuração usado por SIGA/NFC-e.

        No SIGA o login é manual (certificado), então a aba inicial abre direto na tela
        de login do SIGA. No NFC-e o login é automático (CPF/senha), então a aba inicial
        abre no portal SEFAZ-CE em vez da tela do SIGA, que seria irrelevante ali.
        """
        if self._browser_started:
            self._bridge.set_status("O navegador já foi iniciado. Faça o login manual e clique em Executar.")
            return _ok()
        if self._browser_thread is not None and self._browser_thread.is_alive():
            self._bridge.set_status("O navegador já está sendo iniciado. Aguarde alguns instantes.")
            return _ok()

        if not self._settings.connect_browser_url:
            self._settings.connect_browser_url = get_connect_browser_url(self._settings)

        initial_url = self._settings.nfce_login_url if mode == "nfce" else self._settings.siga_url
        narrate("Iniciando o navegador de depuração...")

        def worker() -> None:
            try:
                launch_debug_browser(self._settings, initial_url=initial_url)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Não foi possível abrir o navegador de depuração")
                narrate_error("Falha ao iniciar o navegador: %s", exc)
                self._bridge.browser_failed(str(exc))
            else:
                self._browser_started = True
                if mode == "nfce":
                    narrate_success("Navegador iniciado. Clique em 'Login / Carregar Empresas' para logar automaticamente.")
                else:
                    narrate_success("Navegador iniciado. Aguardando login manual do usuário.")
                self._bridge.browser_started()

        self._browser_thread = threading.Thread(target=worker, daemon=True)
        self._browser_thread.start()
        return _ok()

    # ------------------------------------------------------------------ execução (comum)

    def _start_worker(
        self, target, output_dir: Path, started_status: str, finished_status: str, mode: str
    ) -> dict[str, Any]:
        """Dispara a thread de trabalho com o mesmo envelope de log/estado dos 3 modos."""
        self._pause_event.clear()
        self._cancel_event.clear()
        self._current_mode = mode

        self._bridge.set_progress(0)
        self._bridge.set_status(started_status)

        log_handler = self._open_run_log_file(output_dir)
        narrate("Registrando esta execução em %s", output_dir / "log.txt")

        def worker() -> None:
            try:
                target()
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha na execução disparada pela interface")
                narrate_error("Falha na execução: %s", exc)
                self._bridge.show_message(str(exc), "error")
            finally:
                self._close_run_log_file(log_handler)
                self._bridge.execution_finished(finished_status)

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()
        return _ok()

    def _open_run_log_file(self, output_dir: Path) -> logging.Handler:
        """Grava um `log.txt` (narração + log técnico) junto dos arquivos baixados.

        Facilita conferência e suporte sem precisar abrir a pasta interna de logs — o
        handler vive só pelo tempo da execução.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(str(output_dir / "log.txt"), encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)
        logging.getLogger(NARRATION_LOGGER_NAME).addHandler(handler)
        return handler

    def _close_run_log_file(self, handler: logging.Handler) -> None:
        logging.getLogger().removeHandler(handler)
        logging.getLogger(NARRATION_LOGGER_NAME).removeHandler(handler)
        handler.close()

    def _reject_if_busy(self) -> dict[str, Any] | None:
        if self._worker_running:
            return _fail("Uma execução já está em andamento.", level="info")
        return None

    # ------------------------------------------------------------------ pausar/continuar/encerrar

    def pause_extraction(self) -> dict[str, Any]:
        """Pausa a execução em andamento — cooperativo, some efeito só no próximo ponto seguro
        do laço (início da próxima empresa/chave), não interrompe uma chamada em curso."""
        if not self._worker_running:
            return _fail("Nenhuma execução em andamento para pausar.", level="info")
        self._pause_event.set()
        narrate_warning("Execução pausada pelo usuário. Clique em Continuar para retomar.")
        return _ok()

    def resume_extraction(self) -> dict[str, Any]:
        """Retoma uma execução pausada."""
        if not self._worker_running:
            return _fail("Nenhuma execução em andamento para continuar.", level="info")
        self._pause_event.clear()
        narrate_success("Execução retomada.")
        return _ok()

    def stop_extraction(self) -> dict[str, Any]:
        """Encerra a execução em andamento por completo (não é retomável).

        Sinaliza o cancelamento cooperativo (efetivo no próximo ponto seguro do laço) e,
        para SIGA/NFC-e, também derruba o navegador de depuração na hora — o cancelamento
        sozinho não interrompe uma chamada Selenium já em andamento (ex.: um `wait_for` de
        10-15s), então matar o navegador força essa chamada a falhar rápido, mesma técnica
        já usada em `_on_closing` (`app.py`) ao fechar a janela do app. O modo NF-e não usa
        esse navegador (gerencia seus próprios Chromes via `undetected_chromedriver`,
        fechados individualmente por cada worker ao ver o cancelamento) — chamar
        `shutdown_debug_browser` ali arriscaria matar um navegador de depuração órfão de
        outra sessão sem relação com esta execução.
        """
        if not self._worker_running:
            return _fail("Nenhuma execução em andamento para encerrar.", level="info")
        self._cancel_event.set()
        self._pause_event.clear()  # nao deixa preso pausado — o cancelamento precisa fluir
        narrate_warning("Encerrando a execução a pedido do usuário...")
        # "chain" tambem usa BrowserSession (etapas SIGA e NFC-e da cadeia), mesma razao
        # de siga/nfce: sem isso uma chamada Selenium em andamento nao seria interrompida.
        if self._current_mode in ("siga", "nfce", "chain"):
            from src.utils.browser import shutdown_debug_browser

            shutdown_debug_browser(self._settings)
        return _ok()

    # ------------------------------------------------------------------ execução SIGA

    def start_siga_extraction(self, payload: dict[str, Any]) -> dict[str, Any]:
        busy = self._reject_if_busy()
        if busy:
            return busy
        if not self._browser_started:
            return _fail("Clique em 'Iniciar Navegador' e faça o login antes de executar.", level="warning")

        raw_rows = payload.get("rows") or []
        if not raw_rows:
            return _fail("Selecione pelo menos um CNPJ e uma aba fiscal.", level="warning")

        month = str(payload.get("month") or "").strip()
        if not month:
            return _fail("Informe o mês de referência.", level="warning")
        year = str(payload.get("year") or "").strip()
        if not (year.isdigit() and len(year) == 4):
            return _fail("Informe um ano válido com 4 dígitos.", level="warning")

        output_dir_raw = str(payload.get("output_dir") or "").strip()
        if not output_dir_raw:
            return _fail("Informe uma pasta de saída válida.", level="warning")
        output_dir = Path(output_dir_raw).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _fail(f"Não foi possível criar a pasta de saída:\n{exc}")
        self._settings.output_dir = output_dir

        selected_rows = [_dict_to_row(raw) for raw in raw_rows]
        tabs_by_row_number = {int(raw["row_number"]): list(raw.get("tabs") or []) for raw in raw_rows}
        manual_mode = bool(payload.get("manual_mode"))
        spreadsheet_path = str(payload.get("spreadsheet_path") or "").strip()

        narrate("Execução iniciada pela interface gráfica.")
        return self._start_worker(
            lambda: self._execute_siga(selected_rows, tabs_by_row_number, month, year, manual_mode, spreadsheet_path),
            output_dir,
            "Execução iniciada. Aguarde a conclusão no navegador e no log.",
            "Execução finalizada.",
            mode="siga",
        )

    def _execute_siga(
        self,
        selected_rows: list[SpreadsheetRow],
        tabs_by_row_number: dict[int, list[str]],
        month_reference: str,
        year_value: str,
        manual_mode: bool,
        spreadsheet_path: str,
    ) -> None:
        from src.auth.siga_login import SigaLoginFlow
        from src.extraction.siga_extractor import SigaContributorExtractor

        output_spreadsheet_path = self._prepare_results_spreadsheet(selected_rows, manual_mode, spreadsheet_path)

        extractor = SigaContributorExtractor(
            self._settings,
            allow_manual_login_prompt=False,
            output_spreadsheet_path=output_spreadsheet_path,
        )
        flow = SigaLoginFlow(self._settings)

        with BrowserSession(self._settings) as context:
            authenticated_page = flow.confirm_authenticated_context(context, browser=context.browser)
            narrate_success("Login confirmado: %s", authenticated_page.title())

            def on_row_processed(done: int, total: int) -> None:
                # Reserva os últimos ~10% para a varredura final única da Central de
                # Downloads (não tem granularidade por CNPJ) — os primeiros 90% refletem
                # quantas empresas já tiveram a busca/solicitação concluída de verdade.
                if total > 0:
                    self._bridge.set_progress(min(90.0, (done / total) * 90))

            results = extractor.run_batch_from_spreadsheet_in_context(
                context,
                selected_rows,
                month_reference,
                year_value,
                selected_tabs=None,
                selected_tabs_by_row_number=tabs_by_row_number,
                on_row_processed=on_row_processed,
                cancel_event=self._cancel_event,
                pause_event=self._pause_event,
            )
            # Conta apenas downloads que de fato ocorreram (fiscal.downloaded_at preenchido),
            # nao a quantidade de detalhamentos solicitados/tentados — `fiscal_results` inclui
            # tambem os que falharam ou geraram apenas aviso de indisponibilidade (.txt).
            download_count = sum(
                1
                for result in results
                for fiscal in result.fiscal_results
                if fiscal.downloaded_at is not None
            )
            not_found_count = sum(1 for result in results if result.status == "taxpayer_not_found")
            narrate_success("Processo concluído.")
            narrate("Contribuintes processados: %s de %s", len(results), len(selected_rows))
            narrate("Empresas não encontradas: %s", not_found_count)
            narrate("Detalhamentos baixados: %s", download_count)
            if results:
                narrate("Pasta da última saída: %s", results[-1].taxpayer_folder)

    def _prepare_results_spreadsheet(
        self,
        selected_rows: list[SpreadsheetRow],
        manual_mode: bool,
        spreadsheet_path: str,
    ) -> Path | None:
        """Cria a planilha onde o status de cada CNPJ é gravado durante o lote.

        Vindo de planilha, é uma cópia `_resultados.xlsx` do arquivo original (que nunca
        é alterado). Vindo de entrada manual, não existe arquivo de origem, então é
        gerada uma planilha dedicada na pasta de saída.
        """
        if not manual_mode and spreadsheet_path:
            input_path = Path(spreadsheet_path)
            output_path = input_path.parent / f"{input_path.stem}_resultados{input_path.suffix}"
            try:
                shutil.copy(input_path, output_path)
                narrate_success("Cópia de resultados criada: %s", output_path.name)
                return output_path
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha ao criar cópia da planilha para gravação de resultados")
                narrate_warning("Erro ao criar planilha de resultados: %s", exc)
                return None

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = Path(self._settings.output_dir) / f"resultados_manual_{timestamp}.xlsx"
        try:
            build_manual_entry_workbook(selected_rows, output_path)
            narrate_success("Planilha de resultados criada: %s", output_path.name)
            return output_path
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falha ao criar planilha de resultados para a entrada manual")
            narrate_warning("Erro ao criar planilha de resultados: %s", exc)
            return None

    # ------------------------------------------------------------- descoberta NFC-e

    def load_nfce_companies(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Loga no portal SEFAZ-CE e devolve as empresas elegíveis, para popular a grade
        de seleção antes da execução (substitui a antiga importação de planilha de
        empresas / entrada manual do modo NFC-e — nome e IE agora vêm direto do portal).
        """
        busy = self._reject_if_busy()
        if busy:
            return busy
        if not self._browser_started:
            return _fail("Clique em 'Iniciar Navegador' antes de carregar as empresas.", level="warning")

        cpf = str(payload.get("cpf") or "").strip()
        senha = str(payload.get("senha") or "")
        if not cpf or not senha:
            return _fail("Informe o CPF e a senha do contador antes de usar o modo NFC-e.")

        base_raw = str(payload.get("base_spreadsheet") or "").strip()
        if not base_raw:
            return _fail("Selecione a planilha-base IE/CNPJ.", level="warning")
        base_spreadsheet = Path(base_raw).expanduser()
        if not base_spreadsheet.exists():
            return _fail(f"Planilha-base não encontrada:\n{base_spreadsheet}")

        keys_folder_raw = str(payload.get("keys_folder") or "").strip()
        if not keys_folder_raw:
            return _fail("Selecione a pasta com as planilhas de chaves por empresa.", level="warning")
        keys_folder = Path(keys_folder_raw).expanduser()
        if not _is_folder_or_xlsx(keys_folder):
            return _fail(f"Pasta/arquivo de chaves não encontrado:\n{keys_folder}")

        # CPF/senha vivem só neste atributo, em memória, pelo tempo da execução — nunca
        # são persistidos (nem .env, nem planilha, nem log).
        self._settings.nfce_cpf = cpf
        self._settings.nfce_senha = senha

        # Mesmo tratamento de estado que `_start_worker` dá às execuções de verdade: limpa
        # pausar/cancelar de uma rodada anterior e marca o modo, para que "Pausar"/"Encerrar"
        # funcionem também durante esta chamada — importante porque, se o portal recusar o
        # login por sessão duplicada, o login fica retentando indefinidamente a cada alguns
        # minutos (`Settings.nfce_login_retry_wait_seconds`) até o usuário conseguir de novo
        # ou cancelar.
        self._pause_event.clear()
        self._cancel_event.clear()
        self._current_mode = "nfce"

        narrate("Carregando empresas do portal SEFAZ-CE...")

        def worker() -> None:
            from src.extraction.nfce_extractor import NfceBatchExtractor

            try:
                extractor = NfceBatchExtractor(
                    self._settings,
                    output_dir=self._settings.output_dir,
                    keys_folder=keys_folder,
                    base_spreadsheet_path=base_spreadsheet,
                )
                with BrowserSession(self._settings) as context:
                    rows = extractor.discover_selectable_companies(
                        context, cancel_event=self._cancel_event, pause_event=self._pause_event
                    )
            except Exception as exc:  # noqa: BLE001
                if self._cancel_event.is_set():
                    # A retentativa indefinida de login (sessão duplicada) só para de fato
                    # quando o cancelamento é sinalizado — o caminho normal daí é o login
                    # devolver False e o extractor levantar RuntimeError, não um retorno
                    # limpo; trata isso como cancelamento, não como falha real.
                    narrate_warning("Carregamento de empresas cancelado pelo usuário.")
                    self._bridge.show_message("Carregamento de empresas cancelado.", level="info")
                    return
                LOGGER.exception("Falha ao carregar empresas do portal SEFAZ-CE")
                narrate_error("Falha ao carregar empresas do portal: %s", exc)
                self._bridge.show_message(f"Falha ao carregar empresas do portal:\n{exc}")
                return

            if not rows:
                narrate_warning("Nenhuma empresa elegível encontrada (sem CNPJ resolvido ou sem chaves na pasta).")
                self._bridge.show_message(
                    "Nenhuma empresa elegível foi encontrada — confira a planilha-base e a pasta de chaves.",
                    level="warning",
                )
                return

            narrate_success("%s empresa(s) carregada(s) do portal.", len(rows))
            self._bridge.nfce_companies_loaded(rows)

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()
        return _ok()

    # ------------------------------------------------------------------ execução NFC-e

    def start_nfce_extraction(self, payload: dict[str, Any]) -> dict[str, Any]:
        busy = self._reject_if_busy()
        if busy:
            return busy
        if not self._browser_started:
            return _fail("Clique em 'Iniciar Navegador' antes de executar o modo NFC-e.", level="warning")

        cpf = str(payload.get("cpf") or "").strip()
        senha = str(payload.get("senha") or "")
        if not cpf or not senha:
            return _fail("Informe o CPF e a senha do contador antes de usar o modo NFC-e.")

        output_dir_raw = str(payload.get("output_dir") or "").strip()
        if not output_dir_raw:
            return _fail("Selecione a pasta de saída dos XMLs de NFC-e.", level="warning")
        output_dir = Path(output_dir_raw).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _fail(f"Não foi possível criar a pasta de saída:\n{exc}")

        keys_folder_raw = str(payload.get("keys_folder") or "").strip()
        if not keys_folder_raw:
            return _fail("Selecione a pasta com as planilhas de chaves por empresa.", level="warning")
        keys_folder = Path(keys_folder_raw).expanduser()
        if not _is_folder_or_xlsx(keys_folder):
            return _fail(f"Pasta/arquivo de chaves não encontrado:\n{keys_folder}")

        raw_rows = payload.get("rows") or []
        if not raw_rows:
            return _fail(
                "Carregue pelo menos uma empresa (planilha ou entrada manual) antes de executar.",
                level="warning",
            )
        selected_rows = [_dict_to_row(raw) for raw in raw_rows]

        base_raw = str(payload.get("base_spreadsheet") or "").strip()
        base_spreadsheet = Path(base_raw).expanduser() if base_raw else None

        narrate("Execução do modo NFC-e iniciada pela interface gráfica.")
        return self._start_worker(
            lambda: self._execute_nfce(selected_rows, output_dir, keys_folder, base_spreadsheet, cpf, senha),
            output_dir,
            "Execução NFC-e iniciada. Aguarde a conclusão no log.",
            "Execução NFC-e finalizada.",
            mode="nfce",
        )

    def _execute_nfce(
        self,
        selected_rows: list[SpreadsheetRow],
        output_dir: Path,
        keys_folder: Path,
        base_spreadsheet: Path | None,
        cpf: str,
        senha: str,
    ) -> None:
        from src.extraction.nfce_extractor import NfceBatchExtractor

        # `BrowserContext` deriva o diretório de download de `settings.output_dir` ao
        # abrir a sessão — apontar para a pasta do NFC-e antes de abrir o BrowserSession.
        self._settings.output_dir = output_dir
        self._settings.nfce_keys_folder_path = keys_folder
        self._settings.nfce_base_spreadsheet_path = base_spreadsheet
        # CPF/senha vivem só neste atributo, em memória, pelo tempo da execução —
        # nunca são persistidos (nem .env, nem planilha, nem log).
        self._settings.nfce_cpf = cpf
        self._settings.nfce_senha = senha

        extractor = NfceBatchExtractor(
            self._settings,
            output_dir=output_dir,
            keys_folder=keys_folder,
            base_spreadsheet_path=base_spreadsheet,
        )
        with BrowserSession(self._settings) as context:
            results = extractor.run_batch_in_context(
                context,
                selected_rows,
                cancel_event=self._cancel_event,
                pause_event=self._pause_event,
            )
            success_count = sum(1 for result in results if result.status == "concluido")
            narrate_success("Processo NFC-e concluído.")
            narrate("Empresas processadas com sucesso: %s de %s", success_count, len(results))

    # ------------------------------------------------------------------ execução NF-e

    def start_nfe_extraction(self, payload: dict[str, Any]) -> dict[str, Any]:
        busy = self._reject_if_busy()
        if busy:
            return busy

        input_folder_raw = str(payload.get("input_folder") or "").strip()
        if not input_folder_raw:
            return _fail("Selecione a pasta com as planilhas NF-e.", level="warning")
        input_folder = Path(input_folder_raw).expanduser()
        if not _is_folder_or_xlsx(input_folder):
            return _fail(f"Pasta/arquivo não encontrado:\n{input_folder}")

        output_dir_raw = str(payload.get("output_dir") or "").strip()
        if not output_dir_raw:
            return _fail("Selecione a pasta de destino dos downloads.", level="warning")
        output_folder = Path(output_dir_raw).expanduser()
        try:
            output_folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _fail(f"Não foi possível criar a pasta de destino:\n{exc}")

        try:
            max_workers = int(payload.get("max_workers"))
        except (TypeError, ValueError):
            return _fail("Informe uma quantidade de Chromes entre 1 e 8.", level="warning")
        if not 1 <= max_workers <= 8:
            return _fail("Informe uma quantidade de Chromes entre 1 e 8.", level="warning")

        chrome_raw = str(payload.get("chrome_path") or "").strip()

        narrate("Execução do modo NF-e (Meu DANFE) iniciada pela interface gráfica.")
        return self._start_worker(
            lambda: self._execute_nfe(input_folder, output_folder, max_workers, chrome_raw),
            output_folder,
            "Execução NF-e iniciada. Aguarde a conclusão no log.",
            "Execução NF-e finalizada.",
            mode="nfe",
        )

    def _execute_nfe(self, input_folder: Path, output_folder: Path, max_workers: int, chrome_path: str) -> None:
        from src.extraction.meudanfe_extractor import MeudanfeBatchExtractor

        self._settings.nf_meudanfe_input_folder = input_folder
        self._settings.nf_meudanfe_output_folder = output_folder
        self._settings.nf_meudanfe_max_workers = max_workers
        self._settings.nf_meudanfe_chrome_path = Path(chrome_path).expanduser() if chrome_path else None

        extractor = MeudanfeBatchExtractor(self._settings, input_folder=input_folder, output_folder=output_folder)
        results = extractor.executar_lote(
            on_planilha_concluida=self._push_nfe_result,
            cancelar_evento=self._cancel_event,
            pausar_evento=self._pause_event,
        )
        success_count = sum(1 for result in results if result.status == "concluido")
        narrate_success("Processo NF-e concluído.")
        narrate("Planilhas concluídas: %s de %s", success_count, len(results))

    def _push_nfe_result(self, resultado: Any) -> None:
        """Empurra o resultado de uma planilha para a tabela ao vivo da interface.

        Chamado de dentro de cada worker do `MeudanfeBatchExtractor` — `JsBridge` é
        segura para uso a partir de qualquer thread.
        """
        self._bridge.upsert_nfe_result(self._serialize_nfe_result(resultado))

    @staticmethod
    def _serialize_nfe_result(resultado: Any) -> dict[str, Any]:
        """Converte o `MeudanfeBatchResult` no formato consumido pela tabela.

        O rótulo de status é calculado aqui, e não em `resultado.status`: aquela
        propriedade só distingue sucesso/parcial/erro no fim do lote e, durante a
        execução — antes de qualquer falha ter sido registrada —, já retornaria
        "concluído" mesmo com chaves ainda pendentes. Aqui a comparação é contra o
        total, então uma planilha em andamento aparece como tal.
        """
        processadas = resultado.chaves_baixadas + resultado.chaves_puladas + resultado.chaves_com_falha
        if resultado.chaves_total == 0:
            status_code, status_label = "sem_chaves", "Sem chaves"
        elif processadas < resultado.chaves_total:
            status_code = "andamento"
            status_label = f"Em andamento ({processadas}/{resultado.chaves_total})"
        elif resultado.chaves_com_falha and (resultado.chaves_baixadas + resultado.chaves_puladas):
            status_code, status_label = "parcial", "Parcial"
        elif resultado.chaves_com_falha:
            status_code, status_label = "erro", "Erro"
        else:
            status_code, status_label = "concluido", "Concluído"

        return {
            "caminho": str(resultado.caminho_planilha),
            "nome": resultado.caminho_planilha.name,
            "chaves_total": resultado.chaves_total,
            "chaves_baixadas": resultado.chaves_baixadas,
            "chaves_puladas": resultado.chaves_puladas,
            "chaves_com_falha": resultado.chaves_com_falha,
            "status_code": status_code,
            "status_label": status_label,
        }

    # ------------------------------------------------------------ execução em cadeia

    def start_chain_extraction(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Executa SIGA, depois NF-e (Meu DANFE) e depois NFC-e em sequência.

        Reaproveita a pasta de saída do SIGA como entrada das duas etapas seguintes
        (ver `ChainBatchExtractor`) — o usuário só informa, além dos parâmetros do
        SIGA, as credenciais/planilha-base do NFC-e e os parâmetros do NF-e.
        """
        busy = self._reject_if_busy()
        if busy:
            return busy
        if not self._browser_started:
            return _fail("Clique em 'Iniciar Navegador' e faça o login antes de executar.", level="warning")

        raw_rows = payload.get("rows") or []
        if not raw_rows:
            return _fail("Selecione pelo menos um CNPJ e uma aba fiscal.", level="warning")

        month = str(payload.get("month") or "").strip()
        if not month:
            return _fail("Informe o mês de referência.", level="warning")
        year = str(payload.get("year") or "").strip()
        if not (year.isdigit() and len(year) == 4):
            return _fail("Informe um ano válido com 4 dígitos.", level="warning")

        output_dir_raw = str(payload.get("output_dir") or "").strip()
        if not output_dir_raw:
            return _fail("Informe uma pasta de saída válida.", level="warning")
        output_dir = Path(output_dir_raw).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _fail(f"Não foi possível criar a pasta de saída:\n{exc}")

        cpf = str(payload.get("cpf") or "").strip()
        senha = str(payload.get("senha") or "")
        if not cpf or not senha:
            return _fail("Informe o CPF e a senha do contador (etapa NFC-e).")

        base_raw = str(payload.get("base_spreadsheet") or "").strip()
        if not base_raw:
            return _fail("Selecione a planilha-base CNPJ/IE (etapa NFC-e).", level="warning")
        base_spreadsheet = Path(base_raw).expanduser()
        if not base_spreadsheet.exists():
            return _fail(f"Planilha-base não encontrada:\n{base_spreadsheet}")

        try:
            max_workers = int(payload.get("max_workers"))
        except (TypeError, ValueError):
            return _fail("Informe uma quantidade de Chromes entre 1 e 8 (etapa NF-e).", level="warning")
        if not 1 <= max_workers <= 8:
            return _fail("Informe uma quantidade de Chromes entre 1 e 8 (etapa NF-e).", level="warning")

        chrome_raw = str(payload.get("chrome_path") or "").strip()

        selected_rows = [_dict_to_row(raw) for raw in raw_rows]
        tabs_by_row_number = {int(raw["row_number"]): list(raw.get("tabs") or []) for raw in raw_rows}
        manual_mode = bool(payload.get("manual_mode"))
        spreadsheet_path = str(payload.get("spreadsheet_path") or "").strip()

        narrate("Execução da cadeia completa (SIGA → NF-e → NFC-e) iniciada pela interface gráfica.")
        return self._start_worker(
            lambda: self._execute_chain(
                selected_rows,
                tabs_by_row_number,
                month,
                year,
                manual_mode,
                spreadsheet_path,
                output_dir,
                cpf,
                senha,
                base_spreadsheet,
                max_workers,
                chrome_raw,
            ),
            output_dir,
            "Execução em cadeia iniciada. Aguarde a conclusão no log.",
            "Execução em cadeia finalizada.",
            mode="chain",
        )

    def _execute_chain(
        self,
        selected_rows: list[SpreadsheetRow],
        tabs_by_row_number: dict[int, list[str]],
        month_reference: str,
        year_value: str,
        manual_mode: bool,
        spreadsheet_path: str,
        output_dir: Path,
        cpf: str,
        senha: str,
        base_spreadsheet: Path,
        max_workers: int,
        chrome_path: str,
    ) -> None:
        from src.extraction.chain_extractor import ChainBatchExtractor

        output_spreadsheet_path = self._prepare_results_spreadsheet(selected_rows, manual_mode, spreadsheet_path)

        # CPF/senha vivem só neste atributo, em memória, pelo tempo da execução —
        # nunca são persistidos (nem .env, nem planilha, nem log).
        self._settings.nfce_cpf = cpf
        self._settings.nfce_senha = senha
        self._settings.nf_meudanfe_chrome_path = Path(chrome_path).expanduser() if chrome_path else None

        chain_extractor = ChainBatchExtractor(
            self._settings,
            siga_output_dir=output_dir,
            nfe_output_dir=output_dir / "NFe",
            nfce_output_dir=output_dir / "NFCe",
            nfce_base_spreadsheet_path=base_spreadsheet,
            nfe_max_workers=max_workers,
        )

        stage_status = {
            "siga": "Etapa 1 de 3: extração SIGA em andamento...",
            "nfe": "Etapa 2 de 3: extração NF-e (Meu DANFE) em andamento...",
            "nfce": "Etapa 3 de 3: extração NFC-e em andamento...",
        }

        def on_stage_started(stage: str, base_percent: int) -> None:
            self._bridge.set_status(stage_status.get(stage, ""))
            self._bridge.set_progress(float(base_percent))

        def on_siga_row_processed(done: int, total: int) -> None:
            # Reserva 0-40% para a etapa SIGA (as duas seguintes ganham seus proprios
            # marcos em on_stage_started); mesma logica de _execute_siga, só que numa
            # faixa menor porque aqui existem mais duas etapas depois dela.
            if total > 0:
                self._bridge.set_progress(min(40.0, (done / total) * 40))

        result = chain_extractor.run(
            selected_rows,
            tabs_by_row_number,
            month_reference,
            year_value,
            output_spreadsheet_path,
            on_stage_started=on_stage_started,
            on_siga_row_processed=on_siga_row_processed,
            on_nfe_planilha_concluida=self._push_nfe_result,
            cancel_event=self._cancel_event,
            pause_event=self._pause_event,
        )

        download_count = sum(
            1
            for siga_result in result.siga_results
            for fiscal in siga_result.fiscal_results
            if fiscal.downloaded_at is not None
        )
        nfe_success = sum(1 for r in result.nfe_results if r.status == "concluido")
        nfce_success = sum(1 for r in result.nfce_results if r.status == "concluido")

        narrate_success("Cadeia completa concluída.")
        narrate(
            "SIGA — contribuintes processados: %s de %s (detalhamentos baixados: %s).",
            len(result.siga_results),
            len(selected_rows),
            download_count,
        )
        narrate("NF-e — planilhas concluídas: %s de %s.", nfe_success, len(result.nfe_results))
        narrate("NFC-e — empresas concluídas: %s de %s.", nfce_success, len(result.nfce_results))
