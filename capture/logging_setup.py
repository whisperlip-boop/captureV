#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""애플리케이션 로깅 설정.

파일 입출력, 캡처/변환, 에러 등 주요 동작을 감사 가능하도록 파일과
콘솔에 동시에 기록한다.
"""

import faulthandler
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import IO, Optional

from capture.config import APP_NAME, get_log_dir

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
# 로그 파일 하나의 최대 크기와 보관할 이전 파일 개수. 로테이션이 없으면 오래 쓰는
# 동안 로그 파일이 끝없이 커진다.
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 3

# faulthandler는 파일 핸들을 계속 열어둔 채로 참조해야 해서(로깅 핸들러와
# 달리 자체적으로 파일을 관리하지 않는다), GC로 닫히지 않도록 모듈 전역에 붙잡아 둔다.
_crash_file: Optional[IO[str]] = None


def setup_logging(level: int = logging.INFO) -> Optional[Path]:
    """루트 로거에 파일/콘솔 핸들러를 구성한다.

    이미 핸들러가 등록되어 있으면 재구성하지 않는다. 로그 폴더를 만들거나
    파일을 열 수 없으면(권한·디스크 문제 등) 앱 시작을 막지 않도록 콘솔에만 기록한다.

    Args:
        level: 루트 로거 레벨.

    Returns:
        로그 파일 경로. 파일 로깅을 설정하지 못했으면 None.
    """
    log_dir = get_log_dir()
    log_path: Optional[Path] = log_dir / f"{APP_NAME.lower()}.log"
    file_error: Optional[OSError] = None

    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(level)
        fmt = logging.Formatter(_LOG_FORMAT)

        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(log_path, maxBytes=_LOG_MAX_BYTES,
                                               backupCount=_LOG_BACKUP_COUNT, encoding="utf-8")
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
        except OSError as exc:
            file_error = exc
            log_path = None

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)

    if file_error is not None:
        logging.getLogger(__name__).warning("로그 파일을 열 수 없어 콘솔에만 기록함: %s (%s)",
                                            log_dir, file_error)

    global _crash_file
    if _crash_file is None and log_path is not None:
        # 세그폴트 등 Python 예외로 표현되지 않는 네이티브 크래시는
        # sys.excepthook으로도 못 잡으므로, OS 시그널 단계에서 faulthandler로
        # 그 순간의 파이썬 콜스택을 별도 파일에 남긴다.
        crash_path = log_dir / f"{APP_NAME.lower()}_crash.log"
        try:
            _crash_file = open(crash_path, "a", encoding="utf-8")
            faulthandler.enable(file=_crash_file, all_threads=True)
        except OSError:
            logging.getLogger(__name__).warning("크래시 로그 파일을 열 수 없음: %s", crash_path,
                                                exc_info=True)

    return log_path


def install_excepthook() -> None:
    """처리되지 않은 예외를 앱을 중단시키지 않고 로그 파일에 기록하도록 훅을 건다.

    Qt 이벤트 루프가 호출하는 슬롯/이벤트 핸들러 안에서 발생한 예외는
    이 훅을 거친 뒤에도 이벤트 루프 자체는 계속 돌아간다(그 동작 한 번만
    실패로 끝난다). 여기서 다시 예외를 일으키거나 프로세스를 종료하면
    그 효과가 사라지므로, 로그만 남기고 반드시 정상 반환해야 한다.
    """
    logger = logging.getLogger(__name__)

    def _handle(exc_type: type[BaseException], exc_value: BaseException,
                exc_tb: TracebackType | None) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("처리되지 않은 예외 발생", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _handle
