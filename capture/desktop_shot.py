#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""고DPI 환경을 고려한 전체 데스크톱 화면 그랩."""

import ctypes
import logging

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap

from capture.config import IS_WIN

# ctypes.wintypes는 Windows 전용 서브모듈이라 다른 플랫폼에서 import 시 실패할 수 있다.
if IS_WIN:
    import ctypes.wintypes as wintypes
else:
    wintypes = None

logger = logging.getLogger(__name__)

_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79
_SRCCOPY = 0x00CC0020
_CAPTUREBLT = 0x40000000    # 레이어드 창(반투명 등)까지 그대로 캡처
_DIB_RGB_COLORS = 0
_BI_RGB = 0


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


if IS_WIN:
    # argtypes/restype을 선언하지 않으면 ctypes가 반환값을 32비트 int로 잘라, 64비트
    # 프로세스에서 핸들(HDC/HBITMAP) 상위 비트가 사라질 수 있다. 다른 모듈이 쓰는
    # ctypes.windll.user32 함수 객체에 영향을 주지 않도록 이 모듈 전용 인스턴스에 선언한다.
    _user32 = ctypes.WinDLL("user32")
    _gdi32 = ctypes.WinDLL("gdi32")

    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.ReleaseDC.restype = ctypes.c_int
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int

    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    _gdi32.BitBlt.restype = wintypes.BOOL
    _gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                 ctypes.c_void_p, ctypes.POINTER(_BitmapInfoHeader), wintypes.UINT]
    _gdi32.GetDIBits.restype = ctypes.c_int
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteObject.restype = wintypes.BOOL
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.DeleteDC.restype = wintypes.BOOL


def screen_scales() -> list[float]:
    """연결된 모니터별 배율(devicePixelRatio) 목록을 반환한다."""
    return [s.devicePixelRatio() or 1.0 for s in QGuiApplication.screens()]


def has_mixed_screen_scales() -> bool:
    """모니터마다 배율이 달라 단일 오버레이 좌표가 일부 모니터에서 어긋날 수 있는지 여부."""
    return len({round(s, 3) for s in screen_scales()}) > 1


def _grab_virtual_screen_gdi(x: int, y: int, w: int, h: int) -> QImage:
    """Win32 GDI BitBlt로 가상 데스크톱의 지정 물리 픽셀 영역을 한 번에 캡처한다.

    여러 모니터를 Qt의 QScreen.grabWindow()로 하나씩 따로 캡처해 이어붙이면,
    모니터별 DPI 인식 처리 과정에서 생기는 논리 좌표 반올림/가상화 오차 때문에
    실제로는 붙어 있는 모니터 사이에도 이어붙인 이미지에 빈틈(검은 영역)이
    생길 수 있다. OS가 이미 하나로 합성해 둔 데스크톱 프레임버퍼를 통째로
    한 번에 복사하면 이런 이어붙이기 오차가 원천적으로 없다.

    Args:
        x: 가상 데스크톱 기준 물리 픽셀 x (GetSystemMetrics(SM_XVIRTUALSCREEN)).
        y: 가상 데스크톱 기준 물리 픽셀 y.
        w: 물리 픽셀 너비.
        h: 물리 픽셀 높이.

    Returns:
        캡처한 이미지(불투명 RGB, 알파 없음).

    Raises:
        OSError: GDI 자원 생성 또는 BitBlt/GetDIBits가 실패한 경우.
    """
    hdc_screen = _user32.GetDC(None)
    if not hdc_screen:
        raise OSError("GetDC 실패")
    hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
    hbitmap = _gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    old_bitmap = _gdi32.SelectObject(hdc_mem, hbitmap) if hdc_mem and hbitmap else None
    try:
        if not hdc_mem or not hbitmap:
            raise OSError("GDI 메모리 DC/비트맵 생성 실패")
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
        # 바로 호환된다. QImage는 buf를 참조만 하므로 copy() 한 번으로 buf 수명과 분리한다.
        return QImage(buf, w, h, w * 4, QImage.Format.Format_RGB32).copy()
    finally:
        if old_bitmap is not None:
            _gdi32.SelectObject(hdc_mem, old_bitmap)
        if hbitmap:
            _gdi32.DeleteObject(hbitmap)
        if hdc_mem:
            _gdi32.DeleteDC(hdc_mem)
        _user32.ReleaseDC(None, hdc_screen)


