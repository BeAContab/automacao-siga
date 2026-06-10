from __future__ import annotations

"""Ponto de entrada dedicado da versao com interface grafica.

Este arquivo existe para gerar um executavel Windows voltado apenas para a GUI,
sem janela de console e sem depender do parametro `--gui` na execucao final.
"""

import sys

from src.main import main


def _force_gui_mode(argv: list[str]) -> list[str]:
    """Garante que a aplicacao inicie sempre no modo grafico."""
    filtered = [arg for arg in argv[1:] if arg not in {"--gui", "--skip-certificate-policy"}]
    # A GUI deve abrir rapidamente; a politica de certificado continua disponivel
    # no fluxo de terminal, mas nao deve bloquear a abertura da interface.
    return [argv[0], "--gui", "--skip-certificate-policy", *filtered]


if __name__ == "__main__":
    sys.argv = _force_gui_mode(sys.argv)
    raise SystemExit(main())
