from __future__ import annotations

"""Criação da janela pywebview e ciclo de vida da aplicação.

Equivale ao construtor + `run()` + `_on_close` da antiga `SigaAutomationGUI`: configura
logging, monta a ponte com o JavaScript, cria a janela e trata o fechamento gracioso
(encerrando o navegador de automação e esperando a thread de trabalho sair).
"""

import logging
import sys
import time
from pathlib import Path

import webview

from src.config import Settings
from src.utils.browser import shutdown_debug_browser
from src.utils.logging_setup import configure_logging
from src.utils.narration import (
    NARRATION_LOGGER_NAME,
    configure_narration,
    narrate_warning,
)
from src.webui import assets
from src.webui.api import Api
from src.webui.bridge import BridgeLogHandler, JsBridge
from src.webui.windows_integration import set_app_user_model_id

LOGGER = logging.getLogger(__name__)

WINDOW_TITLE = "SIGA Automação"
WINDOW_SIZE = (1440, 900)
WINDOW_MIN_SIZE = (1280, 780)

# Tempo máximo de espera pela thread de trabalho ao fechar a janela, para o app não
# ficar preso indefinidamente se a automação travar num ponto sem timeout próprio.
WORKER_SHUTDOWN_TIMEOUT = 10


def _level_to_tone(record: logging.LogRecord) -> str:
    """Escolhe a cor da linha no console a partir do tom explícito ou do nível."""
    tone = getattr(record, "tone", None)
    if tone == "success":
        return "success"
    if record.levelno >= logging.ERROR:
        return "error"
    if record.levelno >= logging.WARNING:
        return "warning"
    return "info"


def _narration_line(record: logging.LogRecord) -> tuple[str, str]:
    """Linha do canal de narração: só horário curto + mensagem, sem jargão técnico."""
    hora = time.strftime("%H:%M:%S", time.localtime(record.created))
    return f"{hora}  {record.getMessage()}", _level_to_tone(record)


def _technical_bridge_line(record: logging.LogRecord) -> tuple[str, str]:
    """Linha da rede de segurança técnica (logger raiz, WARNING+).

    Cobre avisos/erros ainda não narrados explicitamente, para que nada fique invisível
    ao operador — mas aponta para o log técnico em vez de despejar o texto interno.
    """
    hora = time.strftime("%H:%M:%S", time.localtime(record.created))
    text = f"{hora}  {record.getMessage()}"
    if record.levelno >= logging.ERROR:
        text += " (mais detalhes em logs\\errors.log)"
    return text, _level_to_tone(record)


