#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CaptureV 전역 상수.

애플리케이션 이름, 핸들 크기, 최소 크기 제한, 8방향 핸들 정의,
핸들별 커서 모양, 강조 색상 등 모든 모듈이 공유하는 값을 모아둔다.
"""

import ctypes
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

APP_NAME: str = "CaptureV"
HANDLE_PX: int = 9          # 캔버스/선택 핸들 크기
MIN_CANVAS: int = 16
MIN_SELECTION: int = 4
IS_WIN: bool = sys.platform == "win32"
TOOLBAR_ICON_PX: int = 40

SPI_GETKEYBOARDDELAY: int = 0x0016     # SystemParametersInfo: 키 자동 반복 시작 지연 조회
DEFAULT_KEY_REPEAT_DELAY_MS: int = 500  # 조회 실패 시 사용할 Windows 기본값


def get_resource_path(relative_path: str) -> Path:
    """PyInstaller 번들 여부에 따라 리소스 파일의 절대 경로를 반환한다.

    Args:
        relative_path: 프로젝트 루트(개발 환경) 또는 번들 루트 기준 상대 경로
            (예: "img/move.png").

    Returns:
        리소스 파일의 절대 경로.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative_path


def get_key_repeat_delay_ms() -> int:
    """OS에 설정된 '키를 누른 뒤 자동 반복이 시작되기까지의 지연'을 ms로 반환한다.

    화살표 키 연타를 '꾹 누르고 있음'으로 오인하지 않으려면 이 값이 필요하다.
    OS 자동 반복은 이 지연보다 빨리 올 수 없으므로, 두 번째 입력이 이보다
    충분히 빨리 들어왔다면 사람이 연타한 것으로 확정할 수 있다.

    Windows의 SPI_GETKEYBOARDDELAY는 0~3 범위의 단계값이며 각각 250/500/750/
    1000ms에 대응한다(제어판 '키보드 속성'에서 사용자가 바꿀 수 있다).

    Returns:
        자동 반복 시작 지연(ms). 조회할 수 없으면 Windows 기본값인 500.
    """
    if not IS_WIN:
        return DEFAULT_KEY_REPEAT_DELAY_MS
    try:
        step = ctypes.c_uint()
        if not ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETKEYBOARDDELAY, 0, ctypes.byref(step), 0):
            return DEFAULT_KEY_REPEAT_DELAY_MS
        return 250 * (min(step.value, 3) + 1)
    except Exception:
        # 설정을 못 읽는다고 기능이 죽어서는 안 되므로 기본값으로 넘어간다.
        return DEFAULT_KEY_REPEAT_DELAY_MS


def get_settings_path() -> Path:
    """사용자 설정을 저장할 INI 파일 경로를 반환한다 (%APPDATA%\\CaptureV\\CaptureV.ini).

    exe로 배포했을 때 레지스트리 대신 사람이 읽을 수 있는 파일로 남겨,
    다른 PC로 옮기거나 백업/초기화하기 쉽게 한다. 부모 폴더가 없어도
    QSettings가 처음 저장할 때 자동으로 만들어준다.
    """
    base = Path(os.environ.get("APPDATA", str(Path.home())))
    return base / APP_NAME / f"{APP_NAME}.ini"

# 8방향 핸들: (dx, dy) ∈ {-1, 0, 1}
HANDLES: list[tuple[int, int]] = [(-1, -1), (0, -1), (1, -1),
                                   (-1, 0), (1, 0),
                                   (-1, 1), (0, 1), (1, 1)]

CURSORS: dict[tuple[int, int], Qt.CursorShape] = {
    (-1, -1): Qt.CursorShape.SizeFDiagCursor, (1, 1): Qt.CursorShape.SizeFDiagCursor,
    (1, -1): Qt.CursorShape.SizeBDiagCursor, (-1, 1): Qt.CursorShape.SizeBDiagCursor,
    (0, -1): Qt.CursorShape.SizeVerCursor, (0, 1): Qt.CursorShape.SizeVerCursor,
    (-1, 0): Qt.CursorShape.SizeHorCursor, (1, 0): Qt.CursorShape.SizeHorCursor,
}

ACCENT: QColor = QColor(0x2d, 0x9c, 0xff)
CANVAS_SURROUND_COLOR: str = "#303030"     # 캔버스 주위(뷰 배경)/탭이 없을 때의 배경색

