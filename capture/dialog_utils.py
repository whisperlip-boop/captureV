#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""팝업 창 제목줄 공통 처리.

모든 팝업에서 최소화/최대화 버튼을 없애고 닫기(X) 버튼만 남긴다.
"""

import ctypes
import logging

from PySide6.QtWidgets import QWidget

from capture.config import IS_WIN

logger = logging.getLogger(__name__)

_GWL_STYLE = -16
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_SWP_FRAMECHANGED = 0x0020

if IS_WIN:
    _user32 = ctypes.windll.user32
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _user32.SetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowPos.restype = ctypes.c_bool
    _user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_uint]


def strip_minmax_buttons(widget: QWidget) -> None:
    """제목줄에서 최소화/최대화 버튼을 없애고 닫기 버튼만 남긴다.

    Args:
        widget: 최소화/최대화 버튼을 제거할 팝업 위젯(QDialog, QMessageBox 등).

    Note:
        Qt의 WindowMinimizeButtonHint/WindowMaximizeButtonHint 플래그
        조합은 Windows 버전/테마에 따라 버튼이 계속 보이거나 닫기 버튼이
        먹통이 되는 등 신뢰할 수 없어(실제로 그런 문제가 보고됨), 대신
        Win32 API로 네이티브 창 스타일(GWL_STYLE)을 직접 수정한다. 이
        앱은 Windows 전용이라 문제 없다.

        widget.winId()가 그 시점에 실제 네이티브 창(HWND)을 만들어내므로
        show()/exec() 전 어디서 호출해도 안전하다.
    """
    if not IS_WIN:
        return
    hwnd = int(widget.winId())
    style = _user32.GetWindowLongW(hwnd, _GWL_STYLE)
    style &= ~(_WS_MINIMIZEBOX | _WS_MAXIMIZEBOX)
    _user32.SetWindowLongW(hwnd, _GWL_STYLE, style)
    if not _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                                 _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED):
        logger.warning("팝업 창 스타일 갱신 실패 (SetWindowPos): hwnd=%s", hwnd)
