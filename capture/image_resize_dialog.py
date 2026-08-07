#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""'이미지 크기 변경' 팝업.

이미지의 실제 픽셀 크기를 지정 크기 또는 지정 비율로 리샘플링한다
(캔버스 경계만 바꾸는 '캔버스 크기 변경'과는 다른 기능).
"""

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                                QRadioButton, QSpinBox, QVBoxLayout, QWidget)

from capture.config import NEW_CANVAS_SIZE_MAX, NEW_CANVAS_SIZE_MIN
from capture.dialog_utils import strip_minmax_buttons

PERCENT_MIN: int = 1
PERCENT_MAX: int = 1000


class ImageResizeDialog(QDialog):
    """가로/세로 픽셀 또는 비율(%)로 이미지 크기를 변경하는 대화상자."""

    def __init__(self, image_width: int, image_height: int, parent: QWidget | None = None) -> None:
        """대화상자를 구성한다.

        Args:
            image_width: 현재 이미지의 가로 픽셀 크기.
            image_height: 현재 이미지의 세로 픽셀 크기.
            parent: 부모 위젯.
        """
        super().__init__(parent)
        self.setWindowTitle("이미지 크기 변경")
        strip_minmax_buttons(self)

        self._image_width = image_width
        self._image_height = image_height
        # 가로/세로 비율 고정 시 기준이 되는 값. 비율 고정을 다시 켤 때마다
        # 그 시점의 가로/세로 값으로 갱신되어, 사용자가 고정을 풀고 자유롭게
        # 값을 바꾼 뒤 다시 고정해도 그 값 기준으로 비율이 맞춰진다.
        self._ratio_base_w = image_width
        self._ratio_base_h = image_height
        self._updating = False

        layout = QVBoxLayout(self)

        self.size_radio = QRadioButton("이미지의 크기를 지정")
        self.percent_radio = QRadioButton("확대/축소할 비율을 지정")
        self.size_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.size_radio)
        mode_group.addButton(self.percent_radio)
        layout.addWidget(self.size_radio)

        size_box = QWidget(self)
        size_layout = QVBoxLayout(size_box)
        size_layout.setContentsMargins(24, 0, 0, 0)
        self.ratio_check = QCheckBox("가로 세로 비율 고정")
        self.ratio_check.setChecked(True)
        size_layout.addWidget(self.ratio_check)

        size_form = QFormLayout()
        self.width_spin = QSpinBox(size_box)
        self.width_spin.setRange(NEW_CANVAS_SIZE_MIN, NEW_CANVAS_SIZE_MAX)
        self.width_spin.setSuffix(" px")
        self.width_spin.setValue(image_width)
        self.height_spin = QSpinBox(size_box)
        self.height_spin.setRange(NEW_CANVAS_SIZE_MIN, NEW_CANVAS_SIZE_MAX)
        self.height_spin.setSuffix(" px")
        self.height_spin.setValue(image_height)
        size_form.addRow("가로", self.width_spin)
        size_form.addRow("세로", self.height_spin)
        size_layout.addLayout(size_form)
        layout.addWidget(size_box)

        layout.addWidget(self.percent_radio)
        percent_box = QWidget(self)
        percent_layout = QVBoxLayout(percent_box)
        percent_layout.setContentsMargins(24, 0, 0, 0)
        self.percent_spin = QSpinBox(percent_box)
        self.percent_spin.setRange(PERCENT_MIN, PERCENT_MAX)
        self.percent_spin.setValue(100)
        self.percent_spin.setSuffix(" %")
        percent_layout.addWidget(self.percent_spin)
        layout.addWidget(percent_box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.size_radio.toggled.connect(self._update_enabled)
        self.ratio_check.toggled.connect(self._on_ratio_toggled)
        self.width_spin.valueChanged.connect(self._on_width_changed)
        self.height_spin.valueChanged.connect(self._on_height_changed)
        self._update_enabled()

    def _update_enabled(self) -> None:
        """선택된 라디오 버튼에 따라 반대쪽 입력 영역을 비활성화한다."""
        is_size = self.size_radio.isChecked()
        self.ratio_check.setEnabled(is_size)
        self.width_spin.setEnabled(is_size)
        self.height_spin.setEnabled(is_size)
        self.percent_spin.setEnabled(not is_size)

    def _on_ratio_toggled(self, checked: bool) -> None:
        """비율 고정을 다시 켤 때 현재 가로/세로 값을 새 기준 비율로 삼는다."""
        if checked:
            self._ratio_base_w = self.width_spin.value()
            self._ratio_base_h = self.height_spin.value()

    def _on_width_changed(self, value: int) -> None:
        """비율 고정 상태에서 가로 값 변경 시 세로 값을 비율대로 맞춘다."""
        if self._updating or not self.ratio_check.isChecked():
            return
        self._updating = True
        new_h = round(value * self._ratio_base_h / self._ratio_base_w)
        self.height_spin.setValue(min(max(new_h, self.height_spin.minimum()), self.height_spin.maximum()))
        self._updating = False

    def _on_height_changed(self, value: int) -> None:
        """비율 고정 상태에서 세로 값 변경 시 가로 값을 비율대로 맞춘다."""
        if self._updating or not self.ratio_check.isChecked():
            return
        self._updating = True
        new_w = round(value * self._ratio_base_w / self._ratio_base_h)
        self.width_spin.setValue(min(max(new_w, self.width_spin.minimum()), self.width_spin.maximum()))
        self._updating = False

    def target_size(self) -> tuple[int, int]:
        """확인(OK) 시 적용할 목표 (width, height)를 반환한다."""
        if self.size_radio.isChecked():
            return self.width_spin.value(), self.height_spin.value()
        pct = self.percent_spin.value() / 100.0
        return max(1, round(self._image_width * pct)), max(1, round(self._image_height * pct))