# ---------- 투명 배경 표시(체커보드) ---------- #
CHECKER_LIGHT_COLOR: QColor = QColor(0xff, 0xff, 0xff)
CHECKER_DARK_COLOR: QColor = QColor(0xcc, 0xcc, 0xcc)
CHECKER_SQUARE_PX: int = 8     # 체커보드 한 칸 크기(캔버스 픽셀 기준)

# ---------- 그리기 도구 ---------- #
THICKNESS_MIN: int = 1
THICKNESS_MAX: int = 10
DEFAULT_THICKNESS: int = 3
HIGHLIGHTER_ALPHA: float = 0.4      # 형광펜 한 번 그을 때의 불투명도 (겹쳐 그리면 짙어짐)
COLOR_BOX_PX: int = 40

# 팔레트 기본 색상 (2행 x 10열). 위 행은 진한 색, 아래 행은 같은 계열의 옅은 색.
PALETTE_COLORS: list[str] = [
    "#000000", "#7F7F7F", "#880015", "#ED1C24", "#FF7F27",
    "#FFF200", "#22B14C", "#00A2E8", "#3F48CC", "#A349A4",
    "#FFFFFF", "#C3C3C3", "#B97A57", "#FFAEC9", "#FFC90E",
    "#EFE4B0", "#B5E61D", "#99D9EA", "#7092BE", "#C8BFE7",
]
DEFAULT_DRAW_COLOR: str = "#FFFFFF"

# "색" 드롭다운(테마 색/표준 색/사용자 지정 색) 관련 상수.
# 테마 색: 10열 x 6행. 각 열은 [기본색, 옅은색..., 진한색] 순서로 지정된 고정값
# (계산으로 생성한 음영이 아니라 열마다 직접 지정한 값).
THEME_COLORS: list[list[str]] = [
    ["#000000", "#808080", "#595959", "#404040", "#262626", "#0D0D0D"],
    ["#FFFFFF", "#F2F2F2", "#D9D9D9", "#BFBFBF", "#A6A6A6", "#808080"],
    ["#880015", "#E7B9C0", "#CF7C89", "#B84A5B", "#660010", "#44000A"],
    ["#ED1C24", "#FBCFD0", "#F8A1A4", "#F47378", "#B21016", "#77070B"],
    ["#FF7F27", "#FFE5D4", "#FFCCA9", "#FFB27D", "#BF5B16", "#803A0A"],
    ["#FFF200", "#FFFCCC", "#FFFA99", "#FFF766", "#BFB500", "#807900"],
    ["#22B14C", "#C8EFD4", "#98E0AD", "#6BD089", "#138535", "#085820"],
    ["#00A2E8", "#C8EBFA", "#94D8F6", "#60C5F1", "#007AAE", "#005174"],
    ["#3F48CC", "#D3D5F5", "#AAAEEB", "#8389E0", "#232B99", "#101566"],
    ["#A349A4", "#EDD3ED", "#DAAADB", "#C785C8", "#7A297B", "#511252"],
]
# Qt 내장 색상 다이얼로그의 "Basic colors"는 8열 x 6행(48개)으로 개수가
# 고정되어 있어 THEME_COLORS 10열 중 3번째(다크 레드)와 10번째(퍼플)를 뺀다.
THEME_COLORS_NATIVE_8COL: list[list[str]] = [THEME_COLORS[i] for i in (0, 1, 3, 4, 5, 6, 7, 8)]
STANDARD_COLORS: list[str] = [
    "#C00000", "#FF0000", "#FFC000", "#FFFF00", "#92D050",
    "#00B050", "#00B0F0", "#0070C0", "#002060", "#7030A0",
]
MAX_CUSTOM_COLORS: int = 10

# ---------- 채우기 도구 ---------- #
FILL_TOLERANCE_MIN: int = 0
FILL_TOLERANCE_MAX: int = 100
DEFAULT_FILL_TOLERANCE: int = 20    # R/G/B 각 채널 최대 허용 차이 = 이 값(%) / 100 * 255

# ---------- 신규(새 캔버스) ---------- #
NEW_CANVAS_SIZE_MIN: int = 16
NEW_CANVAS_SIZE_MAX: int = 20000
DEFAULT_NEW_CANVAS_WIDTH: int = 500
DEFAULT_NEW_CANVAS_HEIGHT: int = 500
DEFAULT_NEW_CANVAS_BG_COLOR: str = "#FFFFFF"

# ---------- 캔버스 확대/축소 ---------- #
ZOOM_PERCENT_MIN: int = 1
ZOOM_PERCENT_MAX: int = 1000

