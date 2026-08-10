# -*- mode: python ; coding: utf-8 -*-

import os

# O spec foi movido para pré-lixo/, um nível abaixo da raiz do projeto onde
# main.py e images/ realmente estão; PyInstaller resolve caminhos relativos
# em relação a SPECPATH (a pasta do .spec), entao subimos um nível aqui.
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'main.py')],
    pathex=[],
    binaries=[],
    datas=[
        (os.path.join(PROJECT_ROOT, 'images', 'logo', 'logo.png'), 'images/logo'),
        (os.path.join(PROJECT_ROOT, 'images', 'icons', 'siga-automacao.ico'), 'images/icons'),
        (os.path.join(PROJECT_ROOT, 'images', 'icons', 'siga-automacao-32x32.png'), 'images/icons'),
    ],
    hiddenimports=[
        'selenium.webdriver.common.action_chains',
        'selenium.webdriver.common.actions.action_builder',
        'selenium.webdriver.common.actions.pointer_input',
        'selenium.webdriver.common.actions.key_input',
        'selenium.webdriver.chrome.options',
        'selenium.webdriver.chrome.webdriver',
        'selenium.webdriver.edge.options',
        'selenium.webdriver.edge.webdriver',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='siga-automacao-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=os.path.join(PROJECT_ROOT, 'images', 'icons', 'siga-automacao.ico'),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
