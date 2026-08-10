#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""고DPI 환경을 고려한 전체 데스크톱 화면 그랩."""

import ctypes
import logging

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap

from capture.config import IS_WIN

logger = logging.getLogger(__name__)

_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79
_SRCCOPY = 0x00CC0020
_CAPTUREBLT = 0x40000000    # 레이어드 창(반투명 등)까지 그대로 캡처
_DIB_RGB_COLORS = 0
_BI_RGB = 0

if IS_WIN:
    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


def _grab_virtual_screen_gdi(x: int, y: int, w: int, h: int) -> QImage:
    """Win32 GDI BitBlt로 가상 데스크톱의 지정 물리 픽셀 영역을 한 번에 캡처한다.

    여러 모니터를 Qt의 QScreen.grabWindow()로 하나씩 따로 캡처해 이어붙이면,
    모니터별 DPI 인식 처리 과정에서 생기는 논리 좌표 반올림/가상화 오차 때문에
    실제로는 붙어 있는 모니터 사이에도 이어붙인 이미지에 빈틈(검은 영역)이
    생길 수 있다. OS가 이미 하나로 합성해 둔 데스크톱 프레임버퍼를 통째로
    한 번에 복사하면 이런 이어붙이기 오차가 원천적으로 없다.

    Args:
        x, y, w, h: 가상 데스크톱 기준 물리 픽셀 좌표/크기
            (GetSystemMetrics(SM_{X,Y,CX,CY}VIRTUALSCREEN) 값).

    Returns:
        캡처한 이미지(불투명 RGB, 알파 없음).
    """
    hdc_screen = _user32.GetDC(None)
    hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
    hbitmap = _gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    old_bitmap = _gdi32.SelectObject(hdc_mem, hbitmap)
    try:
        if not _gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, _SRCCOPY | _CAPTUREBLT):
            raise OSError("BitBlt 실패")

        header = _BitmapInfoHeader()
        header.biSize = ctypes.sizeof(_BitmapInfoHeader)
        header.biWidth = w
        header.biHeight = -h    # 음수 = 위에서 아래로(top-down) 행 순서
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = _BI_RGB

        buf = ctypes.create_string_buffer(w * h * 4)
        if not _gdi32.GetDIBits(hdc_mem, hbitmap, 0, h, buf, ctypes.byref(header), _DIB_RGB_COLORS):
            raise OSError("GetDIBits 실패")

        # GDI의 32bpp BI_RGB 버퍼는 픽셀당 B,G,R,X(사용 안 함) 순서라
        # Qt의 Format_RGB32(메모리상 동일한 바이트 순서, 최상위 바이트 무시)와
        # 바로 호환된다. copy()로 buf의 수명과 무관하게 완전히 분리한다.
        return QImage(bytes(buf), w, h, w * 4, QImage.Format.Format_RGB32).copy()
    finally:
        _gdi32.SelectObject(hdc_mem, old_bitmap)
        _gdi32.DeleteObject(hbitmap)
        _gdi32.DeleteDC(hdc_mem)
        _user32.ReleaseDC(None, hdc_screen)


