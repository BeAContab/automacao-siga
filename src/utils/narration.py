from __future__ import annotations

"""Canal de narração amigável das ações da automação para o usuário final.

Esta camada é deliberadamente separada do logging técnico configurado em
`logging_setup.py`: aquele existe para diagnosticar a automação (XPath,
seletores, estado interno), este existe para o operador (equipe contábil,
não técnica) acompanhar em português simples o que está acontecendo —
"Digitando o CNPJ...", "Clicando em...", "Baixando...". As duas camadas
nunca se misturam (o logger de narração não propaga para o root logger).
"""

import logging
import sys
from pathlib import Path


NARRATION_LOGGER_NAME = "siga.narracao"
_narration_logger = logging.getLogger(NARRATION_LOGGER_NAME)
_narration_logger.propagate = False


def configure_narration(log_dir: Path, *, console: bool = True) -> None:
    """Prepara o canal de narração: arquivo `atividades.log` e, opcionalmente, console.

    Idempotente — pode ser chamada mais de uma vez (ex.: main() e GUI standalone)
    sem duplicar handlers, seguindo o mesmo padrão de `configure_logging`.
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    _narration_logger.handlers.clear()
    _narration_logger.setLevel(logging.INFO)

    # Sem "%(name)s": nem o nome do módulo Python é jargão que o operador precisa ver.
    file_formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(log_dir / "atividades.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(file_formatter)
    _narration_logger.addHandler(file_handler)

    if console:
        # Sem prefixo algum: no terminal, a narração deve ler como texto corrido.
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(logging.Formatter("%(message)s"))
        _narration_logger.addHandler(stream_handler)


def narrate(message: str, *args: object) -> None:
    """Narra uma ação em andamento (tom neutro)."""
    _narration_logger.info(message, *args)


def narrate_success(message: str, *args: object) -> None:
    """Narra a conclusão bem-sucedida de uma ação (tom positivo)."""
    _narration_logger.info(message, *args, extra={"tone": "success"})


def narrate_warning(message: str, *args: object) -> None:
    """Narra um alerta que o operador deveria notar, mas que não interrompe o lote."""
    _narration_logger.warning(message, *args)


def narrate_error(message: str, *args: object) -> None:
    """Narra uma falha que o operador precisa saber que aconteceu."""
    _narration_logger.error(message, *args)