# ---------- 탭 저장 상태 표시 ---------- #
TAB_UNSAVED_COLOR: str = "#E86133"
TAB_SAVED_COLOR: str = "#7DCD28"

# ---------- 텍스트 도구 ---------- #
DEFAULT_TEXT_COLOR: str = "#000000"
DEFAULT_TEXT_FONT_SIZE: int = 12
TEXT_FONT_SIZES: list[int] = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 72]
TEXT_ICON_PX: int = 20     # 텍스트 설정 팝업의 정렬/볼드/이탤릭 아이콘 크기

# ---------- 효과/크기 조절/회전/색상 추출 (2x2 소형 버튼 그룹) ---------- #
MINI_TOOL_ICON_PX: int = 18    # 일반 툴바 아이콘(TOOLBAR_ICON_PX)보다 작게
MINI_TOOL_DIVIDER_COLOR: str = "#8A8A8A"   # 좌우 구분선 색(약간 짙은 회색)
EFFECT_MENU_ICON_PX: int = 16  # '효과' 하위 메뉴 항목 아이콘 크기(기존 메뉴 높이를 유지하는 크기)

# ---------- 고정 크기 캡처 ---------- #
DEFAULT_FIXED_CAPTURE_WIDTH: int = 800
DEFAULT_FIXED_CAPTURE_HEIGHT: int = 600

# ---------- 캔버스 크기 변경 팝업 ---------- #
DEFAULT_CANVAS_SIZE_BG_COLOR: str = "#F2F2F2"

# ---------- 모자이크 효과 ---------- #
MOSAIC_PERCENT_MIN: int = 1
MOSAIC_PERCENT_MAX: int = 30
DEFAULT_MOSAIC_PERCENT: int = 3

# ---------- 흐리게(가우시안 블러) 효과 ---------- #
BLUR_PERCENT_MIN: int = 1
BLUR_PERCENT_MAX: int = 30
DEFAULT_BLUR_PERCENT: int = 5
# 가우시안 표준편차(sigma) = 대상 영역의 짧은 변 길이 * percent/100 * 이 계수.
# 모자이크의 블록 크기 공식(짧은 변 * percent/100)과 같은 비율 기반이지만,
# 가우시안 sigma는 그 절대값 자체가 커지면 과도하게 뭉개지므로 훨씬 작은
# 계수를 곱해 1~30% 범위가 "약한 흐림 ~ 강한 흐림" 정도로 느껴지게 한다.
BLUR_SIGMA_SCALE: float = 0.1

# ---------- 선명하게(언샵 마스킹) 효과 ---------- #
SHARPEN_PERCENT_MIN: int = 1
SHARPEN_PERCENT_MAX: int = 30
DEFAULT_SHARPEN_PERCENT: int = 5
# 언샵 마스킹의 내부 블러 반경(sigma). 경계 검출 범위라 이미지 해상도와
# 무관하게 몇 픽셀 수준의 고정값을 쓴다(블러 효과처럼 해상도에 비례시키면
# 큰 이미지에서 경계가 아니라 뭉뚱그린 명암 대비 강조처럼 되어버린다).
SHARPEN_SIGMA: float = 1.5
# amount(고주파 성분을 원본에 더해주는 배율) = percent * 이 계수.
SHARPEN_AMOUNT_SCALE: float = 0.1

# ---------- 밝기/대비 효과 ---------- #
BRIGHTNESS_CONTRAST_MIN: int = -100
BRIGHTNESS_CONTRAST_MAX: int = 100

# ---------- 색조/채도 효과 ---------- #
HUE_SATURATION_MIN: int = -100
HUE_SATURATION_MAX: int = 100

# ---------- SVG 가져오기 ---------- #
# SVG는 벡터라 정해진 픽셀 크기가 없어, 공칭 크기(width/height 또는 viewBox)에
# 이 배율을 곱해 래스터화한다. 24x24 아이콘 SVG를 공칭 크기로 들여오면 확대
# 시 뭉개지므로 기본값을 100%보다 크게 둔다.
SVG_IMPORT_SCALE_MIN: int = 25
SVG_IMPORT_SCALE_MAX: int = 1600
DEFAULT_SVG_IMPORT_SCALE: int = 200
SVG_IMPORT_SCALE_STEP: int = 25     # 슬라이더 +/- 버튼의 한 번 이동량(%)
# 래스터화 결과의 긴 변 상한(4K 가로 해상도). 배율만 그대로 적용하면 큰 SVG에서
# 크기가 폭발하므로(3000x2000 원본 x 800% = 24000x16000, 약 1.5GB) 반드시 제한한다.
SVG_MAX_LONG_EDGE: int = 3840
SVG_EXTENSIONS: frozenset[str] = frozenset({".svg", ".svgz"})

