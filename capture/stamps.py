#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""스탬프 도구가 쓰는 스탬프 종류 목록과 벡터 그리기 로직.

패널 아이콘과 캔버스에 놓이는 스탬프가 항상 같은 모양이 되도록, 모든
스탬프를 이 모듈의 draw_stamp() 한 곳에서 QPainter 벡터로 그린다. 각
스탬프는 100x100 단위 좌표계로 정의하고 그릴 때 대상 사각형 크기로 늘리므로,
크기를 바꿔 다시 그려도 계단 없이 선명하다.
"""

import logging
from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform

logger = logging.getLogger(__name__)

_UNIT = 100.0   # 스탬프 정의 좌표계 한 변 길이

# 샘플(픽픽 스탬프) 기준 추정 색.
_RED = "#E05A3A"
_BLUE = "#3B7DBF"
_ORANGE = "#EE9A3A"
_GREEN = "#5FA38A"
_PURPLE = "#8E5CB5"
_SKY = "#3BA8C4"
_GRAY = "#5A5A5A"

_WHITE = QColor(0xFF, 0xFF, 0xFF)
_FLAG_POLE_COLOR = QColor(0x8A, 0x8A, 0x8A)
_NUMBER_RIM_COLOR = QColor(0xC8, 0xC8, 0xC8)       # 번호 스탬프 바깥 연회색 외곽선
_NUMBER_TEXT_OUTLINE = QColor(0, 0, 0, 110)        # 밝은 원 위 흰 숫자의 얇은 어두운 외곽선
_DARK_SYMBOL_COLOR = QColor(0x33, 0x33, 0x33)      # 밝은 채움 위 기호(원 안 화살표·?·! 등)의 색
# 이 밝기(0~255, 지각 휘도 근사) 이상인 채움 위에서는 흰색이 묻히므로, 번호 숫자에는
# 외곽선을 더하고 원·마름모 안 기호와 핀 구멍은 어두운 색으로 그린다.
# 번호 스탬프 기본 7색 중에서는 주황(168)·녹색(139.8)·하늘(138.5)이 해당한다.
_LIGHT_FILL_LUMA = 136.0
_NUMBER_FONT_FAMILIES: tuple[str, ...] = ("Segoe UI", "Arial", "Helvetica", "DejaVu Sans")

# (내부 키, 표시 라벨, 기본 색). 순서가 곧 패널 견본 순서.
NUMBER_STAMPS: list[tuple[str, str, str]] = [
    ("number_red", "번호 (빨강)", _RED), ("number_blue", "번호 (파랑)", _BLUE),
    ("number_orange", "번호 (주황)", _ORANGE), ("number_green", "번호 (녹색)", _GREEN),
    ("number_purple", "번호 (보라)", _PURPLE), ("number_sky", "번호 (하늘)", _SKY),
    ("number_gray", "번호 (회색)", _GRAY),
]

# 일반 스탬프: 패널의 줄 배치 그대로(줄마다 최대 7개). 일반 스탬프는 현재 팔레트 색으로
# 찍히므로 여기 색은 팔레트 색을 쓸 수 없을 때의 폴백(샘플 색)이다.
STAMP_ROWS: list[list[tuple[str, str, str]]] = [
    [("arrow_left", "왼쪽 화살표", _RED), ("arrow_up_left", "왼쪽 위 화살표", _RED),
     ("arrow_up", "위쪽 화살표", _RED), ("arrow_up_right", "오른쪽 위 화살표", _RED),
     ("arrow_right", "오른쪽 화살표", _RED), ("arrow_down_right", "오른쪽 아래 화살표", _RED),
     ("arrow_down", "아래쪽 화살표", _RED)],
    [("arrow_down_left", "왼쪽 아래 화살표", _RED), ("chevron_left", "왼쪽 꺾쇠", _RED),
     ("chevron_up", "위쪽 꺾쇠", _RED), ("chevron_right", "오른쪽 꺾쇠", _RED),
     ("chevron_down", "아래쪽 꺾쇠", _RED), ("return_left", "왼쪽 되돌림 화살표", _RED),
     ("return_right", "오른쪽 되돌림 화살표", _RED)],
    [("circle_arrow_up", "원형 위쪽 화살표", _RED), ("circle_arrow_right", "원형 오른쪽 화살표", _RED),
     ("circle_arrow_down", "원형 아래쪽 화살표", _RED), ("circle_arrow_left", "원형 왼쪽 화살표", _RED),
     ("bookmark", "북마크", _RED), ("pin_slim", "위치 핀 (가는)", _RED),
     ("pin_round", "위치 핀 (둥근)", _RED)],
    [("pushpin", "압정", _RED), ("flag", "깃발", _RED), ("tag", "태그", _RED)],
    [("question", "물음표", _BLUE), ("exclamation_blue", "느낌표 (파랑)", _BLUE),
     ("info", "정보", _BLUE), ("exclamation_red", "느낌표 (빨강)", _RED),
     ("prohibited", "금지", _RED), ("x_circle", "원형 X", _RED), ("heart", "하트", _RED)],
    [("plus", "더하기", _GREEN), ("minus", "빼기", _RED), ("plus_circle", "원형 더하기", _RED),
     ("minus_circle", "원형 빼기", _RED), ("check", "체크", _GREEN), ("x_mark", "X 표시", _RED)],
]

NUMBER_STAMP_KEYS: frozenset[str] = frozenset(key for key, _, _ in NUMBER_STAMPS)
_ALL_STAMPS: list[tuple[str, str, str]] = NUMBER_STAMPS + [entry for row in STAMP_ROWS for entry in row]
_LABELS: dict[str, str] = {key: label for key, label, _ in _ALL_STAMPS}
_DEFAULT_COLORS: dict[str, str] = {key: color for key, _, color in _ALL_STAMPS}
STAMP_KEYS: frozenset[str] = frozenset(_LABELS)


def is_number_stamp(key: str) -> bool:
    """key가 번호 스탬프(색 원 + 자동 증가 숫자)인지 여부."""
    return key in NUMBER_STAMP_KEYS


def stamp_label(key: str) -> str:
    """스탬프 키의 한국어 표시 이름 (모르는 키면 키 자체)."""
    return _LABELS.get(key, key)


def stamp_default_color(key: str) -> QColor:
    """번호 스탬프 견본 색, 또는 일반 스탬프의 폴백 색(샘플 색, 모르는 키면 빨강)."""
    return QColor(_DEFAULT_COLORS.get(key, _RED))


# ---------- 그리기 보조 ---------- #
def _fill(painter: QPainter, path: QPainterPath, color: QColor) -> None:
    """path를 테두리 없이 color로 채운다."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)


