#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""애플리케이션 로깅 설정.

파일 입출력, 캡처/변환, 에러 등 주요 동작을 감사 가능하도록 파일과
콘솔에 동시에 기록한다.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from capture.config import APP_NAME

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO) -> Path:
    """루트 로거에 파일/콘솔 핸들러를 구성한다.

    이미 핸들러가 등록되어 있으면 재구성하지 않는다.

    Args:
        level: 루트 로거 레벨.

    Returns:
        로그 파일 경로.
    """
    app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    log_dir = Path(app_data or Path.home() / APP_NAME) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{APP_NAME.lower()}.log"

    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(level)
        fmt = logging.Formatter(_LOG_FORMAT)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)
        root.addHandler(console_handler)

    return log_path
