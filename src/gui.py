from __future__ import annotations

"""Interface gráfica para seleção de CNPJs e abas fiscais do SIGA."""

from dataclasses import dataclass
from pathlib import Path
import logging
import queue
import sys
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src import __version__
from src.auth.siga_login import SigaLoginFlow
from src.config import Settings
from src.extraction.siga_extractor import SigaContributorExtractor
from src.extraction.spreadsheet import (
    SpreadsheetRow,
    build_manual_entry_workbook,
    load_cnpjs_from_text,
    load_cnpjs_from_xlsx,
)
from src.utils.browser import (
    BrowserSession,
    get_connect_browser_url,
    launch_debug_browser,
    shutdown_debug_browser,
)
from src.utils.logging_setup import configure_logging
from src.utils.narration import (
    NARRATION_LOGGER_NAME,
    configure_narration,
    narrate,
    narrate_error,
    narrate_success,
    narrate_warning,
)
from src.months import MONTH_OPTIONS


LOGGER = logging.getLogger(__name__)
DOCUMENT_TABS = ("NF-e", "NFC-e", "CT-e", "Malha Fiscal", "Débitos Fiscais")

# Texto de placeholder do campo "Importar Planilha" antes de qualquer seleção real —
# nunca é tratado como um caminho de arquivo de verdade (ver __init__/_load_spreadsheet_rows).
SPREADSHEET_PATH_PLACEHOLDER = "Selecione o arquivo .xlsx"

# Modos de operação selecionáveis na sidebar (item 8 do pedido de reforma).
OPERATION_MODE_SIGA = "siga"
OPERATION_MODE_NFE = "nfe"
OPERATION_MODE_NFCE = "nfce"
OPERATION_MODE_LABELS = {
    OPERATION_MODE_SIGA: "Extração SIGA",
    OPERATION_MODE_NFE: "Extração NF-e",
    OPERATION_MODE_NFCE: "Extração NFC-e",
}

# Paleta de marca extraída do logo oficial (images/logo/logo.png). Os neutros/semânticos
# (fundo, bordas, texto, sucesso/erro) reaproveitam a identidade "Barreira & Associados"
# já usada em produção em importação/NFCE/codigo-fonte/xml nfce.py (constantes BA_*) —
# são famílias de cor já validadas juntas num outro produto real do escritório.
BRAND_PRIMARY = "#ECAC4C"          # dourado do logo — única cor de CTA/"ignição"
BRAND_PRIMARY_HOVER = "#D99A34"    # dourado escurecido (hover/pressed)
BRAND_STRUCTURAL = "#3C5464"       # petróleo do logo — títulos, nav ativo, cabeçalho de tabela
BRAND_STRUCTURAL_DEEP = "#2F4A55"  # petróleo escuro (= BA_SLATE) — hover, texto sobre dourado
BRAND_ACCENT = "#84949C"           # slate do logo — bordas, ícones secundários
BRAND_CONSOLE_BG = "#1C2C34"       # quase-preto azulado do logo — fundo do console
BG_NEUTRAL = "#F4F6F7"             # = BA_BG — fundo geral, já usado pelo escritório
SURFACE = "#FFFFFF"
BORDER_COLOR = "#DDE3E5"           # = BA_BORDA
TEXT_PRIMARY = "#2C4A54"           # = BA_TXT
TEXT_MUTED = "#5E7C88"             # = BA_SLATE_MID
SUCCESS_COLOR = "#2E7D57"          # = BA_VERDE
ERROR_COLOR = "#B23A3A"            # = BA_VERMELHO
HIGHLIGHT_TINT = "#FCF3E1"         # = BA_LINHA_SEL — âmbar suave, usado no nav ativo

# Identidade do escritório, exibida no header e no rodapé da GUI.
COMPANY_NAME = "Barreira & Associados"
COMPANY_TAGLINE = "Assessoria Contábil"

# Tags de maturidade exibidas em cada card do seletor de função.
MODE_STATUS_TAGS = {
    OPERATION_MODE_SIGA: ("EM TESTES", "testing"),
    OPERATION_MODE_NFE: ("EM TESTES", "testing"),
    OPERATION_MODE_NFCE: ("EM TESTES", "testing"),
}

# Mnemônico curto exibido no badge de cada card do seletor de função.
MODE_BADGE_TEXT = {
    OPERATION_MODE_SIGA: "SG",
    OPERATION_MODE_NFE: "FE",
    OPERATION_MODE_NFCE: "CE",
}

# Descrição de uma linha exibida no topo da área de trabalho de cada modo.
OPERATION_MODE_DESCRIPTIONS = {
    OPERATION_MODE_SIGA: "Extração em lote de NF-e, NFC-e, CT-e, Malha Fiscal e Débitos Fiscais do portal SIGA.",
    OPERATION_MODE_NFE: "Download de XML/PDF de NF-e por chave de acesso, via consulta pública no Meu DANFE.",
    OPERATION_MODE_NFCE: "Login automático e download de XML de NFC-e no portal da SEFAZ-CE por empresa.",
}


@dataclass(slots=True)
class RowSelectionWidgets:
    spreadsheet_row: SpreadsheetRow
    container: ttk.Frame
    nfe_var: tk.BooleanVar
    nfce_var: tk.BooleanVar
    cte_var: tk.BooleanVar
    malha_var: tk.BooleanVar
    debitos_var: tk.BooleanVar
    # Usado só no modo NFC-e: não existe escolha por tipo de documento nesse fluxo
    # (a extração NFC-e sempre baixa todos os XMLs da empresa), então a grade mostra
    # uma única coluna "Incluir" em vez das 5 colunas de documento do modo SIGA.
    incluir_var: tk.BooleanVar | None = None


def _tag_for_record(record: logging.LogRecord) -> str:
    """Escolhe a cor da linha a partir do tom explícito (narração) ou do nível (log técnico)."""
    tone = getattr(record, "tone", None)
    if tone == "success":
        return "log_success"
    if record.levelno >= logging.ERROR:
        return "log_error"
    if record.levelno >= logging.WARNING:
        return "log_warning"
    return "log_info"


def _narration_line(record: logging.LogRecord) -> tuple[str, str]:
    """Formata uma linha do canal de narração: só horário curto + mensagem, sem jargão."""
    hora = time.strftime("%H:%M:%S", time.localtime(record.created))
    return f"{hora}  {record.getMessage()}", _tag_for_record(record)


def _technical_bridge_line(record: logging.LogRecord) -> tuple[str, str]:
    """Formata uma linha da rede de segurança técnica (root logger, nível WARNING+).

    Cobre avisos/erros ainda não narrados explicitamente, para que nada fique invisível
    ao operador — mas aponta para o log técnico em vez de expor o texto interno completo.
    """
    hora = time.strftime("%H:%M:%S", time.localtime(record.created))
    text = f"{hora}  {record.getMessage()}"
    if record.levelno >= logging.ERROR:
        text += " (mais detalhes em logs\\errors.log)"
    return text, _tag_for_record(record)


class QueueLogHandler(logging.Handler):
    """Encaminha linhas já prontas (texto + tag de cor) para a fila consumida pela interface.

    Usado tanto para o canal de narração (siga.narracao) quanto como rede de segurança
    técnica (root logger, nível WARNING+) — dois handlers distintos alimentam a mesma fila,
    mas cada um decide o texto/tag de forma diferente (ver `_narration_tuple`/`_bridge_tuple`).
    """

    def __init__(
        self,
        output_queue: queue.Queue[tuple[str, str]],
        line_builder,
    ) -> None:
        super().__init__()
        self.output_queue = output_queue
        self._line_builder = line_builder

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line, tag = self._line_builder(record)
        except Exception:  # noqa: BLE001
            return
        self.output_queue.put((line, tag))


