#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""캡처 관련 전역 단축키 정의 및 QKeySequence ↔ Win32 핫키 변환.

RegisterHotKey는 Qt의 QKeySequence를 이해하지 못하고 (modifiers, virtual-key)
조합만 받으므로, 사용자가 옵션 화면(Shift/Ctrl/Alt 체크박스 + 키 선택)에서
지정한 단축키를 Win32 코드로 변환하는 역할을 담당한다.
"""

import logging
from typing import NamedTuple, Optional

from PySide6.QtCore import QKeyCombination, QSettings
from PySide6.QtGui import Qt, QKeySequence

logger = logging.getLogger(__name__)

# Win32 RegisterHotKey modifier 플래그
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

_MODIFIER_MAP: dict[Qt.KeyboardModifier, int] = {
    Qt.KeyboardModifier.ControlModifier: MOD_CONTROL,
    Qt.KeyboardModifier.ShiftModifier: MOD_SHIFT,
    Qt.KeyboardModifier.AltModifier: MOD_ALT,
    Qt.KeyboardModifier.MetaModifier: MOD_WIN,
}

# (표시 라벨, Qt Key, Win32 VK 코드) — A-Z/0-9는 값이 동일해 별도 정의가 필요 없다.
_SPECIAL_KEYS: list[tuple[str, Qt.Key, int]] = [
    ("PrintScreen", Qt.Key.Key_Print, 0x2C),
    ("Insert", Qt.Key.Key_Insert, 0x2D),
    ("Delete", Qt.Key.Key_Delete, 0x2E),
    ("Home", Qt.Key.Key_Home, 0x24),
    ("End", Qt.Key.Key_End, 0x23),
    ("PageUp", Qt.Key.Key_PageUp, 0x21),
    ("PageDown", Qt.Key.Key_PageDown, 0x22),
    ("Left", Qt.Key.Key_Left, 0x25),
    ("Up", Qt.Key.Key_Up, 0x26),
    ("Right", Qt.Key.Key_Right, 0x27),
    ("Down", Qt.Key.Key_Down, 0x28),
    ("Escape", Qt.Key.Key_Escape, 0x1B),
    ("Tab", Qt.Key.Key_Tab, 0x09),
    ("Space", Qt.Key.Key_Space, 0x20),
    ("Enter", Qt.Key.Key_Return, 0x0D),
    ("Backspace", Qt.Key.Key_Backspace, 0x08),
] + [(f"F{i}", Qt.Key(Qt.Key.Key_F1 + i - 1), 0x70 + i - 1) for i in range(1, 25)]

_SPECIAL_VK: dict[Qt.Key, int] = {key: vk for _label, key, vk in _SPECIAL_KEYS}

# 옵션 화면의 "키" 콤보박스에 나열할 (표시 라벨, Qt Key) 목록. "없음"은 해당
# 단축키를 비활성화한다는 의미로 key=None을 사용한다.
KEY_OPTIONS: list[tuple[str, Optional[Qt.Key]]] = [("없음", None)]
KEY_OPTIONS += [(chr(k), Qt.Key(k)) for k in range(Qt.Key.Key_A, Qt.Key.Key_Z + 1)]
KEY_OPTIONS += [(chr(k), Qt.Key(k)) for k in range(Qt.Key.Key_0, Qt.Key.Key_9 + 1)]
KEY_OPTIONS += [(label, key) for label, key, _vk in _SPECIAL_KEYS]


class CaptureAction(NamedTuple):
    """설정 가능한 캡처 액션 정의."""

    action_id: str
    label: str
    default: str    # QKeySequence 문자열 (예: "Ctrl+Shift+A")


# 사용자가 옵션 화면에서 단축키를 지정할 수 있는 캡처 액션 목록.
CAPTURE_ACTIONS: list[CaptureAction] = [
    CaptureAction("region", "영역 지정 캡처", "Ctrl+Shift+A"),
    CaptureAction("fullscreen", "전체화면 캡처", "Print"),
    CaptureAction("active_window", "활성 윈도우 캡처", "Alt+Print"),
]

_SETTINGS_GROUP = "shortcuts"
_MISSING = object()


def make_key_sequence(shift: bool, ctrl: bool, alt: bool, key: Optional[Qt.Key]) -> QKeySequence:
    """체크박스 상태와 선택된 키로 QKeySequence를 만든다.

    Args:
        shift: Shift 사용 여부.
        ctrl: Ctrl 사용 여부.
        alt: Alt 사용 여부.
        key: 선택된 키. None이면 단축키를 사용하지 않는다는 뜻으로 빈 시퀀스를 반환한다.

    Returns:
        조합된 키 시퀀스.
    """
    if key is None:
        return QKeySequence()
    mods = Qt.KeyboardModifier.NoModifier
    if shift:
        mods |= Qt.KeyboardModifier.ShiftModifier
    if ctrl:
        mods |= Qt.KeyboardModifier.ControlModifier
    if alt:
        mods |= Qt.KeyboardModifier.AltModifier
    return QKeySequence(QKeyCombination(mods, key))


def decode_key_sequence(seq: QKeySequence) -> tuple[bool, bool, bool, Optional[Qt.Key]]:
    """QKeySequence를 (shift, ctrl, alt, key) 튜플로 분해한다.

    Args:
        seq: 분해할 키 시퀀스.

    Returns:
        (shift, ctrl, alt, key). 비어 있으면 key=None.
    """
    if seq.isEmpty():
        return False, False, False, None
    combo = seq[0]
    mods = combo.keyboardModifiers()
    return (bool(mods & Qt.KeyboardModifier.ShiftModifier),
            bool(mods & Qt.KeyboardModifier.ControlModifier),
            bool(mods & Qt.KeyboardModifier.AltModifier),
            combo.key())


def key_sequence_to_hotkey(seq: QKeySequence) -> Optional[tuple[int, int]]:
    """QKeySequence를 (win32 modifiers, virtual-key) 조합으로 변환한다.

    콤보 1개(단일 키 시퀀스)만 지원한다.

    Args:
        seq: 변환할 키 시퀀스.

    Returns:
        (modifiers, vk) 튜플. 비어 있거나 지원하지 않는 키면 None.
    """
    if seq.isEmpty():
        return None
    combo = seq[0]
    key = combo.key()
    qt_mods = combo.keyboardModifiers()

    mods = 0
    for qt_mod, win_mod in _MODIFIER_MAP.items():
        if qt_mods & qt_mod:
            mods |= win_mod

    if key in _SPECIAL_VK:
        vk = _SPECIAL_VK[key]
    elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        vk = int(key)
    else:
        logger.warning("지원하지 않는 키 조합: %s", seq.toString())
        return None
    return mods, vk


def load_shortcut(settings: QSettings, action: CaptureAction) -> QKeySequence:
    """설정에 저장된 단축키를 불러온다.

    설정에 값이 전혀 없으면 기본값을, 사용자가 명시적으로 "없음"(빈 문자열)을
    저장했으면 빈 시퀀스를 반환한다.
    """
    text = settings.value(f"{_SETTINGS_GROUP}/{action.action_id}", _MISSING)
    if text is _MISSING:
        return QKeySequence(action.default)
    return QKeySequence(text)


def save_shortcut(settings: QSettings, action: CaptureAction, seq: QKeySequence) -> None:
    """지정한 액션의 단축키를 설정에 저장한다."""
    settings.setValue(f"{_SETTINGS_GROUP}/{action.action_id}", seq.toString())
