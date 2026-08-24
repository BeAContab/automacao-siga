from __future__ import annotations

"""Resolução de caminhos dos arquivos estáticos da interface.

Precisa funcionar nos dois modos de execução: rodando do código-fonte
(`python main.py`) e a partir do executável empacotado pelo PyInstaller, que extrai
os dados para uma pasta temporária apontada por `sys._MEIPASS`. É o mesmo problema
que `_resolve_asset_path` resolvia na GUI Tkinter — a diferença é que agora também
precisa localizar o bundle web (`src/web_dist/`), e não só os ícones.
"""

import sys
from pathlib import Path


def base_dir() -> Path:
    """Raiz de onde os assets são lidos (fonte ou bundle do PyInstaller)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def resolve_asset(*parts: str) -> Path:
    """Resolve um caminho relativo à raiz do projeto/bundle."""
    return base_dir().joinpath(*parts)


def web_dist_dir() -> Path:
    """Pasta com o `index.html`, o CSS compilado e o JS da interface."""
    return resolve_asset("src", "web_dist")


def index_html() -> Path:
    """Arquivo carregado na janela do pywebview."""
    return web_dist_dir() / "index.html"


def app_icon() -> Path:
    """Ícone `.ico` usado pela janela e pela barra de tarefas do Windows."""
    return resolve_asset("images", "icons", "siga-automacao.ico")