class ScrollableFrame(ttk.Frame):
    """Frame com rolagem vertical para listas longas de CNPJs."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg="#ffffff", bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def _on_frame_configure(self, _: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.inner_id, width=event.width)


class SigaAutomationGUI:
    """Orquestra a seleção visual dos CNPJs e dispara o backend de extração."""

    def __init__(
        self,
        settings: Settings,
        initial_spreadsheet: str | None = None,
        initial_month: str | None = None,
        initial_year: str | None = None,
    ) -> None:
        self.settings = settings
        self.settings.ensure_runtime_dirs()
        if not logging.getLogger().handlers:
            configure_logging(self.settings.log_dir / "run.log")
        if not logging.getLogger(NARRATION_LOGGER_NAME).handlers:
            # console=False: a janela nao tem um terminal util para o operador ler: a
            # narracao chega pelo console da propria GUI, via self.narration_handler abaixo.
            configure_narration(self.settings.log_dir, console=False)

        self._set_windows_app_user_model_id()
        self.root = tk.Tk()

        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        # Canal de narração amigável — o que o operador realmente deve acompanhar.
        self.narration_handler = QueueLogHandler(self.log_queue, _narration_line)
        self.narration_handler.setLevel(logging.INFO)
        logging.getLogger(NARRATION_LOGGER_NAME).addHandler(self.narration_handler)
        # Rede de seguranca: avisos/erros tecnicos ainda nao narrados explicitamente nao
        # ficam invisiveis, mas so aparecem a partir de WARNING (o INFO tecnico fica so em run.log).
        self.error_bridge_handler = QueueLogHandler(self.log_queue, _technical_bridge_line)
        self.error_bridge_handler.setLevel(logging.WARNING)
        logging.getLogger().addHandler(self.error_bridge_handler)

        self.spreadsheet_path_var = tk.StringVar(value=initial_spreadsheet or SPREADSHEET_PATH_PLACEHOLDER)
        self._default_output_dir = Path(self.settings.output_dir)
        self.output_dir_var = tk.StringVar(value="")
        self.month_var = tk.StringVar(value=initial_month or self._default_previous_month())
        self.year_var = tk.StringVar(value=initial_year or str(time.localtime().tm_year))
        self.status_var = tk.StringVar(value="Carregue uma planilha XLSX ou informe CNPJs manualmente para iniciar.")
        self.loaded_count_var = tk.StringVar(value="Total carregadas: 0")

        self.selection_rows: list[RowSelectionWidgets] = []
        # Guarda os últimos dados renderizados na grade para poder re-renderizar ao
        # trocar entre SIGA/NFC-e (colunas diferentes) sem recarregar a planilha.
        self._last_rendered_rows: list[SpreadsheetRow] = []
        self._last_rendered_source_label: str = "Nenhuma planilha carregada ainda."
        self._worker_thread: threading.Thread | None = None
        self._browser_thread: threading.Thread | None = None
        self._stop_requested = False
        self._closing = False
        self._row_columns = (40, 180, 50, 55, 50, 60, 65)
        self._browser_started = False
        self.start_browser_button: ttk.Button | None = None
        self.execute_button: ttk.Button | None = None
        self.manual_cnpjs_text: tk.Text | None = None
        self.import_path_entry: ttk.Entry | None = None
        self.input_notebook: ttk.Notebook | None = None
        self.rows_container: ttk.Frame | None = None
        self.progress_var = tk.DoubleVar(value=0.0)
        self.nfe_doc_var = tk.BooleanVar(value=True)
        self.nfce_doc_var = tk.BooleanVar(value=True)
        self.cte_doc_var = tk.BooleanVar(value=True)
        self.malha_doc_var = tk.BooleanVar(value=True)
        self.debitos_doc_var = tk.BooleanVar(value=True)
        # Modo de operação — seletor de função (item 8): SIGA, NFC-e e NF-e (Meu DANFE).
        self.mode_var = tk.StringVar(value=OPERATION_MODE_SIGA)
        self.workspace_title_var = tk.StringVar(value=OPERATION_MODE_LABELS[OPERATION_MODE_SIGA])
        self.workspace_desc_var = tk.StringVar(value=OPERATION_MODE_DESCRIPTIONS[OPERATION_MODE_SIGA])
        self.nfce_base_spreadsheet_var = tk.StringVar(value="")
        self.nfce_keys_folder_var = tk.StringVar(value="")
        self.nfce_output_dir_var = tk.StringVar(value="")
        # CPF/senha do modo NFC-e: digitados na própria GUI, vivem só em memória
        # (nesta StringVar e depois em Settings, em runtime) — nunca gravados em disco.
        self.nfce_cpf_var = tk.StringVar(value="")
        self.nfce_senha_var = tk.StringVar(value="")
        # Modo NF-e (Meu DANFE): pasta de entrada com planilhas "Chave NF-e" (ex.: a
        # própria saída do modo SIGA) e caminho opcional do chrome.exe.
        self.nf_meudanfe_input_folder_var = tk.StringVar(value="")
        self.nf_meudanfe_chrome_path_var = tk.StringVar(value="")
        self.nf_meudanfe_max_workers_var = tk.StringVar(value="1")
        self.params_siga_frame: ttk.Frame | None = None
        self.params_nfce_frame: ttk.Frame | None = None
        self.params_nfe_frame: ttk.Frame | None = None
        self.center_grid_frame: ttk.Frame | None = None
        self.center_nfe_frame: ttk.Frame | None = None
        self.mode_nav_cards: dict[str, dict[str, tk.Widget]] = {}
        # Tabela de resultados ao vivo do modo NF-e (Meu DANFE) — uma linha por
        # planilha da pasta de entrada, atualizada conforme cada worker termina
        # (ver `_drain_nfe_results_queue`/`_upsert_nfe_result_row`).
        self.nfe_results_queue: queue.Queue = queue.Queue()
        self.nfe_results_count_var = tk.StringVar(value="0 de 0 planilha(s) concluída(s)")
        self.nfe_results_scrollable: ScrollableFrame | None = None
        self.nfe_results_table: ttk.Frame | None = None
        self.nfe_results_empty_label: ttk.Label | None = None
        self._nfe_results_columns: tuple[int, ...] = ()
        self._nfe_result_vars: dict[Path, list[tk.StringVar]] = {}
        self._nfe_result_data: dict[Path, object] = {}
        self._nfe_result_order: list[Path] = []
        self._nfe_next_row_index: int = 0
        self._window_icon_image: tk.PhotoImage | None = None
        self._logo_image: tk.PhotoImage | None = None
        self._app_icon_path = self._resolve_asset_path("images", "icons", "siga-automacao.ico")
        self._window_icon_photo_path = self._resolve_asset_path("images", "icons", "siga-automacao-32x32.png")
        self._logo_path = self._resolve_asset_path("images", "logo", "logo.png")

        self._configure_window_branding()
        self._build_ui()
        if initial_spreadsheet:
            self._load_spreadsheet_rows(Path(self.spreadsheet_path_var.get()))
        else:
            self._render_rows([], source_label="Nenhuma planilha carregada ainda.")
        self.root.after(100, self._drain_log_queue)
        self.root.after(150, self._drain_nfe_results_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self) -> None:
        """Executa o loop principal da interface."""
        self.root.mainloop()

    def _default_previous_month(self) -> str:
        """Calcula o mês anterior ao mês atual para sugerir a referência padrão."""
        current_month = time.localtime().tm_mon
        previous_month_index = (current_month - 2) % len(MONTH_OPTIONS)
        return MONTH_OPTIONS[previous_month_index]

    def _set_windows_app_user_model_id(self) -> None:
        """Registra um AppUserModelID próprio no Windows antes de criar a janela.

        Sem isso, quando o app roda via `python main.py` (não empacotado como .exe), o
        Windows agrupa o processo sob o ícone do python.exe na barra de tarefas/alt-tab,
        mesmo com `iconbitmap`/`iconphoto` aplicados corretamente na janela — o título e o
        ícone da própria janela ficam certos, mas a barra de tarefas mostra o Python.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BarreiraAssociados.SigaAutomacao")
        except Exception:  # noqa: BLE001
            LOGGER.debug("Nao foi possivel definir o AppUserModelID do Windows.", exc_info=True)

    def _resolve_asset_path(self, *parts: str) -> Path:
        """Resolve caminhos de assets tanto no código-fonte quanto no executável empacotado."""
        base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        return base_dir.joinpath(*parts)

    def _configure_window_branding(self) -> None:
        """Aplica o ícone principal da aplicação e prepara a logo usada no cabeçalho."""
        try:
            if self._app_icon_path.exists():
                self.root.iconbitmap(default=str(self._app_icon_path))
        except Exception:  # noqa: BLE001
            LOGGER.debug("Nao foi possivel aplicar o iconbitmap da janela principal.", exc_info=True)

        try:
            if self._window_icon_photo_path.exists():
                self._window_icon_image = tk.PhotoImage(file=str(self._window_icon_photo_path))
                self.root.iconphoto(True, self._window_icon_image)
        except Exception:  # noqa: BLE001
            LOGGER.debug("Nao foi possivel carregar o iconphoto da aplicacao.", exc_info=True)

        try:
            if self._logo_path.exists():
                raw_logo = tk.PhotoImage(file=str(self._logo_path))
                # A logo original e quadrada; reduzimos para uma altura de cabecalho
                # mais discreta sem distorcer a proporcao.
                reduction_factor = max(1, round(raw_logo.height() / 62))
                self._logo_image = raw_logo.subsample(reduction_factor, reduction_factor)
        except Exception:  # noqa: BLE001
            LOGGER.debug("Nao foi possivel carregar a logo da aplicacao.", exc_info=True)

    def _apply_theme(self) -> None:
        """Configura a aparência: paleta clara e neutra, com as cores da logo como acento."""
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        colors = {
            "bg": BG_NEUTRAL,
            "surface": SURFACE,
            "surface_alt": "#EEF2F3",
            "border": BORDER_COLOR,
            "text": TEXT_PRIMARY,
            "text_muted": TEXT_MUTED,
            "primary": BRAND_PRIMARY,
            "primary_hover": BRAND_PRIMARY_HOVER,
            "on_primary": BRAND_STRUCTURAL_DEEP,
            "structural": BRAND_STRUCTURAL,
            "structural_deep": BRAND_STRUCTURAL_DEEP,
            "accent": BRAND_ACCENT,
            "success": SUCCESS_COLOR,
            "error": ERROR_COLOR,
            "highlight_tint": HIGHLIGHT_TINT,
            "console_bg": BRAND_CONSOLE_BG,
            "console_header": "#152029",
            "table_header": BRAND_STRUCTURAL,
        }
        self._theme_colors = colors

        _ui_font = "Inter"

        # --- Frames estruturais ---
        self.root.configure(bg=colors["bg"])
        style.configure("App.TFrame", background=colors["bg"])
        style.configure("Header.TFrame", background=colors["surface"])
        style.configure("Header.TLabel", background=colors["surface"])
        style.configure("Footer.TFrame", background=colors["surface"])
        style.configure("Footer.TLabel", background=colors["surface"])
        style.configure("NavRail.TFrame", background=colors["surface"])
        style.configure("Workspace.TFrame", background=colors["bg"])
        style.configure("Card.TFrame", background=colors["surface"], relief="flat", borderwidth=0)
        style.configure("CardHeader.TFrame", background=colors["surface"])
        style.configure("Console.TFrame", background=colors["console_bg"])
        style.configure("ConsoleHeader.TFrame", background=colors["console_header"])
        style.configure("ConsoleFooter.TFrame", background=colors["console_header"])
        # Zebra striping da tabela — tint neutro sutil, sem competir com a marca
        style.configure("RowEven.TFrame", background=colors["surface"])
        style.configure("RowOdd.TFrame", background=colors["surface_alt"])
        style.configure("RowHeader.TFrame", background=colors["table_header"])

        # --- Labels ---
        style.configure("HeaderTitle.TLabel",
            background=colors["surface"], foreground=colors["structural"], font=(_ui_font, 17, "bold"))
        style.configure("VersionBadge.TLabel",
            background=colors["surface_alt"], foreground=colors["text_muted"],
            font=(_ui_font, 8, "bold"), padding=(8, 3))
        style.configure("HeaderCompany.TLabel",
            background=colors["surface"], foreground=colors["text"], font=(_ui_font, 12, "bold"))
        style.configure("HeaderCompanyTagline.TLabel",
            background=colors["surface"], foreground=colors["text_muted"], font=(_ui_font, 8))
        style.configure("FooterCompany.TLabel",
            background=colors["surface"], foreground=colors["text_muted"], font=(_ui_font, 9, "bold"))
        style.configure("TagApproved.TLabel",
            background=colors["success"], foreground="#ffffff", font=(_ui_font, 7, "bold"), padding=(6, 2))
        style.configure("TagTesting.TLabel",
            background=colors["structural"], foreground="#ffffff", font=(_ui_font, 7, "bold"), padding=(6, 2))
        style.configure("WorkspaceTitle.TLabel",
            background=colors["bg"], foreground=colors["structural"], font=(_ui_font, 18, "bold"))
        style.configure("WorkspaceDesc.TLabel",
            background=colors["bg"], foreground=colors["text_muted"], font=(_ui_font, 10))
        style.configure("FieldLabel.TLabel",
            background=colors["surface"], foreground=colors["text_muted"],
            font=(_ui_font, 8, "bold"))
        style.configure("CardTitle.TLabel",
            background=colors["surface"], foreground=colors["structural"], font=(_ui_font, 14, "bold"))
        style.configure("CountChip.TLabel",
            background=colors["primary"], foreground=colors["on_primary"],
            font=(_ui_font, 9, "bold"), padding=(10, 4))
        style.configure("Status.TLabel",
            background=colors["surface"], foreground=colors["text_muted"], font=(_ui_font, 9))
        style.configure("Body.TLabel",
            background=colors["surface"], foreground=colors["text"], font=(_ui_font, 10))
        style.configure("BodyMuted.TLabel",
            background=colors["surface"], foreground=colors["text_muted"], font=(_ui_font, 9))
        style.configure("Panel.TLabel",
            background=colors["surface"], foreground=colors["text"], font=(_ui_font, 10))
        style.configure("ConsoleTitle.TLabel",
            background=colors["console_header"], foreground="#9fb3bd", font=(_ui_font, 8, "bold"))
        style.configure("RowEven.TLabel",
            background=colors["surface"], foreground=colors["text"], font=(_ui_font, 9))
        style.configure("RowOdd.TLabel",
            background=colors["surface_alt"], foreground=colors["text"], font=(_ui_font, 9))
        style.configure("RowHeader.TLabel",
            background=colors["table_header"], foreground="#ffffff", font=(_ui_font, 8, "bold"))

        # --- Checkbuttons ---
        style.configure("Field.TCheckbutton",
            background=colors["surface"], foreground=colors["text"], font=(_ui_font, 10))
        style.map("Field.TCheckbutton", background=[("active", colors["surface"])])
        style.configure("RowEven.TCheckbutton",
            background=colors["surface"], foreground=colors["text"], font=(_ui_font, 9))
        style.map("RowEven.TCheckbutton", background=[("active", colors["surface"])])
        style.configure("RowOdd.TCheckbutton",
            background=colors["surface_alt"], foreground=colors["text"], font=(_ui_font, 9))
        style.map("RowOdd.TCheckbutton", background=[("active", colors["surface_alt"])])

        # --- Botões ---
        # Cta — dourado da logo, único botão com essa cor: a "ignição" da automação.
        style.configure("Cta.TButton",
            background=colors["primary"], foreground=colors["on_primary"],
            font=(_ui_font, 12, "bold"), padding=(16, 12), relief="flat", borderwidth=0)
        style.map("Cta.TButton",
            background=[("active", colors["primary_hover"]), ("disabled", colors["surface_alt"])],
            foreground=[("disabled", colors["text_muted"])])
        # Primary — petróleo estrutural (Iniciar Navegador, Carregar, Validar)
        style.configure("Primary.TButton",
            background=colors["structural"], foreground="#ffffff",
            font=(_ui_font, 10, "bold"), padding=(14, 8), relief="flat", borderwidth=0)
        style.map("Primary.TButton",
            background=[("active", colors["structural_deep"]), ("disabled", colors["surface_alt"])],
            foreground=[("disabled", colors["text_muted"])])
        style.configure("Success.TButton",
            background=colors["success"], foreground="#ffffff",
            font=(_ui_font, 10, "bold"), padding=(14, 8), relief="flat", borderwidth=0)
        style.map("Success.TButton", background=[("active", "#256a49")])
        # Ghost — borda em accent, fundo transparente (botões de baixa prioridade)
        style.configure("Ghost.TButton",
            background=colors["surface"], foreground=colors["structural"],
            font=(_ui_font, 10, "bold"), padding=(12, 7), relief="solid", borderwidth=1)
        style.map("Ghost.TButton",
            background=[("active", colors["surface_alt"])], bordercolor=[("active", colors["structural"])])
        # Action — botões secundários neutros (ex.: "Procurar"/"Abrir")
        style.configure("Action.TButton",
            background=colors["surface_alt"], foreground=colors["text"],
            font=(_ui_font, 10), padding=(10, 7), relief="flat", borderwidth=0)
        style.map("Action.TButton", background=[("active", colors["border"])])
        style.configure("ConsoleAction.TButton",
            background=colors["console_header"], foreground="#d4e5ea",
            font=(_ui_font, 9), padding=(10, 6), relief="flat", borderwidth=0)
        style.map("ConsoleAction.TButton", background=[("active", "#20313c")])
        # Danger — texto em vermelho de erro, borda outline suave
        style.configure("Danger.TButton",
            background=colors["surface"], foreground=colors["error"],
            font=(_ui_font, 10, "bold"), padding=(12, 7), relief="solid", borderwidth=1)
        style.map("Danger.TButton", background=[("active", "#fbeaea")])

        # --- Notebook de abas (Importar / Manual) ---
        style.configure("TNotebook", background=colors["surface"], borderwidth=0, tabmargins=0)
        style.configure("TNotebook.Tab",
            background=colors["surface_alt"], foreground=colors["text_muted"],
            padding=(18, 9), font=(_ui_font, 10, "bold"), borderwidth=0)
        style.map("TNotebook.Tab",
            background=[("selected", colors["surface"])],
            foreground=[("selected", colors["structural"])],
            expand=[("selected", [1, 1, 1, 0])])

    def _build_nav_rail(self, parent: ttk.Frame) -> None:
        """Monta o rail de navegação: um card por função (SIGA / NF-e / NFC-e)."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)  # empurra os cards para o topo

        header = ttk.Frame(parent, style="NavRail.TFrame", padding=(18, 20, 18, 10))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="FUNÇÕES", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w")

        cards_box = ttk.Frame(parent, style="NavRail.TFrame", padding=(10, 0))
        cards_box.grid(row=1, column=0, sticky="ew")
        cards_box.columnconfigure(0, weight=1)

        for index, mode in enumerate((OPERATION_MODE_SIGA, OPERATION_MODE_NFE, OPERATION_MODE_NFCE)):
            self._build_mode_nav_card(cards_box, mode, index)

        self._refresh_mode_nav_styles()

    def _build_mode_nav_card(self, parent: ttk.Frame, mode: str, row: int) -> None:
        """Cria um card clicável (badge + título + tag) representando um modo de operação."""
        colors = self._theme_colors
        outer = tk.Frame(parent, bg=colors["surface"], cursor="hand2", highlightthickness=0)
        outer.grid(row=row, column=0, sticky="ew", pady=3)
        outer.columnconfigure(1, weight=1)

        accent = tk.Frame(outer, bg=colors["surface"], width=4)
        accent.grid(row=0, column=0, sticky="ns")
        accent.grid_propagate(False)

        inner = tk.Frame(outer, bg=colors["surface"])
        inner.grid(row=0, column=1, sticky="ew", padx=(12, 10), pady=10)
        inner.columnconfigure(1, weight=1)

        badge = tk.Label(
            inner, text=MODE_BADGE_TEXT[mode], font=("Inter", 11, "bold"),
            bg=colors["structural"], fg="#ffffff", width=3, height=1,
        )
        badge.grid(row=0, column=0, rowspan=2, sticky="nw")

        title = tk.Label(
            inner, text=OPERATION_MODE_LABELS[mode], font=("Inter", 11, "bold"),
            bg=colors["surface"], fg=colors["text"], anchor="w",
        )
        title.grid(row=0, column=1, sticky="w", padx=(10, 0))

        tag_text, tag_kind = MODE_STATUS_TAGS[mode]
        tag_bg = colors["success"] if tag_kind == "approved" else colors["structural"]
        tag = tk.Label(
            inner, text=tag_text, font=("Inter", 7, "bold"),
            bg=tag_bg, fg="#ffffff", padx=6, pady=1,
        )
        tag.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(4, 0))

        self.mode_nav_cards[mode] = {"outer": outer, "accent": accent, "inner": inner, "badge": badge, "title": title}

        for widget in (outer, accent, inner, badge, title):
            widget.bind("<Button-1>", lambda _event, m=mode: self._set_operation_mode(m))
            widget.bind("<Enter>", lambda _event, m=mode: self._on_nav_card_hover(m, True))
            widget.bind("<Leave>", lambda _event, m=mode: self._on_nav_card_hover(m, False))

    def _on_nav_card_hover(self, mode: str, entering: bool) -> None:
        """Realça sutilmente um card inativo ao passar o mouse (o card ativo não reage)."""
        if self.mode_var.get() == mode:
            return
        widgets = self.mode_nav_cards.get(mode)
        if not widgets:
            return
        bg = self._theme_colors["surface_alt"] if entering else self._theme_colors["surface"]
        for key in ("outer", "accent", "inner", "title"):
            widgets[key].configure(bg=bg)

    def _build_parameters_bar(self, parent: ttk.Frame) -> None:
        """Monta o card horizontal de parâmetros do modo ativo (conteúdo trocado por modo)."""
        colors = self._theme_colors
        card_border = tk.Frame(parent, bg=colors["border"])
        card_border.grid(row=0, column=0, sticky="ew")
        card_border.columnconfigure(0, weight=1)
        card = ttk.Frame(card_border, style="Card.TFrame", padding=16)
        card.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        card.columnconfigure(0, weight=1)

        self.params_siga_frame = ttk.Frame(card, style="Card.TFrame")
        self.params_siga_frame.grid(row=0, column=0, sticky="ew")
        self._build_siga_parameters(self.params_siga_frame)

        self.params_nfce_frame = ttk.Frame(card, style="Card.TFrame")
        self.params_nfce_frame.grid(row=0, column=0, sticky="ew")
        self._build_nfce_parameters(self.params_nfce_frame)

        self.params_nfe_frame = ttk.Frame(card, style="Card.TFrame")
        self.params_nfe_frame.grid(row=0, column=0, sticky="ew")
        self._build_nfe_parameters(self.params_nfe_frame)

        self.params_nfce_frame.grid_remove()
        self.params_nfe_frame.grid_remove()

    def _build_path_field(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        label_text: str,
        string_var: tk.StringVar,
        browse_command,
        note: str | None = None,
    ) -> None:
        """Campo padrão label + entry + botão Procurar, usado nas barras de parâmetros."""
        box = ttk.Frame(parent, style="Card.TFrame")
        box.grid(row=row, column=column, sticky="ew", padx=(0, 20) if column == 0 else (0, 0))
        box.columnconfigure(0, weight=1)
        ttk.Label(box, text=label_text.upper(), style="FieldLabel.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        entry = ttk.Entry(box, textvariable=string_var)
        entry.grid(row=1, column=0, sticky="ew")
        ttk.Button(box, text="Procurar", style="Action.TButton", command=browse_command).grid(row=1, column=1, padx=(6, 0))
        if note:
            ttk.Label(box, text=note, style="BodyMuted.TLabel", wraplength=260, justify="left").grid(
                row=2, column=0, columnspan=2, sticky="w", pady=(4, 0)
            )

    def _build_siga_parameters(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(2, weight=1)

        month_box_wrap = ttk.Frame(parent, style="Card.TFrame")
        month_box_wrap.grid(row=0, column=0, sticky="w", padx=(0, 20))
        ttk.Label(month_box_wrap, text="MÊS DE REFERÊNCIA", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Combobox(month_box_wrap, textvariable=self.month_var, values=MONTH_OPTIONS, state="readonly", width=14).grid(row=1, column=0, sticky="w")

        year_wrap = ttk.Frame(parent, style="Card.TFrame")
        year_wrap.grid(row=0, column=1, sticky="w", padx=(0, 20))
        ttk.Label(year_wrap, text="ANO", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Entry(year_wrap, textvariable=self.year_var, width=8).grid(row=1, column=0, sticky="w")

        self._build_path_field(parent, 0, 2, "Pasta de Saída", self.output_dir_var, self._browse_output_dir)

        docs = ttk.Frame(parent, style="Card.TFrame")
        docs.grid(row=1, column=0, columnspan=3, sticky="w", pady=(16, 0))
        ttk.Label(docs, text="DOCUMENTOS FISCAIS", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Checkbutton(docs, text="NF-e", style="Field.TCheckbutton", variable=self.nfe_doc_var, command=lambda: self._set_document_selection("NF-e", self.nfe_doc_var.get())).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Checkbutton(docs, text="NFC-e", style="Field.TCheckbutton", variable=self.nfce_doc_var, command=lambda: self._set_document_selection("NFC-e", self.nfce_doc_var.get())).grid(row=0, column=2, sticky="w", padx=8)
        ttk.Checkbutton(docs, text="CT-e", style="Field.TCheckbutton", variable=self.cte_doc_var, command=lambda: self._set_document_selection("CT-e", self.cte_doc_var.get())).grid(row=0, column=3, sticky="w", padx=8)
        ttk.Checkbutton(docs, text="Malha Fiscal", style="Field.TCheckbutton", variable=self.malha_doc_var, command=lambda: self._set_document_selection("Malha Fiscal", self.malha_doc_var.get())).grid(row=0, column=4, sticky="w", padx=8)
        ttk.Checkbutton(docs, text="Débitos Fiscais", style="Field.TCheckbutton", variable=self.debitos_doc_var, command=lambda: self._set_document_selection("Débitos Fiscais", self.debitos_doc_var.get())).grid(row=0, column=5, sticky="w", padx=8)

    def _build_nfce_parameters(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=1)

        ttk.Label(parent, text="ARQUIVOS", style="FieldLabel.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self._build_path_field(parent, 1, 0, "Base IE/CNPJ (planilha)", self.nfce_base_spreadsheet_var, self._browse_nfce_base_spreadsheet)
        self._build_path_field(
            parent, 1, 1, "Pasta de Chaves (por empresa)", self.nfce_keys_folder_var, self._browse_nfce_keys_folder,
            note="Uma planilha .xlsx por empresa, CNPJ no nome do arquivo, chaves de 44 dígitos em qualquer coluna.",
        )
        self._build_path_field(parent, 1, 2, "Pasta de Saída (XMLs)", self.nfce_output_dir_var, self._browse_nfce_output_dir)

        ttk.Label(parent, text="AUTENTICAÇÃO", style="FieldLabel.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=(16, 4))
        credentials = ttk.Frame(parent, style="Card.TFrame")
        credentials.grid(row=3, column=0, columnspan=3, sticky="w")

        cpf_box = ttk.Frame(credentials, style="Card.TFrame")
        cpf_box.grid(row=0, column=0, sticky="w", padx=(0, 20))
        ttk.Label(cpf_box, text="CPF DO CONTADOR", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Entry(cpf_box, textvariable=self.nfce_cpf_var, width=18).grid(row=1, column=0, sticky="w")

        senha_box = ttk.Frame(credentials, style="Card.TFrame")
        senha_box.grid(row=0, column=1, sticky="w", padx=(0, 20))
        ttk.Label(senha_box, text="SENHA", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Entry(senha_box, textvariable=self.nfce_senha_var, show="•", width=18).grid(row=1, column=0, sticky="w")

        ttk.Label(
            credentials,
            text="Login no portal da SEFAZ-CE. CPF e senha ficam só na memória desta sessão — nunca são salvos em disco.",
            style="BodyMuted.TLabel",
            wraplength=520,
            justify="left",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def _build_nfe_parameters(self, parent: ttk.Frame) -> None:
        """Monta os parâmetros do modo NF-e (Meu DANFE) — sem sessão de navegador
        compartilhada: este modo não depende do botão 'Iniciar Navegador'."""
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)

        self._build_path_field(
            parent, 0, 0, "Pasta com planilhas NF-e", self.nf_meudanfe_input_folder_var,
            self._browse_nf_meudanfe_input_folder,
            note="Qualquer planilha .xlsx com 'NF-e' no nome e a coluna 'Chave NF-e', na pasta ou em subpastas — "
                 "por exemplo, a própria pasta de saída de uma extração do modo SIGA.",
        )
        self._build_path_field(
            parent, 0, 1, "Chrome.exe (opcional)", self.nf_meudanfe_chrome_path_var,
            self._browse_nf_meudanfe_chrome_path,
            note="Deixe em branco para localizar automaticamente.",
        )

        workers_box = ttk.Frame(parent, style="Card.TFrame")
        workers_box.grid(row=1, column=0, sticky="w", pady=(16, 0))
        ttk.Label(workers_box, text="CHROMES EM PARALELO (1–4)", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Spinbox(
            workers_box, from_=1, to=4, width=6, textvariable=self.nf_meudanfe_max_workers_var,
        ).grid(row=1, column=0, sticky="w")

        ttk.Label(
            parent,
            text=(
                "Consulta pública no site Meu DANFE por chave de acesso — sem login. O captcha é resolvido "
                "automaticamente quando possível; se ficar visível no navegador, resolva manualmente."
            ),
            style="BodyMuted.TLabel",
            wraplength=760,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _build_center(self, parent: ttk.Frame) -> None:
        """Monta o conteúdo central com entrada, lista de CNPJs e botões de ação."""
        header = ttk.Frame(parent, style="Workspace.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)

        ttk.Label(header, text="Controle de Empresas", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.loaded_count_var, style="CountChip.TLabel").grid(row=0, column=1, sticky="e")

        # Card de entrada: borda suave de 1px via tk.Frame wrapper (#84949C = outline do design system)
        card_border = tk.Frame(parent, bg="#84949C")
        card_border.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        card_border.columnconfigure(0, weight=1)
        card = ttk.Frame(card_border, style="Card.TFrame", padding=0)
        card.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        card.columnconfigure(0, weight=1)

        self.input_notebook = ttk.Notebook(card)
        self.input_notebook.grid(row=0, column=0, sticky="ew")
        import_tab = ttk.Frame(self.input_notebook, padding=18, style="Card.TFrame")
        manual_tab = ttk.Frame(self.input_notebook, padding=18, style="Card.TFrame")
        self.input_notebook.add(import_tab, text="  Importar Planilha  ")
        self.input_notebook.add(manual_tab, text="  Entrada Manual  ")

        import_tab.columnconfigure(0, weight=1)
        ttk.Label(import_tab, text="Selecione uma planilha XLSX para carregar as empresas.", style="Body.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        import_row = ttk.Frame(import_tab, style="Card.TFrame")
        import_row.grid(row=1, column=0, sticky="ew")
        import_row.columnconfigure(0, weight=1)
        self.import_path_entry = ttk.Entry(import_row, textvariable=self.spreadsheet_path_var)
        self.import_path_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(import_row, text="Abrir", style="Action.TButton", command=self._browse_spreadsheet).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(import_row, text="Carregar", style="Primary.TButton", command=self._reload_spreadsheet).grid(row=0, column=2, padx=(8, 0))

        manual_tab.columnconfigure(0, weight=1)
        ttk.Label(manual_tab, text="Cole um CNPJ por linha, ou vários separados por vírgula, ponto e vírgula ou espaço.", style="Body.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        # Campo de texto com borda suave de 1px simulada por tk.Frame wrapper
        manual_border = tk.Frame(manual_tab, bg="#84949C")
        manual_border.grid(row=1, column=0, sticky="nsew")
        manual_border.columnconfigure(0, weight=1)
        manual_border.rowconfigure(0, weight=1)
        manual_text_frame = tk.Frame(manual_border, bg="#ffffff")
        manual_text_frame.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        manual_text_frame.columnconfigure(0, weight=1)
        manual_text_frame.rowconfigure(0, weight=1)
        self.manual_cnpjs_text = tk.Text(
            manual_text_frame, height=4, wrap="word",
            bg="#ffffff", fg="#191c1d", insertbackground="#191c1d",
            relief="flat", bd=0, padx=8, pady=6,
            font=("Inter", 10),
        )
        manual_scroll = ttk.Scrollbar(manual_text_frame, orient="vertical", command=self.manual_cnpjs_text.yview)
        self.manual_cnpjs_text.configure(yscrollcommand=manual_scroll.set)
        self.manual_cnpjs_text.grid(row=0, column=0, sticky="nsew")
        manual_scroll.grid(row=0, column=1, sticky="ns")
        manual_actions = ttk.Frame(manual_tab, style="Card.TFrame")
        manual_actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        manual_actions.columnconfigure(0, weight=1)
        manual_actions.columnconfigure(1, weight=1)
        ttk.Button(manual_actions, text="Carregar CNPJs manuais", style="Primary.TButton", command=self._load_manual_rows).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(manual_actions, text="Limpar campo", style="Danger.TButton", command=self._clear_manual_input).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        # Card da grade de empresas: borda suave de 1px
        rows_border = tk.Frame(parent, bg="#84949C")
        rows_border.grid(row=2, column=0, sticky="nsew")
        rows_border.columnconfigure(0, weight=1)
        rows_border.rowconfigure(0, weight=1)
        rows_card = ttk.Frame(rows_border, style="Card.TFrame", padding=14)
        rows_card.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        rows_card.columnconfigure(0, weight=1)
        rows_card.rowconfigure(0, weight=1)
        self.rows_container = rows_card
        self.scrollable_rows = ScrollableFrame(rows_card)
        self.scrollable_rows.grid(row=0, column=0, sticky="nsew")

        footer_actions = ttk.Frame(parent, style="Workspace.TFrame")
        footer_actions.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        footer_actions.columnconfigure(0, weight=1)
        footer_actions.columnconfigure(1, weight=1)
        ttk.Button(footer_actions, text="Limpar Lista", style="Danger.TButton", command=self._clear_loaded_rows).grid(row=0, column=0, sticky="e", padx=(0, 8))
        ttk.Button(footer_actions, text="Validar Empresas", style="Primary.TButton", command=self._validate_loaded_rows).grid(row=0, column=1, sticky="w", padx=(8, 0))

    def _build_nfe_results_panel(self, parent: ttk.Frame) -> None:
        """Monta o painel de resultados ao vivo do modo NF-e (Meu DANFE).

        Ao contrário de SIGA/NFC-e, este modo não processa uma lista de empresas
        selecionadas — ele varre uma pasta de planilhas e baixa as chaves pendentes de
        cada uma. Por isso a área central vira uma tabela por planilha (não uma grade
        de CNPJs), atualizada em tempo real conforme cada worker
        (`MeudanfeBatchExtractor`, até 4 Chromes em paralelo) termina um pedaço do
        trabalho — ver `_drain_nfe_results_queue`.
        """
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        header = ttk.Frame(parent, style="Workspace.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)
        ttk.Label(header, text="Resultados por Planilha", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.nfe_results_count_var, style="CountChip.TLabel").grid(row=0, column=1, sticky="e")

        ttk.Label(
            parent,
            text="Cada linha é uma planilha da pasta de entrada; os valores são atualizados conforme os Chromes em paralelo terminam cada chave.",
            style="BodyMuted.TLabel",
            wraplength=560,
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))

        rows_border = tk.Frame(parent, bg="#84949C")
        rows_border.grid(row=2, column=0, sticky="nsew")
        rows_border.columnconfigure(0, weight=1)
        rows_border.rowconfigure(0, weight=1)
        rows_card = ttk.Frame(rows_border, style="Card.TFrame", padding=14)
        rows_card.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        rows_card.columnconfigure(0, weight=1)
        rows_card.rowconfigure(0, weight=1)
        self.nfe_results_scrollable = ScrollableFrame(rows_card)
        self.nfe_results_scrollable.grid(row=0, column=0, sticky="nsew")

        self._nfe_results_columns = (260, 70, 90, 80, 70, 170)
        self._nfe_result_vars = {}
        self._nfe_result_data = {}
        self._nfe_result_order = []
        self._build_nfe_results_table_body()

    def _build_nfe_results_table_body(self) -> None:
        """(Re)constrói o corpo da tabela de resultados NF-e: cabeçalho fixo + estado
        vazio. Chamado na montagem inicial e em `_reset_nfe_results_panel` (início de
        cada execução), para começar sempre sem linhas de uma execução anterior."""
        for child in self.nfe_results_scrollable.inner.winfo_children():
            child.destroy()

        table = ttk.Frame(self.nfe_results_scrollable.inner)
        table.grid(row=0, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)

        header_row, _ = self._create_nfe_result_row(
            table,
            row_index=0,
            values=("PLANILHA", "CHAVES", "BAIXADAS", "PULADAS", "FALHAS", "STATUS"),
            is_header=True,
            row_style="RowHeader",
        )
        header_row.grid(row=0, column=0, sticky="ew")
        sep = tk.Frame(table, height=1, bg="#84949C")
        sep.grid(row=1, column=0, sticky="ew")

        self.nfe_results_empty_label = ttk.Label(
            table,
            text="Nenhuma planilha processada ainda — selecione a pasta e clique em Executar.",
            style="BodyMuted.TLabel",
        )
        self.nfe_results_empty_label.grid(row=2, column=0, sticky="w", pady=(12, 0))

        self.nfe_results_table = table
        self._nfe_next_row_index = 2

    def _create_nfe_result_row(
        self,
        parent: ttk.Frame,
        row_index: int,
        values: tuple[str, str, str, str, str, str],
        is_header: bool,
        row_style: str = "RowEven",
    ) -> tuple[ttk.Frame, list[tk.StringVar]]:
        """Cria uma linha fixa de 6 colunas da tabela de resultados NF-e, com zebra
        striping (mesmo padrão visual da grade de empresas de `_create_selection_row`)."""
        frame_style = f"{row_style}.TFrame"
        label_style = f"{row_style}.TLabel"
        row_frame = ttk.Frame(parent, style=frame_style)
        for column, width in enumerate(self._nfe_results_columns):
            row_frame.columnconfigure(column, minsize=width, weight=1 if column == 0 else 0)

        text_vars: list[tk.StringVar] = []
        for column, (width, value) in enumerate(zip(self._nfe_results_columns, values)):
            cell = ttk.Frame(row_frame, width=width, style=frame_style)
            cell.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
            cell.grid_propagate(False)
            text_var = tk.StringVar(value=value)
            ttk.Label(
                cell,
                textvariable=text_var,
                anchor="w" if column == 0 else "center",
                style=label_style,
            ).pack(fill="x", padx=4, pady=4)
            text_vars.append(text_var)
        return row_frame, text_vars

    def _reset_nfe_results_panel(self) -> None:
        """Limpa a tabela de resultados NF-e antes de disparar uma nova execução, para
        não misturar contagens de uma planilha com o resultado da execução anterior."""
        self._nfe_result_vars = {}
        self._nfe_result_data = {}
        self._nfe_result_order = []
        self._build_nfe_results_table_body()
        self.nfe_results_count_var.set("0 de 0 planilha(s) concluída(s)")

    def _upsert_nfe_result_row(self, resultado) -> None:
        """Insere a linha da planilha na primeira vez que ela aparece, ou atualiza os
        valores de uma linha já existente — chamado pelo drain da fila (thread principal)."""
        caminho: Path = resultado.caminho_planilha
        values = (
            caminho.name,
            str(resultado.chaves_total),
            str(resultado.chaves_baixadas),
            str(resultado.chaves_puladas),
            str(resultado.chaves_com_falha),
            self._nfe_status_label(resultado),
        )
        self._nfe_result_data[caminho] = resultado

        existing = self._nfe_result_vars.get(caminho)
        if existing is not None:
            for var, value in zip(existing, values):
                var.set(value)
            return

        if self.nfe_results_empty_label is not None:
            self.nfe_results_empty_label.grid_remove()

        row_index = self._nfe_next_row_index
        self._nfe_next_row_index += 1
        row_style = "RowEven" if len(self._nfe_result_order) % 2 == 0 else "RowOdd"
        row_frame, text_vars = self._create_nfe_result_row(
            self.nfe_results_table, row_index, values, is_header=False, row_style=row_style,
        )
        row_frame.grid(row=row_index, column=0, sticky="ew")
        self._nfe_result_vars[caminho] = text_vars
        self._nfe_result_order.append(caminho)

    def _nfe_status_label(self, resultado) -> str:
        """Rótulo de status para a tabela ao vivo.

        Não usa `resultado.status` diretamente: essa propriedade só distingue
        sucesso/parcial/erro ao final do lote — durante a execução, antes de qualquer
        falha ter sido registrada, ela já retornaria "concluído" mesmo com chaves
        ainda pendentes. Aqui comparamos contra o total para saber se a planilha
        realmente terminou.
        """
        processadas = resultado.chaves_baixadas + resultado.chaves_puladas + resultado.chaves_com_falha
        if resultado.chaves_total == 0:
            return "Sem chaves"
        if processadas < resultado.chaves_total:
            return f"Em andamento ({processadas}/{resultado.chaves_total})"
        if resultado.chaves_com_falha and (resultado.chaves_baixadas + resultado.chaves_puladas):
            return "Parcial"
        if resultado.chaves_com_falha:
            return "Erro"
        return "Concluído"

    def _refresh_nfe_results_summary(self) -> None:
        """Atualiza o chip "X de Y planilha(s) concluída(s)" do cabeçalho da tabela NF-e."""
        total = len(self._nfe_result_order)
        concluidas = sum(
            1
            for resultado in self._nfe_result_data.values()
            if resultado.chaves_total > 0
            and (resultado.chaves_baixadas + resultado.chaves_puladas + resultado.chaves_com_falha) >= resultado.chaves_total
        )
        self.nfe_results_count_var.set(f"{concluidas} de {total} planilha(s) concluída(s)")

    def _drain_nfe_results_queue(self) -> None:
        """Poll periódico (thread principal) que aplica os `MeudanfeBatchResult`
        colocados na fila por `_execute_selected_nfe` (thread de trabalho) — mesmo
        padrão já usado para o console em `_drain_log_queue`."""
        if self._closing:
            return
        updated = False
        while True:
            try:
                resultado = self.nfe_results_queue.get_nowait()
            except queue.Empty:
                break
            updated = True
            self._upsert_nfe_result_row(resultado)
        if updated:
            self._refresh_nfe_results_summary()
        self.root.after(150, self._drain_nfe_results_queue)

    def _build_console(self, parent: ttk.Frame) -> None:
        """Monta o painel de ações (Iniciar Navegador / Executar) e o console de log."""
        colors = self._theme_colors

        action_border = tk.Frame(parent, bg=colors["border"])
        action_border.grid(row=0, column=0, sticky="ew")
        action_border.columnconfigure(0, weight=1)
        action_box = ttk.Frame(action_border, style="Card.TFrame", padding=(18, 18))
        action_box.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
        action_box.columnconfigure(0, weight=1)

        ttk.Label(action_box, text="EXECUÇÃO", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 14))

        self.start_browser_button = ttk.Button(action_box, text="Iniciar Navegador", style="Primary.TButton", command=self._start_browser_if_needed)
        self.start_browser_button.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.execute_button = ttk.Button(
            action_box,
            text=OPERATION_MODE_LABELS[OPERATION_MODE_SIGA].upper(),
            style="Cta.TButton",
            command=self._run_selected,
            state="disabled",
        )
        self.execute_button.grid(row=2, column=0, sticky="ew")

        # Console de logs — fundo escuro (quase-preto azulado da marca)
        console_box = ttk.Frame(parent, style="Console.TFrame")
        console_box.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        console_box.columnconfigure(0, weight=1)
        console_box.rowconfigure(1, weight=1)

        console_header = ttk.Frame(console_box, style="ConsoleHeader.TFrame", padding=(16, 10))
        console_header.grid(row=0, column=0, sticky="ew")
        console_header.columnconfigure(0, weight=1)
        ttk.Label(console_header, text="CONSOLE DE EXECUÇÃO", style="ConsoleTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(console_header, text="Copiar", style="ConsoleAction.TButton", command=self._copy_log_to_clipboard).grid(row=0, column=1, sticky="e")

        # Fonte JetBrains Mono (fallback: Consolas)
        self.log_text = tk.Text(
            console_box,
            wrap="word",
            width=40,
            height=20,
            state="disabled",
            bg=colors["console_bg"],
            fg="#d4d4d4",
            insertbackground="#ffffff",
            selectbackground="#2a3944",
            relief="flat",
            bd=0,
            padx=14,
            pady=12,
            font=("JetBrains Mono", 10),
        )
        # Configurar tags de cor para diferentes níveis de log (rich console)
        self.log_text.tag_configure("log_info",    foreground="#d4d4d4")
        self.log_text.tag_configure("log_success", foreground="#34d399")
        self.log_text.tag_configure("log_warning", foreground="#e97000")
        self.log_text.tag_configure("log_error",   foreground="#f87171")

        log_scroll = ttk.Scrollbar(console_box, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.grid(row=1, column=0, sticky="nsew")
        log_scroll.grid(row=1, column=1, sticky="ns")

        console_footer = ttk.Frame(console_box, style="ConsoleFooter.TFrame", padding=(16, 10))
        console_footer.grid(row=2, column=0, sticky="ew")
        console_footer.columnconfigure(0, weight=1)
        ttk.Label(console_footer, text="PROGRESSO DA OPERAÇÃO", style="ConsoleTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(console_footer, orient="horizontal", mode="determinate", maximum=100, variable=self.progress_var)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
    def _build_ui(self) -> None:
        self._apply_theme()
        colors = self._theme_colors

        self.root.title(f"SIGA Automação — v{__version__}")
        self.root.geometry("1440x900")
        self.root.minsize(1280, 840)

        main = ttk.Frame(self.root, padding=0, style="App.TFrame")
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        # Linha 0: header, linha 1: corpo (rail + workspace), linha 2: rodapé
        main.rowconfigure(1, weight=1)

        # ================= HEADER =================
        header_wrap = ttk.Frame(main, style="Header.TFrame")
        header_wrap.grid(row=0, column=0, sticky="ew")
        header_wrap.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=0)

        header = ttk.Frame(header_wrap, style="Header.TFrame", padding=(24, 14, 24, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=1)
        header.columnconfigure(2, weight=1)

        brand_box = ttk.Frame(header, style="Header.TFrame")
        brand_box.grid(row=0, column=0, sticky="w")
        if self._logo_image is not None:
            ttk.Label(brand_box, image=self._logo_image, style="Header.TLabel").grid(row=0, column=0, rowspan=2, sticky="w")
        ttk.Label(brand_box, text=COMPANY_NAME, style="HeaderCompany.TLabel").grid(row=0, column=1, sticky="sw", padx=(10, 0))
        ttk.Label(brand_box, text=COMPANY_TAGLINE, style="HeaderCompanyTagline.TLabel").grid(row=1, column=1, sticky="nw", padx=(10, 0))

        title_box = ttk.Frame(header, style="Header.TFrame")
        title_box.grid(row=0, column=1, sticky="n")
        ttk.Label(title_box, text="SIGA Automação", style="HeaderTitle.TLabel", anchor="center").grid(row=0, column=0, padx=(0, 8))
        ttk.Label(title_box, text=f"v{__version__}", style="VersionBadge.TLabel", anchor="center").grid(row=0, column=1)

        # Linha de destaque dourada — única linha "cheia" de cor de marca na tela
        header_accent = tk.Frame(header_wrap, height=3, bg=colors["primary"])
        header_accent.grid(row=1, column=0, sticky="ew")

        # ================= CORPO: nav rail + workspace =================
        body = ttk.Frame(main, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=0, minsize=250)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        rail_border = tk.Frame(body, bg=colors["border"])
        rail_border.grid(row=0, column=0, sticky="nsew")
        nav_rail = ttk.Frame(rail_border, style="NavRail.TFrame")
        nav_rail.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        rail_border.rowconfigure(0, weight=1)
        rail_border.columnconfigure(0, weight=1)

        workspace = ttk.Frame(body, style="Workspace.TFrame", padding=(24, 20))
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(2, weight=1)

        # --- Cabeçalho do workspace: título + descrição do modo ativo ---
        workspace_header = ttk.Frame(workspace, style="Workspace.TFrame")
        workspace_header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        workspace_header.columnconfigure(0, weight=1)
        ttk.Label(workspace_header, textvariable=self.workspace_title_var, style="WorkspaceTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(workspace_header, textvariable=self.workspace_desc_var, style="WorkspaceDesc.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))

        # --- Barra de parâmetros do modo ativo ---
        params_area = ttk.Frame(workspace, style="Workspace.TFrame")
        params_area.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        params_area.columnconfigure(0, weight=1)
        self._build_parameters_bar(params_area)

        # --- Divisão: tabela de empresas (larga) + console de execução (fixo) ---
        content = ttk.Frame(workspace, style="Workspace.TFrame")
        content.grid(row=2, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=0, minsize=360)
        content.rowconfigure(0, weight=1)

        table_area = ttk.Frame(content, style="Workspace.TFrame")
        table_area.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        table_area.columnconfigure(0, weight=1)
        table_area.rowconfigure(0, weight=1)

        console_area = ttk.Frame(content, style="Workspace.TFrame")
        console_area.grid(row=0, column=1, sticky="nsew")
        console_area.columnconfigure(0, weight=1)
        console_area.rowconfigure(1, weight=1)

        self._build_nav_rail(nav_rail)

        # Área de trabalho central: um painel por "forma" de fluxo, não por modo —
        # SIGA e NFC-e compartilham a mesma grade de empresas (ambos processam uma
        # lista de CNPJs), NF-e usa uma tabela de resultados por planilha (não há
        # empresas envolvidas nesse fluxo, só arquivos numa pasta).
        self.center_grid_frame = ttk.Frame(table_area, style="Workspace.TFrame")
        self.center_grid_frame.grid(row=0, column=0, sticky="nsew")
        self.center_grid_frame.columnconfigure(0, weight=1)
        self.center_grid_frame.rowconfigure(2, weight=1)
        self._build_center(self.center_grid_frame)

        self.center_nfe_frame = ttk.Frame(table_area, style="Workspace.TFrame")
        self.center_nfe_frame.grid(row=0, column=0, sticky="nsew")
        self._build_nfe_results_panel(self.center_nfe_frame)
        self.center_nfe_frame.grid_remove()

        self._build_console(console_area)

        # ================= FOOTER =================
        footer_border = tk.Frame(main, height=1, bg=colors["border"])
        footer_border.grid(row=2, column=0, sticky="ew")
        footer = ttk.Frame(main, style="Footer.TFrame", padding=(20, 8, 20, 8))
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, text=f"{COMPANY_NAME} — {COMPANY_TAGLINE}", style="FooterCompany.TLabel").grid(row=0, column=1, sticky="e")
        main.rowconfigure(3, weight=0)

    def _browse_spreadsheet(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecione a planilha XLSX",
            filetypes=[("Planilhas Excel", "*.xlsx")],
        )
        if path:
            self.spreadsheet_path_var.set(path)
            self._reload_spreadsheet()
            # Preencher a pasta de saída com o mesmo diretório da planilha importada
            parent_dir = Path(path).parent
            self.output_dir_var.set(str(parent_dir))

    def _reload_spreadsheet(self) -> None:
        path = Path(self.spreadsheet_path_var.get()).expanduser()
        self._load_spreadsheet_rows(path)

    def _load_manual_rows(self) -> None:
        """Carrega CNPJs digitados manualmente sem depender de planilha."""
        if self.manual_cnpjs_text is None:
            return

        raw_text = self.manual_cnpjs_text.get("1.0", "end").strip()
        if not raw_text:
            messagebox.showwarning("SIGA Automação", "Digite pelo menos um CNPJ no campo manual.")
            return

        try:
            spreadsheet_rows = load_cnpjs_from_text(raw_text)
        except Exception as exc:  # noqa: BLE001
            self.status_var.set(f"Falha ao carregar CNPJs manuais: {exc}")
            messagebox.showerror("SIGA Automação", f"Falha ao carregar CNPJs manuais:\n{exc}")
            return

        if self.input_notebook is not None:
            self.input_notebook.select(1)
        self._render_rows(spreadsheet_rows, source_label="Entrada manual")
        self.status_var.set(f"CNPJs manuais carregados com {len(spreadsheet_rows)} item(ns).")

    def _clear_manual_input(self) -> None:
        """Limpa o campo de entrada manual sem alterar a lista já carregada."""
        if self.manual_cnpjs_text is not None:
            self.manual_cnpjs_text.delete("1.0", "end")

    def _clear_loaded_rows(self) -> None:
        """Remove os CNPJs exibidos na grade sem mexer nas configurações do restante da tela."""
        for child in self.scrollable_rows.inner.winfo_children():
            child.destroy()
        self.selection_rows.clear()
        self.loaded_count_var.set("Total carregadas: 0")
        self.progress_var.set(0)
        self.status_var.set("Lista de empresas limpa.")

    def _validate_loaded_rows(self) -> None:
        """Confirma visualmente se há CNPJs disponíveis para seguir com a automação."""
        if not self.selection_rows:
            messagebox.showwarning("SIGA Automação", "Carregue pelo menos uma empresa antes de validar.")
            return
        self.status_var.set(f"{len(self.selection_rows)} empresa(s) prontas para execução.")

    def _browse_output_dir(self) -> None:
        """Abre o seletor de pasta para o usuario apontar o destino dos arquivos."""
        initial_dir = self._get_output_dir_for_dialog()
        path = filedialog.askdirectory(
            title="Selecione a pasta de saída",
            initialdir=str(initial_dir),
            mustexist=True,
        )
        if path:
            self._set_output_dir(Path(path))
            self.status_var.set(f"Pasta de saída selecionada: {self.output_dir_var.get()}")

    def _reset_output_dir(self) -> None:
        """Restaura a pasta padrao de saida usada pelo projeto."""
        self._set_output_dir(self._default_output_dir)
        self.status_var.set(f"Pasta de saída restaurada para o padrão: {self.output_dir_var.get()}")

    def _set_output_dir(self, path: Path) -> None:
        """Mantem o `Settings.output_dir` e o campo da interface sincronizados."""
        normalized_path = Path(path).expanduser()
        self.settings.output_dir = normalized_path
        self.output_dir_var.set(str(normalized_path))

    def _get_output_dir_for_dialog(self) -> Path:
        """Define a pasta inicial do dialog com base no valor mais recente exibido."""
        raw_value = self.output_dir_var.get().strip()
        if not raw_value:
            return self._default_output_dir
        return Path(raw_value).expanduser()

    def _apply_output_dir_selection(self) -> bool:
        """Valida e cria a pasta escolhida antes de iniciar a execucao."""
        raw_value = self.output_dir_var.get().strip()
        if not raw_value:
            messagebox.showwarning("SIGA Automação", "Informe uma pasta de saída válida.")
            return False

        output_dir = Path(raw_value).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("SIGA Automação", f"Não foi possível criar a pasta de saída:\n{exc}")
            return False

        self._set_output_dir(output_dir)
        return True

    def _load_spreadsheet_rows(self, path: Path) -> None:
        """Carrega CNPJs a partir da planilha e atualiza a grade da interface."""
        if not path.exists():
            self._render_rows([], source_label=f"Planilha nao encontrada: {path}")
            self.status_var.set(f"Planilha nao encontrada: {path}")
            return

        try:
            spreadsheet_rows = load_cnpjs_from_xlsx(path)
        except Exception as exc:  # noqa: BLE001
            self._render_rows([], source_label=f"Falha ao carregar planilha: {exc}")
            self.status_var.set(f"Falha ao carregar planilha: {exc}")
            messagebox.showerror("SIGA Automação", f"Falha ao carregar planilha:\n{exc}")
            return

        if self.input_notebook is not None:
            self.input_notebook.select(0)
        self._render_rows(spreadsheet_rows, source_label=f"Planilha carregada com {len(spreadsheet_rows)} empresa(s)")
        self.status_var.set(f"Planilha carregada com {len(spreadsheet_rows)} empresa(s).")

    def _render_rows(self, spreadsheet_rows: list[SpreadsheetRow], source_label: str) -> None:
        """Atualiza a lista de CNPJs exibida mantendo o alinhamento da grade.

        As colunas mudam conforme o modo ativo: SIGA mostra as 5 colunas de tipo de
        documento; NFC-e mostra uma única coluna "Incluir" (não existe escolha de
        documento nesse fluxo — a extração NFC-e sempre baixa todos os XMLs da
        empresa). Guarda os dados usados para poder re-renderizar ao trocar de modo
        (`_rerender_current_rows`) sem precisar recarregar a planilha.
        """
        self._last_rendered_rows = spreadsheet_rows
        self._last_rendered_source_label = source_label
        mode = self.mode_var.get()

        for child in self.scrollable_rows.inner.winfo_children():
            child.destroy()
        self.selection_rows.clear()
        self.loaded_count_var.set(f"Total carregadas: {len(spreadsheet_rows)}")

        table = ttk.Frame(self.scrollable_rows.inner)
        table.grid(row=0, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)

        # Instrução e fonte de dados
        instrucao = "Marque as empresas que deseja processar." if mode == OPERATION_MODE_NFCE else "Marque as empresas e as abas que deseja processar."
        ttk.Label(table, text=instrucao, style="BodyMuted.TLabel").grid(
            row=0, column=0, columnspan=7, sticky="w", pady=(0, 6)
        )
        ttk.Label(table, text=source_label, style="BodyMuted.TLabel").grid(
            row=1, column=0, columnspan=7, sticky="w", pady=(0, 6)
        )
        # Separador suave antes do cabeçalho
        sep = tk.Frame(table, height=1, bg="#84949C")
        sep.grid(row=2, column=0, columnspan=7, sticky="ew", pady=(0, 0))

        # Cabeçalho com fundo surface_container (RowHeader)
        header = self._create_selection_row(
            parent=table,
            row_index=3,
            cod_text="COD",
            empresa_text="EMPRESA",
            nfe_widget=self._create_header_cell,
            nfce_widget=self._create_header_cell,
            cte_widget=self._create_header_cell,
            malha_widget=self._create_header_cell,
            debitos_widget=self._create_header_cell,
            is_header=True,
            row_style="RowHeader",
            mode=mode,
        )
        header.grid(row=3, column=0, sticky="ew")
        # Separador abaixo do cabeçalho
        sep2 = tk.Frame(table, height=1, bg="#84949C")
        sep2.grid(row=4, column=0, columnspan=7, sticky="ew")

        for index, spreadsheet_row in enumerate(spreadsheet_rows, start=5):
            nfe_var = tk.BooleanVar(value=self.nfe_doc_var.get())
            nfce_var = tk.BooleanVar(value=self.nfce_doc_var.get())
            cte_var = tk.BooleanVar(value=self.cte_doc_var.get())
            malha_var = tk.BooleanVar(value=self.malha_doc_var.get())
            debitos_var = tk.BooleanVar(value=self.debitos_doc_var.get())
            incluir_var = tk.BooleanVar(value=True)
            # Zebra striping: linhas pares com fundo branco, ímpares com surface_low
            row_style = "RowEven" if (index % 2 == 0) else "RowOdd"

            row_frame = self._create_selection_row(
                parent=table,
                row_index=index,
                cod_text=spreadsheet_row.cod or "SEM-COD",
                empresa_text=spreadsheet_row.empresa or "SEM-EMPRESA",
                nfe_widget=lambda parent, rv=incluir_var if mode == OPERATION_MODE_NFCE else nfe_var, rs=row_style: ttk.Checkbutton(parent, variable=rv, style=f"{rs}.TCheckbutton"),
                nfce_widget=lambda parent, rv=nfce_var, rs=row_style: ttk.Checkbutton(parent, variable=rv, style=f"{rs}.TCheckbutton"),
                cte_widget=lambda parent, rv=cte_var, rs=row_style: ttk.Checkbutton(parent, variable=rv, style=f"{rs}.TCheckbutton"),
                malha_widget=lambda parent, rv=malha_var, rs=row_style: ttk.Checkbutton(parent, variable=rv, style=f"{rs}.TCheckbutton"),
                debitos_widget=lambda parent, rv=debitos_var, rs=row_style: ttk.Checkbutton(parent, variable=rv, style=f"{rs}.TCheckbutton"),
                is_header=False,
                row_style=row_style,
                mode=mode,
            )
            row_frame.grid(row=index, column=0, sticky="ew")

            self.selection_rows.append(
                RowSelectionWidgets(
                    spreadsheet_row=spreadsheet_row,
                    container=row_frame,
                    nfe_var=nfe_var,
                    nfce_var=nfce_var,
                    cte_var=cte_var,
                    malha_var=malha_var,
                    debitos_var=debitos_var,
                    incluir_var=incluir_var,
                )
            )

        if not spreadsheet_rows:
            ttk.Label(table, text="Nenhuma empresa disponível.", style="BodyMuted.TLabel").grid(
                row=5, column=0, columnspan=7, sticky="w", pady=(12, 0)
            )

    def _rerender_current_rows(self) -> None:
        """Reconstrói a grade com os dados já carregados, para refletir a troca de modo
        (SIGA mostra 5 colunas de documento; NFC-e mostra só "Incluir") sem precisar
        recarregar a planilha ou a entrada manual."""
        self._render_rows(self._last_rendered_rows, self._last_rendered_source_label)

    def _select_all_documents(self) -> None:
        for row in self.selection_rows:
            row.nfe_var.set(True)
            row.nfce_var.set(True)
            row.cte_var.set(True)
            row.malha_var.set(True)
            row.debitos_var.set(True)

    def _clear_all_documents(self) -> None:
        for row in self.selection_rows:
            row.nfe_var.set(False)
            row.nfce_var.set(False)
            row.cte_var.set(False)
            row.malha_var.set(False)
            row.debitos_var.set(False)

    def _set_operation_mode(self, mode: str) -> None:
        """Alterna o modo de operação: troca a barra de parâmetros e o rótulo do botão Executar."""
        if mode not in OPERATION_MODE_LABELS:
            return
        self.mode_var.set(mode)
        self._refresh_mode_nav_styles()

        frame_by_mode = {
            OPERATION_MODE_SIGA: self.params_siga_frame,
            OPERATION_MODE_NFCE: self.params_nfce_frame,
            OPERATION_MODE_NFE: self.params_nfe_frame,
        }
        for frame_mode, frame in frame_by_mode.items():
            if frame is None:
                continue
            if frame_mode == mode:
                frame.grid()
            else:
                frame.grid_remove()

        # Área de trabalho central: grade de empresas (SIGA/NFC-e) ou tabela de
        # resultados por planilha (NF-e) — nunca as duas ao mesmo tempo.
        if mode == OPERATION_MODE_NFE:
            if self.center_grid_frame is not None:
                self.center_grid_frame.grid_remove()
            if self.center_nfe_frame is not None:
                self.center_nfe_frame.grid()
        else:
            if self.center_nfe_frame is not None:
                self.center_nfe_frame.grid_remove()
            if self.center_grid_frame is not None:
                self.center_grid_frame.grid()
            # Re-renderiza a grade para trocar as colunas (5 checkboxes de documento no
            # SIGA vs. um único "Incluir" no NFC-e) sem precisar recarregar a planilha.
            self._rerender_current_rows()

        # "Iniciar Navegador" só faz sentido em SIGA/NFC-e — o modo NF-e gerencia seus
        # próprios Chromes (undetected_chromedriver) e não depende de BrowserSession.
        if self.start_browser_button is not None:
            if mode == OPERATION_MODE_NFE:
                self.start_browser_button.grid_remove()
            else:
                self.start_browser_button.grid()

        # Reavalia se o botão Executar deve ficar habilitado nesse modo (ver
        # `_restore_browser_controls_state`) — não faz isso se uma execução já
        # estiver em andamento, para não reabilitar o botão no meio de um lote.
        if not (self._worker_thread and self._worker_thread.is_alive()):
            self._restore_browser_controls_state()

        if self.workspace_title_var is not None:
            self.workspace_title_var.set(OPERATION_MODE_LABELS[mode])
        if self.workspace_desc_var is not None:
            self.workspace_desc_var.set(OPERATION_MODE_DESCRIPTIONS[mode])
        if self.execute_button is not None:
            self.execute_button.configure(text=OPERATION_MODE_LABELS[mode].upper())
        narrate("Modo de operação alterado para: %s", OPERATION_MODE_LABELS[mode])

    def _refresh_mode_nav_styles(self) -> None:
        """Realça o card do modo ativo (fundo dourado suave) e neutraliza os demais."""
        colors = self._theme_colors
        current_mode = self.mode_var.get()
        for mode, widgets in self.mode_nav_cards.items():
            is_active = mode == current_mode
            bg = colors["highlight_tint"] if is_active else colors["surface"]
            title_fg = colors["structural"] if is_active else colors["text"]
            widgets["outer"].configure(bg=bg)
            widgets["inner"].configure(bg=bg)
            widgets["title"].configure(bg=bg, fg=title_fg)
            widgets["badge"].configure(bg=colors["primary"] if is_active else colors["structural"])
            widgets["accent"].configure(bg=colors["primary"] if is_active else bg)

    def _browse_nfce_base_spreadsheet(self) -> None:
        """Seleciona a planilha-base de IE/CNPJ usada para resolver empresas no modo NFC-e."""
        path = filedialog.askopenfilename(
            title="Selecione a planilha-base NFC-e (IE/CNPJ)",
            filetypes=[("Planilhas Excel", "*.xlsx")],
        )
        if path:
            self.nfce_base_spreadsheet_var.set(path)
            self.settings.nfce_base_spreadsheet_path = Path(path)

    def _browse_nfce_keys_folder(self) -> None:
        """Seleciona a pasta com as planilhas de chaves de 44 dígitos por empresa."""
        path = filedialog.askdirectory(title="Selecione a pasta de chaves por empresa", mustexist=True)
        if path:
            self.nfce_keys_folder_var.set(path)
            self.settings.nfce_keys_folder_path = Path(path)

    def _browse_nfce_output_dir(self) -> None:
        """Seleciona a pasta de destino dos XMLs baixados no modo NFC-e."""
        path = filedialog.askdirectory(title="Selecione a pasta de saída dos XMLs de NFC-e", mustexist=True)
        if path:
            self.nfce_output_dir_var.set(path)

    def _browse_nf_meudanfe_input_folder(self) -> None:
        """Seleciona a pasta com as planilhas NF-e a processar no modo NF-e (Meu DANFE)."""
        path = filedialog.askdirectory(title="Selecione a pasta com as planilhas NF-e", mustexist=True)
        if path:
            self.nf_meudanfe_input_folder_var.set(path)

    def _browse_nf_meudanfe_chrome_path(self) -> None:
        """Seleciona manualmente o chrome.exe usado pelo modo NF-e (Meu DANFE)."""
        path = filedialog.askopenfilename(
            title="Selecione o chrome.exe (opcional)",
            filetypes=[("Executável", "*.exe")],
        )
        if path:
            self.nf_meudanfe_chrome_path_var.set(path)

    def _copy_log_to_clipboard(self) -> None:
        """Copia todo o conteúdo do console de execução para a área de transferência."""
        content = self.log_text.get("1.0", "end").strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.status_var.set("Log copiado para a área de transferência.")

    def _open_run_log_file(self, output_dir: Path) -> logging.Handler:
        """Anexa um handler que grava um log.txt completo (narração + log técnico) na pasta
        de saída escolhida pelo usuário — tudo que aparece no console (e mais, incluindo o
        detalhe técnico que só vai para logs/run.log) fica registrado junto dos arquivos
        baixados, para facilitar conferência/suporte sem precisar abrir a pasta interna de logs.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(str(output_dir / "log.txt"), encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)
        logging.getLogger(NARRATION_LOGGER_NAME).addHandler(handler)
        return handler

    def _close_run_log_file(self, handler: logging.Handler) -> None:
        """Remove e fecha o handler aberto por `_open_run_log_file`."""
        logging.getLogger().removeHandler(handler)
        logging.getLogger(NARRATION_LOGGER_NAME).removeHandler(handler)
        handler.close()

    def _set_document_selection(self, document_tab: str, enabled: bool) -> None:
        """Marca ou desmarca uma coluna inteira da grade para o documento escolhido."""
        if document_tab not in DOCUMENT_TABS:
            return

        for row in self.selection_rows:
            if document_tab == "NF-e":
                row.nfe_var.set(enabled)
            elif document_tab == "NFC-e":
                row.nfce_var.set(enabled)
            elif document_tab == "CT-e":
                row.cte_var.set(enabled)
            elif document_tab == "Malha Fiscal":
                row.malha_var.set(enabled)
            elif document_tab == "Débitos Fiscais":
                row.debitos_var.set(enabled)

    def _start_browser_if_needed(self) -> None:
        if self._browser_started:
            self.status_var.set("O navegador já foi iniciado. Faça o login manual e clique em Executar.")
            return

        if self._browser_thread is not None and self._browser_thread.is_alive():
            self.status_var.set("O navegador já está sendo iniciado. Aguarde alguns instantes.")
            return

        if not self.settings.connect_browser_url:
            self.settings.connect_browser_url = get_connect_browser_url(self.settings)

        # A abertura do navegador (incluindo a espera pelo CDP) pode levar segundos; rodar em
        # thread evita congelar o loop de eventos do Tkinter e a janela "Não responde".
        if self.start_browser_button is not None:
            self.start_browser_button.state(["disabled"])
        self.status_var.set("Iniciando o navegador... aguarde.")
        narrate("Iniciando o navegador de depuração...")

        def worker() -> None:
            try:
                launch_debug_browser(self.settings)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Não foi possível abrir o navegador de depuração pela GUI")
                narrate_error("Falha ao iniciar o navegador: %s", exc)
                self._ui_after(0, lambda exc=exc: self._on_browser_start_failed(exc))
            else:
                self._ui_after(0, self._on_browser_start_succeeded)

        self._browser_thread = threading.Thread(target=worker, daemon=True)
        self._browser_thread.start()

    def _on_browser_start_succeeded(self) -> None:
        """Atualiza a interface na thread principal após o navegador abrir com sucesso."""
        self._browser_started = True
        if self.start_browser_button is not None:
            self.start_browser_button.state(["disabled"])
        if self.execute_button is not None:
            self.execute_button.state(["!disabled"])
        self.status_var.set("Navegador iniciado. Faça o login manualmente e, depois, clique em Executar.")
        narrate_success("Navegador iniciado. Aguardando login manual do usuário.")

    def _on_browser_start_failed(self, exc: Exception) -> None:
        """Restaura o botão de iniciar o navegador quando a abertura falha."""
        if self.start_browser_button is not None:
            self.start_browser_button.state(["!disabled"])
        self.status_var.set(f"Nao foi possivel abrir o navegador automaticamente: {exc}")

    def _run_selected(self) -> None:
        """Despacha a execução para o backend do modo de operação selecionado."""
        mode = self.mode_var.get()
        if mode == OPERATION_MODE_NFE:
            self._run_selected_nfe()
            return
        if mode == OPERATION_MODE_NFCE:
            self._run_selected_nfce()
            return
        self._run_selected_siga()

    def _run_selected_siga(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showinfo("SIGA Automação", "Uma execução já está em andamento.")
            return

        if not self._browser_started:
            messagebox.showwarning("SIGA Automação", "Clique em 'Iniciar navegador' e faça o login antes de executar.")
            return

        if not self._apply_output_dir_selection():
            return

        selected_rows, selected_tabs_by_row_number = self._collect_selection()
        if not selected_rows:
            messagebox.showwarning("SIGA Automação", "Selecione pelo menos um CNPJ e uma aba fiscal.")
            return

        month_reference = self.month_var.get().strip()
        year_value = self.year_var.get().strip()
        if not month_reference:
            messagebox.showwarning("SIGA Automação", "Informe o mês de referência.")
            return
        if not (year_value.isdigit() and len(year_value) == 4):
            messagebox.showwarning("SIGA Automação", "Informe um ano válido com 4 dígitos.")
            return

        self._set_controls_state("disabled")
        if self.start_browser_button is not None:
            self.start_browser_button.state(["disabled"])
        if self.execute_button is not None:
            self.execute_button.state(["disabled"])
        self.progress_var.set(0)
        self.status_var.set("Execução iniciada. Aguarde a conclusão no navegador e no log.")
        narrate("Execução iniciada pela interface gráfica.")

        log_file_handler = self._open_run_log_file(self.settings.output_dir)
        narrate("Registrando esta execução em %s", self.settings.output_dir / "log.txt")

        def worker() -> None:
            try:
                self._execute_selected(selected_rows, selected_tabs_by_row_number, month_reference, year_value)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha na execução pela GUI")
                narrate_error("Falha na execução: %s", exc)
                self._ui_after(0, lambda exc=exc: messagebox.showerror("SIGA Automação", str(exc)))
            finally:
                self._ui_after(0, lambda: self._set_controls_state("normal"))
                self._ui_after(0, self._restore_browser_controls_state)
                self._ui_after(0, lambda: self.progress_var.set(100))
                self._ui_after(0, lambda: self.status_var.set("Execução finalizada."))
                self._close_run_log_file(log_file_handler)

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _execute_selected(
        self,
        selected_rows: list[SpreadsheetRow],
        selected_tabs_by_row_number: dict[int, list[str]],
        month_reference: str,
        year_value: str,
    ) -> None:
        import shutil
        is_manual_mode = (self.input_notebook is not None and self.input_notebook.index("current") == 1)
        output_spreadsheet_path = None
        if not is_manual_mode:
            input_spreadsheet_path = Path(self.spreadsheet_path_var.get().strip())
            output_spreadsheet_path = input_spreadsheet_path.parent / f"{input_spreadsheet_path.stem}_resultados{input_spreadsheet_path.suffix}"
            try:
                shutil.copy(input_spreadsheet_path, output_spreadsheet_path)
                narrate_success("Cópia de resultados criada: %s", output_spreadsheet_path.name)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha ao criar cópia da planilha para gravação de resultados")
                narrate_warning("Erro ao criar planilha de resultados: %s", exc)
        else:
            # A entrada manual não parte de nenhum arquivo existente; gera uma planilha de
            # resultados dedicada para que o status de cada CNPJ também fique rastreável.
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_spreadsheet_path = Path(self.settings.output_dir) / f"resultados_manual_{timestamp}.xlsx"
            try:
                build_manual_entry_workbook(selected_rows, output_spreadsheet_path)
                narrate_success("Planilha de resultados criada: %s", output_spreadsheet_path.name)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha ao criar planilha de resultados para a entrada manual")
                narrate_warning("Erro ao criar planilha de resultados: %s", exc)
                output_spreadsheet_path = None

        extractor = SigaContributorExtractor(self.settings, allow_manual_login_prompt=False, output_spreadsheet_path=output_spreadsheet_path)
        flow = SigaLoginFlow(self.settings)

        with BrowserSession(self.settings) as context:
            authenticated_page = flow.confirm_authenticated_context(context, browser=context.browser)
            narrate_success("Login confirmado: %s", authenticated_page.title())
            results = extractor.run_batch_from_spreadsheet_in_context(
                context,
                selected_rows,
                month_reference,
                year_value,
                selected_tabs=None,
                selected_tabs_by_row_number=selected_tabs_by_row_number,
            )
            download_count = sum(len(result.fiscal_results) for result in results)
            not_found_count = sum(1 for result in results if result.status == "taxpayer_not_found")
            narrate_success("Processo concluído.")
            narrate("Contribuintes processados: %s de %s", len(results), len(selected_rows))
            narrate("Empresas não encontradas: %s", not_found_count)
            narrate("Detalhamentos baixados: %s", download_count)
            if results:
                narrate("Pasta da última saída: %s", results[-1].taxpayer_folder)

    def _collect_selection(self) -> tuple[list[SpreadsheetRow], dict[int, list[str]]]:
        selected_rows: list[SpreadsheetRow] = []
        tabs_by_row_number: dict[int, list[str]] = {}

        for row in self.selection_rows:
            tabs: list[str] = []
            if row.nfe_var.get():
                tabs.append("NF-e")
            if row.nfce_var.get():
                tabs.append("NFC-e")
            if row.cte_var.get():
                tabs.append("CT-e")
            if row.malha_var.get():
                tabs.append("Malha Fiscal")
            if row.debitos_var.get():
                tabs.append("Débitos Fiscais")
            if tabs:
                selected_rows.append(row.spreadsheet_row)
                tabs_by_row_number[row.spreadsheet_row.row_number] = tabs

        return selected_rows, tabs_by_row_number

    def _collect_included_companies(self) -> list[SpreadsheetRow]:
        """Coleta as empresas marcadas como incluídas no modo NFC-e.

        Diferente do SIGA, o NFC-e não tem escolha por tipo de documento (sempre
        baixa todos os XMLs da empresa) — a grade mostra uma única coluna "Incluir".
        """
        return [row.spreadsheet_row for row in self.selection_rows if row.incluir_var is not None and row.incluir_var.get()]

    def _run_selected_nfce(self) -> None:
        """Valida e dispara a execução do modo NFC-e (item 8), em thread separada."""
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showinfo("SIGA Automação", "Uma execução já está em andamento.")
            return

        if not self._browser_started:
            messagebox.showwarning("SIGA Automação", "Clique em 'Iniciar Navegador' antes de executar o modo NFC-e.")
            return

        nfce_cpf = self.nfce_cpf_var.get().strip()
        nfce_senha = self.nfce_senha_var.get()
        if not nfce_cpf or not nfce_senha:
            messagebox.showerror(
                "SIGA Automação",
                "Informe o CPF e a senha do contador antes de usar o modo NFC-e.",
            )
            return

        output_dir_raw = self.nfce_output_dir_var.get().strip()
        if not output_dir_raw:
            messagebox.showwarning("SIGA Automação", "Selecione a pasta de saída dos XMLs de NFC-e.")
            return
        output_dir = Path(output_dir_raw).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("SIGA Automação", f"Não foi possível criar a pasta de saída:\n{exc}")
            return

        keys_folder_raw = self.nfce_keys_folder_var.get().strip()
        if not keys_folder_raw:
            messagebox.showwarning("SIGA Automação", "Selecione a pasta com as planilhas de chaves por empresa.")
            return
        keys_folder = Path(keys_folder_raw).expanduser()
        if not keys_folder.is_dir():
            messagebox.showerror("SIGA Automação", f"Pasta de chaves não encontrada:\n{keys_folder}")
            return

        selected_rows = self._collect_included_companies()
        if not selected_rows:
            messagebox.showwarning(
                "SIGA Automação",
                "Carregue pelo menos uma empresa (planilha ou entrada manual) antes de executar.",
            )
            return

        self._set_controls_state("disabled")
        if self.start_browser_button is not None:
            self.start_browser_button.state(["disabled"])
        if self.execute_button is not None:
            self.execute_button.state(["disabled"])
        self.progress_var.set(0)
        self.status_var.set("Execução NFC-e iniciada. Aguarde a conclusão no log.")
        narrate("Execução do modo NFC-e iniciada pela interface gráfica.")

        log_file_handler = self._open_run_log_file(output_dir)
        narrate("Registrando esta execução em %s", output_dir / "log.txt")

        def worker() -> None:
            try:
                self._execute_selected_nfce(selected_rows, output_dir, keys_folder, nfce_cpf, nfce_senha)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha na execução do modo NFC-e pela GUI")
                narrate_error("Falha na execução NFC-e: %s", exc)
                self._ui_after(0, lambda exc=exc: messagebox.showerror("SIGA Automação", str(exc)))
            finally:
                self._ui_after(0, lambda: self._set_controls_state("normal"))
                self._ui_after(0, self._restore_browser_controls_state)
                self._ui_after(0, lambda: self.progress_var.set(100))
                self._ui_after(0, lambda: self.status_var.set("Execução NFC-e finalizada."))
                self._close_run_log_file(log_file_handler)

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _execute_selected_nfce(
        self,
        selected_rows: list[SpreadsheetRow],
        output_dir: Path,
        keys_folder: Path,
        nfce_cpf: str,
        nfce_senha: str,
    ) -> None:
        """Roda o lote NFC-e dentro de uma sessão de navegador compartilhada (BrowserSession)."""
        from src.extraction.nfce_extractor import NfceBatchExtractor

        base_spreadsheet_raw = self.nfce_base_spreadsheet_var.get().strip()
        base_spreadsheet_path = Path(base_spreadsheet_raw).expanduser() if base_spreadsheet_raw else None

        # BrowserContext deriva download_dir de settings.output_dir na hora de abrir a
        # sessão — apontar para a pasta de saída do NFC-e antes de abrir o BrowserSession.
        self.settings.output_dir = output_dir
        self.settings.nfce_keys_folder_path = keys_folder
        self.settings.nfce_base_spreadsheet_path = base_spreadsheet_path
        # CPF/senha só ficam neste atributo em memória pelo tempo da execução — nunca
        # persistidos em arquivo (nem .env, nem planilha, nem log).
        self.settings.nfce_cpf = nfce_cpf
        self.settings.nfce_senha = nfce_senha

        extractor = NfceBatchExtractor(
            self.settings,
            output_dir=output_dir,
            keys_folder=keys_folder,
            base_spreadsheet_path=base_spreadsheet_path,
        )
        with BrowserSession(self.settings) as context:
            results = extractor.run_batch_in_context(context, selected_rows)
            success_count = sum(1 for result in results if result.status == "concluido")
            narrate_success("Processo NFC-e concluído.")
            narrate("Empresas processadas com sucesso: %s de %s", success_count, len(results))

    def _run_selected_nfe(self) -> None:
        """Valida e dispara a execução do modo NF-e (Meu DANFE), em thread separada.

        Diferente de SIGA/NFC-e, este modo não usa `BrowserSession` — o extractor
        gerencia seus próprios Chromes (undetected_chromedriver) — então não depende
        do botão "Iniciar Navegador" nem de nenhuma seleção na grade de empresas.
        """
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showinfo("SIGA Automação", "Uma execução já está em andamento.")
            return

        input_folder_raw = self.nf_meudanfe_input_folder_var.get().strip()
        if not input_folder_raw:
            messagebox.showwarning("SIGA Automação", "Selecione a pasta com as planilhas NF-e.")
            return
        input_folder = Path(input_folder_raw).expanduser()
        if not input_folder.is_dir():
            messagebox.showerror("SIGA Automação", f"Pasta não encontrada:\n{input_folder}")
            return

        max_workers_raw = self.nf_meudanfe_max_workers_var.get().strip()
        if not max_workers_raw.isdigit() or not (1 <= int(max_workers_raw) <= 4):
            messagebox.showwarning("SIGA Automação", "Informe uma quantidade de Chromes entre 1 e 4.")
            return

        self._set_controls_state("disabled")
        if self.start_browser_button is not None:
            self.start_browser_button.state(["disabled"])
        if self.execute_button is not None:
            self.execute_button.state(["disabled"])
        self.progress_var.set(0)
        self.status_var.set("Execução NF-e iniciada. Aguarde a conclusão no log.")
        narrate("Execução do modo NF-e (Meu DANFE) iniciada pela interface gráfica.")
        self._reset_nfe_results_panel()

        log_file_handler = self._open_run_log_file(input_folder)
        narrate("Registrando esta execução em %s", input_folder / "log.txt")

        def worker() -> None:
            try:
                self._execute_selected_nfe(input_folder, int(max_workers_raw))
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha na execução do modo NF-e pela GUI")
                narrate_error("Falha na execução NF-e: %s", exc)
                self._ui_after(0, lambda exc=exc: messagebox.showerror("SIGA Automação", str(exc)))
            finally:
                self._ui_after(0, lambda: self._set_controls_state("normal"))
                self._ui_after(0, self._restore_browser_controls_state)
                self._ui_after(0, lambda: self.progress_var.set(100))
                self._ui_after(0, lambda: self.status_var.set("Execução NF-e finalizada."))
                self._close_run_log_file(log_file_handler)

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _execute_selected_nfe(self, input_folder: Path, max_workers: int) -> None:
        """Roda o lote NF-e (Meu DANFE) — o extractor abre e fecha seus próprios Chromes."""
        from src.extraction.meudanfe_extractor import MeudanfeBatchExtractor

        self.settings.nf_meudanfe_input_folder = input_folder
        self.settings.nf_meudanfe_max_workers = max_workers
        chrome_path_raw = self.nf_meudanfe_chrome_path_var.get().strip()
        self.settings.nf_meudanfe_chrome_path = Path(chrome_path_raw).expanduser() if chrome_path_raw else None

        def on_planilha_concluida(resultado, results_queue=self.nfe_results_queue) -> None:
            # Chamado de dentro da thread de trabalho — só enfileira, thread-safe;
            # quem atualiza a tabela é `_drain_nfe_results_queue` na thread principal.
            results_queue.put(resultado)

        extractor = MeudanfeBatchExtractor(self.settings, input_folder=input_folder)
        results = extractor.executar_lote(on_planilha_concluida=on_planilha_concluida)
        success_count = sum(1 for result in results if result.status == "concluido")
        narrate_success("Processo NF-e concluído.")
        narrate("Planilhas concluídas: %s de %s", success_count, len(results))

    def _drain_log_queue(self) -> None:
        if self._closing:
            return
        drained = False
        while True:
            try:
                line, tag = self.log_queue.get_nowait()
            except queue.Empty:
                break
            drained = True
            self._append_text(line, tag)
        if drained:
            self.log_text.see("end")
        self.root.after(100, self._drain_log_queue)

    def _ui_after(self, delay: int, callback) -> None:
        """Agenda uma atualização de UI a partir de threads, ignorando-a se a janela já fechou."""
        if self._closing:
            return
        try:
            self.root.after(delay, callback)
        except tk.TclError:
            # A janela pode ter sido destruída entre a checagem e o agendamento.
            pass

    def _append_text(self, line: str, tag: str) -> None:
        """Insere uma linha no console com a cor já decidida na origem (ver `_tag_for_record`)."""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{line}\n", tag)
        self.log_text.configure(state="disabled")

    def _set_controls_state(self, state: str) -> None:
        for widget in self.root.winfo_children():
            self._set_widget_state(widget, state)

    def _set_widget_state(self, widget: tk.Widget, state: str) -> None:
        if isinstance(widget, (ttk.Entry, ttk.Button, ttk.Checkbutton, ttk.Combobox)):
            try:
                widget.state([state] if state == "disabled" else ["!disabled"])
            except Exception:  # noqa: BLE001
                pass
        for child in widget.winfo_children():
            self._set_widget_state(child, state)

    def _format_cnpj(self, value: str) -> str:
        # Formata o CNPJ mantendo letras e números para dar suporte ao CNPJ alfanumérico.
        digits = "".join(char for char in value if char.isalnum())
        if len(digits) != 14:
            return value
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"

    def _create_selection_row(
        self,
        parent: ttk.Frame,
        row_index: int,
        cod_text: str,
        empresa_text: str,
        nfe_widget,
        nfce_widget,
        cte_widget,
        malha_widget,
        debitos_widget,
        is_header: bool,
        row_style: str = "RowEven",
        mode: str = OPERATION_MODE_SIGA,
    ) -> ttk.Frame:
        """Cria uma linha fixa da grade com células alinhadas, zebra striping e tamanhos previsíveis."""
        # Escolher o estilo de frame e label conforme o tipo de linha
        frame_style = f"{row_style}.TFrame"
        label_style = f"{row_style}.TLabel"

        row_frame = ttk.Frame(parent, style=frame_style)
        row_frame.columnconfigure(0, minsize=self._row_columns[0], weight=0)
        row_frame.columnconfigure(1, minsize=self._row_columns[1], weight=1)
        row_frame.columnconfigure(2, minsize=self._row_columns[2], weight=0)
        row_frame.columnconfigure(3, minsize=self._row_columns[3], weight=0)
        row_frame.columnconfigure(4, minsize=self._row_columns[4], weight=0)
        row_frame.columnconfigure(5, minsize=self._row_columns[5], weight=0)
        row_frame.columnconfigure(6, minsize=self._row_columns[6], weight=0)

        cells = []
        for column, width in enumerate(self._row_columns):
            cell = ttk.Frame(row_frame, width=width, style=frame_style)
            cell.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
            cell.grid_propagate(False)
            cells.append(cell)

        ttk.Label(
            cells[0],
            text=cod_text,
            anchor="center",
            style=label_style,
        ).pack(fill="x", padx=4, pady=4)
        ttk.Label(
            cells[1],
            text=empresa_text,
            anchor="w" if not is_header else "center",
            style=label_style,
        ).pack(fill="x", padx=4, pady=4)

        # No modo NFC-e não existe escolha por tipo de documento (sempre baixa todos
        # os XMLs da empresa) — só a coluna "Incluir" (célula 2) é usada; as demais
        # ficam em branco, mantendo o alinhamento das 7 colunas fixas da grade.
        if mode == OPERATION_MODE_NFCE:
            if is_header:
                ttk.Label(cells[2], text="Incluir", anchor="center", style=label_style).pack(expand=True, fill="both")
            else:
                nfe_widget(cells[2]).pack(expand=True)
        elif is_header:
            for index, label in enumerate(("NF-e", "NFC-e", "CT-e", "Malha", "Débitos"), start=2):
                ttk.Label(cells[index], text=label, anchor="center", style=label_style).pack(expand=True, fill="both")
        else:
            nfe_widget(cells[2]).pack(expand=True)
            nfce_widget(cells[3]).pack(expand=True)
            cte_widget(cells[4]).pack(expand=True)
            malha_widget(cells[5]).pack(expand=True)
            debitos_widget(cells[6]).pack(expand=True)

        return row_frame

    def _create_header_cell(self, parent: ttk.Frame) -> ttk.Label:
        """Cria uma célula de cabeçalho neutra para manter a grade alinhada."""
        return ttk.Label(parent, text="")

    def _restore_browser_controls_state(self) -> None:
        """Mantém o botão de executar disponível após o navegador já estar iniciado.

        No modo NF-e (Meu DANFE) não existe navegador persistente para "iniciar" — o
        extractor abre e fecha seus próprios Chromes por conta própria — então o botão
        Executar não pode ficar condicionado a `_browser_started` nesse modo, senão
        ficaria desabilitado para sempre (esse estado nunca vira `True` sem o botão
        "Iniciar Navegador", que fica escondido no modo NF-e).
        """
        if self.mode_var.get() == OPERATION_MODE_NFE:
            if self.execute_button is not None:
                self.execute_button.state(["!disabled"])
            return
        if self.start_browser_button is not None:
            self.start_browser_button.state(["disabled"] if self._browser_started else ["!disabled"])
        if self.execute_button is not None:
            self.execute_button.state(["!disabled"] if self._browser_started else ["disabled"])

    def _on_close(self) -> None:
        worker_running = self._worker_thread is not None and self._worker_thread.is_alive()

        if worker_running:
            confirmed = messagebox.askyesno(
                "SIGA Automação",
                "Uma extração está em andamento. Deseja realmente sair?\n\n"
                "A operação atual será interrompida e o navegador de automação será encerrado.",
            )
            if not confirmed:
                return

        # Sinaliza o encerramento para as threads e impede novos agendamentos de UI.
        self._closing = True
        self._stop_requested = True

        if worker_running:
            narrate_warning("Encerrando a execução a pedido do usuário...")
            # Encerrar o navegador da automação faz as chamadas do Selenium falharem rápido,
            # permitindo que a thread de trabalho saia do bloco de sessão em vez de ficar presa.
            try:
                shutdown_debug_browser(self.settings)
            except Exception:  # noqa: BLE001
                LOGGER.exception("Falha ao encerrar o navegador durante o fechamento da interface")
            # Aguarda um encerramento gracioso da thread, sem travar a interface indefinidamente.
            self._worker_thread.join(timeout=10)

        logging.getLogger(NARRATION_LOGGER_NAME).removeHandler(self.narration_handler)
        logging.getLogger().removeHandler(self.error_bridge_handler)
        self.root.destroy()


def launch_gui(
    settings: Settings,
    initial_spreadsheet: str | None = None,
    initial_month: str | None = None,
    initial_year: str | None = None,
) -> int:
    """Abre a interface gráfica e devolve código de saída compatível com o main."""
    app = SigaAutomationGUI(
        settings,
        initial_spreadsheet=initial_spreadsheet,
        initial_month=initial_month,
        initial_year=initial_year,
    )
    app.run()
    return 0