def _stroke(painter: QPainter, path: QPainterPath, color: QColor, width: float,
            cap: Qt.PenCapStyle = Qt.PenCapStyle.FlatCap,
            join: Qt.PenJoinStyle = Qt.PenJoinStyle.MiterJoin) -> None:
    """path를 채우기 없이 지정 두께의 획으로 그린다."""
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(cap)
    pen.setJoinStyle(join)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)


def _polyline(*points: tuple[float, float]) -> QPainterPath:
    """점들을 차례로 잇는 열린 경로."""
    path = QPainterPath()
    path.moveTo(*points[0])
    for p in points[1:]:
        path.lineTo(*p)
    return path


def _polygon(*points: tuple[float, float]) -> QPainterPath:
    """점들을 잇는 닫힌 다각형 경로."""
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    path.closeSubpath()
    return path


def _circle(cx: float, cy: float, r: float) -> QPainterPath:
    """중심 (cx, cy), 반지름 r인 원 경로."""
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def _rounded_rect(x: float, y: float, w: float, h: float, r: float) -> QPainterPath:
    """모서리가 둥근 사각형 경로."""
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def _rotated(painter: QPainter, degrees: float, scale: float = 1.0) -> None:
    """정의 좌표계 중심(50, 50)을 기준으로 회전(시계 방향)·확대한다."""
    painter.translate(_UNIT / 2, _UNIT / 2)
    painter.rotate(degrees)
    painter.scale(scale, scale)
    painter.translate(-_UNIT / 2, -_UNIT / 2)


