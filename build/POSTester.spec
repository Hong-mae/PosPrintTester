# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 스펙 — POSTester.exe

    pyinstaller --clean --noconfirm build/POSTester.spec

hidden import 를 직접 적어 둔 이유:
  * serial.tools.list_ports  — 문자열로 동적 임포트되어 PyInstaller 가 못 찾는다.
  * win32print               — pywin32 확장 모듈. 자동 탐지가 자주 실패한다.
  * win32timezone            — pywin32 가 런타임에 늦게 부르는 모듈.
                               빠지면 실행 직후 ImportError 로 창이 안 뜬다.
"""

import os
import sys

# 스펙을 build/ 안에 두었으므로 프로젝트 루트는 한 단계 위다.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

block_cipher = None

hiddenimports = [
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
    "serial.tools.list_ports_windows",
    "serial.win32",
    "win32print",
    "win32api",
    "win32con",
    "win32timezone",
    "pywintypes",
]

# QSS 와 아이콘은 코드가 아니므로 명시적으로 넣어 준다.
datas = [
    (os.path.join(ROOT, "pos_tester", "ui", "theme.qss"), os.path.join("pos_tester", "ui")),
    (os.path.join(ROOT, "build", "icon.ico"), "."),
]

# 쓰지 않는 Qt 모듈과 표준 라이브러리를 빼서 exe 크기와 첫 실행 시간을 줄인다.
#
# 주의: shiboken6 은 절대 제외하지 말 것. PySide6 가 임포트되는 순간
# shiboken6.Shiboken 을 부르기 때문에, 빼면 exe 가 실행 직후
# ModuleNotFoundError 로 죽는다 (창이 아예 뜨지 않는다).
excludes = [
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    "tkinter",
    "unittest",
    "pydoc_data",
    "test",
    "lib2to3",
    "pytest",
    "numpy",
    "PIL",
]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="POSTester",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX 압축은 백신 오탐을 자주 부른다. 현장 배포용이라 끈다.
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # --windowed: 검은 콘솔 창이 뜨지 않는다.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,     # 관리자 권한 요구 안 함 — UAC 프롬프트가 뜨지 않는다.
    uac_uiaccess=False,
    icon=os.path.join(ROOT, "build", "icon.ico"),
)
