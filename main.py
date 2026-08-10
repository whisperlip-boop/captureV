#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CaptureV - 화면 캡처 + 탭 편집기 (PySide6) 진입점.

PicPick의 불편했던 부분(저장 대화상자 지연)을 없애고, 필요한 기능만 담은 도구.

핵심: 사각 영역 캡처
  - 드래그로 영역 지정 → 마우스를 떼는 즉시 확정 (별도 조절 모드 없음)
  - 더블클릭/Ctrl+A = 전체화면 확정, Esc = 드래그 취소/오버레이 닫기
  - 돋보기(M 토글) + 십자선 + 실시간 좌표/크기 표시로 픽셀 단위 정밀 지정
  - 고정 크기 캡처 (예: 800x600) / 마지막 영역 반복 캡처
  - 고DPI(배율 125%, 150% 등) 환경에서 물리 픽셀 원본 해상도로 캡처

그 외
  - 탭 편집기 + 캔버스 핸들 드래그로 여백 확장
  - 클립보드 붙여넣기로 여러 캡처 합성 (Ctrl+V 후 드래그 이동)
  - 지정 폴더 즉시 저장 (Ctrl+S — 파일 대화상자 없음)

실행:  python main.py
설치:  pip install PySide6
"""

import ctypes
import logging
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from capture.config import APP_NAME, IS_WIN, get_resource_path
from capture.hotkeys import unregister_global_hotkeys
from capture.logging_setup import install_excepthook, setup_logging
from capture.main_window import MainWindow

logger = logging.getLogger(__name__)


def main() -> None:
    """QApplication을 생성하고 메인 윈도우를 실행한다."""
    # 이후 코드에서 발생하는 예외/크래시를 빠짐없이 로그로 남기기 위해
    # 다른 어떤 처리보다도 먼저 로깅과 예외 훅을 구성한다.
    log_path = setup_logging()
    install_excepthook()
    logger.info("%s 시작 (로그 파일: %s)", APP_NAME, log_path)

    if IS_WIN:
        # python.exe(또는 PyInstaller 부트로더)의 기본 매니페스트는 보통
        # "System DPI Aware"(모니터 전체에 단일 DPI만 적용)라, 배율이 같아도
        # 모니터별로 따로 합성되는 화면 캡처/오버레이에서 경계가 어긋나거나
        # 화면이 밀리는 문제가 생길 수 있다. Qt가 초기화되기 전(QApplication
        # 생성 전)에 Per-Monitor V2로 직접 올려야 나중에는 바꿀 수 없다.
        try:
            set_dpi_context = ctypes.windll.user32.SetProcessDpiAwarenessContext
            set_dpi_context.argtypes = [ctypes.c_void_p]
            set_dpi_context.restype = ctypes.c_bool
            per_monitor_v2 = ctypes.c_void_p((-4) & 0xFFFFFFFFFFFFFFFF)
            if not set_dpi_context(per_monitor_v2):
                logger.warning("Per-Monitor V2 DPI 인식 설정 실패(이미 다른 값으로 설정됐거나 미지원 Windows 버전)")
        except Exception:
            logger.exception("DPI 인식 설정 중 예외 발생")

    if IS_WIN:
        # 이 AppUserModelID를 지정해야 작업표시줄이 python.exe 대신 이 앱의
        # 아이콘을 보여준다 (지정하지 않으면 다른 파이썬 앱과 그룹화되거나
        # 인터프리터 기본 아이콘이 뜬다).
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("vuno.capturev.desktop.v1")
        except Exception:
            logger.exception("작업표시줄 AppUserModelID 설정 실패")

    app = QApplication(sys.argv)
    app.setOrganizationName(APP_NAME)
    app.setApplicationName(APP_NAME)
    icon = QIcon(str(get_resource_path("img/capture.ico")))
    app.setWindowIcon(icon)

    win = MainWindow()     # 전역 캡처 단축키는 MainWindow가 자체적으로 등록한다.
    win.setWindowIcon(icon)
    win.show()

    exit_code = app.exec()
    unregister_global_hotkeys(win.hotkey_filter)
    logger.info("%s 종료 (exit_code=%d)", APP_NAME, exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