def _fitted_text_path(text: str, box: QRectF) -> QPainterPath:
    """굵은 글꼴의 text 윤곽을 box 안에 비율을 유지한 채 가득 맞춘 경로.

    글자 수(1~3자리)와 무관하게 원 안에 들어가도록, 글리프의 실제 윤곽
    크기를 기준으로 가로·세로 중 더 빡빡한 쪽에 맞춘다.
    """
    font = QFont()
    # 기본 글꼴은 환경마다 달라(기호·바코드 글꼴로 잡히는 경우도 있다) 숫자 모양이
    # 바뀌지 않도록 흔한 산세리프 글꼴을 우선순위대로 지정한다.
    font.setFamilies(list(_NUMBER_FONT_FAMILIES))
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setBold(True)
    font.setPixelSize(100)
    path = QPainterPath()
    path.addText(0, 0, font, text)
    bounds = path.boundingRect()
    if bounds.width() <= 0 or bounds.height() <= 0:
        return QPainterPath()
    s = min(box.width() / bounds.width(), box.height() / bounds.height())
    transform = QTransform()
    transform.translate(box.center().x(), box.center().y())
    transform.scale(s, s)
    transform.translate(-bounds.center().x(), -bounds.center().y())
    return transform.map(path)


def _luma(color: QColor) -> float:
    """색의 지각 밝기 근사값(0~255)."""
    return 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()


def _symbol_color(fill: QColor) -> QColor:
    """채움 색 fill 위에 얹는 기호 색: 밝은 채움이면 어두운 회색, 아니면 흰색."""
    return QColor(_DARK_SYMBOL_COLOR if _luma(fill) >= _LIGHT_FILL_LUMA else _WHITE)


# ---------- 개별 스탬프 (모두 100x100 좌표계) ---------- #
_ARROW_W = 18.0
_ARROW_RIGHT = _polyline((10, 50), (80, 50))
_ARROW_HEAD_RIGHT = _polyline((50, 20), (80, 50), (50, 80))


def _draw_arrow(painter: QPainter, color: QColor, degrees: float) -> None:
    """오른쪽 화살표를 degrees만큼 회전해 그린다 (대각선은 칸을 채우도록 조금 키운다)."""
    painter.save()
    _rotated(painter, degrees, 1.12 if degrees % 90 else 1.0)
    _stroke(painter, _ARROW_RIGHT, color, _ARROW_W)
    _stroke(painter, _ARROW_HEAD_RIGHT, color, _ARROW_W)
    painter.restore()


def _draw_chevron(painter: QPainter, color: QColor, degrees: float) -> None:
    """오른쪽 꺾쇠(>)를 degrees만큼 회전해 그린다."""
    painter.save()
    _rotated(painter, degrees)
    _stroke(painter, _polyline((32, 18), (64, 50), (32, 82)), color, _ARROW_W)
    painter.restore()


def _draw_return(painter: QPainter, color: QColor, mirrored: bool) -> None:
    """위에서 내려와 꺾여 왼쪽(mirrored면 오른쪽)을 가리키는 되돌림 화살표."""
    painter.save()
    if mirrored:
        painter.translate(_UNIT, 0)
        painter.scale(-1, 1)
    body = QPainterPath()
    body.moveTo(74, 10)
    body.lineTo(74, 44)
    body.cubicTo(74, 60, 64, 68, 50, 68)
    body.lineTo(22, 68)
    _stroke(painter, body, color, 16)
    _stroke(painter, _polyline((42, 48), (22, 68), (42, 88)), color, 16)
    painter.restore()


def _draw_circle_arrow(painter: QPainter, color: QColor, degrees: float) -> None:
    """색 원 안에 흰 화살표를 degrees 방향으로 그린다."""
    _fill(painter, _circle(50, 50, 46), color)
    painter.save()
    _rotated(painter, degrees, 0.66)
    _stroke(painter, _ARROW_RIGHT, _symbol_color(color), _ARROW_W)
    _stroke(painter, _ARROW_HEAD_RIGHT, _symbol_color(color), _ARROW_W)
    painter.restore()


def _draw_bookmark(painter: QPainter, color: QColor) -> None:
    """아래쪽이 V자로 파인 북마크 리본."""
    _fill(painter, _polygon((24, 6), (76, 6), (76, 94), (50, 72), (24, 94)), color)


def _pin_path(head_y: float, radius: float, tip_y: float) -> QPainterPath:
    """원형 머리와 아래 뾰족한 끝으로 된 위치 핀 윤곽."""
    head = _circle(50, head_y, radius)
    shoulder = head_y + radius * 0.45
    half = radius * 0.89
    return head.united(_polygon((50 - half, shoulder), (50 + half, shoulder), (50, tip_y)))