# ---------- 저장 형식 ---------- #
SAVE_FILTERS: str = ("PNG (*.png);;JPEG (*.jpg);;WebP (*.webp);;AVIF (*.avif);;"
                     "TIFF (*.tif);;ICO (*.ico);;BMP (*.bmp)")
# 열기 대화상자 필터. Qt가 읽을 수 있는 포맷을 전부 나열하면 목록이 지나치게
# 길어지므로(pbm, xbm, wbmp, icns 등) 실제로 쓰이는 것만 추리고, 나머지는
# "모든 파일"로 직접 골라 열 수 있게 한다.
OPEN_FILTERS: str = (
    "이미지 파일 (*.png *.jpg *.jpeg *.bmp *.webp *.avif *.svg *.svgz *.gif *.tif *.tiff *.ico);;"
    "PNG (*.png);;JPEG (*.jpg *.jpeg);;WebP (*.webp);;AVIF (*.avif);;SVG (*.svg *.svgz);;"
    "BMP (*.bmp);;모든 파일 (*)"
)
# 확장자 -> QImage.save()에 넘길 Qt 포맷 이름. 확장자와 실제 파일 내용이 어긋나는
# 것을 막기 위해 저장 포맷은 항상 이 표에서 파생시킨다.
#
# 이 표는 화이트리스트다. "Qt가 쓸 수 있으면 무엇이든 허용"으로 넓히면 안 된다 -
# Qt는 pbm/xbm/wbmp에 1비트 흑백, pgm에 흑백, icns/cur에 규격 크기로 조용히 변환해
# 저장하면서 QImage.save()로는 성공(True)을 돌려주기 때문에, 사용자가 손실을
# 알아차릴 방법이 없다. 추가하려면 해당 포맷의 왕복 결과를 먼저 실측할 것.
SAVE_EXT_TO_FORMAT: dict[str, str] = {
    "png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP", "avif": "AVIF",
    "tif": "TIFF", "tiff": "TIFF", "ico": "ICO", "bmp": "BMP",
}
# Qt가 다루지 못해 Pillow를 거쳐 읽고 쓰는 포맷(capture.avif_io 참조).
PILLOW_FORMATS: frozenset[str] = frozenset({"AVIF"})
DEFAULT_SAVE_FORMAT: str = "PNG"
# 포맷별 저장 품질(-1 = Qt 기본값). WebP는 Qt 핸들러가 quality >= 100일 때
# 무손실로 인코딩하므로, 글자가 많은 화면 캡처가 뭉개지지 않도록 100을 쓴다.
# AVIF는 100이어도 완전 무손실이 아니다(Pillow가 무손실을 지원하지 않는다).
# 최대 품질 + 4:4:4로 오차를 채널당 2 이내로 억제한다 - capture/avif_io.py 참조.
SAVE_QUALITY: dict[str, int] = {"JPEG": 100, "WEBP": 100, "AVIF": 100}

# open_files()가 "열었던 파일에 Ctrl+S로 곧바로 덮어써도 되는" 확장자.
# 저장 가능 여부(SAVE_EXT_TO_FORMAT)와는 다른 판단이라 표를 따로 둔다:
# ICO는 16/32/48/256px 멀티사이즈를, TIFF는 여러 페이지를 담을 수 있는데 이 앱은
# 단일 이미지만 쓸 수 있어, 열었던 원본을 덮어쓰면 나머지 프레임이 사라진다.
# 그래서 저장 자체는 허용하되('다른 이름으로 저장'에서 사용자가 명시적으로 고를
# 때) 원본 자동 덮어쓰기 대상에서는 뺀다.
OVERWRITE_SAFE_EXTENSIONS: frozenset[str] = frozenset(
    {"png", "jpg", "jpeg", "webp", "avif", "bmp"})

# ICO 규격상 한 변의 최대 길이. 이보다 큰 이미지를 넘기면 Qt가 조용히 축소해
# 저장하므로(1920x1080 -> 256x144, 그런데도 save()는 성공을 반환) 저장 전에
# 사용자에게 확인을 받아야 한다.
ICO_MAX_EDGE: int = 256

# ---------- 도형 도구 ---------- #
DEFAULT_SHAPE_SUBTOOL: str = "rectangle"
SHAPE_ICON_PX: int = 26    # 도형/선 갤러리 아이콘 크기
