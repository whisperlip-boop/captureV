#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""그리기 색상 선택 팔레트 위젯.

항상 보이는 20색 고정 팔레트(+ 그 아래 사용자 지정 색 줄)와, 현재 색상 박스
아래 화살표를 누르면 열리는 테마 색/표준 색/사용자 지정 색 드롭다운 두 가지
방식을 함께 제공한다. 드롭다운(색 박스+화살표+메뉴) 부분은 ColorDropdownButton
으로 분리해, 텍스트 설정처럼 색상 선택이 필요한 다른 곳에서도 재사용한다.
"""

import logging
from typing import Optional

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QColorDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                                QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget, QWidgetAction)

from capture.config import (COLOR_BOX_PX, MAX_CUSTOM_COLORS, PALETTE_COLORS, STANDARD_COLORS,
                             THEME_COLORS, THEME_COLORS_NATIVE_8COL, get_resource_path)
from capture.dialog_utils import strip_minmax_buttons

logger = logging.getLogger(__name__)

_SWATCH_PX = 18
_COLUMNS = 10
_SETTINGS_KEY = "custom_colors"

# #drawArrow 화살표 버튼 공통 스타일. 툴바 QSS에 의존하지 않고 어디서든
# (텍스트 설정 팝업 등) 그대로 재사용할 수 있도록 위젯에 직접 지정한다.
_ARROW_STYLE = (
    "QToolButton#drawArrow { border: none; }"
    "QToolButton#drawArrow:hover { background-color: #F0F0F0; border: 1px solid #D9D9D9; }"
    "QToolButton#drawArrow:checked { background-color: #E1E1E1; border: 1px solid #C7C7C7; }"
    "QToolButton#drawArrow:checked:hover { background-color: #E1E1E1; border: 1px solid #C7C7C7; }"
    "QToolButton#drawArrow::menu-indicator { subcontrol-origin: padding; subcontrol-position: center; }")


class ColorDropdownButton(QWidget):
    """색상 박스 + 화살표 + 테마 색/표준 색/사용자 지정 색 드롭다운.

    항상 보이는 팔레트(PaletteWidget)와 텍스트 설정 팝업처럼, 같은 방식의
    색상 선택 드롭다운이 필요한 곳 어디서나 재사용할 수 있도록 분리했다.
    """

    colorChanged = Signal(QColor)
    startColorPicking = Signal()   # 색상 추출 도구 클릭 시 발생 (사용하는 쪽이 처리)

    def __init__(self, initial_color: QColor, settings: Optional[QSettings] = None,
                 label: Optional[str] = None, vertical: bool = True, parent=None,
                 settings_key: str = _SETTINGS_KEY) -> None:
        """Args:
            initial_color: 시작 시 표시할 색상.
            settings: 사용자 지정 색을 저장/불러올 QSettings. None이면 저장하지 않는다.
            label: 색상 박스 아래 표시할 라벨. None이면 표시하지 않는다.
            vertical: True면 박스/라벨/화살표를 세로로, False면 박스+화살표를 가로로 배치.
            parent: 부모 위젯.
            settings_key: 사용자 지정 색 목록을 저장할 설정 키. 그리기 색/텍스트 색처럼
                같은 QSettings를 공유하는 인스턴스가 여럿일 때 서로 덮어쓰지 않도록
                구분해서 지정해야 한다.
        """
        super().__init__(parent)
        self._color = QColor(initial_color)
        self._settings = settings
        self._settings_key = settings_key
        self._custom_colors: list[str] = self._load_custom_colors()

        self._color_box = QLabel()
        self._color_box.setFixedSize(COLOR_BOX_PX, COLOR_BOX_PX)
        self._update_color_box()

        self._menu = QMenu(self)
        self._rebuild_menu()

        arrow = QToolButton()
        arrow.setObjectName("drawArrow")
        arrow.setStyleSheet(_ARROW_STYLE)
        arrow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        arrow.setMenu(self._menu)
        arrow.setCheckable(True)

        if vertical:
            arrow.setFixedHeight(14)
            arrow.setFixedWidth(COLOR_BOX_PX)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(self._color_box, alignment=Qt.AlignmentFlag.AlignHCenter)
            if label:
                lbl = QLabel(label)
                lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                layout.addWidget(lbl)
            layout.addWidget(arrow, alignment=Qt.AlignmentFlag.AlignHCenter)
        else:
            arrow.setFixedSize(14, COLOR_BOX_PX)
            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(2)
            layout.addWidget(self._color_box)
            layout.addWidget(arrow)

    # ---------- 현재 색상 ---------- #
    def _update_color_box(self) -> None:
        """현재 색상 박스의 배경을 갱신한다."""
        self._color_box.setStyleSheet(
            f"background-color: {self._color.name()}; border: 1px solid #999999;")

    def color(self) -> QColor:
        """현재 선택된 색상."""
        return QColor(self._color)

    def set_color(self, color: QColor) -> None:
        """현재 색상을 설정하고 필요 시 colorChanged를 방출한다."""
        if color == self._color:
            return
        self._color = QColor(color)
        self._update_color_box()
        self.colorChanged.emit(self._color)

    # ---------- 사용자 지정 색 ---------- #
    def _load_custom_colors(self) -> list[str]:
        """설정에서 사용자 지정 색 목록을 불러온다."""
        if self._settings is None:
            return []
        value = self._settings.value(self._settings_key, [])
        if isinstance(value, str):     # 항목이 1개면 QSettings가 문자열로 반환할 수 있음
            value = [value]
        return list(value)[:MAX_CUSTOM_COLORS]

    def _save_custom_colors(self) -> None:
        """사용자 지정 색 목록을 설정에 저장한다."""
        if self._settings is not None:
            self._settings.setValue(self._settings_key, self._custom_colors)

    def custom_colors(self) -> list[str]:
        """현재 사용자 지정 색 목록(hex 문자열)의 복사본을 반환한다."""
        return list(self._custom_colors)

    def _known_theme_colors(self) -> set[str]:
        """테마 색 + 표준 색의 hex 집합을 반환한다."""
        known = {c.upper() for c in STANDARD_COLORS}
        for column in THEME_COLORS:
            known.update(c.upper() for c in column)
        return known

    def add_custom_color(self, color: QColor) -> None:
        """테마/표준 색에 없는 색이면 사용자 지정 색에 추가한다 (최대 MAX_CUSTOM_COLORS개, 오래된 것부터 교체)."""
        hex_color = color.name().upper()
        if hex_color in self._known_theme_colors():
            return
        existing = [c.upper() for c in self._custom_colors]
        if hex_color in existing:
            return
        self._custom_colors.append(hex_color)
        if len(self._custom_colors) > MAX_CUSTOM_COLORS:
            self._custom_colors.pop(0)
        self._save_custom_colors()
        self._rebuild_menu()

    # ---------- 드롭다운 메뉴 ---------- #
    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def make_swatch(self, color: QColor) -> QPushButton:
        """클릭하면 해당 색을 선택하는 작은 스와치 버튼을 만든다."""
        btn = QPushButton()
        btn.setFixedSize(_SWATCH_PX, _SWATCH_PX)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {color.name()}; border: 1px solid #999999; }}"
            f"QPushButton:hover {{ border: 1px solid #333333; }}")
        btn.clicked.connect(lambda _checked=False, c=QColor(color): self._pick(c))
        return btn

    @staticmethod
    def make_empty_swatch() -> QPushButton:
        """아직 채워지지 않은 사용자 지정 색 자리를 나타내는 빈 스와치를 만든다."""
        empty = QPushButton()
        empty.setFixedSize(_SWATCH_PX, _SWATCH_PX)
        empty.setEnabled(False)
        empty.setStyleSheet("QPushButton { background: transparent; border: 1px solid #cccccc; }")
        return empty

    def _pick(self, color: QColor) -> None:
        """드롭다운/팔레트에서 색을 선택했을 때 처리한다."""
        self.set_color(color)
        self._menu.close()

    def _rebuild_menu(self) -> None:
        """테마 색/표준 색/사용자 지정 색 드롭다운 내용을 다시 만든다."""
        self._menu.clear()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        layout.addWidget(QLabel("테마 색"))
        theme_grid = QGridLayout()
        theme_grid.setSpacing(2)
        for col, column_colors in enumerate(THEME_COLORS):
            for row, hex_color in enumerate(column_colors):
                theme_grid.addWidget(self.make_swatch(QColor(hex_color)), row, col)
        layout.addLayout(theme_grid)

        layout.addWidget(self._separator())
        layout.addWidget(QLabel("표준 색"))
        standard_grid = QGridLayout()
        standard_grid.setSpacing(2)
        for col, hex_color in enumerate(STANDARD_COLORS):
            standard_grid.addWidget(self.make_swatch(QColor(hex_color)), 0, col)
        layout.addLayout(standard_grid)

        layout.addWidget(self._separator())
        layout.addWidget(QLabel("사용자 지정 색"))
        custom_grid = QGridLayout()
        custom_grid.setSpacing(2)
        for col in range(MAX_CUSTOM_COLORS):
            if col < len(self._custom_colors):
                custom_grid.addWidget(self.make_swatch(QColor(self._custom_colors[col])), 0, col)
            else:
                custom_grid.addWidget(self.make_empty_swatch(), 0, col)
        layout.addLayout(custom_grid)

        layout.addWidget(self._separator())
        pick_btn = QPushButton(QIcon(str(get_resource_path("img/pipette.png"))), "색상 추출 도구")
        pick_btn.setIconSize(QSize(18, 18))    # 버튼 높이(약 24~26px)에 맞춘 아이콘 크기
        pick_btn.clicked.connect(self._start_color_picking)
        layout.addWidget(pick_btn)

        other_btn = QPushButton("다른 색...")
        other_btn.clicked.connect(self._open_other_color_dialog)
        layout.addWidget(other_btn)

        action = QWidgetAction(self._menu)
        action.setDefaultWidget(content)
        self._menu.addAction(action)

    # ---------- 색상 추출 / 다른 색 ---------- #
    def _start_color_picking(self) -> None:
        """색상 추출 모드를 시작하도록 상위(MainWindow)에 요청한다."""
        self._menu.close()
        self.startColorPicking.emit()

    def _open_other_color_dialog(self) -> None:
        """Qt 기본 색상 다이얼로그를 열어 임의의 색을 선택한다."""
        self._menu.close()
        for i, hex_color in enumerate(self._custom_colors[:MAX_CUSTOM_COLORS]):
            QColorDialog.setCustomColor(i, QColor(hex_color))
        dlg = QColorDialog(self._color, self)
        dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        strip_minmax_buttons(dlg)
        self._compact_color_dialog(dlg)
        if dlg.exec() == QColorDialog.DialogCode.Accepted:
            color = dlg.selectedColor()
            if color.isValid():
                self.add_custom_color(color)
                self.set_color(color)

    @staticmethod
    def _compact_color_dialog(dlg: QColorDialog) -> None:
        """Qt 기본 색상 다이얼로그를 우리 테마 색으로 채우고 라벨을 정리한다.

        QColorDialog은 내부 구조가 공개 API가 아니라 findChildren()으로 위젯을
        찾아 텍스트/너비 같은 표시 속성만 조정한다. 라벨 텍스트·너비, HTML 입력칸
        너비 조정, setStandardColor()는 안전하게 동작하지만, 숫자 입력용
        QSpinBox는 너비를 강제로 줄이면 표시가 깨지는 PySide6 렌더링 문제가
        있어 건드리지 않는다.
        """
        # "Basic colors"(8열 x 6행 = 48개로 고정) 라벨을 "Theme color"로 바꾸고
        # THEME_COLORS_NATIVE_8COL로 채운다. setStandardColor(index, ...)는
        # 열 우선(index = col*6 + row) 순서로 채워진다.
        for label in dlg.findChildren(QLabel):
            if label.text().replace("&", "").strip().lower() == "basic colors":
                label.setText("Theme color")
        for col, column_colors in enumerate(THEME_COLORS_NATIVE_8COL):
            for row, hex_color in enumerate(column_colors):
                dlg.setStandardColor(col * 6 + row, QColor(hex_color))

        short_labels = {"hue": "H", "sat": "S", "val": "V",
                        "red": "R", "green": "G", "blue": "B", "html": "#"}
        for label in dlg.findChildren(QLabel):
            key = label.text().replace("&", "").rstrip(":").strip().lower()
            if key in short_labels:
                label.setText(short_labels[key])
                label.setFixedWidth(16)

        # H/S/V 스핀박스와 비슷한 너비로 맞춘다 (스핀박스 자체는 너비를 강제로
        # 줄이면 표시가 깨지므로, HTML 입력칸만 그 너비를 참고해 조정한다).
        html_edit = dlg.findChild(QLineEdit, "qt_colorname_lineedit")
        if html_edit is not None:
            html_edit.setFixedWidth(90)

            def strip_hash_prefix(_color: QColor = QColor()) -> None:
                """라벨이 이미 '#'을 표시하므로 입력칸에는 값만 남기고 '#'은 지운다.

                내부적으로 색이 바뀔 때마다 Qt가 입력칸 텍스트를 '#RRGGBB'
                형태로 되돌리는데, 그 갱신이 끝난 뒤(QueuedConnection)에
                다시 지워야 '#'이 남지 않는다. 즉시 연결하면 우리 코드가
                먼저 지운 뒤 Qt가 곧바로 '#'을 다시 채워버린다.
                """
                html_edit.setText(html_edit.text().lstrip("#"))

            dlg.currentColorChanged.connect(strip_hash_prefix, Qt.ConnectionType.QueuedConnection)
            strip_hash_prefix()
        dlg.adjustSize()


class PaletteWidget(QWidget):
    """현재 색상 표시 박스(+ 하위 메뉴) + 항상 보이는 색상 팔레트 그리드.

    팔레트 또는 하위 메뉴에서 색을 고르면 colorChanged 신호가 발생하고,
    현재 색상 박스에 바로 반영된다.
    """

    colorChanged = Signal(QColor)
    startColorPicking = Signal()   # 색상 추출 도구 클릭 시 발생 (MainWindow가 처리)

    def __init__(self, initial_color: QColor, settings: Optional[QSettings] = None, parent=None) -> None:
        """Args:
            initial_color: 시작 시 표시할 색상.
            settings: 사용자 지정 색을 저장/불러올 QSettings. None이면 저장하지 않는다.
            parent: 부모 위젯.
        """
        super().__init__(parent)
        self._color_ctrl = ColorDropdownButton(initial_color, settings, label="색", vertical=True,
                                                settings_key="draw_custom_colors")
        self._color_ctrl.colorChanged.connect(self.colorChanged.emit)
        self._color_ctrl.startColorPicking.connect(self.startColorPicking.emit)

        grid = QGridLayout()
        grid.setSpacing(2)
        for i, hex_color in enumerate(PALETTE_COLORS):
            row, col = divmod(i, _COLUMNS)
            grid.addWidget(self._color_ctrl.make_swatch(QColor(hex_color)), row, col)
        self._palette_grid = grid
        self._custom_row = len(PALETTE_COLORS) // _COLUMNS    # 고정 색 아래, 사용자 지정 색 줄
        self._populate_custom_row()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._color_ctrl)
        layout.addLayout(grid)

    def color(self) -> QColor:
        """현재 선택된 색상."""
        return self._color_ctrl.color()

    def set_color(self, color: QColor) -> None:
        """현재 색상을 설정하고 필요 시 colorChanged를 방출한다."""
        self._color_ctrl.set_color(color)

    def add_custom_color(self, color: QColor) -> None:
        """테마/표준 색에 없는 색이면 사용자 지정 색에 추가한다."""
        self._color_ctrl.add_custom_color(color)
        self._populate_custom_row()

    def _populate_custom_row(self) -> None:
        """항상 보이는 팔레트의 사용자 지정 색 줄을 현재 목록으로 다시 그린다."""
        custom_colors = self._color_ctrl.custom_colors()
        for col in range(MAX_CUSTOM_COLORS):
            item = self._palette_grid.itemAtPosition(self._custom_row, col)
            if item is not None:
                old = item.widget()
                self._palette_grid.removeWidget(old)
                old.deleteLater()
            if col < len(custom_colors):
                swatch = self._color_ctrl.make_swatch(QColor(custom_colors[col]))
            else:
                swatch = self._color_ctrl.make_empty_swatch()
            self._palette_grid.addWidget(swatch, self._custom_row, col)