def _draw_pin(painter: QPainter, color: QColor, head_y: float, radius: float) -> None:
    """가운데 흰 구멍이 있는 위치 핀."""
    _fill(painter, _pin_path(head_y, radius, 95), color)
    _fill(painter, _circle(50, head_y, radius * 0.4), _symbol_color(color))


def _draw_pushpin(painter: QPainter, color: QColor) -> None:
    """바늘이 왼쪽 아래를 향하도록 기울어진 압정."""
    painter.save()
    # 45도로 기울이면 윤곽이 오른쪽 위로 치우쳐 칸 밖으로 나가므로 중심으로 되돌린다.
    painter.translate(-6, 7)
    _rotated(painter, 45, 1.08)
    _fill(painter, _rounded_rect(29, 2, 42, 15, 3), color)
    _fill(painter, _polygon((37, 15), (63, 15), (60, 46), (40, 46)), color)
    _fill(painter, _rounded_rect(20, 43, 60, 16, 3), color)
    _stroke(painter, _polyline((50, 58), (50, 96)), color, 7, Qt.PenCapStyle.RoundCap)
    painter.restore()


def _draw_flag(painter: QPainter, color: QColor) -> None:
    """회색 깃대에 걸린 삼각 깃발 (깃대 색은 고정)."""
    _fill(painter, _rounded_rect(22, 6, 6, 90, 2), _FLAG_POLE_COLOR)
    _fill(painter, _polygon((28, 8), (82, 28), (28, 48)), color)


def _draw_tag(painter: QPainter, color: QColor) -> None:
    """끝이 왼쪽 위를 향한 가격표: 끝부분은 색, 몸통은 흰 바탕에 색 테두리."""
    painter.save()
    # 기울인 윤곽이 오른쪽 아래로 치우쳐 칸 밖으로 나가므로 중심으로 되돌린다.
    painter.translate(-7.5, -7.5)
    _rotated(painter, -45, 0.95)
    outline = _polygon((50, 4), (78, 30), (78, 94), (22, 94), (22, 30))
    _fill(painter, outline, _WHITE)
    tip = _polygon((50, 4), (78, 30), (78, 40), (22, 40), (22, 30))
    _fill(painter, tip, color)
    _stroke(painter, outline, color, 6, join=Qt.PenJoinStyle.RoundJoin)
    _fill(painter, _circle(50, 26, 5.5), _symbol_color(color))
    painter.restore()


def _draw_question(painter: QPainter, color: QColor) -> None:
    """색 원 안의 흰 물음표."""
    _fill(painter, _circle(50, 50, 46), color)
    hook = QPainterPath()
    arc = QRectF(34, 18, 32, 30)
    hook.arcMoveTo(arc, 165)
    hook.arcTo(arc, 165, -255)
    hook.lineTo(50, 60)
    _stroke(painter, hook, _symbol_color(color), 12, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin)
    _fill(painter, _circle(50, 75, 7.5), _symbol_color(color))


def _draw_exclamation(painter: QPainter, color: QColor) -> None:
    """색 원 안의 흰 느낌표."""
    _fill(painter, _circle(50, 50, 46), color)
    _fill(painter, _rounded_rect(43, 18, 14, 44, 6), _symbol_color(color))
    _fill(painter, _circle(50, 75, 7.5), _symbol_color(color))


def _draw_info(painter: QPainter, color: QColor) -> None:
    """모서리가 살짝 둥근 색 마름모 안의 흰 i."""
    diamond = _polygon((50, 8), (92, 50), (50, 92), (8, 50))
    _fill(painter, diamond, color)
    _stroke(painter, diamond, color, 8, join=Qt.PenJoinStyle.RoundJoin)
    _fill(painter, _circle(50, 30, 6.5), _symbol_color(color))
    _fill(painter, _rounded_rect(44, 41, 12, 34, 4), _symbol_color(color))


def _draw_prohibited(painter: QPainter, color: QColor) -> None:
    """흰 바탕 원 테두리에 왼쪽 위→오른쪽 아래 사선이 그어진 금지 표시."""
    _fill(painter, _circle(50, 50, 40), _WHITE)
    _stroke(painter, _circle(50, 50, 40), color, 12)
    _stroke(painter, _polyline((22, 22), (78, 78)), color, 12)


