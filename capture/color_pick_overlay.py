#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""화면 전체(다른 창 포함)에서 색을 추출하는 전체화면 오버레이.

메인 윈도우를 가리지 않고 먼저 화면을 그랩해 자신의 캔버스 내용도 추출
대상에 포함시킨 뒤, 그 스냅샷을 그대로 보여주는 전체화면 오버레이를
띄운다. 실제 다른 창과 상호작용하는 것이 아니라, PicPick 등 다른 도구와
동일하게 "그 순간의 화면을 통째로 찍어 그 사진에서 픽셀을 읽는" 방식이다.
"""

import logging
from typing import Optional

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QKeyEvent, QMouseEvent, QPainter, QPainterPath,
                            QPaintEvent, QPen, QPixmap)
from PySide6.QtWidgets import QWidget

from capture.config import ACCENT
from capture.desktop_shot import DesktopShot

logger = logging.getLogger(__name__)

_MAGNIFIER_DIAMETER = 216
_MAGNIFIER_ZOOM = 8
_MAGNIFIER_GAP = 18                     # 커서와 돋보기 사이 간격
_MAGNIFIER_GRID_COLOR = QColor(128, 128, 128, 120)
_MAGNIFIER_LABEL_HEIGHT = 18
_MAGNIFIER_LABEL_BOTTOM_MARGIN = 6      # 라벨 박스 아래쪽 변을 원의 맨 아래 접점에서 이만큼 띄운다
_MAGNIFIER_LABEL_BG_ALPHA = 180         # 기존(200)보다 10% 더 투명하게

_CURSOR_SIZE = 21     # 홀수라야 정중앙이 픽셀 하나로 딱 떨어진다
_CURSOR_GAP = 3        # 중심에서 이만큼은 선을 그리지 않아, 추출될 픽셀이 커서에 가리지 않는다


def _make_crosshair_cursor() -> QCursor:
    """중심 1px이 뚫린 십자 커서를 만든다.

    표준 CrossCursor는 중심까지 선이 이어져 있어 실제로 추출될 픽셀이
    커서 선에 가려 보인다. 중심 부근에 빈 칸을 둬서 그 아래 픽셀이
    그대로 드러나도록 한다. 밝은/어두운 배경 모두에서 잘 보이도록
    흰색 테두리(굵게) 위에 검은 선(얇게)을 겹쳐 그린다.
    """
    center = _CURSOR_SIZE // 2
    pm = QPixmap(_CURSOR_SIZE, _CURSOR_SIZE)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    for color, width in ((Qt.GlobalColor.white, 3), (Qt.GlobalColor.black, 1)):
        pen = QPen(color)
        pen.setWidth(width)
        p.setPen(pen)
        p.drawLine(0, center, center - _CURSOR_GAP, center)
        p.drawLine(center + _CURSOR_GAP, center, _CURSOR_SIZE - 1, center)
        p.drawLine(center, 0, center, center - _CURSOR_GAP)
        p.drawLine(center, center + _CURSOR_GAP, center, _CURSOR_SIZE - 1)
    p.end()
    return QCursor(pm, center, center)


class ColorPickOverlay(QWidget):
    """전체 화면(그랩한 스냅샷)을 덮고, 클릭한 지점의 색을 추출하는 오버레이."""

    picked = Signal(QColor)

    def __init__(self, shot: Optional[DesktopShot] = None) -> None:
        """오버레이를 생성하고 전체 가상 데스크톱 위에 배치한다.

        Args:
            shot: 재사용할 화면 그랩. None이면 새로 생성한다. 메인 윈도우를
                가리기 전에 그랩해야 자신의 캔버스 내용도 추출 대상에
                포함된다(RegionOverlay와 달리 메인 윈도우를 숨기지 않는다).
        """
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                          | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.shot: DesktopShot = shot or DesktopShot()
        self.setGeometry(self.shot.logical_geo)
        self.setCursor(_make_crosshair_cursor())
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 매 마우스 이동마다 전체 화면 픽스맵을 변환하지 않도록 한 번만 QImage로
        # 바꿔 픽셀 조회에 쓴다(devicePixelRatio를 1.0으로 되돌려 물리 픽셀
        # 좌표 그대로 인덱싱한다).
        pm = self.shot.pixmap
        pm.setDevicePixelRatio(1.0)
        self._image = pm.toImage()

        self._cursor: QPoint = QPoint(0, 0)

    def _color_at(self, logical_pos: QPoint) -> QColor:
        """논리 좌표 지점의 화면 색을 반환한다(경계 밖이면 가장 가까운 픽셀로 고정)."""
        phys = self.shot.physical_rect(QRect(logical_pos, logical_pos))
        x = min(max(phys.left(), 0), self._image.width() - 1)
        y = min(max(phys.top(), 0), self._image.height() - 1)
        return self._image.pixelColor(x, y)

    # ---------- 그리기 ---------- #
    def paintEvent(self, _event: QPaintEvent) -> None:
        """그랩해 둔 화면 스냅샷과 돋보기를 그린다."""
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.shot.pixmap)
        self._paint_magnifier(p)
        p.end()

    def _magnifier_pos(self, diameter: int) -> QPoint:
        """돋보기가 놓일 좌표를 계산한다.

        화면(오버레이 전체) 중앙을 기준으로 커서가 어느 사분면에 있는지에
        따라, 항상 커서의 대각선 반대 방향에 돋보기가 오도록 한다 (커서가
        좌상단이면 돋보기는 커서 기준 우하단, 좌하단이면 우상단 등). 화면
        경계를 넘어갈 때만 반응하는 방식보다 위치가 갑자기 바뀌지 않아
        더 예측 가능하다.
        """
        gap = _MAGNIFIER_GAP
        half_w, half_h = self.width() / 2, self.height() / 2
        x = self._cursor.x() + gap if self._cursor.x() < half_w else self._cursor.x() - diameter - gap
        y = self._cursor.y() + gap if self._cursor.y() < half_h else self._cursor.y() - diameter - gap
        return QPoint(int(x), int(y))

    def _paint_magnifier(self, p: QPainter) -> None:
        """커서 주변을 원형으로 확대해 픽셀 격자와 추출 지점 표시, hex 값을 보여주는 돋보기를 그린다.

        hex 값 라벨은 원 안쪽 아래쪽에 완전히 들어가도록 그리되, 라벨
        박스의 아래쪽 두 모서리가 원의 곡선에 정확히 닿는 폭으로 그려
        원에서 자연스럽게 이어지는 것처럼 보이게 한다(위쪽 두 모서리는
        원 중심에 더 가까워 자동으로 원 안쪽에 들어간다).
        """
        diameter, zoom = _MAGNIFIER_DIAMETER, _MAGNIFIER_ZOOM
        radius = diameter / 2
        src_logical = diameter / zoom
        src = QRectF(self._cursor.x() - src_logical / 2, self._cursor.y() - src_logical / 2,
                     src_logical, src_logical)
        s = self.shot.scale
        src_phys = QRectF(src.left() * s, src.top() * s, src.width() * s, src.height() * s)

        pos = self._magnifier_pos(diameter)
        target = QRect(pos, QPoint(pos.x() + diameter, pos.y() + diameter))
        cx, cy = target.center().x(), target.center().y()

        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        circle_path = QPainterPath()
        circle_path.addEllipse(QRectF(target))
        p.setClipPath(circle_path)
        p.fillRect(target.adjusted(-1, -1, 1, 1), QColor(0, 0, 0, 200))
        p.drawPixmap(QRectF(target), self.shot.pixmap, src_phys)

        # 확대 배율(zoom)만큼 간격을 둔 격자선을 그려, 원본 픽셀 하나하나의
        # 경계를 눈으로 확인할 수 있게 한다.
        grid_pen = QPen(_MAGNIFIER_GRID_COLOR)
        grid_pen.setWidth(1)
        p.setPen(grid_pen)
        x = target.left()
        while x <= target.right():
            p.drawLine(x, target.top(), x, target.bottom())
            x += zoom
        y = target.top()
        while y <= target.bottom():
            p.drawLine(target.left(), y, target.right(), y)
            y += zoom
        p.setClipping(False)

        p.setPen(QPen(ACCENT))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(target)

        # 추출 대상 픽셀 한 칸(격자 한 칸과 정확히 일치)을 빨간 사각형으로 표시한다.
        center_pen = QPen(QColor(0xff, 0x33, 0x33))
        center_pen.setWidth(1)
        p.setPen(center_pen)
        p.drawRect(QRectF(cx - zoom / 2, cy - zoom / 2, zoom, zoom))

        # 라벨 박스의 아래쪽 변이 원 중심에서 (radius - margin)만큼 떨어진
        # 높이에 있으므로, 그 높이의 원 현(chord) 폭을 라벨 박스 폭으로 쓴다.
        # 위쪽 변은 그보다 원 중심에 더 가까워(현이 더 넓어) 자동으로 원
        # 안쪽에 들어간다.
        label_height = _MAGNIFIER_LABEL_HEIGHT
        dy = radius - _MAGNIFIER_LABEL_BOTTOM_MARGIN
        half_w = (radius * radius - dy * dy) ** 0.5 if abs(dy) < radius else 0.0
        label_bottom = cy + dy
        label_rect = QRect(int(round(cx - half_w)), int(round(label_bottom - label_height)),
                            max(int(round(half_w * 2)), 1), label_height)

        color = self._color_at(self._cursor)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, _MAGNIFIER_LABEL_BG_ALPHA))
        p.drawRect(label_rect)
        p.setPen(Qt.GlobalColor.white)
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        p.setFont(font)
        p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, color.name().upper())
        p.restore()

    # ---------- 마우스/키보드 ---------- #
    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        """돋보기 위치를 갱신한다."""
        self._cursor = e.position().toPoint()
        self.update()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        """좌클릭 지점의 색을 추출해 방출하고, 우클릭이면 취소한다."""
        if e.button() == Qt.MouseButton.RightButton:
            self.close()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()
        color = self._color_at(pos)
        logger.info("화면 색상 추출: %s at (%d, %d)", color.name(), pos.x(), pos.y())
        self.close()
        self.picked.emit(color)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        """Esc로 추출을 취소한다."""
        if e.key() == Qt.Key.Key_Escape:
            self.close()
