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
    # UPX는 확장 모듈/DLL을 압축하다 깨뜨리는 사례가 있다. PyInstaller가 Qt
    # '플러그인'과 CFG가 켜진 Windows 바이너리는 자동으로 제외하지만, Qt6Core.dll
    # 같은 일반 DLL과 Pillow의 C 확장은 대상이 아니라 직접 지정한다.
    # 파이썬 버전이 바뀌면 파일명(_avif.cp313-win_amd64.pyd)도 바뀌므로, 보호가
    # 조용히 풀리지 않도록 글롭으로 쓴다(upx_exclude는 PurePath.match 기반이라
    # '*' 와일드카드를 지원한다).
    upx_exclude=['_avif*.pyd', '_imaging*.pyd', 'Qt6*.dll'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='img/capture.ico',
)
