#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""텍스트 도구의 폰트/크기/색상/정렬 설정 패널.

'텍스트' 툴바 버튼의 화살표를 누르면 열리는 드롭다운 내용으로 쓰인다.
값이 바뀔 때마다 optionsChanged를 방출하며, 사용하는 쪽(MainWindow)이
현재 값을 읽어 편집 중인 텍스트 박스와 다음에 만들 텍스트 박스의 기본값에
반영한다.
"""

from typing import Optional

from PySide6.QtCore import QEvent, QObject, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QHideEvent, QIcon, QIntValidator, QKeyEvent
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFontComboBox, QHBoxLayout, QToolButton,
                                QVBoxLayout, QWidget)

from capture.config import (DEFAULT_TEXT_FONT_SIZE, TEXT_FONT_SIZE_MAX, TEXT_FONT_SIZE_MIN, TEXT_FONT_SIZES,
                            TEXT_ICON_PX, get_resource_path)
from capture.palette import ColorDropdownButton
from capture.shape_settings import TOGGLE_STYLE


class TextSettingsPanel(QWidget):
    """폰트 종류/크기/색상 + 볼드·이탤릭 + 좌우/상하 정렬 설정 UI."""

    optionsChanged = Signal()
    startColorPicking = Signal()   # 색상 추출 도구 클릭 시 발생 (MainWindow가 처리)

    def __init__(self, initial_color: QColor, settings: Optional[QSettings] = None,
                 parent: QWidget | None = None) -> None:
        """Args:
            initial_color: 시작 시 표시할 텍스트 색상.
            settings: 사용자 지정 색을 저장/불러올 QSettings (툴바 팔레트와 공유).
            parent: 부모 위젯.
        """
        super().__init__(parent)

        self._font_combo = QFontComboBox()
        self._font_combo.currentFontChanged.connect(lambda _f: self.optionsChanged.emit())

        # 마지막으로 확정된(범위 안) 글자 크기. 입력란에 범위 밖 값이 남아 있으면 이 값을 쓴다.
        self._committed_size = DEFAULT_TEXT_FONT_SIZE
        self._size_combo = QComboBox()
        self._size_combo.setEditable(True)
        self._size_combo.addItems([str(s) for s in TEXT_FONT_SIZES])
        self._size_combo.setCurrentText(str(DEFAULT_TEXT_FONT_SIZE))
        self._size_combo.setFixedWidth(56)
        # 숫자만 범위 안에서 입력받는다. 키를 누를 때마다 반영하면 "12"를 "120"으로
        # 고치는 중간 값("1")까지 선택된 텍스트에 적용되므로, 목록에서 고르거나 입력을
        # 마쳤을 때(Enter/포커스 이동)만 반영한다.
        self._size_combo.setValidator(QIntValidator(TEXT_FONT_SIZE_MIN, TEXT_FONT_SIZE_MAX, self._size_combo))
        # Enter를 누르면 editingFinished와 activated가 함께 오므로, 값이 실제로 바뀐 경우에만 알린다.
        self._size_combo.activated.connect(lambda _i: self._on_size_committed())
        self._size_combo.lineEdit().editingFinished.connect(self._on_size_committed)
        # "0"/"401"처럼 범위 밖 값은 검증기가 '입력 중'으로 남겨 두어 editingFinished가 오지
        # 않으므로, Enter·포커스 이동 시점을 직접 잡아 마지막 유효값으로 되돌린다.
        self._size_combo.lineEdit().installEventFilter(self)

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
        btn.setStyleSheet(TOGGLE_STYLE)
        return btn

    # ---------- 설정 복원 ---------- #
    def set_font(self, font: QFont) -> None:
        """저장된 폰트 종류/크기/볼드/이탤릭을 위젯에 반영한다 (앱 시작 시 복원용)."""
        self._font_combo.setCurrentFont(font)
        size = self._parse_size(str(font.pointSize()))
        self._committed_size = size if size is not None else DEFAULT_TEXT_FONT_SIZE
        self._size_combo.setCurrentText(str(self._committed_size))
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
        """현재 설정된 폰트(종류/크기/볼드/이탤릭)를 반환한다.

        크기 입력란에 범위 밖 값이 남아 있으면 먼저 마지막 유효값으로 되돌려, 화면에
        보이는 값과 실제로 적용되는 값이 어긋나지 않게 한다.
        """
        self._normalize_size_text()
        font = QFont(self._font_combo.currentFont())
        font.setPointSize(self._current_size())
        font.setBold(self._bold_btn.isChecked())
        font.setItalic(self._italic_btn.isChecked())
        return font

    def _on_size_committed(self) -> None:
        """글자 크기 입력을 마쳤을 때(목록 선택/Enter/포커스 이동) 값이 바뀌었으면 optionsChanged를 보낸다."""
        size = self._current_size()
        if size == self._committed_size:
            return
        self._committed_size = size
        self.optionsChanged.emit()

    @staticmethod
    def _parse_size(text: str) -> Optional[int]:
        """글자 크기 문자열을 정수로 바꾼다. 숫자가 아니거나 범위(TEXT_FONT_SIZE_MIN~MAX) 밖이면 None."""
        try:
            size = int(text.strip())
        except ValueError:
            return None
        return size if TEXT_FONT_SIZE_MIN <= size <= TEXT_FONT_SIZE_MAX else None

    def _current_size(self) -> int:
        """입력란의 글자 크기를 반환한다 (비었거나 범위 밖이면 마지막으로 확정된 값)."""
        size = self._parse_size(self._size_combo.currentText())
        return size if size is not None else self._committed_size

    def _normalize_size_text(self) -> None:
        """입력란 값이 비었거나 범위 밖이면 마지막으로 확정된 값으로 되돌린다."""
        if self._parse_size(self._size_combo.currentText()) is None:
            self._size_combo.setEditText(str(self._committed_size))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """크기 입력란에서 Enter를 누르거나 포커스가 빠질 때 범위 밖 값을 되돌린다 (이벤트는 그대로 전달)."""
        if watched is self._size_combo.lineEdit():
            etype = event.type()
            if etype == QEvent.Type.FocusOut:
                self._normalize_size_text()
            elif (etype == QEvent.Type.KeyPress and isinstance(event, QKeyEvent)
                  and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
                self._normalize_size_text()
        return super().eventFilter(watched, event)

    def hideEvent(self, event: QHideEvent) -> None:
        """드롭다운이 닫힐 때(포커스 이동 없이 닫히는 경우 포함) 범위 밖 입력을 되돌린다."""
        self._normalize_size_text()
        super().hideEvent(event)

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
