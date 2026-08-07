#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""값 두 개를 각각 입력 박스+슬라이더로 조절하는 범용 팝업.

밝기/대비, 색조/채도처럼 "값 두 개(-N~N)" 하나만 받는 효과 설정 팝업이
모두 재사용한다. 매번 항상 0/0(중앙값)에서 시작한다.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QSlider, QSpinBox,
                                QToolButton, QVBoxLayout, QWidget)

from capture.dialog_utils import strip_minmax_buttons

_STEP_BTN_PX = 24
_WIDTH_SCALE = 1.5     # 팝업 전체와 입력 박스 너비를 기본 크기의 이 배수로 넓힌다


class DualSliderDialog(QDialog):
    """값 두 개를 각각 입력 박스+슬라이더로 조절하는 대화상자 (항상 0/0에서 시작)."""

    def __init__(self, window_title: str, label1: str, label2: str, minimum: int, maximum: int,
                 parent: QWidget | None = None) -> None:
        """대화상자를 구성한다.

        Args:
            window_title: 창 제목(예: "밝기/대비 설정").
            label1: 첫 번째 값의 라벨(예: "명도").
            label2: 두 번째 값의 라벨(예: "대비").
            minimum: 허용 최솟값.
            maximum: 허용 최댓값.
            parent: 부모 위젯.
        """
        super().__init__(parent)
        self.setWindowTitle(window_title)
        strip_minmax_buttons(self)
        self._minimum = minimum
        self._maximum = maximum

        layout = QVBoxLayout(self)
        self.spin1, self.slider1 = self._add_row(layout, label1)
        self.spin2, self.slider2 = self._add_row(layout, label2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("확인(O)")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소(C)")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # 너비를 넓히기 전(기본 크기)의 sizeHint를 먼저 구해야, 이미 넓어진
        # 크기에 다시 배수를 곱해 이중으로 커지는 것을 피할 수 있다. 슬라이더는
        # Expanding 정책이라 팝업 최소 너비만 늘리면 자동으로 같이 넓어진다.
        natural_dialog_width = self.sizeHint().width()
        natural_spin1_width = self.spin1.sizeHint().width()
        natural_spin2_width = self.spin2.sizeHint().width()
        self.spin1.setFixedWidth(round(natural_spin1_width * _WIDTH_SCALE))
        self.spin2.setFixedWidth(round(natural_spin2_width * _WIDTH_SCALE))
        self.setMinimumWidth(round(natural_dialog_width * _WIDTH_SCALE))

    def _add_row(self, layout: QVBoxLayout, label_text: str) -> tuple[QSpinBox, QSlider]:
        """"라벨 + 입력 박스" 줄과 "− 슬라이더 +" 줄을 만들어 layout에 추가하고, 서로 연동한다."""
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel(label_text))
        top_row.addStretch()
        spin = QSpinBox(self)
        spin.setRange(self._minimum, self._maximum)
        spin.setValue(0)
        top_row.addWidget(spin)
        layout.addLayout(top_row)

        slider_row = QHBoxLayout()
        minus_btn = QToolButton(self)
        minus_btn.setText("−")
        minus_btn.setFixedSize(_STEP_BTN_PX, _STEP_BTN_PX)
        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setRange(self._minimum, self._maximum)
        slider.setValue(0)
        plus_btn = QToolButton(self)
        plus_btn.setText("+")
        plus_btn.setFixedSize(_STEP_BTN_PX, _STEP_BTN_PX)
        slider_row.addWidget(minus_btn)
        slider_row.addWidget(slider)
        slider_row.addWidget(plus_btn)
        layout.addLayout(slider_row)

        spin.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(spin.setValue)
        minus_btn.clicked.connect(lambda: slider.setValue(slider.value() - 1))
        plus_btn.clicked.connect(lambda: slider.setValue(slider.value() + 1))
        return spin, slider

    def value1(self) -> int:
        """확인(OK) 시 적용할 첫 번째 값을 반환한다."""
        return self.spin1.value()

    def value2(self) -> int:
        """확인(OK) 시 적용할 두 번째 값을 반환한다."""
        return self.spin2.value()
