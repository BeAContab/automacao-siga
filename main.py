from __future__ import annotations

import sys
from src.main import main


def _force_gui_mode(argv: list[str]) -> list[str]:
    """Garante que a aplicacao inicie sempre no modo grafico."""
    filtered = [arg for arg in argv[1:] if arg != "--skip-certificate-policy"]
    # A GUI deve abrir rapidamente; a politica de certificado continua disponivel,
    # mas nao deve bloquear a abertura da interface.
    return [argv[0], "--skip-certificate-policy", *filtered]


if __name__ == "__main__":
    sys.argv = _force_gui_mode(sys.argv)
    raise SystemExit(main())
