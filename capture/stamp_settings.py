#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""'스탬프' 버튼 하위 메뉴: 번호 스탬프 7색과 일반 스탬프를 고르는 갤러리 패널.

'도형' 패널(ShapeSubtoolPanel)과 같은 QMenu + QWidgetAction 구조로 쓰인다.
칸을 클릭하면 stampChosen을 보내고(팝업은 상위에서 닫는다), '다음 번호'
스핀박스를 바꾸면 nextNumberChanged를 보낸다(팝업은 열린 채 유지).
"""

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeyEvent
from PySide6.QtWidgets import (QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QSpinBox, QToolButton,
                                QVBoxLayout, QWidget)

from capture.config import (STAMP_CELL_PX, STAMP_GRID_COLUMNS, STAMP_ICON_PX, STAMP_NUMBER_MAX,
                            STAMP_NUMBER_MIN)
from capture.shape_settings import TOGGLE_STYLE
from capture.stamps import NUMBER_STAMPS, STAMP_ROWS, make_stamp_pixmap

# 아이콘을 2배 해상도로 그려 두면 고DPI(125~200%) 화면에서도 흐리지 않다.
_ICON_DPR = 2.0


class _MenuSpinBox(QSpinBox):
    """팝업 메뉴 안에서 Enter를 눌러도 메뉴가 닫히지 않는 스핀박스.

    QSpinBox는 Enter를 처리한 뒤 이벤트를 무시(ignore)해 부모 QMenu로 넘기고,
    QMenu는 그것을 '항목 실행'으로 받아 팝업을 닫는다.
    """

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Enter/Return은 값 확정만 하고 부모로 넘기지 않는다."""
        super().keyPressEvent(event)
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()


class StampPanel(QWidget):
    """번호 스탬프(다음 번호 + 7색 견본) + 일반 스탬프 격자 갤러리."""

    stampChosen = Signal(str)
    nextNumberChanged = Signal(int)

    def __init__(self, current_key: Optional[str] = None, next_number: int = STAMP_NUMBER_MIN,
                 general_color: Optional[QColor] = None, parent: QWidget | None = None) -> None:
        """Args:
            current_key: 처음에 선택 표시할 스탬프 키 (None이면 선택 표시 없음).
            next_number: '다음 번호' 초기값.
            general_color: 일반 스탬프 아이콘 색(현재 팔레트 색). None이면 스탬프별 샘플 색.
            parent: 부모 위젯.
        """
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}
        self._general_color: Optional[QColor] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(QLabel("번호 스탬프"))
        header.addStretch(1)
        header.addWidget(QLabel("다음 번호"))
        self._number_spin = _MenuSpinBox()
        self._number_spin.setRange(STAMP_NUMBER_MIN, STAMP_NUMBER_MAX)
        self._number_spin.setValue(min(max(next_number, STAMP_NUMBER_MIN), STAMP_NUMBER_MAX))
        self._number_spin.setAccessibleName("다음 번호")
        self._number_spin.setToolTip("다음에 놓을 번호 스탬프의 숫자")
        self._number_spin.valueChanged.connect(self._on_spin_changed)
        header.addWidget(self._number_spin)
        layout.addLayout(header)

        number_grid = QGridLayout()
        number_grid.setSpacing(2)
        for col, (key, label, _color) in enumerate(NUMBER_STAMPS):
            number_grid.addWidget(self._make_button(key, label), 0, col)
        layout.addLayout(number_grid)
        self._refresh_number_icons()

        layout.addWidget(QLabel("일반 스탬프"))
        grid = QGridLayout()
        grid.setSpacing(2)
        for row, entries in enumerate(STAMP_ROWS):
            for col, (key, label, _color) in enumerate(entries[:STAMP_GRID_COLUMNS]):
                grid.addWidget(self._make_button(key, label), row, col)
        layout.addLayout(grid)
        self._refresh_general_icons(general_color)

        self.set_current(current_key)

    def _make_button(self, key: str, label: str) -> QToolButton:
        """스탬프 한 칸(체크형 아이콘 버튼)을 만든다. 아이콘은 호출 측이 채운다."""
        btn = QToolButton()
        btn.setIconSize(QSize(STAMP_ICON_PX, STAMP_ICON_PX))
        btn.setFixedSize(STAMP_CELL_PX, STAMP_CELL_PX)
        btn.setCheckable(True)
        btn.setToolTip(label)
        btn.setAccessibleName(label)
        btn.setStyleSheet(TOGGLE_STYLE)
        btn.clicked.connect(lambda _checked=False, k=key: self.stampChosen.emit(k))
        self._group.addButton(btn)
        self._buttons[key] = btn
        return btn

    def _refresh_number_icons(self) -> None:
        """번호 스탬프 견본을 현재 '다음 번호'로 다시 그린다."""
        number = self._number_spin.value()
        for key, _label, color in NUMBER_STAMPS:
            self._buttons[key].setIcon(QIcon(make_stamp_pixmap(key, STAMP_ICON_PX, QColor(color), number,
                                                               device_pixel_ratio=_ICON_DPR)))

    def _refresh_general_icons(self, color: Optional[QColor]) -> None:
        """일반 스탬프 아이콘을 color로 다시 그린다 (None·무효 색이면 스탬프별 샘플 색)."""
        self._general_color = QColor(color) if color is not None and color.isValid() else None
        for entries in STAMP_ROWS:
            for key, _label, fallback in entries[:STAMP_GRID_COLUMNS]:
                icon_color = self._general_color if self._general_color is not None else QColor(fallback)
                self._buttons[key].setIcon(QIcon(make_stamp_pixmap(key, STAMP_ICON_PX, icon_color,
                                                                   device_pixel_ratio=_ICON_DPR)))

    def set_general_color(self, color: QColor) -> None:
        """일반 스탬프 아이콘을 현재 팔레트 색으로 맞춘다 (색이 같으면 다시 그리지 않는다)."""
        if self._general_color is not None and color.isValid() and QColor(color) == self._general_color:
            return
        self._refresh_general_icons(color)

    def _on_spin_changed(self, value: int) -> None:
        """사용자가 '다음 번호'를 바꾸면 견본을 갱신하고 알린다."""
        self._refresh_number_icons()
        self.nextNumberChanged.emit(value)

    def set_current(self, key: Optional[str]) -> None:
        """key 칸만 선택 표시한다 (None이거나 모르는 키면 모두 해제)."""
        btn = self._buttons.get(key) if key else None
        if btn is not None:
            btn.setChecked(True)
            return
        # 배타 그룹은 마지막 선택을 그냥 끌 수 없어 잠시 배타를 풀고 해제한다.
        self._group.setExclusive(False)
        for b in self._buttons.values():
            b.setChecked(False)
        self._group.setExclusive(True)

    def set_next_number(self, value: int) -> None:
        """'다음 번호'를 신호 없이 바꾼다 (탭 전환·스탬프 배치·되돌리기 반영용)."""
        value = min(max(value, STAMP_NUMBER_MIN), STAMP_NUMBER_MAX)
        if value == self._number_spin.value():
            return
        self._number_spin.blockSignals(True)
        self._number_spin.setValue(value)
        self._number_spin.blockSignals(False)
        self._refresh_number_icons()
