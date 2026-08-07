#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""텍스트 도구의 폰트/크기/색상/정렬 설정 패널.

'텍스트' 툴바 버튼의 화살표를 누르면 열리는 드롭다운 내용으로 쓰인다.
값이 바뀔 때마다 optionsChanged를 방출하며, 사용하는 쪽(MainWindow)이
현재 값을 읽어 편집 중인 텍스트 박스와 다음에 만들 텍스트 박스의 기본값에
반영한다.
"""

import logging
from typing import Optional

from PySide6.QtCore import QSettings, QSize, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFontComboBox, QHBoxLayout, QToolButton,
                                QVBoxLayout, QWidget)

from capture.config import DEFAULT_TEXT_FONT_SIZE, TEXT_FONT_SIZES, TEXT_ICON_PX, get_resource_path
from capture.palette import ColorDropdownButton

logger = logging.getLogger(__name__)

_TOGGLE_STYLE = (
    "QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; }"
    "QToolButton:hover { background-color: #F0F0F0; border: 1px solid #D9D9D9; }"
    "QToolButton:checked { background-color: #E1E1E1; border: 1px solid #C7C7C7; }"
    "QToolButton:checked:hover { background-color: #E1E1E1; border: 1px solid #C7C7C7; }")


class TextSettingsPanel(QWidget):
    """폰트 종류/크기/색상 + 볼드·이탤릭 + 좌우/상하 정렬 설정 UI."""

    optionsChanged = Signal()
    startColorPicking = Signal()   # 색상 추출 도구 클릭 시 발생 (MainWindow가 처리)

    def __init__(self, initial_color: QColor, settings: Optional[QSettings] = None, parent=None) -> None:
        """Args:
            initial_color: 시작 시 표시할 텍스트 색상.
            settings: 사용자 지정 색을 저장/불러올 QSettings (툴바 팔레트와 공유).
            parent: 부모 위젯.
        """
        super().__init__(parent)

        self._font_combo = QFontComboBox()
        self._font_combo.currentFontChanged.connect(lambda _f: self.optionsChanged.emit())

        self._size_combo = QComboBox()
        self._size_combo.setEditable(True)
        self._size_combo.addItems([str(s) for s in TEXT_FONT_SIZES])
        self._size_combo.setCurrentText(str(DEFAULT_TEXT_FONT_SIZE))
        self._size_combo.setFixedWidth(56)
        self._size_combo.currentTextChanged.connect(lambda _t: self.optionsChanged.emit())

        self._color_ctrl = ColorDropdownButton(QColor(initial_color), settings, label=None, vertical=False,
                                                settings_key="text_custom_colors")
        self._color_ctrl.colorChanged.connect(lambda _c: self.optionsChanged.emit())
        self._color_ctrl.startColorPicking.connect(self.startColorPicking.emit)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        top_row.addWidget(self._font_combo)
        top_row.addWidget(self._size_combo)
        top_row.addWidget(self._color_ctrl)

        self._bold_btn = self._make_toggle("bold.png", "볼드")
        self._italic_btn = self._make_toggle("italic.png", "이탤릭")

        self._align_h_group = QButtonGroup(self)
        self._align_h_group.setExclusive(True)
        self._left_btn = self._make_toggle("left.png", "왼쪽 맞춤")
        self._center_btn = self._make_toggle("Center.png", "가운데 맞춤")
        self._right_btn = self._make_toggle("right.png", "오른쪽 맞춤")
        for b in (self._left_btn, self._center_btn, self._right_btn):
            self._align_h_group.addButton(b)
        self._left_btn.setChecked(True)

        self._align_v_group = QButtonGroup(self)
        self._align_v_group.setExclusive(True)
        self._top_btn = self._make_toggle("top-alignment.png", "위쪽 맞춤")
        self._middle_btn = self._make_toggle("vertical-alignment.png", "가운데 맞춤(세로)")
        self._bottom_btn = self._make_toggle("bottom-alignment.png", "아래쪽 맞춤")
        for b in (self._top_btn, self._middle_btn, self._bottom_btn):
            self._align_v_group.addButton(b)
        self._top_btn.setChecked(True)

        for btn in (self._bold_btn, self._italic_btn, self._left_btn, self._center_btn, self._right_btn,
                    self._top_btn, self._middle_btn, self._bottom_btn):
            btn.toggled.connect(lambda _checked=False: self.optionsChanged.emit())

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(2)
        for btn in (self._bold_btn, self._italic_btn, self._left_btn, self._center_btn, self._right_btn,
                    self._top_btn, self._middle_btn, self._bottom_btn):
            bottom_row.addWidget(btn)
        bottom_row.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addLayout(top_row)
        layout.addLayout(bottom_row)

    @staticmethod
    def _make_toggle(icon_file: str, tooltip: str) -> QToolButton:
        """이름 없이 아이콘만 있는 체크 가능한 버튼을 만든다."""
        btn = QToolButton()
        btn.setIcon(QIcon(str(get_resource_path(f"img/{icon_file}"))))
        btn.setIconSize(QSize(TEXT_ICON_PX, TEXT_ICON_PX))
        btn.setCheckable(True)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(_TOGGLE_STYLE)
        return btn

    # ---------- 설정 복원 ---------- #
    def set_font(self, font: QFont) -> None:
        """저장된 폰트 종류/크기/볼드/이탤릭을 위젯에 반영한다 (앱 시작 시 복원용)."""
        self._font_combo.setCurrentFont(font)
        self._size_combo.setCurrentText(str(font.pointSize()))
        self._bold_btn.setChecked(font.bold())
        self._italic_btn.setChecked(font.italic())

    def set_align(self, align_h: str, align_v: str) -> None:
        """저장된 가로/세로 정렬을 위젯에 반영한다 (앱 시작 시 복원용)."""
        {"left": self._left_btn, "center": self._center_btn,
         "right": self._right_btn}.get(align_h, self._left_btn).setChecked(True)
        {"top": self._top_btn, "middle": self._middle_btn,
         "bottom": self._bottom_btn}.get(align_v, self._top_btn).setChecked(True)

    # ---------- 조회 ---------- #
    def current_font(self) -> QFont:
        """현재 설정된 폰트(종류/크기/볼드/이탤릭)를 반환한다."""
        font = QFont(self._font_combo.currentFont())
        font.setPointSize(self._current_size())
        font.setBold(self._bold_btn.isChecked())
        font.setItalic(self._italic_btn.isChecked())
        return font

    def _current_size(self) -> int:
        try:
            return max(1, int(self._size_combo.currentText()))
        except ValueError:
            return DEFAULT_TEXT_FONT_SIZE

    def color(self) -> QColor:
        """현재 설정된 텍스트 색상."""
        return self._color_ctrl.color()

    def align_h(self) -> str:
        """현재 설정된 가로 정렬 ('left'/'center'/'right')."""
        if self._center_btn.isChecked():
            return "center"
        if self._right_btn.isChecked():
            return "right"
        return "left"

    def align_v(self) -> str:
        """현재 설정된 세로 정렬 ('top'/'middle'/'bottom')."""
        if self._middle_btn.isChecked():
            return "middle"
        if self._bottom_btn.isChecked():
            return "bottom"
        return "top"

    # ---------- 색상 추출 결과 반영 ---------- #
    def add_custom_color(self, color: QColor) -> None:
        """색상 추출 등으로 얻은 색을 사용자 지정 색에 추가한다."""
        self._color_ctrl.add_custom_color(color)

    def set_color(self, color: QColor) -> None:
        """텍스트 색상을 설정한다 (optionsChanged 발생)."""
        self._color_ctrl.set_color(color)
