#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""도형/선 도구가 공유하는 종류 목록, 기하 정의, 그리기 로직.

캔버스에 실제로 그려지는 도형과 하위 메뉴 아이콘이 항상 같은 모양을
쓰도록, 도형별 그리기 함수를 한 곳에 모아 양쪽이 재사용한다.
"""

import math
from typing import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

# (내부 키, 표시 라벨) 순서가 곧 하위 메뉴에 표시되는 순서.
SHAPE_KINDS: list[tuple[str, str]] = [
    ("rectangle", "사각형"), ("rounded_rect", "둥근 사각형"), ("ellipse", "타원"), ("circle", "원"),
    ("triangle", "삼각형"), ("diamond", "마름모"), ("pentagon", "오각형"), ("hexagon", "육각형"),
]
LINE_KINDS: list[tuple[str, str]] = [
    ("line", "직선"), ("line_arrow", "직선 (끝점 화살표)"), ("line_double_arrow", "직선 (양끝 화살표)"),
    ("freehand", "자유곡선"), ("freehand_arrow", "자유곡선 (끝점 화살표)"),
    ("freehand_double_arrow", "자유곡선 (양끝 화살표)"),
]
_LINE_KIND_KEYS: frozenset[str] = frozenset(key for key, _ in LINE_KINDS)
FREEHAND_KINDS: frozenset[str] = frozenset({"freehand", "freehand_arrow", "freehand_double_arrow"})
DOUBLE_ARROW_KINDS: frozenset[str] = frozenset({"line_double_arrow", "freehand_double_arrow"})
ARROW_KINDS: frozenset[str] = frozenset({"line_arrow", "freehand_arrow"}) | DOUBLE_ARROW_KINDS

DEFAULT_ROUNDED_RADIUS_RATIO = 0.25   # 둥근 사각형 기본 모서리 반지름 = 짧은 변 * 이 비율
MAX_ROUNDED_RADIUS_RATIO = 0.5        # 이 비율에서 짧은 변 양 끝이 완전한 반원이 된다
_ARROWHEAD_ANGLE_DEG = 25.0     # 화살표(^) 두 날개가 선 방향과 이루는 각도
_ARROWHEAD_LEN_RATIO = 3.0      # 화살표 날개 길이 = 두께 * 이 배수
_ARROWHEAD_LEN_MIN = 8.0        # 두께가 매우 얇아도 화살표가 보이도록 하는 최소 길이


def is_line_kind(kind: str) -> bool:
    """kind가 '선' 하위 메뉴(직선/자유곡선 계열)에 속하는지 여부."""
    return kind in _LINE_KIND_KEYS


def arrowhead_length(thickness: float) -> float:
    """두께에 비례한 화살표 날개 길이 (얇은 선에서도 보이도록 최솟값을 둔다)."""
    return max(thickness * _ARROWHEAD_LEN_RATIO, _ARROWHEAD_LEN_MIN)


def ngon_points(rect: QRectF, n: int, start_angle_deg: float) -> QPolygonF:
    """rect에 내접하는 타원 위에 균등 간격으로 놓인 n각형 꼭짓점을 만든다."""
    cx, cy = rect.center().x(), rect.center().y()
    rx, ry = rect.width() / 2, rect.height() / 2
    points = []
    for i in range(n):
        angle = math.radians(start_angle_deg + 360.0 * i / n)
        points.append(QPointF(cx + rx * math.cos(angle), cy + ry * math.sin(angle)))
    return QPolygonF(points)


def clamp_radius_ratio(ratio: float) -> float:
    """둥근 사각형 반지름 비율을 허용 범위 [0, MAX_ROUNDED_RADIUS_RATIO]로 제한한다."""
    return min(max(ratio, 0.0), MAX_ROUNDED_RADIUS_RATIO)


def rounded_radius(rect: QRectF, ratio: float) -> float:
    """rect 크기와 비율로 둥근 사각형의 실제 모서리 반지름(px)을 계산한다."""
    return min(rect.width(), rect.height()) * clamp_radius_ratio(ratio)


def draw_bbox_shape(painter: QPainter, kind: str, rect: QRectF,
                    radius_ratio: float = DEFAULT_ROUNDED_RADIUS_RATIO) -> None:
    """바운딩 박스 rect 안에 도형(사각형/타원/삼각형/마름모/오각형/육각형 등)을 그린다.

    Args:
        painter: 그릴 대상 painter (pen/brush는 호출 측에서 설정).
        kind: SHAPE_KINDS의 내부 키.
        rect: 도형의 바운딩 박스.
        radius_ratio: 둥근 사각형 전용. 모서리 반지름을 짧은 변 대비 비율로 지정.
    """
    if kind == "rectangle":
        painter.drawRect(rect)
    elif kind == "rounded_rect":
        radius = rounded_radius(rect, radius_ratio)
        painter.drawRoundedRect(rect, radius, radius)
    elif kind in ("ellipse", "circle"):
        painter.drawEllipse(rect)
    elif kind == "triangle":
        painter.drawPolygon(QPolygonF([QPointF(rect.center().x(), rect.top()),
                                        QPointF(rect.left(), rect.bottom()),
                                        QPointF(rect.right(), rect.bottom())]))
    elif kind == "diamond":
        painter.drawPolygon(QPolygonF([QPointF(rect.center().x(), rect.top()),
                                        QPointF(rect.right(), rect.center().y()),
                                        QPointF(rect.center().x(), rect.bottom()),
                                        QPointF(rect.left(), rect.center().y())]))
    elif kind == "pentagon":
        painter.drawPolygon(ngon_points(rect, 5, -90))
    elif kind == "hexagon":
        painter.drawPolygon(ngon_points(rect, 6, 0))


def lock_square(origin: QPointF, current: QPointF) -> QRectF:
    """origin에서 current로의 드래그를 가로세로 비율 1:1(정사각형)로 맞춘다."""
    dx, dy = current.x() - origin.x(), current.y() - origin.y()
    side = max(abs(dx), abs(dy))
    sx = side if dx >= 0 else -side
    sy = side if dy >= 0 else -side
    return QRectF(origin, QPointF(origin.x() + sx, origin.y() + sy)).normalized()


def snap_line_angle(origin: QPointF, current: QPointF) -> QPointF:
    """origin->current 각도를 가장 가까운 45도 단위(수평/수직/대각선)로 맞춘다."""
    dx, dy = current.x() - origin.x(), current.y() - origin.y()
    length = math.hypot(dx, dy)
    if length == 0:
        return QPointF(current)
    step = math.pi / 4
    angle = round(math.atan2(dy, dx) / step) * step
    return QPointF(origin.x() + length * math.cos(angle), origin.y() + length * math.sin(angle))


def _draw_open_arrowhead(painter: QPainter, tip: QPointF, direction_angle_rad: float, thickness: float) -> None:
    """직선/자유곡선 끝점에 삼각형이 아닌 '^' 모양(열린) 화살표를 그린다."""
    length = arrowhead_length(thickness)
    back = direction_angle_rad + math.pi
    for wing_angle in (back - math.radians(_ARROWHEAD_ANGLE_DEG), back + math.radians(_ARROWHEAD_ANGLE_DEG)):
        wing = QPointF(tip.x() + length * math.cos(wing_angle), tip.y() + length * math.sin(wing_angle))
        painter.drawLine(tip, wing)


def draw_line_kind(painter: QPainter, kind: str, p1: QPointF, p2: QPointF, thickness: float) -> None:
    """직선 종류(line/line_arrow/line_double_arrow)를 p1->p2 방향으로 그린다."""
    painter.drawLine(p1, p2)
    if kind in ARROW_KINDS:
        angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
        _draw_open_arrowhead(painter, p2, angle, thickness)
    if kind in DOUBLE_ARROW_KINDS:
        _draw_open_arrowhead(painter, p1, angle + math.pi, thickness)


def draw_bezier_kind(painter: QPainter, kind: str, points: Sequence[QPointF], thickness: float) -> None:
    """자유곡선 종류(freehand/freehand_arrow/freehand_double_arrow)를 4개 제어점
    (시작/제어1/제어2/끝)의 3차 베지에(cubic Bezier) 곡선으로 그린다."""
    p0, p1, p2, p3 = points
    path = QPainterPath()
    path.moveTo(p0)
    path.cubicTo(p1, p2, p3)
    painter.drawPath(path)
    if kind in ARROW_KINDS:
        _draw_open_arrowhead(painter, p3, _tangent_angle(p2, p3, (p1, p0)), thickness)
    if kind in DOUBLE_ARROW_KINDS:
        _draw_open_arrowhead(painter, p0, _tangent_angle(p1, p0, (p2, p3)), thickness)


def _tangent_angle(control: QPointF, end: QPointF, fallbacks: Sequence[QPointF]) -> float:
    """베지에 끝점에서 바깥쪽을 향하는 접선 각도(rad).

    제어점이 끝점과 겹치면 접선이 정의되지 않으므로, 다음 제어점을 차례로 대신 쓴다.
    """
    for ref in (control, *fallbacks):
        if ref != end:
            return math.atan2(end.y() - ref.y(), end.x() - ref.x())
    return 0.0


def make_icon_pixmap(kind: str, size: int, margin: int = 5) -> QPixmap:
    """도형/선 하위 메뉴에 쓸 작은 미리보기 아이콘을 생성한다."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(0x40, 0x40, 0x40))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    if is_line_kind(kind):
        if kind in FREEHAND_KINDS:
            draw_bezier_kind(painter, kind, [QPointF(rect.left(), rect.bottom()),
                                              QPointF(rect.left(), rect.top()),
                                              QPointF(rect.right(), rect.top()),
                                              QPointF(rect.right(), rect.bottom())], 1.6)
        else:
            draw_line_kind(painter, kind, QPointF(rect.left(), rect.bottom()),
                            QPointF(rect.right(), rect.top()), 1.6)
    else:
        draw_bbox_shape(painter, kind, rect)
    painter.end()
    return pixmap
