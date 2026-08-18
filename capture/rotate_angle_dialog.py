#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""자유로운 각도로 회전하는 팝업.

회전 방향(시계/반시계)과 0.0~359.9도 사이의 회전 각도를 입력받는다.
"""

from typing import Optional

from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QDoubleSpinBox, QHBoxLayout,
                                QLabel, QRadioButton, QVBoxLayout, QWidget)

from capture.dialog_utils import strip_minmax_buttons

ANGLE_MIN = 0.0
ANGLE_MAX = 359.9
ANGLE_DECIMALS = 1
ANGLE_STEP = 1.0    # 위/아래 화살표를 누를 때의 증감 단위(직접 입력은 소수점 1자리까지 가능)


class _AngleSpinBox(QDoubleSpinBox):
    """화살표는 항상 1도 단위로, 360도를 기준으로 순환하는 스핀박스.

    QDoubleSpinBox의 기본 순환(setWrapping)은 최댓값을 넘으면 곧바로
    최솟값으로, 최솟값을 밑돌면 곧바로 최댓값(359.9)으로 튀어 화살표의
    1도 단위 감각과 어긋난다(0도에서 아래로 한 번 누르면 359.0도가
    아니라 359.9도가 됨). 화살표 클릭(stepBy)만 360을 나머지로 하는
    순환 계산으로 대체해, 0도 아래는 359.0도로 이어지게 한다.

    다만 setWrapping(True) 자체는 그대로 켜 둬야 한다. 이 값이 꺼져
    있으면(기본값) 값이 최솟값(0.0)일 때 Qt가 아래쪽 화살표 버튼을
    자동으로 비활성화해버려(최댓값일 때는 위쪽 버튼), 정확히 0.0도인
    기본 상태에서는 화살표를 눌러도 반응이 없는 것처럼 보인다. 실제
    순환 계산은 stepBy 재정의가 전담하므로 setWrapping의 기본 계산
    로직 자체는 쓰이지 않고, 버튼을 계속 눌릴 수 있게 하는 용도로만
    남겨둔다.
    """

    def stepBy(self, steps: int) -> None:
        self.setValue((self.value() + steps * self.singleStep()) % 360.0)


class RotateAngleDialog(QDialog):
    """회전 방향과 각도(0.0~359.9도)를 함께 입력받는 대화상자."""

    def __init__(self, initial_angle: float, initial_clockwise: bool, parent: Optional[QWidget] = None) -> None:
        """대화상자를 구성한다.

        Args:
            initial_angle: 회전 각도의 초기값(0.0~359.9).
            initial_clockwise: True면 '시계 방향'을, False면 '시계 반대 방향'을 초기 선택한다.
            parent: 부모 위젯.
        """
        super().__init__(parent)
        self.setWindowTitle("회전")
        strip_minmax_buttons(self)

        layout = QVBoxLayout(self)

        self._cw_btn = QRadioButton("시계 방향")
        self._ccw_btn = QRadioButton("시계 반대 방향")
        direction_group = QButtonGroup(self)
        direction_group.addButton(self._cw_btn)
        direction_group.addButton(self._ccw_btn)
        (self._cw_btn if initial_clockwise else self._ccw_btn).setChecked(True)
        layout.addWidget(self._cw_btn)
        layout.addWidget(self._ccw_btn)

        angle_row = QHBoxLayout()
        angle_row.addWidget(QLabel("회전 각도"))
        angle_row.addStretch()
        self._angle_spin = _AngleSpinBox(self)
        self._angle_spin.setDecimals(ANGLE_DECIMALS)
        self._angle_spin.setRange(ANGLE_MIN, ANGLE_MAX)
        self._angle_spin.setSingleStep(ANGLE_STEP)
        self._angle_spin.setWrapping(True)
        self._angle_spin.setValue(initial_angle)
        angle_row.addWidget(self._angle_spin)
        layout.addLayout(angle_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("확인(O)")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소(C)")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def angle(self) -> float:
        """확인(OK) 시 적용할 회전 각도(0.0~359.9, 방향 무관 크기)를 반환한다."""
        return self._angle_spin.value()

    def is_clockwise(self) -> bool:
        """확인(OK) 시 적용할 회전 방향(True: 시계 방향, False: 반시계 방향)을 반환한다."""
        return self._cw_btn.isChecked()
