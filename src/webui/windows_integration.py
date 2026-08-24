from __future__ import annotations

"""Integrações específicas do Windows, independentes do toolkit de interface.

Este módulo saiu quase intacto da GUI Tkinter: são chamadas de API do próprio Windows
(não do Tkinter nem do pywebview), então continuam valendo igual depois da migração.
"""

import logging
import sys

LOGGER = logging.getLogger(__name__)

APP_USER_MODEL_ID = "BarreiraAssociados.SigaAutomacao"


def set_app_user_model_id() -> None:
    """Registra um AppUserModelID próprio antes de a janela ser criada.

    Sem isso, ao rodar via `python main.py` (não empacotado como .exe), o Windows
    agrupa o processo sob o ícone do python.exe na barra de tarefas e no alt-tab,
    mesmo com o ícone da janela aplicado corretamente.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001
        LOGGER.debug("Não foi possível definir o AppUserModelID do Windows.", exc_info=True)