def _draw_x_circle(painter: QPainter, color: QColor) -> None:
    """색 원 안의 흰 X."""
    _fill(painter, _circle(50, 50, 46), color)
    _stroke(painter, _polyline((32, 32), (68, 68)), _symbol_color(color), 14)
    _stroke(painter, _polyline((68, 32), (32, 68)), _symbol_color(color), 14)


def _draw_heart(painter: QPainter, color: QColor) -> None:
    """하트."""
    path = QPainterPath()
    path.moveTo(50, 90)
    path.cubicTo(20, 68, 6, 50, 6, 32)
    path.cubicTo(6, 16, 18, 8, 30, 8)
    path.cubicTo(40, 8, 47, 14, 50, 22)
    path.cubicTo(53, 14, 60, 8, 70, 8)
    path.cubicTo(82, 8, 94, 16, 94, 32)
    path.cubicTo(94, 50, 80, 68, 50, 90)
    path.closeSubpath()
    _fill(painter, path, color)


def _plus_path(arm: float, thick: float) -> QPainterPath:
    """중심에서 arm만큼 뻗은 굵기 thick의 십자 경로."""
    half = thick / 2
    vertical = QPainterPath()
    vertical.addRect(QRectF(50 - half, 50 - arm, thick, 2 * arm))
    horizontal = QPainterPath()
    horizontal.addRect(QRectF(50 - arm, 50 - half, 2 * arm, thick))
    return vertical.united(horizontal)


def _minus_path(arm: float, thick: float) -> QPainterPath:
    """중심에서 좌우로 arm만큼 뻗은 굵기 thick의 가로 막대 경로."""
    path = QPainterPath()
    path.addRect(QRectF(50 - arm, 50 - thick / 2, 2 * arm, thick))
    return path


def _draw_circle_symbol(painter: QPainter, color: QColor, symbol: QPainterPath) -> None:
    """색 원 안에 흰 기호(symbol 경로)를 그린다."""
    _fill(painter, _circle(50, 50, 46), color)
    _fill(painter, symbol, _symbol_color(color))


def _draw_check(painter: QPainter, color: QColor) -> None:
    """굵은 체크 표시."""
    _stroke(painter, _polyline((12, 52), (38, 78), (90, 24)), color, 16)


def _draw_x_mark(painter: QPainter, color: QColor) -> None:
    """굵은 X 표시."""
    _stroke(painter, _polyline((16, 16), (84, 84)), color, 18)
    _stroke(painter, _polyline((84, 16), (16, 84)), color, 18)


def _draw_number(painter: QPainter, color: QColor, number: int) -> None:
    """연회색 외곽선 + 흰 테두리 + 색 원 + 흰 굵은 숫자(1~3자리 자동 맞춤)."""
    rim = QPen(_NUMBER_RIM_COLOR)
    rim.setWidthF(2.0)
    painter.setPen(rim)
    painter.setBrush(_WHITE)
    painter.drawPath(_circle(50, 50, 47))
    _fill(painter, _circle(50, 50, 40), color)
    digits = _fitted_text_path(str(number), QRectF(22, 27, 56, 46))
    if digits.isEmpty():
        logger.warning("번호 스탬프 숫자 윤곽을 만들지 못함(글꼴 없음 추정): %d", number)
        return
    if _luma(color) >= _LIGHT_FILL_LUMA:
        # 바깥쪽 절반만 보이도록 획을 먼저 그리고 그 위를 흰 글자로 덮는다.
        _stroke(painter, digits, _NUMBER_TEXT_OUTLINE, 4.0, join=Qt.PenJoinStyle.RoundJoin)
    _fill(painter, digits, _WHITE)


