#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""전체화면·활성 윈도우 원클릭 캡처."""

import ctypes
import logging
from typing import Optional

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage

from capture.config import IS_WIN
from capture.desktop_shot import DesktopShot

logger = logging.getLogger(__name__)

# DWM 확장 프레임 경계 속성. 최신 Windows에서 보이지 않는 리사이즈 테두리를
# 제외한 실제 창 외곽선을 얻기 위해 GetWindowRect 대신 사용한다.
_DWMWA_EXTENDED_FRAME_BOUNDS = 9


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _foreground_window_rect() -> Optional[QRect]:
    """현재 포그라운드 창의 물리 픽셀 화면 좌표 사각형을 반환한다.

    Returns:
        창 사각형. 활성 창이 없거나 최소화 상태거나 좌표를 가져오지 못하면 None.
    """
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        logger.warning("활성 윈도우를 찾을 수 없음")
        return None
    if user32.IsIconic(hwnd):
        logger.warning("활성 윈도우가 최소화 상태라 캡처할 수 없음")
        return None

    rect = _RECT()
    hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect))
    if hr != 0 and not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        logger.warning("활성 윈도우의 좌표를 가져오지 못함 (hwnd=%s)", hwnd)
        return None
    if rect.right <= rect.left or rect.bottom <= rect.top:
        logger.warning("활성 윈도우 좌표가 비정상적임: %s", (rect.left, rect.top, rect.right, rect.bottom))
        return None
    return QRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def capture_active_window() -> Optional[QImage]:
    """현재 활성화된(포그라운드) 창을 물리 해상도로 캡처한다.

    화면을 그대로 그랩해 창 영역만 잘라내는 방식이라, 이 창 위에 다른 창이
    겹쳐 있으면 겹친 부분도 함께 캡처된다.

    Returns:
        캡처된 이미지. 활성 창을 찾을 수 없으면 None.
    """
    if not IS_WIN:
        logger.warning("Windows가 아니므로 활성 윈도우 캡처를 지원하지 않음")
        return None
    rect = _foreground_window_rect()
    if rect is None:
        return None
    shot = DesktopShot()
    img = shot.crop_physical(rect)
    logger.info("활성 윈도우 캡처: %dx%d", img.width(), img.height())
    return img


def capture_fullscreen() -> QImage:
    """전체 가상 데스크톱을 물리 해상도로 캡처한다.

    Returns:
        캡처된 이미지.
    """
    shot = DesktopShot()
    img = shot.crop(QRect(QPoint(0, 0), shot.logical_geo.size()))
    logger.info("전체화면 캡처: %dx%d", img.width(), img.height())
    return img