class DesktopShot:
    """모든 모니터를 하나의 픽스맵으로 합쳐 보관.

    Attributes:
        logical_geo: 위젯 좌표계(논리 픽셀)의 가상 데스크톱 사각형.
        scale: 물리/논리 배율 (여러 모니터면 가장 큰 배율 기준).
        pixmap: 물리 픽셀 해상도 이미지 (devicePixelRatio = scale).
    """

    def __init__(self) -> None:
        """모든 화면을 그랩하여 단일 물리 픽셀 픽스맵으로 합성한다."""
        if IS_WIN:
            try:
                self._init_win32()
                return
            except Exception:
                logger.exception("Win32 단일 캡처 실패, Qt 개별 그랩 방식으로 대체한다")
        self._init_qt_fallback()

    def _init_win32(self) -> None:
        """Win32 GDI로 가상 데스크톱 전체를 한 번에 캡처한다(모니터 경계 이어붙이기 오차 없음).

        main.py에서 프로세스를 Per-Monitor V2 DPI 인식으로 설정해 둔 뒤라야
        GetSystemMetrics(SM_*VIRTUALSCREEN)가 가상화되지 않은 실제 물리
        픽셀 좌표를 반환한다.
        """
        screens = QGuiApplication.screens()
        self.scale: float = max((s.devicePixelRatio() for s in screens), default=1.0) or 1.0

        x = _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
        y = _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
        w = _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
        h = _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)

        image = _grab_virtual_screen_gdi(x, y, w, h)
        pm = QPixmap.fromImage(image)
        pm.setDevicePixelRatio(self.scale)
        self.pixmap: QPixmap = pm
        # Qt의 QScreen.geometry() 합집합은 모니터별 논리 좌표 반올림/가상화
        # 오차로 실제로는 붙어 있는 모니터 사이에도 논리 좌표상 틈이 생길 수
        # 있어(예: 노트북 화면 좌우의 4K 모니터), pixmap과 반드시 같은 비율로
        # 대응해야 하는 logical_geo는 Qt 값이 아니라 이 물리 좌표를 scale로
        # 나눠 직접 계산한다.
        self.logical_geo: QRect = QRect(
            round(x / self.scale), round(y / self.scale), round(w / self.scale), round(h / self.scale))
        logger.info("화면 그랩(Win32 단일 캡처): 물리 %dx%d at (%d,%d), scale=%.2f, %d개 모니터",
                    w, h, x, y, self.scale, len(screens))

    def _init_qt_fallback(self) -> None:
        """Qt로 모니터를 하나씩 그랩해 이어붙인다 (Windows가 아닐 때의 대체 경로)."""
        screens = QGuiApplication.screens()
        geo = screens[0].geometry()
        for s in screens[1:]:
            geo = geo.united(s.geometry())
        self.logical_geo: QRect = geo
        self.scale: float = max((s.devicePixelRatio() for s in screens), default=1.0) or 1.0

        pm = QPixmap(int(round(geo.width() * self.scale)),
                     int(round(geo.height() * self.scale)))
        pm.fill(Qt.GlobalColor.black)
        painter = QPainter(pm)
        for s in screens:
            g = s.geometry()
            shot = s.grabWindow(0)
            shot.setDevicePixelRatio(1.0)
            target = QRectF((g.left() - geo.left()) * self.scale, (g.top() - geo.top()) * self.scale,
                             shot.width(), shot.height())
            painter.drawPixmap(target, shot, QRectF(shot.rect()))
        painter.end()
        pm.setDevicePixelRatio(self.scale)
        self.pixmap: QPixmap = pm
        logger.info("화면 그랩(Qt 개별 그랩): %d개 모니터, 논리 %dx%d, scale=%.2f",
                    len(screens), geo.width(), geo.height(), self.scale)

    def physical_rect(self, logical_rect: QRect) -> QRect:
        """오버레이(논리) 좌표를 픽스맵(물리) 좌표로 변환한다.

        Args:
            logical_rect: 논리 픽셀 좌표계의 사각형.

        Returns:
            물리 픽셀 좌표계로 환산된 사각형.
        """
        s = self.scale
        return QRect(int(round(logical_rect.left() * s)), int(round(logical_rect.top() * s)),
                     max(int(round(logical_rect.width() * s)), 1),
                     max(int(round(logical_rect.height() * s)), 1))

    def crop(self, logical_rect: QRect) -> QImage:
        """논리 좌표 사각형을 물리 해상도 원본으로 잘라 반환한다.

        Args:
            logical_rect: 잘라낼 논리 픽셀 좌표계의 사각형.

        Returns:
            물리 해상도 그대로의 잘라낸 이미지.
        """
        pm = QPixmap(self.pixmap)
        pm.setDevicePixelRatio(1.0)
        img = pm.copy(self.physical_rect(logical_rect)).toImage()
        img.setDevicePixelRatio(1.0)
        return img

    def crop_physical(self, screen_rect: QRect) -> QImage:
        """가상 데스크톱 물리 픽셀 좌표(예: Win32 GetWindowRect) 사각형을 그대로 잘라 반환한다.

        논리 좌표를 거치지 않고 물리 좌표를 직접 pixmap 좌표계로 변환한다.
        범위를 벗어난 사각형은 pixmap 경계로 잘라낸다.

        Args:
            screen_rect: 가상 데스크톱 물리 픽셀 좌표계의 사각형.

        Returns:
            잘라낸 이미지.
        """
        origin = QPoint(int(round(self.logical_geo.left() * self.scale)),
                         int(round(self.logical_geo.top() * self.scale)))
        local_rect = QRect(screen_rect.topLeft() - origin, screen_rect.size())

        pm = QPixmap(self.pixmap)
        pm.setDevicePixelRatio(1.0)
        clipped = local_rect.intersected(pm.rect())
        img = pm.copy(clipped).toImage()
        img.setDevicePixelRatio(1.0)
        return img
