# -*- mode: python ; coding: utf-8 -*-
"""Empacotamento do SIGA Automação com PyInstaller.

IMPORTANTE: rode o build da interface ANTES deste spec, senão o .exe sai sem CSS/JS:

    python web/build.py
    pyinstaller siga-automacao.spec

O que precisa ir junto do executável:

- `src/web_dist/`: a interface compilada (HTML, CSS do Tailwind já minificado, JS e as
  fontes vendorizadas). É lida em runtime por `src/webui/assets.py`, que resolve o
  caminho a partir de `sys._MEIPASS` quando empacotado. Sem isto a janela abre em
  branco — ou nem abre, porque `create_window` valida a existência do index.html.
- `images/`: ícone da janela e logo exibida no cabeçalho.

Node **não** é necessário na máquina do usuário: só serve para gerar `src/web_dist/`.

Requisito de runtime: o **Microsoft Edge WebView2 Runtime**, usado pelo pywebview para
renderizar a interface. Ele acompanha o Windows 11 e o Windows 10 atualizado; em
máquinas antigas pode precisar ser instalado (o app detecta a ausência e mostra uma
mensagem explicativa em vez de falhar de forma críptica — ver `src/webui/app.py`).
"""

from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("src/web_dist", "src/web_dist"),
    ("images", "images"),
]

# O pywebview escolhe o backend de renderização em tempo de execução, por import
# dinâmico — o PyInstaller não enxerga isso na análise estática do código.
hiddenimports = collect_submodules("webview.platforms")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],  # a interface antiga saiu; não empacotar o Tcl/Tk por engano
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="siga-automacao",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # aplicativo de janela: nada de console preto atrás da interface
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="images/icons/siga-automacao.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="siga-automacao",
)
