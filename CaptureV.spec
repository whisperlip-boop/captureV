# -*- mode: python ; coding: utf-8 -*-
"""CaptureV PyInstaller 빌드 스펙 (단일 exe).

빌드:   pyinstaller CaptureV.spec
결과물: dist/CaptureV.exe
"""

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('img', 'img')],
    # scipy._cyutility: scipy.linalg 등 여러 Cython 모듈이 내부적으로
    # cimport하는 공용 헬퍼 확장 모듈이라, PyInstaller의 scipy 훅이 정적
    # 분석만으로는 찾지 못해 명시적으로 추가해야 한다(없으면 실행 시
    # "ModuleNotFoundError: No module named 'scipy._cyutility'"로 실패).
    hiddenimports=['scipy._cyutility'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CaptureV',
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
    icon='img/capture.ico',
)
