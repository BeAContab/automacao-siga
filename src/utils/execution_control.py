from __future__ import annotations

"""Controle cooperativo de pausar/continuar/encerrar, compartilhado pelos 3 modos de extração.

Cada modo (SIGA, NFC-e, NF-e) roda seu lote num laço síncrono, numa única thread de
trabalho por vez (`src/webui/api.py`, `_start_worker`). Pausar/encerrar é cooperativo:
o laço em execução precisa checar periodicamente se deve parar — não há como
interromper uma chamada Selenium/undetected_chromedriver já em andamento a partir de
fora dela. `wait_if_paused` é o ponto de checagem único, chamado nos pontos seguros de
cada laço (início de cada empresa/chave/planilha processada).
"""

import threading
import time


def wait_if_paused(
    cancel_event: threading.Event | None,
    pause_event: threading.Event | None,
    poll_interval: float = 0.5,
) -> bool:
    """Bloqueia enquanto `pause_event` estiver ativo, respeitando `cancel_event` o tempo todo.

    Devolve `False` quando o chamador deve parar (cancelamento solicitado, antes ou durante
    uma pausa); `True` para seguir em frente normalmente. Ambos os parâmetros podem ser
    `None` (uso fora do fluxo da GUI, ex. testes ou scripts avulsos) — nesse caso sempre
    devolve `True` sem bloquear.
    """
    while pause_event is not None and pause_event.is_set():
        if cancel_event is not None and cancel_event.is_set():
            return False
        time.sleep(poll_interval)
    return not (cancel_event is not None and cancel_event.is_set())
