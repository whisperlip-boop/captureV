#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""고DPI 환경을 고려한 전체 데스크톱 화면 그랩."""

import logging

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap

logger = logging.getLogger(__name__)


class DesktopShot:
    """모든 모니터를 하나의 픽스맵으로 합쳐 보관.

    Attributes:
        logical_geo: 위젯 좌표계(논리 픽셀)의 가상 데스크톱 사각형.
        scale: 물리/논리 배율 (여러 모니터면 가장 큰 배율 기준).
        pixmap: 물리 픽셀 해상도 이미지 (devicePixelRatio = scale).
    """

    def __init__(self) -> None:
        """모든 화면을 그랩하여 단일 물리 픽셀 픽스맵으로 합성한다."""
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
            shot.setDevicePixelRatio(1.0)   # 물리 픽셀 그대로 다룸
            target = QRectF((g.left() - geo.left()) * self.scale,
                             (g.top() - geo.top()) * self.scale,
                             g.width() * self.scale, g.height() * self.scale)
            painter.drawPixmap(target, shot, QRectF(shot.rect()))
        painter.end()
        pm.setDevicePixelRatio(self.scale)
        self.pixmap: QPixmap = pm
        logger.info("화면 그랩: %d개 모니터, 논리 %dx%d, scale=%.2f",
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
