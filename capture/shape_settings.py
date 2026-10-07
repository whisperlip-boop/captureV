#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""'도형' 버튼 하위 메뉴: 도형/선 종류를 고르는 아이콘 갤러리 패널.

항목을 클릭하면 그리기의 브러시/지우개/형광펜 전환과 동일하게 즉시 그
종류가 활성 하위 도구가 된다 (팝업은 선택과 동시에 상위에서 닫는다).
"""

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from capture.config import SHAPE_ICON_PX, get_resource_path
from capture.shapes import LINE_KINDS, SHAPE_KINDS, make_icon_pixmap

_SHAPE_GRID_COLUMNS = 4
_LINE_GRID_COLUMNS = 3   # 한 줄에 직선 계열, 다음 줄에 자유곡선 계열

# 준비된 이미지 파일을 쓴다. 없는 종류만 make_icon_pixmap()으로 대체 생성한다.
_CUSTOM_ICON_FILES: dict[str, str] = {
    "rectangle": "rectangle.png",
    "rounded_rect": "rounded-rectangle.png",
    "ellipse": "ellipse.png",
    "circle": "circle.png",
    "triangle": "triangle.png",
    "diamond": "rhombus.png",
    "pentagon": "pentagon.png",
    "hexagon": "hexagon.png",
    "line": "diagonal-line.png",
    "line_arrow": "diagonal-line-arrow.png",
    "line_double_arrow": "doublehead-arrow.png",
    "freehand": "free-curved.png",
    "freehand_arrow": "free-curved-arrow.png",
    "freehand_double_arrow": "doubelhead-free-curved-arrow.png",
}

_TOGGLE_STYLE = (
    "QToolButton { border: 1px solid transparent; border-radius: 4px; }"
    "QToolButton:hover { background-color: #F0F0F0; border: 1px solid #D9D9D9; }"
    "QToolButton:checked { background-color: #E1E1E1; border: 1px solid #C7C7C7; }"
    "QToolButton:checked:hover { background-color: #E1E1E1; border: 1px solid #C7C7C7; }")


class ShapeSubtoolPanel(QWidget):
    """도형(사각형/타원/.../육각형) + 선(직선/자유곡선, 화살표 없음/끝점/양끝) 갤러리."""

    subtoolChosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Args:
            parent: 부모 위젯.

        어떤 하위 도구를 실제로 쓸지는 별도로 기억/복원되지만(main_window의
        shape_subtool 설정), 그 사실이 갤러리에 미리 선택된 것처럼 보이면
        이번 실행에서 아직 아무것도 고르지 않았는데도 무언가 골라둔 것처럼
        보여 혼동을 준다. 그래서 이 팝업은 항상 아무 항목도 선택 표시 없이
        시작하고, 실제로 클릭해야만 그 항목이 선택 표시된다.
        """
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        layout.addWidget(QLabel("도형"))
        layout.addLayout(self._make_grid(SHAPE_KINDS, _SHAPE_GRID_COLUMNS))
        layout.addWidget(QLabel("선"))
        layout.addLayout(self._make_grid(LINE_KINDS, _LINE_GRID_COLUMNS))

    def _make_grid(self, kinds: list[tuple[str, str]], columns: int) -> QGridLayout:
        """kinds의 각 항목을 아이콘 버튼으로 만들어 격자에 배치한다."""
        grid = QGridLayout()
        grid.setSpacing(2)
        for i, (key, label) in enumerate(kinds):
            row, col = divmod(i, columns)
            icon_file = _CUSTOM_ICON_FILES.get(key)
            icon = (QIcon(str(get_resource_path(f"img/{icon_file}"))) if icon_file
                    else QIcon(make_icon_pixmap(key, SHAPE_ICON_PX)))
            btn = QToolButton()
            btn.setIcon(icon)
            btn.setIconSize(QSize(SHAPE_ICON_PX, SHAPE_ICON_PX))
            btn.setCheckable(True)
            btn.setToolTip(label)
            btn.setStyleSheet(_TOGGLE_STYLE)
            btn.clicked.connect(lambda _checked=False, k=key: self.subtoolChosen.emit(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            grid.addWidget(btn, row, col)
        return grid
