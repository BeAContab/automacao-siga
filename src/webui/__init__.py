from __future__ import annotations

"""Camada de interface do SIGA Automação, renderizada por pywebview.

Substitui a antiga GUI Tkinter (`src/gui.py`): o backend de extração
(`SigaContributorExtractor`, `NfceBatchExtractor`, `MeudanfeBatchExtractor`,
`SigaLoginFlow`, `BrowserSession`) permanece exatamente o mesmo — só a camada de
apresentação passou a ser HTML/CSS/JS servido de `src/web_dist/`, com o Python
expondo métodos ao JavaScript via `js_api` (ver `api.py`) e empurrando eventos de
volta via `window.run_js` (ver `bridge.py`).
"""

from src.webui.app import launch_gui

__all__ = ["launch_gui"]
