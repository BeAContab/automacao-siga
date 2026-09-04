from __future__ import annotations

"""Canal Python → JavaScript da interface.

Substitui os dois pares fila+polling da GUI Tkinter (`log_queue`/`_drain_log_queue` e
`nfe_results_queue`/`_drain_nfe_results_queue`), que existiam só porque o Tkinter
exige que toda atualização de widget aconteça na thread principal. No pywebview isso
não é necessário: `window.run_js` pode ser chamado de qualquer thread, então as
threads de trabalho empurram os eventos direto, sem intermediário.

Duas proteções, ambas obrigatórias na prática:

1. **Buffer de replay.** Sem uma fila, existe uma janela real entre abrir a janela e o
   JS registrar as funções globais do contrato. Mensagens emitidas nesse intervalo se
   perderiam silenciosamente. Enquanto o JS não confirma que está pronto
   (`Api.on_window_ready`), tudo fica num buffer e é despejado em lote depois.
2. **Guarda de fechamento.** Depois que a janela começa a fechar, qualquer chamada de
   `run_js` falha; como o canal de log é alimentado por um `logging.Handler`, uma
   exceção aqui poderia virar ruído no encerramento. Toda falha é engolida e só
   registrada em nível debug.
"""

import json
import logging
import threading
from typing import Any

LOGGER = logging.getLogger(__name__)

# Teto do buffer de replay: se algo der muito errado e o JS nunca ficar pronto, o
# buffer não pode crescer sem limite consumindo memória.
MAX_REPLAY = 500


class JsBridge:
    """Empurra chamadas para as funções globais registradas em `web/src/js/main.js`."""

    def __init__(self) -> None:
        self._window: Any = None
        self._ready = False
        self._closing = False
        self._lock = threading.Lock()
        self._replay: list[str] = []

    # ------------------------------------------------------------------ ciclo de vida

    def attach(self, window: Any) -> None:
        """Associa a janela recém-criada; ainda não libera o envio direto."""
        with self._lock:
            self._window = window

    def mark_ready(self) -> None:
        """Chamado quando o JS confirma que o DOM e o contrato estão prontos."""
        with self._lock:
            if self._ready:
                return
            self._ready = True
            pending, self._replay = self._replay, []
        for script in pending:
            self._run(script)

    def mark_closing(self) -> None:
        """Silencia o canal: a janela está sendo destruída."""
        with self._lock:
            self._closing = True

    @property
    def ready(self) -> bool:
        return self._ready

    # ---------------------------------------------------------------------- envio

    def dispatch(self, function_name: str, *args: Any) -> None:
        """Chama `window.<function_name>(...)` no JS, de qualquer thread."""
        # ensure_ascii=True de propósito: o script é injetado como código JS literal, e
        # escapar tudo para \uXXXX evita que caracteres como U+2028/U+2029 (válidos em
        # JSON, mas quebra de linha em JS) gerem script inválido.
        payload = ", ".join(json.dumps(arg, ensure_ascii=True, default=str) for arg in args)
        script = f"window.{function_name}({payload});"

        with self._lock:
            if self._closing:
                return
            if not self._ready:
                if len(self._replay) < MAX_REPLAY:
                    self._replay.append(script)
                return

        self._run(script)

    def _run(self, script: str) -> None:
        window = self._window
        if window is None:
            return
        try:
            # run_js (e não evaluate_js): não precisamos do retorno, e evaluate_js
            # bloquearia a thread de trabalho esperando o round-trip do JS.
            window.run_js(script)
        except Exception:  # noqa: BLE001
            LOGGER.debug("Falha ao despachar evento para a interface.", exc_info=True)

    # ------------------------------------------------------- atalhos do contrato

    def append_log(self, text: str, level: str) -> None:
        self.dispatch("sigaAppendLog", {"text": text, "level": level})

    def upsert_nfe_result(self, result: dict[str, Any]) -> None:
        self.dispatch("sigaUpsertNfeResult", result)

    def browser_started(self) -> None:
        self.dispatch("sigaOnBrowserStarted")

    def browser_failed(self, message: str) -> None:
        self.dispatch("sigaOnBrowserFailed", {"message": message})

    def execution_finished(self, status: str) -> None:
        self.dispatch("sigaOnExecutionFinished", {"status": status})

    def nfce_companies_loaded(self, rows: list[dict]) -> None:
        self.dispatch("sigaOnNfceCompaniesLoaded", {"rows": rows})

    def set_progress(self, percent: float) -> None:
        self.dispatch("sigaSetProgress", percent)

    def set_status(self, text: str) -> None:
        self.dispatch("sigaSetStatus", text)

    def show_message(self, message: str, level: str = "error") -> None:
        self.dispatch("sigaShowMessage", {"message": message, "level": level})


class BridgeLogHandler(logging.Handler):
    """Encaminha registros de log para o console da interface.

    Equivale ao `QueueLogHandler` da GUI Tkinter, mas escreve direto no canal em vez
    de numa fila. São dois handlers com este mesmo tipo: um no logger de narração
    (mensagens em português para o operador) e outro no logger raiz, a partir de
    WARNING, como rede de segurança para nada técnico ficar invisível.
    """

    def __init__(self, bridge: JsBridge, formatter_fn) -> None:
        super().__init__()
        self._bridge = bridge
        self._formatter_fn = formatter_fn

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text, level = self._formatter_fn(record)
            self._bridge.append_log(text, level)
        except Exception:  # noqa: BLE001
            # Nunca deixar o canal de log derrubar quem está logando.
            pass