class DesktopShot:
    """모든 모니터를 하나의 픽스맵으로 합쳐 보관.

    좌표계는 세 가지다: 오버레이 위젯의 논리 좌표, pixmap 픽셀 좌표(물리, 가상
    데스크톱 좌상단 = (0, 0)), 가상 데스크톱 절대 물리 좌표(Win32 창 좌표).

    Attributes:
        logical_geo: 위젯 좌표계(논리 픽셀)의 가상 데스크톱 사각형.
        scale: 물리/논리 배율 (여러 모니터면 가장 큰 배율 기준).
        physical_origin: pixmap (0, 0)에 해당하는 가상 데스크톱 절대 물리 좌표.
        mixed_scale: 모니터마다 배율이 다른지 여부(오버레이 좌표가 일부 모니터에서 어긋날 수 있음).
        pixmap: 물리 픽셀 해상도 이미지 (devicePixelRatio = scale).
    """

    def __init__(self) -> None:
        """모든 화면을 그랩하여 단일 물리 픽셀 픽스맵으로 합성한다.

        Raises:
            RuntimeError: 연결된 화면이 없어 그랩할 수 없는 경우.
        """
        self.mixed_scale: bool = has_mixed_screen_scales()
        if self.mixed_scale:
            logger.warning("모니터별 배율이 서로 다름(%s): 오버레이 좌표가 일부 모니터에서 어긋날 수 있음",
                           ", ".join(f"{s:.2f}" for s in screen_scales()))
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
        if w <= 0 or h <= 0:
            raise OSError(f"가상 화면 크기를 얻지 못함: {w}x{h}")

        image = _grab_virtual_screen_gdi(x, y, w, h)
        pm = QPixmap.fromImage(image)
        pm.setDevicePixelRatio(self.scale)
        self.pixmap: QPixmap = pm
        self.physical_origin: QPoint = QPoint(x, y)
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
        if not screens:
            raise RuntimeError("연결된 화면이 없어 캡처할 수 없음")
        geo = screens[0].geometry()
        for s in screens[1:]:
            geo = geo.united(s.geometry())
        self.logical_geo: QRect = geo
        self.scale: float = max((s.devicePixelRatio() for s in screens), default=1.0) or 1.0
        self.physical_origin: QPoint = QPoint(int(round(geo.left() * self.scale)),
                                              int(round(geo.top() * self.scale)))

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

    def pixel_rect(self) -> QRect:
        """pixmap 전체를 물리 픽셀 좌표로 나타낸 사각형 (0, 0, 너비, 높이)."""
        return QRect(0, 0, self.pixmap.width(), self.pixmap.height())

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

    def crop_pixels(self, pixel_rect: QRect) -> QImage:
        """pixmap 물리 픽셀 좌표 사각형을 그대로 잘라 반환한다(범위 밖은 잘라낸다).

        Args:
            pixel_rect: pixmap 좌상단 기준 물리 픽셀 사각형.

        Returns:
            잘라낸 이미지(devicePixelRatio 1.0). 겹치는 부분이 없으면 null 이미지.
        """
        pm = QPixmap(self.pixmap)
        pm.setDevicePixelRatio(1.0)
        clipped = pixel_rect.intersected(pm.rect())
        if clipped.isEmpty():
            return QImage()
        img = pm.copy(clipped).toImage()
        img.setDevicePixelRatio(1.0)
        return img

    def full_image(self) -> QImage:
        """가상 데스크톱 전체를 배율 변환 없이 원본 물리 해상도 그대로 반환한다."""
        img = self.pixmap.toImage()
        img.setDevicePixelRatio(1.0)
        return img

    def crop(self, logical_rect: QRect) -> QImage:
        """논리 좌표 사각형을 물리 해상도 원본으로 잘라 반환한다.

        Args:
            logical_rect: 잘라낼 논리 픽셀 좌표계의 사각형.

        Returns:
            물리 해상도 그대로의 잘라낸 이미지.
        """
        return self.crop_pixels(self.physical_rect(logical_rect))

    def crop_physical(self, screen_rect: QRect) -> QImage:
        """가상 데스크톱 물리 픽셀 좌표(예: Win32 GetWindowRect) 사각형을 그대로 잘라 반환한다.

        논리 좌표를 거치지 않고 물리 좌표를 직접 pixmap 좌표계로 변환한다.
        범위를 벗어난 사각형은 pixmap 경계로 잘라낸다.

        Args:
            screen_rect: 가상 데스크톱 물리 픽셀 좌표계의 사각형.

        Returns:
            잘라낸 이미지.
        """
        return self.crop_pixels(screen_rect.translated(-self.physical_origin))
