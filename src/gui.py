from __future__ import annotations

"""Interface gráfica para seleção de CNPJs e abas fiscais do SIGA."""

from dataclasses import dataclass
from pathlib import Path
import logging
import queue
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.auth.siga_login import SigaLoginFlow
from src.config import Settings
from src.extraction.siga_extractor import SigaContributorExtractor
from src.extraction.spreadsheet import SpreadsheetRow, load_cnpjs_from_xlsx
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
        self.canvas = tk.Canvas(self, highlightthickness=0)
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
        current_month = MONTH_OPTIONS[max(0, min(11, time.localtime().tm_mon - 1))]
        self.month_var = tk.StringVar(value=initial_month or current_month)
        self.year_var = tk.StringVar(value=initial_year or str(time.localtime().tm_year))
        self.status_var = tk.StringVar(value="Clique em 'Iniciar navegador' para abrir o SIGA e fazer o login manual.")

        self.selection_rows: list[RowSelectionWidgets] = []
        self._worker_thread: threading.Thread | None = None
        self._stop_requested = False
        self._row_columns = (260, 96, 96, 96)
        self._browser_started = False
        self.start_browser_button: ttk.Button | None = None
        self.execute_button: ttk.Button | None = None

        self._build_ui()
        self._load_spreadsheet_rows(Path(self.spreadsheet_path_var.get()))
        self.root.after(100, self._drain_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self) -> None:
        """Executa o loop principal da interface."""
        self.root.mainloop()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        header = ttk.LabelFrame(main, text="Configurações da execução", padding=10)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        header.columnconfigure(3, weight=1)

        ttk.Label(header, text="Planilha XLSX").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(header, textvariable=self.spreadsheet_path_var)
        entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(header, text="Abrir", command=self._browse_spreadsheet).grid(row=0, column=2, sticky="ew")
        ttk.Button(header, text="Carregar", command=self._reload_spreadsheet).grid(row=0, column=3, sticky="ew", padx=(8, 0))

        ttk.Label(header, text="Pasta de saída").grid(row=1, column=0, sticky="w", pady=(10, 0))
        output_entry = ttk.Entry(header, textvariable=self.output_dir_var)
        output_entry.grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(10, 0))
        ttk.Button(header, text="Escolher", command=self._browse_output_dir).grid(row=1, column=2, sticky="ew", pady=(10, 0))
        ttk.Button(header, text="Padrão", command=self._reset_output_dir).grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=(10, 0))

        ttk.Label(header, text="Mês").grid(row=2, column=0, sticky="w", pady=(10, 0))
        month_box = ttk.Combobox(header, textvariable=self.month_var, values=MONTH_OPTIONS, state="readonly", width=18)
        month_box.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        ttk.Label(header, text="Ano").grid(row=2, column=2, sticky="e", pady=(10, 0))
        year_entry = ttk.Entry(header, textvariable=self.year_var, width=10)
        year_entry.grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(10, 0))

        action_bar = ttk.Frame(main)
        action_bar.grid(row=1, column=0, sticky="ew", pady=(12, 8))
        action_bar.columnconfigure(0, weight=1)
        action_bar.columnconfigure(1, weight=1)

        document_actions = ttk.LabelFrame(action_bar, text="Ações por documento", padding=8)
        document_actions.grid(row=0, column=0, sticky="ew")
        for column in range(3):
            document_actions.columnconfigure(column, weight=1)

        self.nfe_select_button = ttk.Button(document_actions, text="Marcar NF-e", command=lambda: self._set_document_selection("NF-e", True))
        self.nfe_select_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.nfce_select_button = ttk.Button(document_actions, text="Marcar NFC-e", command=lambda: self._set_document_selection("NFC-e", True))
        self.nfce_select_button.grid(row=0, column=1, sticky="ew", padx=6)
        self.cte_select_button = ttk.Button(document_actions, text="Marcar CT-e", command=lambda: self._set_document_selection("CT-e", True))
        self.cte_select_button.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        self.nfe_clear_button = ttk.Button(document_actions, text="Desmarcar NF-e", command=lambda: self._set_document_selection("NF-e", False))
        self.nfe_clear_button.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(6, 0))
        self.nfce_clear_button = ttk.Button(document_actions, text="Desmarcar NFC-e", command=lambda: self._set_document_selection("NFC-e", False))
        self.nfce_clear_button.grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        self.cte_clear_button = ttk.Button(document_actions, text="Desmarcar CT-e", command=lambda: self._set_document_selection("CT-e", False))
        self.cte_clear_button.grid(row=1, column=2, sticky="ew", padx=(6, 0), pady=(6, 0))

        execution_actions = ttk.LabelFrame(action_bar, text="Execução", padding=8)
        execution_actions.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        execution_actions.columnconfigure(0, weight=1)
        execution_actions.columnconfigure(1, weight=1)

        self.start_browser_button = ttk.Button(execution_actions, text="Iniciar navegador", command=self._start_browser_if_needed)
        self.start_browser_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.execute_button = ttk.Button(execution_actions, text="Executar", command=self._run_selected, state="disabled")
        self.execute_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        content = ttk.Panedwindow(main, orient=tk.HORIZONTAL)
        content.grid(row=2, column=0, sticky="nsew")

        left = ttk.Labelframe(content, text="CNPJs do anexo", padding=8)
        right = ttk.Labelframe(content, text="Log da execução", padding=8)
        content.add(left, weight=3)
        content.add(right, weight=2)

        self.scrollable_rows = ScrollableFrame(left)
        self.scrollable_rows.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self.log_text = tk.Text(right, wrap="word", height=20, state="disabled")
        log_scroll = ttk.Scrollbar(right, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll.grid(row=0, column=1, sticky="ns")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        status = ttk.Label(main, textvariable=self.status_var, anchor="w")
        status.grid(row=3, column=0, sticky="ew", pady=(8, 0))

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
        for child in self.scrollable_rows.inner.winfo_children():
            child.destroy()
        self.selection_rows.clear()

        if not path.exists():
            self.status_var.set(f"Planilha nao encontrada: {path}")
            return

        try:
            spreadsheet_rows = load_cnpjs_from_xlsx(path)
        except Exception as exc:  # noqa: BLE001
            self.status_var.set(f"Falha ao carregar planilha: {exc}")
            messagebox.showerror("SIGA Automação", f"Falha ao carregar planilha:\n{exc}")
            return

        table = ttk.Frame(self.scrollable_rows.inner)
        table.grid(row=0, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)

        ttk.Label(table, text="Marque os CNPJs e as abas que deseja processar.").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )
        ttk.Separator(table, orient="horizontal").grid(
            row=1, column=0, columnspan=4, sticky="ew", pady=(0, 8)
        )

        header = self._create_selection_row(
            parent=table,
            row_index=2,
            cnpj_text="CNPJ",
            nfe_widget=self._create_header_cell,
            nfce_widget=self._create_header_cell,
            cte_widget=self._create_header_cell,
            is_header=True,
        )
        header.grid(row=2, column=0, sticky="ew", pady=(0, 4))

        for index, spreadsheet_row in enumerate(spreadsheet_rows, start=3):
            nfe_var = tk.BooleanVar(value=True)
            nfce_var = tk.BooleanVar(value=True)
            cte_var = tk.BooleanVar(value=True)

            row_frame = self._create_selection_row(
                parent=table,
                row_index=index,
                cnpj_text=self._format_cnpj(spreadsheet_row.cnpj),
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

        self.status_var.set(f"Planilha carregada com {len(spreadsheet_rows)} CNPJ(s).")

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
            self._append_log_line("")
            self._append_log_line("Processo concluído.")
            self._append_log_line(f"Contribuintes processados: {len(results)} de {len(selected_rows)}")
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
        cnpj_text: str,
        nfe_widget,
        nfce_widget,
        cte_widget,
        is_header: bool,
    ) -> ttk.Frame:
        """Cria uma linha fixa da grade com células alinhadas e tamanhos previsíveis."""
        row_frame = ttk.Frame(parent)
        row_frame.columnconfigure(0, minsize=self._row_columns[0], weight=1)
        row_frame.columnconfigure(1, minsize=self._row_columns[1], weight=0)
        row_frame.columnconfigure(2, minsize=self._row_columns[2], weight=0)
        row_frame.columnconfigure(3, minsize=self._row_columns[3], weight=0)

        cells = []
        for column, width in enumerate(self._row_columns):
            cell = ttk.Frame(row_frame, width=width)
            cell.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))
            cell.grid_propagate(False)
            cells.append(cell)

        ttk.Label(
            cells[0],
            text=cnpj_text,
            anchor="w" if not is_header else "center",
        ).pack(fill="x", padx=4, pady=2)

        if is_header:
            for index, label in enumerate(("NF-e", "NFC-e", "CT-e"), start=1):
                ttk.Label(cells[index], text=label, anchor="center").pack(expand=True, fill="both")
        else:
            nfe_widget(cells[1]).pack(expand=True)
            nfce_widget(cells[2]).pack(expand=True)
            cte_widget(cells[3]).pack(expand=True)

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
