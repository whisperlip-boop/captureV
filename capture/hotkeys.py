#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 전역 단축키 (RegisterHotKey) 처리."""

import ctypes
import logging
from typing import Callable, NamedTuple, Optional

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from capture.config import IS_WIN
from capture.shortcuts import key_sequence_to_hotkey

# ctypes.wintypes는 Windows 전용 서브모듈이라 다른 플랫폼에서 import 시 실패한다.
if IS_WIN:
    import ctypes.wintypes as wintypes
else:
    wintypes = None

logger = logging.getLogger(__name__)


class HotkeySpec(NamedTuple):
    """등록할 전역 단축키 하나에 대한 정의."""

    action_id: str
    key_sequence: QKeySequence
    callback: Callable[[], None]


class HotkeyFilter(QAbstractNativeEventFilter):
    """WM_HOTKEY 네이티브 메시지를 감지해 등록된 콜백을 실행한다."""

    WM_HOTKEY: int = 0x0312

    def __init__(self, callbacks: dict[int, Callable[[], None]]) -> None:
        """Args:
            callbacks: {hotkey_id: callable} 매핑.
        """
        super().__init__()
        self.callbacks = callbacks

    def nativeEventFilter(self, event_type: bytes, message: int) -> tuple[bool, int]:
        """WM_HOTKEY 메시지를 가로채 해당 콜백을 호출한다."""
        if event_type == b"windows_generic_MSG":
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == self.WM_HOTKEY:
                    cb = self.callbacks.get(int(msg.wParam))
                    if cb:
                        cb()
                        return True, 0
            except Exception:
                logger.exception("전역 단축키 처리 중 오류 (message=%r)", message)
        return False, 0


def register_global_hotkeys(app: QApplication, specs: list[HotkeySpec]) -> Optional[HotkeyFilter]:
    """전역 단축키 목록을 등록한다.

    Args:
        app: 네이티브 이벤트 필터를 설치할 QApplication.
        specs: 등록할 (액션 ID, 키 시퀀스, 콜백) 목록.

    Returns:
        설치된 HotkeyFilter. Windows가 아니면 None.
    """
    if not IS_WIN:
        logger.info("Windows가 아니므로 전역 단축키를 등록하지 않음")
        return None
    user32 = ctypes.windll.user32
    filt = HotkeyFilter({})
    app.installNativeEventFilter(filt)

    for hotkey_id, spec in enumerate(specs, start=1):
        if spec.key_sequence.isEmpty():
            logger.info("전역 단축키 사용 안 함: %s", spec.action_id)
            continue
        conv = key_sequence_to_hotkey(spec.key_sequence)
        if conv is None:
            logger.warning("전역 단축키 등록 건너뜀(지원하지 않는 키): %s = %s",
                            spec.action_id, spec.key_sequence.toString())
            continue
        mods, vk = conv
        ok = user32.RegisterHotKey(None, hotkey_id, mods, vk)
        logger.info("전역 단축키 등록: %s (%s) = %s",
                     spec.action_id, spec.key_sequence.toString(), bool(ok))
        if ok:
            filt.callbacks[hotkey_id] = spec.callback
        else:
            logger.warning("전역 단축키 등록 실패(다른 프로그램이 선점했을 수 있음): %s = %s",
                            spec.action_id, spec.key_sequence.toString())
    return filt


def unregister_global_hotkeys(filt: Optional[HotkeyFilter]) -> None:
    """register_global_hotkeys()로 등록한 전역 단축키를 모두 해제한다.

    Args:
        filt: register_global_hotkeys()가 반환한 필터. None이면 아무 것도 하지 않는다.
    """
    if not IS_WIN or filt is None:
        return
    user32 = ctypes.windll.user32
    for hotkey_id in filt.callbacks:
        user32.UnregisterHotKey(None, hotkey_id)
    logger.info("전역 단축키 해제 완료")
