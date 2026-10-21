#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사각 영역 캡처를 위한 전체화면 오버레이."""

import logging
from typing import Optional

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QKeyEvent, QMouseEvent,
                            QPainter, QPaintEvent, QPen)
from PySide6.QtWidgets import QWidget

from capture.config import ACCENT, MIN_SELECTION
from capture.desktop_shot import DesktopShot

logger = logging.getLogger(__name__)


class RegionOverlay(QWidget):
    """전체 화면을 덮고 사각 영역을 지정받는 오버레이.

    상태 전이는 idle → dragging → (확정) 순으로 진행된다. 드래그 중 마우스를
    떼는 순간 바로 확정되어 별도의 조절 모드/Enter 확정 단계는 없다.
    fixed_size 가 주어지면 커서를 따라다니는 고정 크기 사각형 모드로 동작한다.
    """

    captured = Signal(QImage, QRect)   # 잘라낸 이미지, 사용한 물리 픽셀 사각형(pixmap 좌표)

    def __init__(self, shot: Optional[DesktopShot] = None,
                 fixed_size: Optional[tuple[int, int]] = None) -> None:
        """오버레이를 생성하고 전체 가상 데스크톱 위에 배치한다.

        Args:
            shot: 재사용할 화면 그랩. None이면 새로 생성한다.
            fixed_size: (width, height) 실제(물리) 픽셀. 지정 시 고정 크기 캡처 모드로
                동작하며, 결과 이미지는 화면보다 크지 않은 한 정확히 이 크기다.

        Raises:
            RuntimeError: 화면을 그랩할 수 없는 경우 (DesktopShot 참조).
        """
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.shot: DesktopShot = shot or DesktopShot()
        self.fixed_size: Optional[tuple[int, int]] = fixed_size
        # 고정 크기는 물리 픽셀이라, 화면(논리 좌표)에 표시할 사각형은 배율로 나눈 크기다.
        self._fixed_logical: Optional[tuple[int, int]] = None
        if fixed_size is not None:
            s = self.shot.scale
            self._fixed_logical = (max(int(round(fixed_size[0] / s)), 1),
                                   max(int(round(fixed_size[1] / s)), 1))
        self._whole_screen: bool = False     # 더블클릭/Ctrl+A로 전체 화면을 고른 경우
        # 고정 크기가 화면보다 커서 결과가 요청 크기보다 작게 잘렸는지 (확정 후 MainWindow가 확인)
        self.fixed_clipped: bool = False
        self.setGeometry(self.shot.logical_geo)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._state: str = "idle"
        self._origin: Optional[QPoint] = None
        self._sel: QRect = QRect()
        self._cursor: QPoint = QPoint(0, 0)
        self._show_magnifier: bool = True

    # ---------- 좌표 유틸 ---------- #
    @staticmethod
    def _rect_from_points(a: QPoint, b: QPoint) -> QRect:
        """두 점으로 사각형을 생성한다. 너비는 좌표 차이(=실제 픽셀 수)와 같다."""
        return QRect(min(a.x(), b.x()), min(a.y(), b.y()),
                     abs(b.x() - a.x()), abs(b.y() - a.y()))

    def _clamp(self, rect: QRect) -> QRect:
        """사각형을 오버레이(화면) 범위 안으로 밀어넣는다."""
        r = QRect(rect).normalized()
        bounds = self.rect()
        if r.width() > bounds.width():
            r.setWidth(bounds.width())
        if r.height() > bounds.height():
            r.setHeight(bounds.height())
        dx = min(0, bounds.right() - r.right()) or max(0, bounds.left() - r.left())
        dy = min(0, bounds.bottom() - r.bottom()) or max(0, bounds.top() - r.top())
        r.translate(dx, dy)
        return r

    # ---------- 그리기 ---------- #
    def paintEvent(self, _event: QPaintEvent) -> None:
        """오버레이 배경, 선택 영역, 안내문, 돋보기를 그린다."""
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.shot.pixmap)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))

        if not self._sel.isNull() and self._sel.width() > 0:
            self._paint_selection(p)
        else:
            self._paint_crosshair(p)
            p.setPen(QColor(0xff, 0xff, 0xff))
            f = QFont(); f.setPointSize(11); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "드래그하여 사각 영역 지정 (놓으면 즉시 캡처)\n"
                       "Esc/우클릭 취소 · 더블클릭/Ctrl+A 전체화면")

        if self._show_magnifier and self._state in ("idle", "dragging"):
            self._paint_magnifier(p)
        p.end()

    def _paint_crosshair(self, p: QPainter) -> None:
        """선택 전 커서를 따라다니는 십자선을 그린다."""
        pen = QPen(QColor(0x2d, 0x9c, 0xff, 160)); pen.setWidth(1)
        p.setPen(pen)
        p.drawLine(0, self._cursor.y(), self.width(), self._cursor.y())
        p.drawLine(self._cursor.x(), 0, self._cursor.x(), self.height())

    def _paint_selection(self, p: QPainter) -> None:
        """선택 영역과 크기/좌표 라벨을 그린다."""
        sel = self._sel
        # 선택 영역만 원본 밝기로
        p.drawPixmap(sel, self.shot.pixmap, self.shot.physical_rect(sel))
        pen = QPen(ACCENT); pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(sel.adjusted(0, 0, -1, -1))

        # 크기/좌표 라벨. 크기는 결과 이미지와 같은 물리 픽셀로 보여준다(배율 100%면 논리와 같다).
        size = self._capture_rect().size()
        label = f"{size.width()} x {size.height()}   ({sel.left()}, {sel.top()})"
        f = QFont(); f.setPointSize(9); p.setFont(f)
        fm = p.fontMetrics()
        tw, th = fm.horizontalAdvance(label) + 10, fm.height() + 6
        ty = sel.top() - th - 3
        if ty < 0:
            ty = min(sel.bottom() + 3, self.height() - th)
        tx = min(max(sel.left(), 0), max(self.width() - tw, 0))
        p.setBrush(QBrush(QColor(0, 0, 0, 190)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRect(tx, ty, tw, th))
        p.setPen(Qt.GlobalColor.white)
        p.drawText(QRect(tx, ty, tw, th), Qt.AlignmentFlag.AlignCenter, label)

    def _magnifier_pos(self, box: int) -> QPoint:
        """돋보기가 놓일 좌표를 계산한다.

        화면(오버레이 전체) 중앙을 기준으로 커서가 어느 사분면에 있는지에
        따라, 항상 커서의 대각선 반대 방향에 돋보기가 오도록 한다 (커서가
        좌상단이면 돋보기는 커서 기준 우하단, 좌하단이면 우상단 등). 화면
        경계를 넘어갈 때만 반응하는 방식보다 위치가 갑자기 바뀌지 않아
        더 예측 가능하다.
        """
        gap = 18
        half_w, half_h = self.width() / 2, self.height() / 2
        x = self._cursor.x() + gap if self._cursor.x() < half_w else self._cursor.x() - box - gap
        y = self._cursor.y() + gap if self._cursor.y() < half_h else self._cursor.y() - box - gap
        return QPoint(int(x), int(y))

    def _paint_magnifier(self, p: QPainter) -> None:
        """커서 주변을 확대해 픽셀 단위로 확인할 수 있는 돋보기를 그린다."""
        box, zoom = 108, 8
        src_logical = box / zoom
        src = QRectF(self._cursor.x() - src_logical / 2, self._cursor.y() - src_logical / 2,
                     src_logical, src_logical)
        s = self.shot.scale
        src_phys = QRectF(src.left() * s, src.top() * s, src.width() * s, src.height() * s)

        pos = self._magnifier_pos(box)
        target = QRect(pos, QPoint(pos.x() + box, pos.y() + box))

        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.fillRect(target.adjusted(-1, -1, 1, 1), QColor(0, 0, 0, 200))
        p.drawPixmap(QRectF(target), self.shot.pixmap, src_phys)
        pen = QPen(QColor(0xff, 0x33, 0x55)); pen.setWidth(1)
        p.setPen(pen)
        cx, cy = target.center().x(), target.center().y()
        p.drawLine(target.left(), cy, target.right(), cy)
        p.drawLine(cx, target.top(), cx, target.bottom())
        p.setPen(QPen(ACCENT))
        p.drawRect(target)
        # 커서 위치 좌표
        f = QFont(); f.setPointSize(8); p.setFont(f)
        txt = f"{self._cursor.x() + self.shot.logical_geo.left()}, " \
              f"{self._cursor.y() + self.shot.logical_geo.top()}"
        p.fillRect(QRect(target.left(), target.bottom() + 1, box, 16), QColor(0, 0, 0, 200))
        p.setPen(Qt.GlobalColor.white)
        p.drawText(QRect(target.left(), target.bottom() + 1, box, 16), Qt.AlignmentFlag.AlignCenter, txt)
        p.restore()

    # ---------- 마우스 ---------- #
    def mousePressEvent(self, e: QMouseEvent) -> None:
        """드래그를 시작한다 (고정 크기 모드에서는 즉시 확정, 우클릭은 드래그 취소)."""
        if e.button() == Qt.MouseButton.RightButton:
            if self._state == "dragging":
                self._cancel_drag()
            else:
                self.close()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()
        if self.fixed_size:
            self._confirm()
            return
        self._state = "dragging"
        self._origin = pos
        self._sel = QRect(pos.x(), pos.y(), 0, 0)
        self.update()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        """고정 크기 추적 또는 드래그 중 선택 영역을 갱신한다."""
        pos = e.position().toPoint()
        self._cursor = pos

        if self._fixed_logical:
            w, h = self._fixed_logical
            self._sel = self._clamp(QRect(pos.x() - w // 2, pos.y() - h // 2, w, h))
            self.update()
            return

        if self._state == "dragging" and self._origin is not None:
            self._sel = self._rect_from_points(self._origin, pos)
        self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        """드래그를 마치면 마우스를 떼는 즉시 영역을 확정하거나, 너무 작으면 취소한다."""
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._state != "dragging":
            return
        if self._sel.width() < MIN_SELECTION or self._sel.height() < MIN_SELECTION:
            self._sel = QRect()
            self._state = "idle"
            self.update()
            return
        self._confirm()

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        """idle 상태에서 좌클릭 더블클릭하면 전체화면을 확정한다."""
        if e.button() == Qt.MouseButton.LeftButton and self._state == "idle":
            self._sel = QRect(self.rect())
            self._whole_screen = True
            self._confirm()

    def _cancel_drag(self) -> None:
        """드래그 중인 영역 지정을 취소하고 idle 상태로 되돌린다."""
        if self._state == "dragging":
            self._state = "idle"
            self._sel = QRect()
            self.update()

    # ---------- 키보드 ---------- #
    def keyPressEvent(self, e: QKeyEvent) -> None:
        """Esc(드래그 취소/오버레이 닫기)/M(돋보기 토글)/Ctrl+A(전체화면 확정)를 처리한다."""
        key = e.key()
        if key == Qt.Key.Key_Escape:
            if self._state == "dragging":
                self._cancel_drag()
            else:
                self.close()
            return
        if key == Qt.Key.Key_M:
            self._show_magnifier = not self._show_magnifier
            self.update()
            return
        if key == Qt.Key.Key_A and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._sel = QRect(self.rect())
            self._whole_screen = True
            self._confirm()

    # ---------- 확정 ---------- #
    def _capture_rect(self) -> QRect:
        """현재 선택을 잘라낼 물리 픽셀 사각형(pixmap 좌표)으로 바꾼다.

        고정 크기 모드는 표시 사각형(논리)을 다시 배율로 곱하면 반올림 때문에 1px씩
        어긋날 수 있어, 좌상단만 변환하고 크기는 입력한 물리 픽셀 그대로 쓴다.
        """
        bounds = self.shot.pixel_rect()
        if self._whole_screen:
            return bounds
        if self.fixed_size is None:
            return self.shot.physical_rect(self._sel).intersected(bounds)
        w, h = self.fixed_size
        s = self.shot.scale
        x = min(max(int(round(self._sel.left() * s)), 0), max(bounds.width() - w, 0))
        y = min(max(int(round(self._sel.top() * s)), 0), max(bounds.height() - h, 0))
        return QRect(x, y, w, h).intersected(bounds)

    def _confirm(self) -> None:
        """현재 선택 영역을 잘라내어 captured 신호로 방출하고 오버레이를 닫는다."""
        sel = self._sel
        if sel.isNull():
            return
        # 고정 크기는 입력값(물리 픽셀)이 기준이라, 배율로 줄인 표시 크기가 작아도 막지 않는다.
        if self.fixed_size is None and (sel.width() < MIN_SELECTION or sel.height() < MIN_SELECTION):
            return
        rect = self._capture_rect()
        if rect.isEmpty():
            return
        img = self.shot.crop_pixels(rect)
        clipped = (self.fixed_size is not None and not self._whole_screen
                   and (rect.width(), rect.height()) != self.fixed_size)
        self.fixed_clipped = clipped
        if clipped:
            logger.warning("고정 크기 캡처가 화면보다 커서 잘림: 요청 %dx%d -> %dx%d",
                           self.fixed_size[0], self.fixed_size[1], rect.width(), rect.height())
        logger.info("영역 캡처 확정: 물리 %dx%d at (%d, %d), 배율 %.2f",
                    rect.width(), rect.height(), rect.left(), rect.top(), self.shot.scale)
        self.close()
        self.captured.emit(img, QRect(rect))