class SigaWebApp:
    """Monta a janela, conecta os canais de log e cuida do encerramento."""

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
            # console=False: a janela não tem um terminal útil para o operador ler — a
            # narração chega pelo console da própria interface, via os handlers abaixo.
            configure_narration(self.settings.log_dir, console=False)

        self.bridge = JsBridge()
        self.api = Api(
            self.settings,
            self.bridge,
            initial_spreadsheet=initial_spreadsheet,
            initial_month=initial_month,
            initial_year=initial_year,
        )

        # Canal amigável: o que o operador realmente deve acompanhar.
        self.narration_handler = BridgeLogHandler(self.bridge, _narration_line)
        self.narration_handler.setLevel(logging.INFO)
        # Rede de segurança: avisos/erros técnicos não narrados não ficam invisíveis,
        # mas só aparecem a partir de WARNING (o INFO técnico fica só em run.log).
        self.error_bridge_handler = BridgeLogHandler(self.bridge, _technical_bridge_line)
        self.error_bridge_handler.setLevel(logging.WARNING)

        self._closing = False
        self._close_dialog_open = False
        self.window: webview.Window | None = None

    # ------------------------------------------------------------------ inicialização

    def create_window(self) -> webview.Window:
        set_app_user_model_id()

        index = assets.index_html()
        if not index.exists():
            raise FileNotFoundError(
                "Interface não encontrada em "
                f"{index}.\nRode `npm install && npm run build:css` dentro de web/ "
                "para gerar os arquivos estáticos."
            )

        self.window = webview.create_window(
            WINDOW_TITLE,
            url=str(index),
            js_api=self.api,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=WINDOW_MIN_SIZE,
            background_color="#F4F6F7",
            # A seleção de texto é controlada pelo CSS, que é mais preciso: bloqueada no
            # "chrome" da janela, liberada nos campos e no console (onde copiar ajuda).
            text_select=True,
        )
        self.api._attach_window(self.window)
        self.bridge.attach(self.window)
        self.window.events.closing += self._on_closing

        logging.getLogger(NARRATION_LOGGER_NAME).addHandler(self.narration_handler)
        logging.getLogger().addHandler(self.error_bridge_handler)
        return self.window

    def run(self) -> int:
        self.create_window()
        try:
            # debug=True habilita o DevTools do WebView2 (F12) — útil só em desenvolvimento.
            webview.start(debug=bool(self.settings.webui_debug), icon=self._icon_path())
        finally:
            self._detach_log_handlers()
        return 0

    def _icon_path(self) -> str | None:
        icon = assets.app_icon()
        return str(icon) if icon.exists() else None

    # ------------------------------------------------------------------ encerramento

    def _on_closing(self) -> bool | None:
        """Confirma e encerra graciosamente antes de a janela ser destruída.

        Devolver `False` cancela o fechamento (o `Event` de `closing` do pywebview é
        bloqueante e trata `False` como veto). É o equivalente do `_on_close` da versão
        Tkinter, que usava `messagebox.askyesno` + `shutdown_debug_browser` + `join`.
        """
        if self._closing:
            return None

        # Reentrância: com o diálogo aberto, o usuário pode clicar no X de novo ou dar
        # Alt+F4; sem esta guarda, uma segunda confirmação empilharia sobre a primeira.
        if self._close_dialog_open:
            return False

        if self.api._worker_running:
            self._close_dialog_open = True
            try:
                confirmed = self.window.create_confirmation_dialog(
                    WINDOW_TITLE,
                    "Uma execução está em andamento.\n\nFechar agora vai interrompê-la. Deseja sair mesmo assim?",
                )
            except Exception:  # noqa: BLE001
                # Se o diálogo nativo falhar por qualquer motivo, não prender o usuário
                # com uma janela que não fecha: registra e segue com o encerramento.
                LOGGER.exception("Falha ao abrir o diálogo de confirmação de fechamento")
                confirmed = True
            finally:
                self._close_dialog_open = False

            if not confirmed:
                return False

        self._closing = True
        self.bridge.mark_closing()

        if self.api._worker_running:
            narrate_warning("Encerrando a execução a pedido do usuário...")
            # Encerrar o navegador da automação faz as chamadas do Selenium falharem
            # rápido, permitindo que a thread de trabalho saia do bloco de sessão em vez
            # de ficar presa esperando um elemento que nunca vem.
            try:
                shutdown_debug_browser(self.settings)
            except Exception:  # noqa: BLE001
                LOGGER.exception("Falha ao encerrar o navegador durante o fechamento da interface")
            self.api._join_worker(timeout=WORKER_SHUTDOWN_TIMEOUT)

        self._detach_log_handlers()
        return None

    def _detach_log_handlers(self) -> None:
        for logger, handler in (
            (logging.getLogger(NARRATION_LOGGER_NAME), self.narration_handler),
            (logging.getLogger(), self.error_bridge_handler),
        ):
            try:
                logger.removeHandler(handler)
            except Exception:  # noqa: BLE001
                LOGGER.debug("Falha ao remover handler de log da interface.", exc_info=True)


def launch_gui(
    settings: Settings,
    initial_spreadsheet: str | None = None,
    initial_month: str | None = None,
    initial_year: str | None = None,
) -> int:
    """Abre a interface e devolve um código de saída compatível com o `main`."""
    app = SigaWebApp(
        settings,
        initial_spreadsheet=initial_spreadsheet,
        initial_month=initial_month,
        initial_year=initial_year,
    )
    try:
        return app.run()
    except Exception as exc:  # noqa: BLE001
        # O erro mais provável aqui é a ausência do WebView2 Runtime na máquina —
        # nesse caso a mensagem crua do pywebview não ajuda o operador em nada.
        LOGGER.exception("Falha ao abrir a interface gráfica")
        _report_startup_failure(exc)
        return 1


def _report_startup_failure(exc: Exception) -> None:
    """Explica em português o que fazer quando a janela não abre."""
    message = (
        "Não foi possível abrir a interface do SIGA Automação.\n\n"
        f"Detalhe técnico: {exc}\n\n"
        "Causa mais comum: o componente 'Microsoft Edge WebView2 Runtime' não está "
        "instalado nesta máquina. Ele acompanha o Windows 11 e o Windows 10 atualizado; "
        "em máquinas mais antigas pode ser necessário instalá-lo pelo site da Microsoft."
    )
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "SIGA Automação", 0x10)
        except Exception:  # noqa: BLE001
            LOGGER.debug("Não foi possível exibir a caixa de erro nativa.", exc_info=True)
