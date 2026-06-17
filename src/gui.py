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

from src.auth.siga_login import SigaLoginFlow
from src.config import Settings
from src.extraction.siga_extractor import SigaContributorExtractor
from src.extraction.spreadsheet import SpreadsheetRow, load_cnpjs_from_text, load_cnpjs_from_xlsx
from src.utils.browser import BrowserSession, get_connect_browser_url, launch_debug_browser
from src.utils.logging_setup import configure_logging
from src.months import MONTH_OPTIONS


LOGGER = logging.getLogger(__name__)
DOCUMENT_TABS = ("NF-e", "NFC-e", "CT-e")


@dataclass(slots=True)
class RowSelectionWidgets:
    spreadsheet_row: SpreadsheetRow
    container: ttk.Frame
    nfe_var: tk.BooleanVar
    nfce_var: tk.BooleanVar
    cte_var: tk.BooleanVar


class QueueLogHandler(logging.Handler):
    """Encaminha mensagens de log para a fila consumida pela interface."""

    def __init__(self, output_queue: queue.Queue[str]) -> None:
        super().__init__()
        self.output_queue = output_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # noqa: BLE001
            return
        self.output_queue.put(message)


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

        self.root = tk.Tk()
        self.root.title("SIGA Automação")
        self.root.geometry("1280x840")
        self.root.minsize(1080, 720)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.log_handler = QueueLogHandler(self.log_queue)
        self.log_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        logging.getLogger().addHandler(self.log_handler)

        self.spreadsheet_path_var = tk.StringVar(value=initial_spreadsheet or "cnpj.xlsx")
        self._default_output_dir = Path(self.settings.output_dir)
        self.output_dir_var = tk.StringVar(value=str(self.settings.output_dir))
        self.month_var = tk.StringVar(value=initial_month or self._default_previous_month())
        self.year_var = tk.StringVar(value=initial_year or str(time.localtime().tm_year))
        self.status_var = tk.StringVar(value="Carregue uma planilha XLSX ou informe CNPJs manualmente para iniciar.")
        self.loaded_count_var = tk.StringVar(value="Total carregadas: 0")

        self.selection_rows: list[RowSelectionWidgets] = []
        self._worker_thread: threading.Thread | None = None
        self._stop_requested = False
        self._row_columns = (72, 220, 84, 84, 84)
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
        self._window_icon_image: tk.PhotoImage | None = None
        self._logo_image: tk.PhotoImage | None = None
        self._app_icon_path = self._resolve_asset_path("images", "icons", "siga-automacao.ico")
        self._window_icon_photo_path = self._resolve_asset_path("images", "icons", "siga-automacao-32x32.png")
        self._logo_path = self._resolve_asset_path("images", "logo", "logo.png")

        self._configure_window_branding()
        self._build_ui()
        self._load_spreadsheet_rows(Path(self.spreadsheet_path_var.get()))
        self.root.after(100, self._drain_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self) -> None:
        """Executa o loop principal da interface."""
        self.root.mainloop()

    def _default_previous_month(self) -> str:
        """Calcula o mês anterior ao mês atual para sugerir a referência padrão."""
        current_month = time.localtime().tm_mon
        previous_month_index = (current_month - 2) % len(MONTH_OPTIONS)
        return MONTH_OPTIONS[previous_month_index]

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
        """Configura a aparência base da interface com uma paleta corporativa clara."""
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        colors = {
            "surface": "#f8f9fa",
            "surface_container": "#edeeef",
            "surface_low": "#f3f4f5",
            "surface_lowest": "#ffffff",
            "outline": "#c5c6ce",
            "outline_strong": "#75777e",
            "primary": "#031632",
            "primary_container": "#1a2b48",
            "on_surface": "#191c1d",
            "on_surface_variant": "#44474d",
            "success": "#28a745",
            "error": "#ba1a1a",
            "console": "#1e1e1e",
            "console_header": "#2d2d2d",
            "console_line": "#3d3d3d",
        }
        self._theme_colors = colors

        self.root.configure(bg=colors["surface"])
        style.configure("App.TFrame", background=colors["surface"])
        style.configure("Topbar.TFrame", background=colors["surface_lowest"])
        style.configure("Sidebar.TFrame", background=colors["surface_container"], relief="solid", borderwidth=1)
        style.configure("Center.TFrame", background=colors["surface"])
        style.configure("ConsolePanel.TFrame", background=colors["surface_lowest"], relief="solid", borderwidth=1)
        style.configure("Card.TFrame", background=colors["surface_lowest"], relief="solid", borderwidth=1)
        style.configure("Console.TFrame", background=colors["console"])
        style.configure("ConsoleHeader.TFrame", background=colors["console_header"])
        style.configure("ConsoleFooter.TFrame", background=colors["console_header"])

        style.configure("BrandTitle.TLabel", background=colors["surface_lowest"], foreground=colors["primary"], font=("Segoe UI", 22, "bold"))
        style.configure("VersionBadge.TLabel", background="#ececec", foreground=colors["on_surface"], font=("Segoe UI", 9, "bold"), padding=(8, 3))
        style.configure("Section.TLabel", background=colors["surface"], foreground=colors["on_surface_variant"], font=("Segoe UI", 10, "bold"))
        style.configure("SidebarTitle.TLabel", background=colors["surface_container"], foreground=colors["on_surface_variant"], font=("Segoe UI", 10, "bold"))
        style.configure("CardTitle.TLabel", background=colors["surface_lowest"], foreground=colors["primary"], font=("Segoe UI", 17, "bold"))
        style.configure("CountChip.TLabel", background=colors["primary_container"], foreground="#ffffff", font=("Segoe UI", 10, "bold"), padding=(12, 6))
        style.configure("Status.TLabel", background=colors["surface"], foreground=colors["on_surface_variant"], font=("Segoe UI", 9))
        style.configure("Body.TLabel", background=colors["surface"], foreground=colors["on_surface"], font=("Segoe UI", 10))
        style.configure("BodyMuted.TLabel", background=colors["surface"], foreground=colors["on_surface_variant"], font=("Segoe UI", 9))
        style.configure("Panel.TLabel", background=colors["surface_lowest"], foreground=colors["on_surface"], font=("Segoe UI", 10))
        style.configure("CardSubtle.TLabel", background=colors["surface_lowest"], foreground=colors["on_surface_variant"], font=("Segoe UI", 9, "italic"))
        style.configure("ConsoleTitle.TLabel", background=colors["console_header"], foreground="#a0a0a0", font=("Segoe UI", 9, "bold"))
        style.configure("ConsoleStatus.TLabel", background=colors["console_header"], foreground="#ffffff", font=("Segoe UI", 9, "bold"))
        style.configure("Panel.TCheckbutton", background=colors["surface_container"], foreground=colors["on_surface"], font=("Segoe UI", 10))
        style.map("Panel.TCheckbutton", background=[("active", colors["surface_container"])], foreground=[("disabled", colors["outline_strong"])])

        style.configure("Primary.TButton", background=colors["primary"], foreground="#ffffff", font=("Segoe UI", 10, "bold"), padding=(12, 8))
        style.map("Primary.TButton", background=[("active", colors["primary_container"]), ("disabled", "#808080")])
        style.configure("Success.TButton", background=colors["success"], foreground="#ffffff", font=("Segoe UI", 10, "bold"), padding=(12, 8))
        style.map("Success.TButton", background=[("active", "#1f7a34"), ("disabled", "#9fb7a6")])
        style.configure("Ghost.TButton", background=colors["surface_lowest"], foreground=colors["primary"], font=("Segoe UI", 10, "bold"), padding=(10, 6), borderwidth=1, relief="solid")
        style.map("Ghost.TButton", background=[("active", colors["surface_low"])])
        style.configure("Action.TButton", background=colors["surface_lowest"], foreground=colors["on_surface"], font=("Segoe UI", 10, "bold"), padding=(10, 7))
        style.map("Action.TButton", background=[("active", colors["surface_low"])])
        style.configure("Danger.TButton", background=colors["surface_lowest"], foreground=colors["error"], font=("Segoe UI", 10, "bold"), padding=(10, 7), borderwidth=1, relief="solid")
        style.map("Danger.TButton", background=[("active", "#ffecec")])

        style.configure("TNotebook", background=colors["surface_lowest"], borderwidth=0)
        style.configure("TNotebook.Tab", background=colors["surface_low"], foreground=colors["on_surface_variant"], padding=(18, 10), font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", colors["surface_lowest"])], foreground=[("selected", colors["primary"])])

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        """Monta o painel lateral de parâmetros e ações auxiliares."""
        ttk.Label(parent, text="PARÂMETROS DE EXTRAÇÃO", style="SidebarTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 16))

        ttk.Label(parent, text="Mês de Referência", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 6))
        month_box = ttk.Combobox(parent, textvariable=self.month_var, values=MONTH_OPTIONS, state="readonly", width=22)
        month_box.grid(row=2, column=0, sticky="ew")

        ttk.Label(parent, text="Ano", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=(16, 6))
        year_entry = ttk.Entry(parent, textvariable=self.year_var)
        year_entry.grid(row=4, column=0, sticky="ew")

        ttk.Label(parent, text="Documentos Fiscais", style="SidebarTitle.TLabel").grid(row=5, column=0, sticky="w", pady=(20, 8))
        docs = ttk.Frame(parent, style="Sidebar.TFrame")
        docs.grid(row=6, column=0, sticky="ew")
        docs.columnconfigure(0, weight=1)

        ttk.Checkbutton(docs, text="NF-e (Nota Fiscal Eletrônica)", style="Panel.TCheckbutton", variable=self.nfe_doc_var, command=lambda: self._set_document_selection("NF-e", self.nfe_doc_var.get())).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Checkbutton(docs, text="NFC-e (Consumidor)", style="Panel.TCheckbutton", variable=self.nfce_doc_var, command=lambda: self._set_document_selection("NFC-e", self.nfce_doc_var.get())).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Checkbutton(docs, text="CT-e (Transporte)", style="Panel.TCheckbutton", variable=self.cte_doc_var, command=lambda: self._set_document_selection("CT-e", self.cte_doc_var.get())).grid(row=2, column=0, sticky="w", pady=4)

        ttk.Label(parent, text="Pasta de Saída", style="SidebarTitle.TLabel").grid(row=7, column=0, sticky="w", pady=(20, 6))
        output_row = ttk.Frame(parent, style="Sidebar.TFrame")
        output_row.grid(row=8, column=0, sticky="ew")
        output_row.columnconfigure(0, weight=1)
        output_entry = ttk.Entry(output_row, textvariable=self.output_dir_var)
        output_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(output_row, text="Browse", style="Action.TButton", command=self._browse_output_dir).grid(row=0, column=1, padx=(8, 0))

    def _build_center(self, parent: ttk.Frame) -> None:
        """Monta o conteúdo central com entrada, lista de CNPJs e botões de ação."""
        header = ttk.Frame(parent, style="Center.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)

        ttk.Label(header, text="Controle de empresas", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.loaded_count_var, style="CountChip.TLabel").grid(row=0, column=1, sticky="e")

        card = ttk.Frame(parent, style="Card.TFrame", padding=0)
        card.grid(row=1, column=0, sticky="nsew", pady=(18, 16))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        self.input_notebook = ttk.Notebook(card)
        self.input_notebook.grid(row=0, column=0, sticky="ew")
        import_tab = ttk.Frame(self.input_notebook, padding=18, style="Card.TFrame")
        manual_tab = ttk.Frame(self.input_notebook, padding=18, style="Card.TFrame")
        self.input_notebook.add(import_tab, text="Importar Planilha")
        self.input_notebook.add(manual_tab, text="Entrada Manual")

        import_tab.columnconfigure(0, weight=1)
        ttk.Label(import_tab, text="Selecione uma planilha XLSX para carregar as empresas.", style="Body.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        import_row = ttk.Frame(import_tab, style="Card.TFrame")
        import_row.grid(row=1, column=0, sticky="ew")
        import_row.columnconfigure(0, weight=1)
        self.import_path_entry = ttk.Entry(import_row, textvariable=self.spreadsheet_path_var)
        self.import_path_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(import_row, text="Abrir", style="Action.TButton", command=self._browse_spreadsheet).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(import_row, text="Carregar", style="Primary.TButton", command=self._reload_spreadsheet).grid(row=0, column=2, padx=(8, 0))

        manual_tab.columnconfigure(0, weight=1)
        ttk.Label(manual_tab, text="Cole um CNPJ por linha, ou vários separados por vírgula, ponto e vírgula ou espaço.", style="Body.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        manual_text_frame = ttk.Frame(manual_tab, style="Card.TFrame")
        manual_text_frame.grid(row=1, column=0, sticky="nsew")
        manual_text_frame.columnconfigure(0, weight=1)
        manual_text_frame.rowconfigure(0, weight=1)
        self.manual_cnpjs_text = tk.Text(manual_text_frame, height=8, wrap="word", bg="#ffffff", fg="#191c1d", insertbackground="#191c1d", relief="solid", bd=1)
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

        rows_card = ttk.Frame(parent, style="Card.TFrame", padding=14)
        rows_card.grid(row=2, column=0, sticky="nsew")
        rows_card.columnconfigure(0, weight=1)
        rows_card.rowconfigure(0, weight=1)
        self.rows_container = rows_card
        self.scrollable_rows = ScrollableFrame(rows_card)
        self.scrollable_rows.grid(row=0, column=0, sticky="nsew")

        footer_actions = ttk.Frame(parent, style="Center.TFrame")
        footer_actions.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        footer_actions.columnconfigure(0, weight=1)
        footer_actions.columnconfigure(1, weight=1)
        ttk.Button(footer_actions, text="Limpar Lista", style="Danger.TButton", command=self._clear_loaded_rows).grid(row=0, column=0, sticky="e", padx=(0, 8))
        ttk.Button(footer_actions, text="Validar empresas", style="Primary.TButton", command=self._validate_loaded_rows).grid(row=0, column=1, sticky="w", padx=(8, 0))

    def _build_console(self, parent: ttk.Frame) -> None:
        """Monta o painel escuro de fluxo e log da operação."""
        action_box = ttk.Frame(parent, style="Topbar.TFrame", padding=(20, 18))
        action_box.grid(row=0, column=0, sticky="ew")
        action_box.columnconfigure(0, weight=1)

        ttk.Label(action_box, text="FLUXO DE TRABALHO", style="SidebarTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 14))

        self.start_browser_button = ttk.Button(action_box, text="Iniciar Navegador", style="Primary.TButton", command=self._start_browser_if_needed)
        self.start_browser_button.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.execute_button = ttk.Button(action_box, text="Executar Extração", style="Success.TButton", command=self._run_selected, state="disabled")
        self.execute_button.grid(row=2, column=0, sticky="ew")

        console_box = ttk.Frame(parent, style="Console.TFrame")
        console_box.grid(row=1, column=0, sticky="nsew")
        console_box.columnconfigure(0, weight=1)
        console_box.rowconfigure(1, weight=1)

        console_header = ttk.Frame(console_box, style="ConsoleHeader.TFrame", padding=(16, 8))
        console_header.grid(row=0, column=0, sticky="ew")
        console_header.columnconfigure(0, weight=1)
        ttk.Label(console_header, text="LOG DE EXECUÇÃO", style="ConsoleTitle.TLabel").grid(row=0, column=0, sticky="w")

        self.log_text = tk.Text(console_box, wrap="word", height=20, state="disabled", bg="#1e1e1e", fg="#d4d4d4", insertbackground="#ffffff", relief="flat", bd=0, padx=14, pady=12, font=("Consolas", 10))
        log_scroll = ttk.Scrollbar(console_box, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.grid(row=1, column=0, sticky="nsew")
        log_scroll.grid(row=1, column=1, sticky="ns")

        console_footer = ttk.Frame(console_box, style="ConsoleFooter.TFrame", padding=(16, 10))
        console_footer.grid(row=2, column=0, sticky="ew")
        console_footer.columnconfigure(0, weight=1)
        ttk.Label(console_footer, text="Progresso da Operação", style="ConsoleTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(console_footer, orient="horizontal", mode="determinate", maximum=100, variable=self.progress_var)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
    def _build_ui(self) -> None:
        self._apply_theme()

        self.root.title("SIGA Automação")
        self.root.geometry("1440x900")
        self.root.minsize(1280, 840)
        self.root.configure(bg="#f8f9fa")

        main = ttk.Frame(self.root, padding=0, style="App.TFrame")
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        header = ttk.Frame(main, style="Topbar.TFrame", padding=(24, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)
        header.columnconfigure(2, weight=1)
        header.grid_columnconfigure(0, uniform="header")
        header.grid_columnconfigure(2, uniform="header")

        brand_box = ttk.Frame(header, style="Topbar.TFrame")
        brand_box.grid(row=0, column=0, sticky="w")
        title_box = ttk.Frame(header, style="Topbar.TFrame")
        title_box.grid(row=0, column=1, sticky="n")

        if self._logo_image is not None:
            ttk.Label(brand_box, image=self._logo_image).grid(row=0, column=0, sticky="w")
        ttk.Label(title_box, text="SIGA Automação", style="BrandTitle.TLabel", anchor="center").grid(row=0, column=1, sticky="n")

        header_actions = ttk.Frame(header, style="Topbar.TFrame")
        header_actions.grid(row=0, column=2, sticky="e")
        ttk.Button(header_actions, text="Ajuda", style="Ghost.TButton", command=self._show_help_dialog).grid(row=0, column=0)

        body = ttk.Frame(main, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=0, minsize=300)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=0, minsize=360)
        body.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(body, style="Sidebar.TFrame", padding=(20, 20))
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.columnconfigure(0, weight=1)

        center = ttk.Frame(body, style="Center.TFrame", padding=(24, 20))
        center.grid(row=0, column=1, sticky="nsew")
        center.columnconfigure(0, weight=1)
        center.rowconfigure(2, weight=1)

        right = ttk.Frame(body, style="ConsolePanel.TFrame", padding=0)
        right.grid(row=0, column=2, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._build_sidebar(sidebar)
        self._build_center(center)
        self._build_console(right)

        footer = ttk.Frame(main, style="App.TFrame", padding=(20, 0, 20, 14))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky="ew")

    def _browse_spreadsheet(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecione a planilha XLSX",
            filetypes=[("Planilhas Excel", "*.xlsx")],
        )
        if path:
            self.spreadsheet_path_var.set(path)
            self._reload_spreadsheet()

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

    def _show_help_dialog(self) -> None:
        """Exibe um passo a passo simples para orientar o uso da ferramenta."""
        help_text = (
            "Passo a passo para usar o SIGA Automação:\n\n"
            "1. Abra a aba 'Importar Planilha' e carregue um arquivo XLSX, ou use 'Entrada Manual' para colar CNPJs.\n"
            "2. Clique em 'Carregar CNPJs manuais' se estiver usando a entrada digitada.\n"
            "3. Escolha o mês, ano, documentos e a pasta de saída no painel lateral.\n"
            "4. Clique em 'Iniciar Navegador' e faça o login manual no SIGA.\n"
            "5. Quando o navegador estiver autenticado, clique em 'Executar Extração'.\n"
            "6. Acompanhe o andamento pelo painel de log à direita.\n\n"
            "Dicas:\n"
            "- Você pode marcar ou desmarcar NF-e, NFC-e e CT-e antes de executar.\n"
            "- Se uma empresa não for localizada, a ferramenta gera um arquivo .txt de aviso e segue para a próxima.\n"
            "- Os downloads ficam organizados por COD, EMPRESA, CNPJ, mês e documento."
        )
        messagebox.showinfo("Ajuda - SIGA Automação", help_text)

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
        """Atualiza a lista de CNPJs exibida mantendo o alinhamento da grade."""
        for child in self.scrollable_rows.inner.winfo_children():
            child.destroy()
        self.selection_rows.clear()
        self.loaded_count_var.set(f"Total carregadas: {len(spreadsheet_rows)}")

        table = ttk.Frame(self.scrollable_rows.inner)
        table.grid(row=0, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)

        ttk.Label(table, text="Marque as empresas e as abas que deseja processar.").grid(
            row=0, column=0, columnspan=5, sticky="w", pady=(0, 8)
        )
        ttk.Label(table, text=source_label, foreground="#555555").grid(
            row=1, column=0, columnspan=5, sticky="w", pady=(0, 6)
        )
        ttk.Separator(table, orient="horizontal").grid(
            row=2, column=0, columnspan=5, sticky="ew", pady=(0, 8)
        )

        header = self._create_selection_row(
            parent=table,
            row_index=3,
            cod_text="COD",
            empresa_text="EMPRESA",
            nfe_widget=self._create_header_cell,
            nfce_widget=self._create_header_cell,
            cte_widget=self._create_header_cell,
            is_header=True,
        )
        header.grid(row=3, column=0, sticky="ew", pady=(0, 4))

        for index, spreadsheet_row in enumerate(spreadsheet_rows, start=4):
            nfe_var = tk.BooleanVar(value=True)
            nfce_var = tk.BooleanVar(value=True)
            cte_var = tk.BooleanVar(value=True)

            row_frame = self._create_selection_row(
                parent=table,
                row_index=index,
                cod_text=spreadsheet_row.cod or "SEM-COD",
                empresa_text=spreadsheet_row.empresa or "SEM-EMPRESA",
                nfe_widget=lambda parent: ttk.Checkbutton(parent, variable=nfe_var),
                nfce_widget=lambda parent: ttk.Checkbutton(parent, variable=nfce_var),
                cte_widget=lambda parent: ttk.Checkbutton(parent, variable=cte_var),
                is_header=False,
            )
            row_frame.grid(row=index, column=0, sticky="ew", pady=1)

            self.selection_rows.append(
                RowSelectionWidgets(
                    spreadsheet_row=spreadsheet_row,
                    container=row_frame,
                    nfe_var=nfe_var,
                    nfce_var=nfce_var,
                    cte_var=cte_var,
                )
            )

        if not spreadsheet_rows:
            ttk.Label(table, text="Nenhuma empresa disponivel.", foreground="#aa0000").grid(
                row=4, column=0, columnspan=5, sticky="w", pady=(8, 0)
            )

    def _select_all_documents(self) -> None:
        for row in self.selection_rows:
            row.nfe_var.set(True)
            row.nfce_var.set(True)
            row.cte_var.set(True)

    def _clear_all_documents(self) -> None:
        for row in self.selection_rows:
            row.nfe_var.set(False)
            row.nfce_var.set(False)
            row.cte_var.set(False)

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

    def _start_browser_if_needed(self) -> None:
        if self._browser_started:
            self.status_var.set("O navegador já foi iniciado. Faça o login manual e clique em Executar.")
            return

        if not self.settings.connect_browser_url:
            self.settings.connect_browser_url = get_connect_browser_url(self.settings)
        try:
            launch_debug_browser(self.settings)
            self._browser_started = True
            if self.start_browser_button is not None:
                self.start_browser_button.state(["disabled"])
            if self.execute_button is not None:
                self.execute_button.state(["!disabled"])
            self.status_var.set("Navegador iniciado. Faça o login manualmente e, depois, clique em Executar.")
            self._append_log_line("Navegador iniciado. Aguardando login manual do usuário.")
        except Exception as exc:  # noqa: BLE001
            self.status_var.set(f"Nao foi possivel abrir o navegador automaticamente: {exc}")
            LOGGER.exception("Não foi possível abrir o navegador de depuração pela GUI")

    def _run_selected(self) -> None:
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
        self._append_log_line("Execução iniciada pela interface gráfica.")

        def worker() -> None:
            try:
                self._execute_selected(selected_rows, selected_tabs_by_row_number, month_reference, year_value)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falha na execução pela GUI")
                self._append_log_line(f"Falha na execução: {exc}")
                self.root.after(0, lambda exc=exc: messagebox.showerror("SIGA Automação", str(exc)))
            finally:
                self.root.after(0, lambda: self._set_controls_state("normal"))
                self.root.after(0, self._restore_browser_controls_state)
                self.root.after(0, lambda: self.progress_var.set(100))
                self.root.after(0, lambda: self.status_var.set("Execução finalizada."))

        self._worker_thread = threading.Thread(target=worker, daemon=True)
        self._worker_thread.start()

    def _execute_selected(
        self,
        selected_rows: list[SpreadsheetRow],
        selected_tabs_by_row_number: dict[int, list[str]],
        month_reference: str,
        year_value: str,
    ) -> None:
        extractor = SigaContributorExtractor(self.settings, allow_manual_login_prompt=False)
        flow = SigaLoginFlow(self.settings)

        with BrowserSession(self.settings) as context:
            authenticated_page = flow.confirm_authenticated_context(context, browser=context.browser)
            self._append_log_line(f"Login confirmado: {authenticated_page.title()}")
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
            self._append_log_line("")
            self._append_log_line("Processo concluído.")
            self._append_log_line(f"Contribuintes processados: {len(results)} de {len(selected_rows)}")
            self._append_log_line(f"Empresas nao encontradas: {not_found_count}")
            self._append_log_line(f"Detalhamentos baixados: {download_count}")
            if results:
                self._append_log_line(f"Pasta da última saída: {results[-1].taxpayer_folder}")

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
            if tabs:
                selected_rows.append(row.spreadsheet_row)
                tabs_by_row_number[row.spreadsheet_row.row_number] = tabs

        return selected_rows, tabs_by_row_number

    def _append_log_line(self, text: str) -> None:
        self.log_queue.put(text)

    def _drain_log_queue(self) -> None:
        drained = False
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            drained = True
            self._append_text(line)
        if drained:
            self.log_text.see("end")
        self.root.after(100, self._drain_log_queue)

    def _append_text(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{line}\n")
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
        digits = "".join(char for char in value if char.isdigit())
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
        is_header: bool,
    ) -> ttk.Frame:
        """Cria uma linha fixa da grade com células alinhadas e tamanhos previsíveis."""
        row_frame = ttk.Frame(parent)
        row_frame.columnconfigure(0, minsize=self._row_columns[0], weight=0)
        row_frame.columnconfigure(1, minsize=self._row_columns[1], weight=1)
        row_frame.columnconfigure(2, minsize=self._row_columns[2], weight=0)
        row_frame.columnconfigure(3, minsize=self._row_columns[3], weight=0)
        row_frame.columnconfigure(4, minsize=self._row_columns[4], weight=0)

        cells = []
        for column, width in enumerate(self._row_columns):
            cell = ttk.Frame(row_frame, width=width)
            cell.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))
            cell.grid_propagate(False)
            cells.append(cell)

        ttk.Label(
            cells[0],
            text=cod_text,
            anchor="center",
        ).pack(fill="x", padx=4, pady=2)
        ttk.Label(
            cells[1],
            text=empresa_text,
            anchor="w" if not is_header else "center",
        ).pack(fill="x", padx=4, pady=2)

        if is_header:
            for index, label in enumerate(("NF-e", "NFC-e", "CT-e"), start=2):
                ttk.Label(cells[index], text=label, anchor="center").pack(expand=True, fill="both")
        else:
            nfe_widget(cells[2]).pack(expand=True)
            nfce_widget(cells[3]).pack(expand=True)
            cte_widget(cells[4]).pack(expand=True)

        return row_frame

    def _create_header_cell(self, parent: ttk.Frame) -> ttk.Label:
        """Cria uma célula de cabeçalho neutra para manter a grade alinhada."""
        return ttk.Label(parent, text="")

    def _restore_browser_controls_state(self) -> None:
        """Mantém o botão de executar disponível após o navegador já estar iniciado."""
        if self.start_browser_button is not None:
            self.start_browser_button.state(["disabled"] if self._browser_started else ["!disabled"])
        if self.execute_button is not None:
            self.execute_button.state(["!disabled"] if self._browser_started else ["disabled"])

    def _on_close(self) -> None:
        logging.getLogger().removeHandler(self.log_handler)
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
