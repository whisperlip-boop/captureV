#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""'캔버스 크기 변경' 팝업.

캔버스 경계(가로/세로)와 확장 시 채울 배경색을 지정한다. 이미지 내용을
리샘플링하는 '이미지 크기 변경'과는 다른 기능이다.
"""

from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFrame,
                                QHBoxLayout, QLabel, QPushButton, QSpinBox, QToolButton, QVBoxLayout,
                                QWidget)

from capture.config import (MINI_TOOL_DIVIDER_COLOR, MINI_TOOL_ICON_PX, NEW_CANVAS_SIZE_MAX,
                             NEW_CANVAS_SIZE_MIN, get_resource_path)
from capture.dialog_utils import strip_minmax_buttons
from capture.palette import ColorDropdownButton

_BG_SWATCH_SIZE = (72, 64)

# (표시 이름, (가로, 세로)). 크기가 None인 두 항목("현재 이미지 크기"/"클립보드")은
# 다이얼로그를 열 때/클립보드 상태에 따라 동적으로 계산한다.
_PRESETS: list[tuple[str, Optional[tuple[int, int]]]] = [
    ("현재 이미지 크기", None),
    ("클립보드", None),
    ("1920x1080 (FHD)", (1920, 1080)),
    ("1366x768 (HD)", (1366, 768)),
    ("1600x900 (HD+)", (1600, 900)),
    ("1280x800 (WXGA)", (1280, 800)),
    ("1024x768 (XGA)", (1024, 768)),
    ("800x600 (SVGA)", (800, 600)),
    ("640x480 (VGA)", (640, 480)),
]


class CanvasSizeDialog(QDialog):
    """프리셋/가로/세로/배경색으로 캔버스 크기를 지정하는 대화상자."""

    def __init__(self, image_width: int, image_height: int, bg_color: QColor,
                 parent: QWidget | None = None) -> None:
        """대화상자를 구성한다.

        Args:
            image_width: 현재 캔버스의 가로 픽셀 크기 ("현재 이미지 크기" 프리셋 값).
            image_height: 현재 캔버스의 세로 픽셀 크기.
            bg_color: 배경색 박스의 초기 색상.
            parent: 부모 위젯.
        """
        super().__init__(parent)
        self.setWindowTitle("캔버스 크기 변경")
        strip_minmax_buttons(self)

        self._image_width = image_width
        self._image_height = image_height
        self._bg_color = QColor(bg_color)

        outer = QVBoxLayout(self)

        panel = QFrame(self)
        panel.setObjectName("canvasSizePanel")
        panel.setStyleSheet("QFrame#canvasSizePanel { background-color: #F3F3F3; border-radius: 4px; }")
        panel_layout = QVBoxLayout(panel)

        title = QLabel("캔버스 크기")
        title.setStyleSheet("font-weight: bold;")
        panel_layout.addWidget(title)

        panel_layout.addWidget(QLabel("프리셋"))
        self.preset_combo = QComboBox(panel)
        for name, _size in _PRESETS:
            self.preset_combo.addItem(name)
        panel_layout.addWidget(self.preset_combo)

        row = QHBoxLayout()

        size_col = QVBoxLayout()
        size_col.addWidget(QLabel("가로 (Width)"))
        self.width_spin = QSpinBox(panel)
        self.width_spin.setRange(NEW_CANVAS_SIZE_MIN, NEW_CANVAS_SIZE_MAX)
        self.width_spin.setSuffix(" px")
        self.width_spin.setValue(image_width)
        size_col.addWidget(self.width_spin)

        self.swap_btn = QToolButton(panel)
        self.swap_btn.setIcon(QIcon(str(get_resource_path("img/rotation_canvas.png"))))
        self.swap_btn.setIconSize(QSize(MINI_TOOL_ICON_PX, MINI_TOOL_ICON_PX))
        self.swap_btn.setToolTip("가로/세로 값 바꾸기")
        size_col.addWidget(self.swap_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        size_col.addWidget(QLabel("세로 (Height)"))
        self.height_spin = QSpinBox(panel)
        self.height_spin.setRange(NEW_CANVAS_SIZE_MIN, NEW_CANVAS_SIZE_MAX)
        self.height_spin.setSuffix(" px")
        self.height_spin.setValue(image_height)
        size_col.addWidget(self.height_spin)
        row.addLayout(size_col)

        divider = QFrame(panel)
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        divider.setMinimumHeight(140)
        divider.setStyleSheet(f"QFrame {{ color: {MINI_TOOL_DIVIDER_COLOR}; }}")
        row.addWidget(divider)

        bg_col = QVBoxLayout()
        bg_col.addWidget(QLabel("배경색"))
        self.bg_swatch = QPushButton(panel)
        self.bg_swatch.setFixedSize(*_BG_SWATCH_SIZE)
        self._update_bg_swatch()
        bg_col.addWidget(self.bg_swatch)
        bg_col.addStretch()
        row.addLayout(bg_col)

        panel_layout.addLayout(row)
        outer.addWidget(panel)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.swap_btn.clicked.connect(self._on_swap)
        self.bg_swatch.clicked.connect(self._pick_bg_color)

    def _set_size(self, width: int, height: int) -> None:
        """가로/세로 입력 박스에 값을 반영한다 (스핀박스 범위를 벗어나면 잘린다)."""
        self.width_spin.setValue(width)
        self.height_spin.setValue(height)

    def _on_preset_changed(self, index: int) -> None:
        """프리셋 선택에 따라 가로/세로 값을 갱신한다."""
        name, size = _PRESETS[index]
        if size is not None:
            self._set_size(*size)
            return
        if name == "현재 이미지 크기":
            self._set_size(self._image_width, self._image_height)
        else:   # 클립보드: 이미지가 없으면 값을 바꾸지 않는다.
            image = QGuiApplication.clipboard().image()
            if not image.isNull():
                self._set_size(image.width(), image.height())

    def _on_swap(self) -> None:
        """가로/세로 값을 서로 바꾼다."""
        width, height = self.width_spin.value(), self.height_spin.value()
        self.width_spin.setValue(height)
        self.height_spin.setValue(width)

    def _update_bg_swatch(self) -> None:
        """배경색 박스의 표시 색을 갱신한다."""
        self.bg_swatch.setStyleSheet(
            f"QPushButton {{ background-color: {self._bg_color.name()}; border: 1px solid #999999; }}")

    def _pick_bg_color(self) -> None:
        """기존 '다른 색' 팝업과 동일한 색상 다이얼로그를 열어 배경색을 선택한다."""
        dlg = QColorDialog(self._bg_color, self)
        dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        strip_minmax_buttons(dlg)
        ColorDropdownButton._compact_color_dialog(dlg)
        if dlg.exec() == QColorDialog.DialogCode.Accepted:
            color = dlg.selectedColor()
            if color.isValid():
                self._bg_color = color
                self._update_bg_swatch()

    def target_size(self) -> tuple[int, int]:
        """확인(OK) 시 적용할 목표 (width, height)를 반환한다."""
        return self.width_spin.value(), self.height_spin.value()

    def background_color(self) -> QColor:
        """확인(OK) 시 적용할 배경색을 반환한다."""
        return QColor(self._bg_color)
