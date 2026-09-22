#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AVIF 읽기/쓰기 (Pillow 브리지).

Qt에는 AVIF 이미지 플러그인이 없어 QImage/QImageReader로는 AVIF를 다룰 수 없다.
Pillow 11.3부터 AVIF 코덱(libavif)이 공식 휠에 포함되므로, QImage <-> Pillow
변환을 거쳐 읽기/쓰기를 지원한다.

픽셀 데이터는 항상 RGBA8888로 주고받는다. QImage의 각 행은 4바이트 경계에 맞춰
지는데 RGB888(3바이트/픽셀)은 행 끝에 패딩이 붙을 수 있어 그대로 넘기면 이미지가
비스듬히 밀린다. RGBA8888은 폭과 무관하게 패딩이 없어 이런 위험이 없다.
"""

import logging
import os

from PIL import Image
from PySide6.QtGui import QImage

logger = logging.getLogger(__name__)

AVIF_EXTENSIONS: frozenset[str] = frozenset({".avif"})

# Pillow의 AVIF 인코더로는 '진짜 무손실'에 도달할 수 없다. AvifImagePlugin에는
# lossless 인자도, 무손실에 필요한 matrix_coefficients(identity) 제어도 없어서
# RGB -> YUV 변환의 반올림 오차가 항상 남는다(lossless=True를 넘기면 오류 없이
# 조용히 무시되고 기본 품질 75로 저장되므로 특히 주의).
# 실측(256x256 전 색공간 그라디언트 + 알파):
#   quality=100, 기본 subsampling(4:2:0) -> 최대 채널 오차 120, 채널 65%가 오차 > 1
#   quality=100, subsampling="4:4:4"     -> 최대 채널 오차 2,  채널 0.3%가 오차 > 1
# 그래서 품질을 최대로 올리는 것만으로는 부족하고 4:4:4를 반드시 함께 지정해야
# 한다. 무채색(흰/검) 이미지만으로 시험하면 두 설정 모두 '완전 일치'로 보이므로
# 이 값을 바꿀 때는 반드시 유채색 이미지로 검증할 것.
AVIF_MAX_QUALITY: int = 100
AVIF_SUBSAMPLING: str = "4:4:4"

# 디코딩을 허용할 최대 픽셀 수. AVIF는 몇 KB짜리 파일에 거대한 해상도를 선언할 수
# 있어(압축 폭탄), 헤더의 크기를 먼저 보고 거부하지 않으면 수 GB를 할당하려 든다.
# Qt의 QImageReader 기본 할당 한도(256MB)를 4바이트/픽셀로 환산한 값과 맞춰,
# AVIF가 다른 포맷보다 느슨하게 열리지 않도록 한다(8192x8192 정도).
AVIF_MAX_PIXELS: int = 256 * 1024 * 1024 // 4


def is_avif_path(path: str) -> bool:
    """확장자로 AVIF 파일인지 판단한다.

    Args:
        path: 판단할 파일 경로.

    Returns:
        확장자가 .avif면 True.
    """
    return os.path.splitext(path)[1].lower() in AVIF_EXTENSIONS


def read_avif(path: str) -> QImage:
    """AVIF 파일을 QImage로 읽는다.

    애니메이션 AVIF는 첫 프레임만 사용한다(이 앱은 정지 이미지 편집기라 프레임
    개념이 없다). 알파가 없는 파일은 Pillow가 RGB로 읽지만, 편집 파이프라인이
    알파를 전제로 하므로 항상 RGBA로 변환한다.

    Image.open()은 헤더만 읽는 지연 로딩이라, 실제 디코딩(convert) 전에 선언된
    크기를 검사해 압축 폭탄을 미리 걸러낸다.

    크기 한도를 통과한 합법적인 파일도 순간 메모리가 픽셀 버퍼의 두 배까지
    오른다(PIL 버퍼 -> bytes 사본 -> QImage 사본). AVIF_MAX_PIXELS 기준으로는
    약 512MB이므로, 메모리가 부족한 상황에서도 앱이 죽지 않도록 변환과 복사를
    모두 try 안에 두고 MemoryError까지 함께 잡는다. 그러지 않으면 '파일 하나로
    앱이 종료된다'는, 이 검사로 막으려던 바로 그 실패 모드가 되살아난다.

    Args:
        path: 읽을 AVIF 파일 경로.

    Returns:
        읽어들인 이미지. 실패하면 isNull()이 True인 빈 QImage
        (QImage(path)의 실패 방식과 같아 호출부가 분기를 나눌 필요가 없다).
    """
    try:
        with Image.open(path) as pil_image:
            width, height = pil_image.size
            if width * height > AVIF_MAX_PIXELS:
                logger.warning("AVIF 크기 한도 초과로 거부: %s (%dx%d, 한도 %d픽셀)",
                               path, width, height, AVIF_MAX_PIXELS)
                return QImage()
            rgba = pil_image.convert("RGBA")

        # tobytes()의 결과는 패딩 없이 꽉 찬 RGBA 바이트열이라 stride = 폭 * 4.
        data = rgba.tobytes()
        # QImage는 data만 참조하므로 PIL 버퍼는 여기서 놓아준다. 이걸 빼면
        # copy()가 끝날 때까지 PIL 버퍼 + bytes + QImage 세 개가 동시에 살아
        # 피크가 픽셀 버퍼의 세 배가 된다.
        del rgba
        # QImage는 넘겨받은 버퍼를 복사하지 않으므로, 임시 bytes가 해제되기 전에
        # copy()로 자체 버퍼를 확보해야 한다.
        return QImage(data, width, height, width * 4,
                      QImage.Format.Format_RGBA8888).copy()
    except (OSError, ValueError, SyntaxError, MemoryError,
            Image.DecompressionBombError) as exc:
        # Pillow는 손상 파일에 OSError, 알 수 없는 포맷에 UnidentifiedImageError
        # (OSError 하위), 일부 디코더 오류에 SyntaxError를 던진다.
        # DecompressionBombError는 OSError/ValueError가 아니라 Exception 직속이고
        # MemoryError는 어느 쪽도 아니라, 둘 다 명시해야 잡힌다(빠뜨리면
        # 드래그&드롭 한 번으로 앱이 죽는다).
        logger.warning("AVIF 읽기 실패: %s (%s: %s)", path, type(exc).__name__, exc)
        return QImage()


def write_avif(image: QImage, path: str, quality: int) -> None:
    """QImage를 AVIF 파일로 저장한다.

    Args:
        image: 저장할 이미지.
        path: 저장 경로.
        quality: 인코딩 품질(0~100). 음수(Qt의 "기본값" 표기)를 받으면 최대
            품질로 처리한다. 100이라도 완전 무손실은 아니다(모듈 상단 주석 참조).
            픽셀이 정확히 보존돼야 하면 PNG/WebP/TIFF로 저장해야 한다.

    Raises:
        OSError: 인코딩 또는 파일 쓰기에 실패한 경우. 호출부(_write_image)가
            Qt 저장 실패와 같은 방식으로 처리할 수 있도록 OSError로 맞춘다.
    """
    effective_quality = AVIF_MAX_QUALITY if quality < 0 else min(quality, AVIF_MAX_QUALITY)

    try:
        # 변환과 버퍼 복사도 try 안에 둔다. 큰 이미지에서 MemoryError가 날 수 있고,
        # null QImage가 들어오면 constBits()가 None이라 bytes()가 TypeError를 낸다.
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        # bytesPerLine()을 명시해, Qt가 행 끝에 패딩을 넣더라도 어긋나지 않게 한다.
        pil_image = Image.frombuffer("RGBA", (rgba.width(), rgba.height()),
                                     bytes(rgba.constBits()), "raw", "RGBA",
                                     rgba.bytesPerLine(), 1)
        pil_image.save(path, format="AVIF", quality=effective_quality,
                       subsampling=AVIF_SUBSAMPLING)
    except OSError:
        # 디스크 오류 등은 호출부가 이미 같은 방식으로 처리하므로 그대로 올린다.
        raise
    except Exception as exc:
        # Pillow가 AVIF 코덱 없이 빌드된 경우(11.3 미만) ValueError/KeyError가,
        # 메모리 부족 시 MemoryError가 오는 등 예외 종류를 특정할 수 없다.
        # 호출부(_write_image)는 OSError/MemoryError만 처리하므로, 나머지가 앱까지
        # 올라가지 않도록 여기서 OSError로 정규화한다.
        raise OSError(f"AVIF 인코딩 실패: {type(exc).__name__}: {exc}") from exc
    logger.info("AVIF 저장: %s (%dx%d, quality=%d, subsampling=%s)", path,
                rgba.width(), rgba.height(), effective_quality, AVIF_SUBSAMPLING)
