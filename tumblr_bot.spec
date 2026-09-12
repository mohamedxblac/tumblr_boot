# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

ROOT_DIR = os.path.abspath(SPECPATH)
BOT_DIR = os.path.join(ROOT_DIR, 'tumblr_boot')

# Collect all resources and dependencies for undetected_chromedriver and selenium
datas_uc, binaries_uc, hiddenimports_uc = collect_all('undetected_chromedriver')
datas_sel, binaries_sel, hiddenimports_sel = collect_all('selenium')

all_datas = datas_uc + datas_sel
icon_file = os.path.join(ROOT_DIR, 'assets', 'app_icon.ico')
if os.path.exists(icon_file):
    all_datas.append((icon_file, 'assets'))

all_binaries = binaries_uc + binaries_sel
all_hiddenimports = (
    hiddenimports_uc
    + hiddenimports_sel
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
        'core.browser',
        'core.contact_history',
        'core.engine',
        'core.messenger',
        'core.navigation',
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
