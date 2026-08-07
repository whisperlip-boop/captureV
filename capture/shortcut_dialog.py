#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""캡처 단축키 설정 다이얼로그.

PicPick 옵션 화면처럼 Shift/Ctrl/Alt 체크박스와 키 선택 콤보박스로 단축키를
지정한다. 키를 "없음"으로 두면 해당 캡처의 전역 단축키를 사용하지 않는다.
"""

from typing import Optional

from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
                                QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from capture.config import APP_NAME
from capture.dialog_utils import strip_minmax_buttons
from capture.shortcuts import (CAPTURE_ACTIONS, KEY_OPTIONS, decode_key_sequence,
                                make_key_sequence, load_shortcut, save_shortcut)


class _ShortcutRow:
    """단축키 하나(Shift/Ctrl/Alt 체크박스 + 키 선택 콤보)에 대응하는 위젯 묶음."""

    def __init__(self, grid: QGridLayout, row: int, label: str) -> None:
        """Args:
            grid: 위젯을 배치할 그리드 레이아웃.
            row: 배치할 행 번호.
            label: 캡처 액션 표시 이름.
        """
        self.shift_cb = QCheckBox()
        self.ctrl_cb = QCheckBox()
        self.alt_cb = QCheckBox()
        self.key_combo = QComboBox()
        for text, key in KEY_OPTIONS:
            self.key_combo.addItem(text, key)

        grid.addWidget(QLabel(label), row, 0)
        grid.addWidget(self.shift_cb, row, 1)
        grid.addWidget(self.ctrl_cb, row, 2)
        grid.addWidget(self.alt_cb, row, 3)
        grid.addWidget(self.key_combo, row, 4)

    def set_sequence(self, seq: QKeySequence) -> None:
        """키 시퀀스로 체크박스/콤보 상태를 갱신한다."""
        shift, ctrl, alt, key = decode_key_sequence(seq)
        self.shift_cb.setChecked(shift)
        self.ctrl_cb.setChecked(ctrl)
        self.alt_cb.setChecked(alt)
        idx = self.key_combo.findData(key)
        self.key_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def to_sequence(self) -> QKeySequence:
        """현재 체크박스/콤보 상태를 키 시퀀스로 변환한다."""
        key = self.key_combo.currentData()
        return make_key_sequence(self.shift_cb.isChecked(), self.ctrl_cb.isChecked(),
                                  self.alt_cb.isChecked(), key)


class ShortcutSettingsDialog(QDialog):
    """영역/전체화면/활성 윈도우 캡처의 전역 단축키를 지정하는 다이얼로그."""

    def __init__(self, settings: QSettings, parent: Optional[QWidget] = None) -> None:
        """Args:
            settings: 단축키를 읽고 저장할 QSettings.
            parent: 부모 위젯.
        """
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - 캡처 단축키 설정")
        strip_minmax_buttons(self)
        self._settings = settings
        self._rows: dict[str, _ShortcutRow] = {}

        grid = QGridLayout()
        grid.addWidget(QLabel("Shift"), 0, 1)
        grid.addWidget(QLabel("Ctrl"), 0, 2)
        grid.addWidget(QLabel("Alt"), 0, 3)
        grid.addWidget(QLabel("키"), 0, 4)
        for i, action in enumerate(CAPTURE_ACTIONS, start=1):
            row = _ShortcutRow(grid, i, action.label)
            row.set_sequence(load_shortcut(settings, action))
            self._rows[action.action_id] = row

        reset_btn = QPushButton("기본값으로 재설정")
        reset_btn.clicked.connect(self._reset_defaults)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                    QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(reset_btn)
        layout.addWidget(buttons)

    def _reset_defaults(self) -> None:
        """모든 단축키 입력을 기본값으로 되돌린다."""
        for action in CAPTURE_ACTIONS:
            self._rows[action.action_id].set_sequence(QKeySequence(action.default))

    def accept(self) -> None:
        """단축키 중복이 없는지 확인한 뒤 설정에 저장한다."""
        sequences: dict[str, QKeySequence] = {
            action_id: row.to_sequence() for action_id, row in self._rows.items()
        }
        seen: dict[str, str] = {}
        for action in CAPTURE_ACTIONS:
            text = sequences[action.action_id].toString()
            if not text:      # "없음"은 여러 액션에 중복 지정해도 무방
                continue
            if text in seen:
                box = QMessageBox(
                    QMessageBox.Icon.Warning, APP_NAME,
                    f"단축키가 중복되었습니다: {text}\n({seen[text]} / {action.label})",
                    QMessageBox.StandardButton.Ok, self)
                strip_minmax_buttons(box)
                box.exec()
                return
            seen[text] = action.label

        for action in CAPTURE_ACTIONS:
            save_shortcut(self._settings, action, sequences[action.action_id])
        super().accept()
