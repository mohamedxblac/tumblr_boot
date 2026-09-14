# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

ROOT_DIR = os.path.abspath(SPECPATH)
BOT_DIR = os.path.join(ROOT_DIR, 'tumblr_boot')

# Collect the direct WebSocket client used by Firefox WebDriver BiDi.
datas_ws, binaries_ws, hiddenimports_ws = collect_all('websockets')

all_datas = datas_ws
icon_file = os.path.join(ROOT_DIR, 'assets', 'app_icon.ico')
if os.path.exists(icon_file):
    all_datas.append((icon_file, 'assets'))

uia_file = os.path.join(ROOT_DIR, 'vendor', 'UIA-v2', 'Lib', 'UIA.ahk')
uia_license = os.path.join(ROOT_DIR, 'vendor', 'UIA-v2', 'LICENSE')
if not os.path.isfile(uia_file):
    raise FileNotFoundError('The vendored UIA-v2 library is required for native Firefox login.')
all_datas.append((uia_file, os.path.join('vendor', 'UIA-v2', 'Lib')))
if os.path.isfile(uia_license):
    all_datas.append((uia_license, os.path.join('vendor', 'UIA-v2')))

all_binaries = binaries_ws
ahk_candidates = [
    os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'AutoHotkey', 'v2', 'AutoHotkey64.exe'),
    os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'AutoHotkey', 'v2', 'AutoHotkey32.exe'),
]
ahk_file = next((path for path in ahk_candidates if os.path.isfile(path)), None)
if not ahk_file:
    raise FileNotFoundError('AutoHotkey v2 is required to build the standalone executable.')
all_binaries.append((ahk_file, 'tools'))

all_hiddenimports = (
    hiddenimports_ws
    + [
        'sqlite3',
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'json',
        'multiprocessing',
        'threading',
        'queue',
        'shutil',
        'tempfile',
        'logging',
        'urllib.request',
        'setuptools',
        'setuptools._distutils',
        'distutils',
        'distutils.version',
        'config',
        'config.settings',
        'config.fingerprints',
        'core',
        'core.auth',
        'core.bidi',
        'core.browser',
        'core.compat',
        'core.contact_history',
        'core.engine',
        'core.messenger',
        'core.persistence',
        'core.scraper',
        'gui',
        'gui.accounts_tab',
        'gui.app',
        'gui.clipboard',
        'gui.messages_tab',
        'gui.runner_tab',
        'gui.settings_tab',
        'gui.stats_tab',
        'utils',
        'utils.helpers',
        'utils.logger',
    ]
)

excluded_packages = [
    'IPython', 'ipykernel', 'jupyter', 'jupyter_core', 'jupyter_client',
    'torch', 'transformers', 'matplotlib', 'pandas', 'scipy',
    'onnxruntime', 'streamlit', 'pydeck', 'altair',
    'pytest', 'unittest', 'test', 'tests'
]

a = Analysis(
    [os.path.join(BOT_DIR, 'main.py')],
    pathex=[ROOT_DIR, BOT_DIR],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_packages,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TumblrBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file if os.path.exists(icon_file) else None,
)
