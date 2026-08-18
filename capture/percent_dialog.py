#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""'%' 값 하나를 입력 박스와 슬라이더로 함께 조절하는 범용 팝업.

모자이크/흐리게처럼 "강도(%)" 하나만 받는 효과 설정 팝업이 모두 재사용한다.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QSlider, QSpinBox,
                                QToolButton, QVBoxLayout, QWidget)

from capture.dialog_utils import strip_minmax_buttons

_STEP_BTN_PX = 24
_WIDTH_SCALE = 1.5     # 팝업 전체와 입력 박스 너비를 기본 크기의 이 배수로 넓힌다


class PercentSettingsDialog(QDialog):
    """"%" 강도를 입력 박스와 슬라이더로 함께 조절하는 대화상자."""

    def __init__(self, window_title: str, label_text: str, initial_percent: int, minimum: int,
                 maximum: int, parent: QWidget | None = None) -> None:
        """대화상자를 구성한다.

        Args:
            window_title: 창 제목(예: "모자이크 설정").
            label_text: 값 위에 표시할 라벨(예: "모자이크 %").
            initial_percent: 슬라이더/입력 박스의 초기값(%).
            minimum: 허용 최솟값(%).
            maximum: 허용 최댓값(%).
            parent: 부모 위젯.
        """
        super().__init__(parent)
        self.setWindowTitle(window_title)
        strip_minmax_buttons(self)

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel(label_text))
        top_row.addStretch()
        self.percent_spin = QSpinBox(self)
        self.percent_spin.setRange(minimum, maximum)
        self.percent_spin.setValue(initial_percent)
        top_row.addWidget(self.percent_spin)
        layout.addLayout(top_row)

        slider_row = QHBoxLayout()
        self.minus_btn = QToolButton(self)
        self.minus_btn.setText("−")
        self.minus_btn.setFixedSize(_STEP_BTN_PX, _STEP_BTN_PX)
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(initial_percent)
        self.plus_btn = QToolButton(self)
        self.plus_btn.setText("+")
        self.plus_btn.setFixedSize(_STEP_BTN_PX, _STEP_BTN_PX)
        slider_row.addWidget(self.minus_btn)
        slider_row.addWidget(self.slider)
        slider_row.addWidget(self.plus_btn)
        layout.addLayout(slider_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.percent_spin.valueChanged.connect(self.slider.setValue)
        self.slider.valueChanged.connect(self.percent_spin.setValue)
        self.minus_btn.clicked.connect(lambda: self.slider.setValue(self.slider.value() - 1))
        self.plus_btn.clicked.connect(lambda: self.slider.setValue(self.slider.value() + 1))

        # 너비를 넓히기 전(기본 크기)의 sizeHint를 먼저 구해야, 이미 넓어진
        # 크기에 다시 배수를 곱해 이중으로 커지는 것을 피할 수 있다. 슬라이더는
        # Expanding 정책이라 팝업 최소 너비만 늘리면 자동으로 같이 넓어진다.
        natural_dialog_width = self.sizeHint().width()
        natural_spin_width = self.percent_spin.sizeHint().width()
        self.percent_spin.setFixedWidth(round(natural_spin_width * _WIDTH_SCALE))
        self.setMinimumWidth(round(natural_dialog_width * _WIDTH_SCALE))

    def percent(self) -> int:
        """확인(OK) 시 적용할 값(%)을 반환한다."""
        return self.percent_spin.value()
