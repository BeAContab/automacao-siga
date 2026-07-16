# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('images/logo/logo.png', 'images/logo'),
        ('images/icons/siga-automacao.ico', 'images/icons'),
        ('images/icons/siga-automacao-32x32.png', 'images/icons'),
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
    icon='images/icons/siga-automacao.ico',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