_DRAWERS: dict[str, Callable[[QPainter, QColor], None]] = {
    "arrow_left": lambda p, c: _draw_arrow(p, c, 180),
    "arrow_up_left": lambda p, c: _draw_arrow(p, c, 225),
    "arrow_up": lambda p, c: _draw_arrow(p, c, 270),
    "arrow_up_right": lambda p, c: _draw_arrow(p, c, 315),
    "arrow_right": lambda p, c: _draw_arrow(p, c, 0),
    "arrow_down_right": lambda p, c: _draw_arrow(p, c, 45),
    "arrow_down": lambda p, c: _draw_arrow(p, c, 90),
    "arrow_down_left": lambda p, c: _draw_arrow(p, c, 135),
    "chevron_left": lambda p, c: _draw_chevron(p, c, 180),
    "chevron_up": lambda p, c: _draw_chevron(p, c, 270),
    "chevron_right": lambda p, c: _draw_chevron(p, c, 0),
    "chevron_down": lambda p, c: _draw_chevron(p, c, 90),
    "return_left": lambda p, c: _draw_return(p, c, False),
    "return_right": lambda p, c: _draw_return(p, c, True),
    "circle_arrow_up": lambda p, c: _draw_circle_arrow(p, c, 270),
    "circle_arrow_right": lambda p, c: _draw_circle_arrow(p, c, 0),
    "circle_arrow_down": lambda p, c: _draw_circle_arrow(p, c, 90),
    "circle_arrow_left": lambda p, c: _draw_circle_arrow(p, c, 180),
    "bookmark": _draw_bookmark,
    "pin_slim": lambda p, c: _draw_pin(p, c, 30, 21),
    "pin_round": lambda p, c: _draw_pin(p, c, 35, 28),
    "pushpin": _draw_pushpin,
    "flag": _draw_flag,
    "tag": _draw_tag,
    "question": _draw_question,
    "exclamation_blue": _draw_exclamation,
    "info": _draw_info,
    "exclamation_red": _draw_exclamation,
    "prohibited": _draw_prohibited,
    "x_circle": _draw_x_circle,
    "heart": _draw_heart,
    "plus": lambda p, c: _fill(p, _plus_path(42, 24), c),
    "minus": lambda p, c: _fill(p, _minus_path(42, 24), c),
    "plus_circle": lambda p, c: _draw_circle_symbol(p, c, _plus_path(26, 13)),
    "minus_circle": lambda p, c: _draw_circle_symbol(p, c, _minus_path(26, 13)),
    "check": _draw_check,
    "x_mark": _draw_x_mark,
}


def draw_stamp(painter: QPainter, key: str, rect: QRectF, color: QColor, number: Optional[int] = None) -> None:
    """rect 안에 스탬프 key를 color로 그린다.

    painter의 기존 상태(변환·pen·brush·불투명도)는 그대로 이어받고, 끝나면
    호출 전 상태로 되돌린다. 모르는 키는 아무것도 그리지 않고 기록만 남긴다.

    Args:
        painter: 그릴 대상 painter.
        key: 스탬프 내부 키 (NUMBER_STAMPS 또는 STAMP_ROWS의 키).
        rect: 스탬프를 그릴 사각형. 정사각형이 아니면 그 비율대로 늘어난다.
        color: 스탬프 주 색 (흰 기호·깃대 등 고정 색 부분은 바뀌지 않는다).
        number: 번호 스탬프에 표시할 숫자. 번호 스탬프가 아니면 무시한다.
    """
    if rect.width() <= 0 or rect.height() <= 0:
        return
    drawer = _DRAWERS.get(key)
    if drawer is None and not is_number_stamp(key):
        logger.warning("알 수 없는 스탬프 키라 그리지 않음: %r", key)
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(rect.topLeft())
    painter.scale(rect.width() / _UNIT, rect.height() / _UNIT)
    try:
        if drawer is None:
            _draw_number(painter, QColor(color), number if number is not None else 1)
        else:
            drawer(painter, QColor(color))
    finally:
        painter.restore()


def make_stamp_pixmap(key: str, size: int, color: QColor, number: Optional[int] = None,
                      device_pixel_ratio: float = 1.0) -> QPixmap:
    """스탬프 하나를 size x size(논리 픽셀) 투명 픽스맵에 그린다.

    Args:
        key: 스탬프 내부 키.
        size: 결과 한 변 길이(논리 픽셀).
        color: 스탬프 주 색.
        number: 번호 스탬프에 표시할 숫자.
        device_pixel_ratio: 고DPI 아이콘용 배율. 캔버스 아이템은 1.0(실제 픽셀)을 쓴다.

    Returns:
        그려진 픽스맵.
    """
    side = max(int(round(size * device_pixel_ratio)), 1)
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    draw_stamp(painter, key, QRectF(0, 0, side, side), color, number)
    painter.end()
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    return pixmap
