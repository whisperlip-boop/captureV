#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""메인 윈도우: 탭 관리, 툴바/단축키, 캡처·저장·붙여넣기 흐름을 담당한다."""

import logging
import os
import re
from datetime import datetime
from typing import Callable, Optional, cast

from PySide6.QtCore import QPoint, QRect, QSettings, QSize, QStandardPaths, QUrl, Qt, Signal
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent, QColor, QDesktopServices,
                            QDragEnterEvent, QDropEvent, QFont, QGuiApplication, QIcon, QImage,
                            QImageReader, QKeySequence, QMouseEvent, QPixmap,
                            QShortcut)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QDialogButtonBox, QFileDialog,
                                QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                                QMainWindow, QMenu, QMessageBox, QRadioButton, QSizePolicy, QSpinBox,
                                QTabBar, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
                                QWidgetAction)

from capture import screen_capture
from capture.avif_io import is_avif_path, read_avif, write_avif
from capture.canvas_size_dialog import CanvasSizeDialog
from capture.canvas_view import CanvasView
from capture.color_pick_overlay import ColorPickOverlay
from capture.config import (APP_NAME, BLUR_PERCENT_MAX, BLUR_PERCENT_MIN, BRIGHTNESS_CONTRAST_MAX,
                            BRIGHTNESS_CONTRAST_MIN, CANVAS_SURROUND_COLOR, DEFAULT_BLUR_PERCENT,
                            DEFAULT_CANVAS_SIZE_BG_COLOR, DEFAULT_DRAW_COLOR, DEFAULT_FILL_TOLERANCE,
                            DEFAULT_FIXED_CAPTURE_HEIGHT, DEFAULT_FIXED_CAPTURE_WIDTH, DEFAULT_MOSAIC_PERCENT,
                            DEFAULT_NEW_CANVAS_BG_COLOR, DEFAULT_NEW_CANVAS_HEIGHT, DEFAULT_NEW_CANVAS_WIDTH,
                            DEFAULT_SAVE_FORMAT, DEFAULT_SHAPE_SUBTOOL, DEFAULT_SHARPEN_PERCENT,
                            DEFAULT_SVG_IMPORT_SCALE, DEFAULT_TEXT_COLOR, DEFAULT_THICKNESS,
                            EFFECT_MENU_ICON_PX, FILL_TOLERANCE_MAX, FILL_TOLERANCE_MIN, HUE_SATURATION_MAX,
                            HUE_SATURATION_MIN, ICO_MAX_EDGE, MINI_TOOL_DIVIDER_COLOR, MINI_TOOL_ICON_PX,
                            MOSAIC_PERCENT_MAX, MOSAIC_PERCENT_MIN, NEW_CANVAS_SIZE_MAX, NEW_CANVAS_SIZE_MIN,
                            OPEN_FILTERS, OVERWRITE_SAFE_EXTENSIONS, PILLOW_FORMATS, SAVE_EXT_TO_FORMAT,
                            SAVE_FILTERS, SAVE_QUALITY, SHARPEN_PERCENT_MAX, SHARPEN_PERCENT_MIN,
                            SVG_EXTENSIONS, SVG_IMPORT_SCALE_MAX, SVG_IMPORT_SCALE_MIN, SVG_IMPORT_SCALE_STEP,
                            SVG_MAX_LONG_EDGE, TAB_SAVED_COLOR, TAB_UNSAVED_COLOR, THICKNESS_MAX,
                            THICKNESS_MIN, TOOLBAR_ICON_PX, ZOOM_PERCENT_MAX, ZOOM_PERCENT_MIN,
                            get_resource_path, get_settings_path)
from capture.desktop_shot import DesktopShot
from capture.dialog_utils import strip_minmax_buttons
from capture.dual_slider_dialog import DualSliderDialog
from capture.hotkeys import HotkeyFilter, HotkeySpec, register_global_hotkeys, unregister_global_hotkeys
from capture.image_resize_dialog import ImageResizeDialog
from capture.logging_setup import get_log_dir
from capture.palette import ColorDropdownButton, PaletteWidget
from capture.percent_dialog import PercentSettingsDialog
from capture.region_overlay import RegionOverlay
from capture.rotate_angle_dialog import RotateAngleDialog
from capture.shape_settings import ShapeSubtoolPanel
from capture.shapes import LINE_KINDS, SHAPE_KINDS
from capture.shortcut_dialog import ShortcutSettingsDialog
from capture.shortcuts import CAPTURE_ACTIONS, load_shortcut
from capture.text_settings import TextSettingsPanel

logger = logging.getLogger(__name__)

_MAGIC_ARROW_PX = 12   # 매직툴 버튼 오른쪽 ▼(허용범위 메뉴) 영역 폭


class _ClickableLabel(QLabel):
    """클릭을 신호로 알리는 QLabel (배율 표시 클릭 시 입력 팝업을 띄우는 데 사용)."""

    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _ZoomPopup(QWidget):
    """확대/축소 배율(%)을 직접 입력하는 작은 팝업."""

    def __init__(self, current_percent: int, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        self.spin = QSpinBox()
        self.spin.setRange(ZOOM_PERCENT_MIN, ZOOM_PERCENT_MAX)
        self.spin.setValue(current_percent)
        self.spin.setSuffix("%")
        layout.addWidget(self.spin)


class MainWindow(QMainWindow):
    """탭 기반 편집기 메인 윈도우."""

    def __init__(self) -> None:
        """윈도우, 탭 영역, 툴바, 단축키, 저장 폴더 설정을 초기화한다."""
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 760)
        self.setAcceptDrops(True)

        # 레지스트리 대신 사람이 읽을 수 있는 INI 파일에 설정을 저장한다
        # (exe로 배포 시 다른 PC로 옮기거나 백업/초기화하기 쉽도록).
        self.settings = QSettings(str(get_settings_path()), QSettings.Format.IniFormat)
        default_dir = os.path.join(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation) or
            os.path.expanduser("~"), APP_NAME)
        self.save_dir: str = cast(str, self.settings.value("save_dir", default_dir))
        self.last_region: Optional[QRect] = None      # 마지막 캡처 영역(논리 좌표)
        self._active_view: Optional[CanvasView] = None    # 탭 전환 시 이전 탭의 텍스트 편집 반영용

        geometry = self.settings.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        # 탭이 하나도 없을 때 빈 화면이 기본 위젯 배경(흰색)으로 나오면 마치
        # 캔버스가 이미 열려 있는 것처럼 보인다. 탭 안 캔버스 주위 배경색과
        # 동일하게 맞춰 '아직 아무것도 없는' 상태임을 분명히 한다.
        # 탭이 0개면 ::pane만으로는 채워지지 않아(스타일이 빈 팬 영역을
        # 그리지 않음) QTabWidget 자체 배경도 함께 지정해야 한다.
        self.tabs.setStyleSheet(
            f"QTabWidget {{ background-color: {CANVAS_SURROUND_COLOR}; }}"
            f"QTabWidget::pane {{ background-color: {CANVAS_SURROUND_COLOR}; }}")
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        # 캔버스 크기·확대/축소 배율·마지막 영역·저장 폴더를 모두 같은 모양의
        # 짧은 구분선으로 나눠 나란히 표시한다.
        status_group = QWidget()
        status_layout = QHBoxLayout(status_group)
        status_layout.setContentsMargins(0, 0, 8, 0)
        status_layout.setSpacing(8)
        self._canvas_size_label = QLabel()
        status_layout.addWidget(self._canvas_size_label)
        self._canvas_zoom_divider = self._make_status_divider()
        status_layout.addWidget(self._canvas_zoom_divider)
        self._zoom_label = _ClickableLabel()
        self._zoom_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zoom_label.setToolTip("클릭하여 배율 직접 입력")
        self._zoom_label.clicked.connect(self._open_zoom_popup)
        status_layout.addWidget(self._zoom_label)
        self._last_region_divider = self._make_status_divider()
        status_layout.addWidget(self._last_region_divider)
        self._last_region_label = QLabel()
        status_layout.addWidget(self._last_region_label)
        status_layout.addWidget(self._make_status_divider())
        self._save_dir_label = QLabel()
        status_layout.addWidget(self._save_dir_label)
        self.statusBar().addPermanentWidget(status_group)

        self._overlay: Optional[RegionOverlay] = None
        self._color_pick_overlay: Optional[ColorPickOverlay] = None
        # register_global_hotkeys()가 반환하는 필터. 참조를 유지해야 GC로 소멸되지 않는다.
        self.hotkey_filter: Optional[HotkeyFilter] = None
        self._build_toolbar()
        self._build_menu()
        self._build_shortcuts()
        self._update_status()
        self._register_hotkeys()

    # ---------- UI ---------- #
    @staticmethod
    def _make_status_divider() -> QFrame:
        """상태바 항목 사이에 쓰는 짧은 세로 구분선을 만든다."""
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        divider.setFixedHeight(14)
        return divider

    def _build_toolbar(self) -> None:
        """도구 툴바를 구성한다. 도구는 상호 배타적으로 선택되며, 추후 다른 도구를 추가한다."""
        self._current_tool = "move"

        saved_subtool = str(self.settings.value("draw_subtool", "brush"))
        self._draw_subtool = saved_subtool if saved_subtool in ("brush", "eraser", "highlighter") else "brush"

        saved_shape_subtool = str(self.settings.value("shape_subtool", DEFAULT_SHAPE_SUBTOOL))
        valid_shape_subtools = {k for k, _ in SHAPE_KINDS} | {k for k, _ in LINE_KINDS}
        self._shape_subtool = (saved_shape_subtool if saved_shape_subtool in valid_shape_subtools
                                else DEFAULT_SHAPE_SUBTOOL)

        saved_thickness = int(str(self.settings.value("draw_thickness", DEFAULT_THICKNESS)))
        self._draw_thickness = min(max(saved_thickness, THICKNESS_MIN), THICKNESS_MAX)

        self._draw_color = QColor(self.settings.value("draw_color", DEFAULT_DRAW_COLOR))
        self._fill_tolerance = int(str(self.settings.value("fill_tolerance", DEFAULT_FILL_TOLERANCE)))
        saved_magic_tolerance = int(str(self.settings.value("magic_tolerance", DEFAULT_FILL_TOLERANCE)))
        self._magic_tolerance = min(max(saved_magic_tolerance, FILL_TOLERANCE_MIN), FILL_TOLERANCE_MAX)
        self._new_canvas_width = int(str(self.settings.value("new_canvas_width", DEFAULT_NEW_CANVAS_WIDTH)))
        self._new_canvas_height = int(str(self.settings.value("new_canvas_height", DEFAULT_NEW_CANVAS_HEIGHT)))
        self._new_canvas_bg_color = QColor(
            self.settings.value("new_canvas_bg_color", DEFAULT_NEW_CANVAS_BG_COLOR))
        self._new_canvas_bg_transparent = bool(
            self.settings.value("new_canvas_bg_transparent", False, type=bool))
        self._canvas_size_bg_color = QColor(
            self.settings.value("canvas_size_bg_color", DEFAULT_CANVAS_SIZE_BG_COLOR))
        saved_svg_scale = int(str(self.settings.value("svg_import_scale", DEFAULT_SVG_IMPORT_SCALE)))
        self._svg_import_scale = min(max(saved_svg_scale, SVG_IMPORT_SCALE_MIN), SVG_IMPORT_SCALE_MAX)
        self._color_pick_target: str = "draw"      # 색상 추출이 그리기 색/텍스트 색 중 어디로 갈지

        self._toolbar = QToolBar("main")
        self._toolbar.setMovable(False)
        self._toolbar.setIconSize(QSize(TOOLBAR_ICON_PX, TOOLBAR_ICON_PX))
        self._toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        # 평상시엔 배경 없이 아이콘만 보이고, 선택(체크)된 도구만 눌린 느낌의
        # 옅은 배경(#E1E1E1)과 은은한 테두리로 구분한다. '두께'와 '그리기'
        # 화살표(#thicknessBtn/#drawArrow)는 화살표를 텍스트 하단 중앙에
        # 오도록 별도로 위치를 지정해 두 버튼의 하위 메뉴 표시 방식을 통일한다.
        # #thicknessBtn/#drawArrow와 동일한 padding-bottom(14px)을 '이동'/'선택'
        # 처럼 하위 메뉴 화살표가 없는 버튼(#plainToolBtn)에도 똑같이 줘서, 화살표
        # 자리만큼의 빈 공간까지 포함해 네 버튼의 전체 높이·아이콘/텍스트 위치를 맞춘다.
        self._toolbar.setStyleSheet(
            "QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; }"
            "QToolButton:hover { background-color: #F0F0F0; border: 1px solid #D9D9D9; }"
            "QToolButton:checked { background-color: #E1E1E1; border: 1px solid #C7C7C7; }"
            "QToolButton:checked:hover { background-color: #E1E1E1; border: 1px solid #C7C7C7; }"
            "QToolButton#plainToolBtn { padding-bottom: 14px; }"
            "QToolButton#thicknessBtn { padding-bottom: 14px; }"
            "QToolButton#thicknessBtn::menu-indicator { subcontrol-origin: padding; subcontrol-position: bottom center; }"
            "QToolButton#drawArrow { border: none; }"
            "QToolButton#drawArrow:hover { background-color: #F0F0F0; border: 1px solid #D9D9D9; }"
            "QToolButton#drawArrow:checked { background-color: #E1E1E1; border: 1px solid #C7C7C7; }"
            "QToolButton#drawArrow:checked:hover { background-color: #E1E1E1; border: 1px solid #C7C7C7; }"
            "QToolButton#drawArrow::menu-indicator { subcontrol-origin: padding; subcontrol-position: center; }")
        self.addToolBar(self._toolbar)

        self._build_new_button()

        # 도구 버튼들은 라디오 버튼처럼 하나만 선택되도록 그룹으로 묶는다.
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)

        self._move_action = QAction(QIcon(str(get_resource_path("img/move.png"))), "이동", self)
        self._move_action.setCheckable(True)
        self._move_action.setToolTip("이동")
        self._move_action.triggered.connect(lambda: self._set_tool("move"))
        self._tool_group.addAction(self._move_action)
        self._toolbar.addAction(self._move_action)
        self._toolbar.widgetForAction(self._move_action).setObjectName("plainToolBtn")
        # 실행할 때마다 기본 도구('이동')가 항상 명확히 선택 표시된 상태로
        # 시작해야 한다 (지난 실행에서 마지막에 쓰던 도구가 화면에 남아있는
        # 것처럼 보이면, 실제로는 '이동'이 활성인데 다른 도구가 선택된 것으로
        # 착각해 캔버스를 드래그하는 등 혼동이 생길 수 있다).
        self._move_action.setChecked(True)

        self._select_action = QAction(QIcon(str(get_resource_path("img/select.png"))), "선택", self)
        self._select_action.setCheckable(True)
        self._select_action.setToolTip("선택 (드래그로 영역 지정, Ctrl+C 복사 / Ctrl+X 잘라내기)")
        self._select_action.triggered.connect(lambda: self._set_tool("select"))
        self._tool_group.addAction(self._select_action)
        self._toolbar.addAction(self._select_action)
        self._toolbar.widgetForAction(self._select_action).setObjectName("plainToolBtn")

        self._build_draw_button()
        self._build_fill_button()
        self._build_thickness_button()
        self._build_text_button()
        self._build_shape_button()

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._toolbar.addWidget(spacer)

        self._build_mini_tools_group()

        self._palette = PaletteWidget(self._draw_color, self.settings)
        self._palette.colorChanged.connect(self._on_color_changed)
        self._palette.startColorPicking.connect(self._start_color_picking)
        self._toolbar.addWidget(self._palette)

    def _build_new_button(self) -> None:
        """'신규' 버튼(캔버스 크기 설정 하위 메뉴)을 구성한다.

        본체를 클릭하면 설정된 크기의 흰색 캔버스로 새 탭이 바로 생성되고,
        화살표를 누르면 캔버스 크기를 설정하는 팝업을 여는 메뉴가 열린다.
        도구가 아니라 즉시 실행되는 동작이라 _tool_group에는 넣지 않는다.
        """
        self._new_action = QAction(QIcon(str(get_resource_path("img/new.png"))), "신규", self)
        self._new_action.setToolTip("신규 (설정된 크기의 새 캔버스 탭 생성)")
        self._new_action.triggered.connect(self._create_new_canvas)

        self._new_menu = QMenu(self)
        new_settings_action = QAction("새로 만들기 설정...", self)
        new_settings_action.triggered.connect(self._open_new_canvas_settings_dialog)
        self._new_menu.addAction(new_settings_action)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        new_body = QToolButton()
        new_body.setDefaultAction(self._new_action)
        new_body.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        new_body.setIconSize(QSize(TOOLBAR_ICON_PX, TOOLBAR_ICON_PX))

        new_arrow = QToolButton()
        new_arrow.setObjectName("drawArrow")
        new_arrow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        new_arrow.setMenu(self._new_menu)
        new_arrow.setFixedHeight(14)
        new_arrow.setFixedWidth(new_body.sizeHint().width())

        layout.addWidget(new_body)
        layout.addWidget(new_arrow, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._toolbar.addWidget(container)

    def _open_new_canvas_settings_dialog(self) -> None:
        """'신규' 버튼 클릭 시 생성할 캔버스의 크기(Width/Height)와 배경을 설정한다."""
        dialog = QDialog(self)
        dialog.setWindowTitle("새로 만들기 설정")
        strip_minmax_buttons(dialog)
        form = QFormLayout(dialog)

        width_spin = QSpinBox(dialog)
        width_spin.setRange(NEW_CANVAS_SIZE_MIN, NEW_CANVAS_SIZE_MAX)
        width_spin.setValue(self._new_canvas_width)
        form.addRow("Width (px):", width_spin)

        height_spin = QSpinBox(dialog)
        height_spin.setRange(NEW_CANVAS_SIZE_MIN, NEW_CANVAS_SIZE_MAX)
        height_spin.setValue(self._new_canvas_height)
        form.addRow("Height (px):", height_spin)

        color_ctrl = ColorDropdownButton(self._new_canvas_bg_color, self.settings, label="색",
                                          vertical=True, settings_key="new_canvas_custom_colors",
                                          parent=dialog)
        color_ctrl.startColorPicking.connect(lambda: self._start_new_canvas_color_picking(dialog, color_ctrl))

        custom_radio = QRadioButton("사용자 지정색", dialog)
        transparent_radio = QRadioButton("투명색", dialog)
        bg_group = QButtonGroup(dialog)
        bg_group.addButton(custom_radio)
        bg_group.addButton(transparent_radio)
        (transparent_radio if self._new_canvas_bg_transparent else custom_radio).setChecked(True)
        color_ctrl.setEnabled(not self._new_canvas_bg_transparent)
        custom_radio.toggled.connect(color_ctrl.setEnabled)

        radio_col = QVBoxLayout()
        radio_col.addWidget(custom_radio)
        radio_col.addWidget(transparent_radio)
        bg_row = QHBoxLayout()
        bg_row.addWidget(color_ctrl)
        bg_row.addLayout(radio_col)
        bg_row.addStretch()
        form.addRow(bg_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._new_canvas_width = width_spin.value()
        self._new_canvas_height = height_spin.value()
        self._new_canvas_bg_color = color_ctrl.color()
        self._new_canvas_bg_transparent = transparent_radio.isChecked()
        self.settings.setValue("new_canvas_width", self._new_canvas_width)
        self.settings.setValue("new_canvas_height", self._new_canvas_height)
        self.settings.setValue("new_canvas_bg_color", self._new_canvas_bg_color.name())
        self.settings.setValue("new_canvas_bg_transparent", self._new_canvas_bg_transparent)
        logger.info("신규 캔버스 설정: %dx%d, 배경=%s", self._new_canvas_width, self._new_canvas_height,
                    "투명" if self._new_canvas_bg_transparent else self._new_canvas_bg_color.name())

    def _start_new_canvas_color_picking(self, dialog: QDialog, color_ctrl: ColorDropdownButton) -> None:
        """'새로 만들기 설정' 안에서 색상 추출 도구를 시작한다.

        다이얼로그가 모달(exec())로 열려 있는 동안에는 다른 창이 클릭을
        받을 수 없으므로, 추출하는 동안만 다이얼로그를 잠시 숨기고 오버레이가
        닫히면(추출 완료/취소 모두) 다시 보여준다.
        """
        dialog.hide()
        overlay = ColorPickOverlay()
        dialog._pick_overlay = overlay     # GC로 창이 사라지지 않도록 붙잡아 둔다

        def on_picked(color: QColor) -> None:
            color_ctrl.add_custom_color(color)
            color_ctrl.set_color(color)

        def on_closed() -> None:
            dialog._pick_overlay = None
            dialog.show()
            dialog.activateWindow()

        overlay.picked.connect(on_picked)
        overlay.destroyed.connect(on_closed)
        overlay.show()
        overlay.activateWindow()
        overlay.raise_()
        overlay.setFocus()

    def _create_new_canvas(self) -> None:
        """설정된 배경(사용자 지정색/투명)의 새 캔버스로 새 탭을 생성한다.

        클립보드에 이미지가 있으면 그 이미지의 크기를 사용하고(내용은
        붙여넣지 않고 크기만 참고), 없으면 '새로 만들기 설정'에서 지정한
        크기를 사용한다.
        """
        clipboard_image = QGuiApplication.clipboard().image()
        if not clipboard_image.isNull():
            width, height = clipboard_image.width(), clipboard_image.height()
        else:
            width, height = self._new_canvas_width, self._new_canvas_height
        if self._new_canvas_bg_transparent:
            image = QImage(width, height, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
        else:
            image = QImage(width, height, QImage.Format.Format_RGB32)
            image.fill(self._new_canvas_bg_color)
        self.add_tab(image, datetime.now().strftime("%Y-%m-%d_%H%M%S"))
        logger.info("신규 캔버스 생성: %dx%d", width, height)

    def _build_draw_button(self) -> None:
        """'그리기' 버튼(브러시/지우개/형광펜 하위 메뉴)을 구성한다.

        아이콘+텍스트 본체를 클릭하면 마지막으로 선택한 하위 도구가 바로
        실행되고, 본체 아래 작은 화살표를 클릭하면 하위 메뉴가 열린다.
        QToolButton의 기본 MenuButtonPopup은 화살표가 오른쪽에 붙어 '두께'
        버튼(화살표가 텍스트 하단 중앙)과 모양이 달라지므로, 본체 버튼과
        화살표 버튼을 세로로 쌓은 합성 위젯으로 직접 구성해 모양을 통일한다.
        """
        self._draw_subtool_group = QActionGroup(self)
        self._draw_subtool_group.setExclusive(True)
        self._draw_menu = QMenu(self)
        self._draw_subtool_actions: dict[str, QAction] = {}

        subtools = [("brush", "브러시", "brush.png"), ("eraser", "지우개", "eraser.png"),
                    ("highlighter", "형광펜", "highlighter.png")]
        for subtool, label, icon_file in subtools:
            a = QAction(QIcon(str(get_resource_path(f"img/{icon_file}"))), label, self)
            a.setCheckable(True)
            a.triggered.connect(lambda _checked=False, st=subtool: self._set_draw_subtool(st))
            self._draw_subtool_group.addAction(a)
            self._draw_menu.addAction(a)
            self._draw_subtool_actions[subtool] = a
        self._draw_subtool_actions[self._draw_subtool].setChecked(True)

        self._draw_action = QAction(QIcon(str(get_resource_path("img/brush.png"))), "그리기", self)
        self._draw_action.setCheckable(True)
        self._draw_action.setToolTip("그리기 (브러시/지우개/형광펜)")
        self._draw_action.triggered.connect(lambda: self._set_tool("draw"))
        self._tool_group.addAction(self._draw_action)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        draw_body = QToolButton()
        draw_body.setDefaultAction(self._draw_action)
        draw_body.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        # 툴바의 addWidget()으로 들어가는 버튼은 QToolBar의 iconSize를 자동으로
        # 물려받지 않아 명시적으로 지정해야 다른 도구 버튼과 아이콘 크기가 같아진다.
        draw_body.setIconSize(QSize(TOOLBAR_ICON_PX, TOOLBAR_ICON_PX))

        draw_arrow = QToolButton()
        draw_arrow.setObjectName("drawArrow")
        draw_arrow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        draw_arrow.setMenu(self._draw_menu)
        draw_arrow.setCheckable(True)
        draw_arrow.setFixedHeight(14)
        # 화살표 버튼 너비를 본체 버튼과 맞춰야 화살표가 '두께'처럼 버튼 중앙에 온다
        # (QVBoxLayout은 자식 위젯을 컨테이너 너비만큼 자동으로 늘려주지 않는다).
        draw_arrow.setFixedWidth(draw_body.sizeHint().width())
        self._draw_action.toggled.connect(draw_arrow.setChecked)

        layout.addWidget(draw_body)
        layout.addWidget(draw_arrow, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._toolbar.addWidget(container)

    def _build_fill_button(self) -> None:
        """'채우기' 버튼(허용범위 하위 메뉴)을 구성한다.

        본체를 클릭하면 채우기 도구가 바로 활성화되고, 화살표를 누르면
        허용 범위를 설정하는 팝업을 여는 메뉴가 열린다. '그리기' 화살표와
        동일한 #drawArrow 스타일을 재사용해 모양을 통일한다.
        """
        self._fill_action = QAction(QIcon(str(get_resource_path("img/fill.png"))), "채우기", self)
        self._fill_action.setCheckable(True)
        self._fill_action.setToolTip("채우기 (클릭한 지점과 비슷한 색 영역을 현재 색으로 채움)")
        self._fill_action.triggered.connect(lambda: self._set_tool("fill"))
        self._tool_group.addAction(self._fill_action)

        self._fill_menu = QMenu(self)
        tolerance_action = QAction("허용범위...", self)
        tolerance_action.triggered.connect(self._open_fill_tolerance_dialog)
        self._fill_menu.addAction(tolerance_action)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        fill_body = QToolButton()
        fill_body.setDefaultAction(self._fill_action)
        fill_body.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        fill_body.setIconSize(QSize(TOOLBAR_ICON_PX, TOOLBAR_ICON_PX))

        fill_arrow = QToolButton()
        fill_arrow.setObjectName("drawArrow")
        fill_arrow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        fill_arrow.setMenu(self._fill_menu)
        fill_arrow.setCheckable(True)
        fill_arrow.setFixedHeight(14)
        fill_arrow.setFixedWidth(fill_body.sizeHint().width())
        self._fill_action.toggled.connect(fill_arrow.setChecked)

        layout.addWidget(fill_body)
        layout.addWidget(fill_arrow, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._toolbar.addWidget(container)

    def _get_int(self, title: str, label: str, value: int, min_: int, max_: int) -> tuple[int, bool]:
        """제목줄에 닫기 버튼만 남은 정수 입력 다이얼로그를 열어 (값, 확인 여부)를 반환한다."""
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setInputMode(QInputDialog.InputMode.IntInput)
        dialog.setIntRange(min_, max_)
        dialog.setIntValue(value)
        strip_minmax_buttons(dialog)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return value, False
        return dialog.intValue(), True

    def _warn(self, text: str) -> None:
        """제목줄에 닫기 버튼만 남은 경고 메시지 창을 띄운다."""
        box = QMessageBox(QMessageBox.Icon.Warning, APP_NAME, text, QMessageBox.StandardButton.Ok, self)
        strip_minmax_buttons(box)
        box.exec()

    def _open_fill_tolerance_dialog(self) -> None:
        """채우기 허용 범위(%)를 입력받아 설정에 저장한다."""
        value, ok = self._get_int(
            "허용 범위", "채우기 허용 범위 (%):\n(0 = 정확히 같은 색만, 100 = 거의 모든 인접 영역)",
            self._fill_tolerance, FILL_TOLERANCE_MIN, FILL_TOLERANCE_MAX)
        if not ok:
            return
        self._fill_tolerance = value
        self.settings.setValue("fill_tolerance", value)
        self._sync_view(self.current_view())
        self.statusBar().showMessage(f"채우기 허용 범위: {value}%", 2500)
        logger.info("채우기 허용 범위 변경: %d%%", value)

    def _open_magic_tolerance_dialog(self) -> None:
        """매직툴 허용 범위(%)를 입력받아 설정에 저장한다 (채우기 허용 범위와 별도)."""
        value, ok = self._get_int(
            "허용 범위", "매직툴 허용 범위 (%):\n(0 = 정확히 같은 색만, 100 = 거의 모든 인접 영역)",
            self._magic_tolerance, FILL_TOLERANCE_MIN, FILL_TOLERANCE_MAX)
        if not ok:
            return
        self._magic_tolerance = value
        self.settings.setValue("magic_tolerance", value)
        v = self.current_view()
        if v is not None:
            v.set_magic_tolerance(value)
        self.statusBar().showMessage(f"매직툴 허용 범위: {value}%", 2500)
        logger.info("매직툴 허용 범위 변경: %d%%", value)

    def _build_thickness_button(self) -> None:
        """'두께' 버튼(1~10px 하위 메뉴)을 구성한다."""
        self._thickness_group = QActionGroup(self)
        self._thickness_group.setExclusive(True)
        self._thickness_menu = QMenu(self)
        self._thickness_actions: dict[int, QAction] = {}

        for px in range(THICKNESS_MIN, THICKNESS_MAX + 1):
            a = QAction(f"{px}px", self)
            a.setCheckable(True)
            a.triggered.connect(lambda _checked=False, p=px: self._set_thickness(p))
            self._thickness_group.addAction(a)
            self._thickness_menu.addAction(a)
            self._thickness_actions[px] = a
        self._thickness_actions[self._draw_thickness].setChecked(True)

        self._thickness_button = QToolButton()
        self._thickness_button.setObjectName("thicknessBtn")
        self._thickness_button.setIcon(QIcon(str(get_resource_path("img/linewidth.png"))))
        self._thickness_button.setIconSize(QSize(TOOLBAR_ICON_PX, TOOLBAR_ICON_PX))
        self._thickness_button.setText("두께")
        self._thickness_button.setToolTip("선 두께 (1~10px)")
        self._thickness_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self._thickness_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._thickness_button.setMenu(self._thickness_menu)
        self._toolbar.addWidget(self._thickness_button)

    def _build_text_button(self) -> None:
        """'텍스트' 버튼(폰트/크기/색상/정렬 설정 하위 메뉴)을 구성한다.

        본체를 클릭하면 텍스트 도구가 활성화되고, 화살표를 누르면 폰트/크기/
        색상/볼드·이탤릭/정렬을 설정하는 패널이 열린다 (확인 버튼 없이 즉시 적용).
        """
        self._text_action = QAction(QIcon(str(get_resource_path("img/text.png"))), "텍스트", self)
        self._text_action.setCheckable(True)
        self._text_action.setToolTip("텍스트 (드래그로 영역을 지정해 글자를 입력)")
        self._text_action.triggered.connect(lambda: self._set_tool("text"))
        self._tool_group.addAction(self._text_action)

        saved_text_color = QColor(self.settings.value("text_color", DEFAULT_TEXT_COLOR))
        self._text_settings = TextSettingsPanel(saved_text_color, self.settings)

        # optionsChanged 연결 전에 모든 값을 먼저 복원한다. 먼저 연결해두면
        # set_font()/set_align() 각각이 optionsChanged를 즉시 발생시켜, 아직
        # 복원되지 않은 나머지 값(예: set_font 시점의 정렬)을 그 순간의
        # 기본값으로 다시 저장해버려 방금 불러온 값을 덮어쓰게 된다.
        saved_font_str = str(self.settings.value("text_font", ""))
        if saved_font_str:
            saved_font = QFont()
            saved_font.fromString(saved_font_str)
            self._text_settings.set_font(saved_font)
        self._text_settings.set_align(str(self.settings.value("text_align_h", "left")),
                                       str(self.settings.value("text_align_v", "top")))

        self._text_settings.optionsChanged.connect(self._on_text_options_changed)
        self._text_settings.startColorPicking.connect(self._start_text_color_picking)

        text_menu = QMenu(self)
        action = QWidgetAction(text_menu)
        action.setDefaultWidget(self._text_settings)
        text_menu.addAction(action)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        text_body = QToolButton()
        text_body.setDefaultAction(self._text_action)
        text_body.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        text_body.setIconSize(QSize(TOOLBAR_ICON_PX, TOOLBAR_ICON_PX))

        text_arrow = QToolButton()
        text_arrow.setObjectName("drawArrow")
        text_arrow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        text_arrow.setMenu(text_menu)
        text_arrow.setCheckable(True)
        text_arrow.setFixedHeight(14)
        text_arrow.setFixedWidth(text_body.sizeHint().width())
        self._text_action.toggled.connect(text_arrow.setChecked)

        layout.addWidget(text_body)
        layout.addWidget(text_arrow, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._toolbar.addWidget(container)

    def _build_shape_button(self) -> None:
        """'도형' 버튼(도형/선 갤러리 하위 메뉴)을 구성한다.

        본체를 클릭하면 활성 도구가 '도형'으로 바뀌면서 화살표를 누른 것과
        똑같은 위치에 도형/선 갤러리 팝업이 열린다(대표 아이콘이 없는
        갤러리형 도구라, '그리기'처럼 본체 클릭 시 마지막 하위 도구를 바로
        활성화하지 않는다). 팝업 위치를 화살표와 완전히 동일하게 맞추기
        위해, 본체에는 메뉴를 따로 달지 않고 화살표의 showMenu()를 그대로
        재사용한다(본체에 메뉴를 달면 Qt 기본 팝업 위치 계산이 화살표와
        달라진다). 갤러리에서 항목을 클릭하면 그 즉시 하위 도구가 바뀌고
        팝업이 닫힌다.
        """
        self._shape_action = QAction(QIcon(str(get_resource_path("img/figure.png"))), "도형", self)
        self._shape_action.setCheckable(True)
        self._shape_action.setToolTip("도형 (사각형/타원/삼각형 등 도형과 직선/자유곡선)")
        self._shape_action.triggered.connect(lambda: self._set_tool("shape"))
        self._tool_group.addAction(self._shape_action)

        self._shape_panel = ShapeSubtoolPanel()
        self._shape_panel.subtoolChosen.connect(self._set_shape_subtool)

        self._shape_menu = QMenu(self)
        action = QWidgetAction(self._shape_menu)
        action.setDefaultWidget(self._shape_panel)
        self._shape_menu.addAction(action)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        shape_body = QToolButton()
        shape_body.setDefaultAction(self._shape_action)
        shape_body.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        shape_body.setIconSize(QSize(TOOLBAR_ICON_PX, TOOLBAR_ICON_PX))

        shape_arrow = QToolButton()
        shape_arrow.setObjectName("drawArrow")
        shape_arrow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        shape_arrow.setMenu(self._shape_menu)
        shape_arrow.setCheckable(True)
        shape_arrow.setFixedHeight(14)
        shape_arrow.setFixedWidth(shape_body.sizeHint().width())
        self._shape_action.toggled.connect(shape_arrow.setChecked)
        self._shape_action.triggered.connect(shape_arrow.showMenu)

        layout.addWidget(shape_body)
        layout.addWidget(shape_arrow, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._toolbar.addWidget(container)

    def _build_mini_tools_group(self) -> None:
        """색 박스 왼쪽에 '효과'/'회전'/'크기 조절'/'색상 추출' 2x2 소형 버튼 그룹을 구성한다.

        효과/회전/크기 조절은 하위 메뉴를 나중에 하나씩 채울 자리라 지금은 빈
        메뉴만 달아 화살표만 보이게 해둔다. 색상 추출은 팔레트의 기존 색상
        추출 도구(그리기 색 추출)로 바로 연결되는 바로가기다. 왼쪽 구분선
        바깥에는 '모든 탭 닫기' 아이콘 버튼을 함께 둔다.
        """
        self._effect_menu = QMenu(self)
        self._rotate_menu = QMenu(self)
        self._resize_menu = QMenu(self)
        self._populate_effect_menu()
        self._populate_rotate_menu()
        self._populate_resize_menu()

        effect_btn = self._make_mini_tool_button("효과", "effect.png", self._effect_menu)
        rotate_btn = self._make_mini_tool_button("회전", "Rotation.png", self._rotate_menu)
        resize_btn = self._make_mini_tool_button("크기 조절", "size.png", self._resize_menu)
        self._pick_btn = self._make_mini_tool_button("색상 추출", "pipette.png", None)
        self._pick_btn.setCheckable(True)
        self._pick_btn.setStyleSheet(
            "QToolButton:hover { background-color: #F0F0F0; border: 1px solid #D9D9D9; }"
            "QToolButton:checked { background-color: #E1E1E1; border: 1px solid #C7C7C7; }"
            "QToolButton:checked:hover { background-color: #E1E1E1; border: 1px solid #C7C7C7; }")
        self._pick_btn.clicked.connect(self._start_color_picking)
        pick_btn = self._pick_btn

        # '모든 탭 닫기'는 도구가 아니라 즉시 실행되는 동작이라 2x2 그리드에
        # 넣지 않고, 그룹 왼쪽 구분선 바깥에 아이콘만 따로 둔다(글자를 넣으면
        # 소형 버튼들과 같은 종류로 보여 실수로 누를 위험이 있다).
        self._close_all_btn = QToolButton()
        self._close_all_btn.setIcon(QIcon(str(get_resource_path("img/allclose.png"))))
        self._close_all_btn.setIconSize(QSize(MINI_TOOL_ICON_PX, MINI_TOOL_ICON_PX))
        self._close_all_btn.setToolTip("모든 탭 닫기")
        self._close_all_btn.setStyleSheet(
            "QToolButton:hover { background-color: #F0F0F0; border: 1px solid #D9D9D9; }")
        self._close_all_btn.clicked.connect(self._close_all_tabs)

        # 매직툴은 '모든 탭 닫기' 아래 빈 칸에 아이콘만 둔다. 다른 도구와 같은
        # 그룹(_tool_group)에 넣어 배타적으로 선택되며, 오른쪽 ▾에서 허용 범위를 고른다.
        self._magic_action = QAction(QIcon(str(get_resource_path("img/magic-tool.png"))), "매직툴", self)
        self._magic_action.setCheckable(True)
        self._magic_action.setToolTip(
            "매직툴 (클릭한 지점과 비슷한 색 영역 선택, Shift+클릭 추가 / Alt+클릭 빼기 / Esc 해제)\n"
            "Ctrl+C 복사, Ctrl+X 잘라내기, Delete 지우기, 채우기 도구로 영역 안 클릭 시 전체 채우기")
        self._magic_action.triggered.connect(lambda: self._set_tool("magic"))
        self._tool_group.addAction(self._magic_action)
        magic_menu = QMenu(self)
        magic_tolerance_action = QAction("허용범위...", self)
        magic_tolerance_action.triggered.connect(self._open_magic_tolerance_dialog)
        magic_menu.addAction(magic_tolerance_action)
        self._magic_btn = QToolButton()
        self._magic_btn.setDefaultAction(self._magic_action)
        self._magic_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._magic_btn.setIconSize(QSize(MINI_TOOL_ICON_PX, MINI_TOOL_ICON_PX))
        self._magic_btn.setMenu(magic_menu)
        self._magic_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        # 스타일시트를 쓰면 ▼(menu-button) 자리가 따로 잡히지 않아 아이콘 위에 겹치므로,
        # 오른쪽 padding으로 ▼ 폭만큼 공간을 확보하고 그 안에 ▼를 둔다.
        self._magic_btn.setStyleSheet(
            f"QToolButton {{ padding-right: {_MAGIC_ARROW_PX}px; }}"
            f"QToolButton::menu-button {{ width: {_MAGIC_ARROW_PX}px; border: none; }}"
            "QToolButton:hover { background-color: #F0F0F0; border: 1px solid #D9D9D9; }"
            "QToolButton:checked { background-color: #E1E1E1; border: 1px solid #C7C7C7; }"
            "QToolButton:checked:hover { background-color: #E1E1E1; border: 1px solid #C7C7C7; }")

        # 네 버튼 너비를 통일해 화살표(v)가 텍스트 길이와 무관하게 항상
        # 같은 위치(오른쪽 끝)에 오도록 한다. 폭을 맞추지 않으면 짧은 글자의
        # 버튼(효과/회전)은 화살표가 글자 바로 옆에 붙어버린다.
        buttons = (effect_btn, rotate_btn, resize_btn, pick_btn)
        width = max(b.sizeHint().width() for b in buttons)
        for b in buttons:
            b.setFixedWidth(width)

        # '모든 탭 닫기' 버튼과 구분선까지 한 그리드에 담는다. 버튼을 별도
        # 레이아웃에 두면 두 줄 그리드의 위쪽 줄과 높이·수직 위치가 어긋나
        # ('효과'보다 위로 8px 정도 뜬다), 같은 행(row 0)에 넣어야 '효과'와
        # 정확히 같은 높이에 놓인다. 구분선은 두 줄 전체 높이로 span 한다.
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        # 매직툴은 ▼ 폭만큼 넓으므로 두 버튼을 왼쪽 정렬해 아이콘의 세로 줄을 맞춘다.
        grid.addWidget(self._close_all_btn, 0, 0, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._magic_btn, 1, 0, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._make_mini_group_divider(), 0, 1, 2, 1)
        grid.addWidget(effect_btn, 0, 2)
        grid.addWidget(rotate_btn, 0, 3)
        grid.addWidget(resize_btn, 1, 2)
        grid.addWidget(pick_btn, 1, 3)
        grid.addWidget(self._make_mini_group_divider(), 0, 4, 2, 1)

        layout = QHBoxLayout()
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        layout.addLayout(grid)

        container = QWidget()
        container.setLayout(layout)
        self._toolbar.addWidget(container)

    @staticmethod
    def _make_mini_group_divider() -> QFrame:
        """소형 버튼 그룹 좌우에 두는 짙은 회색 구분선."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setStyleSheet(f"QFrame {{ color: {MINI_TOOL_DIVIDER_COLOR}; }}")
        return line

    @staticmethod
    def _make_mini_tool_button(text: str, icon_file: str, menu: Optional[QMenu]) -> QToolButton:
        """아이콘이 왼쪽, 글자가 오른쪽인 소형 버튼을 만든다 (menu가 있으면 화살표도 표시).

        menu가 있는 버튼은 InstantPopup이라 클릭 자체를 토글할 수 없으므로,
        하위 메뉴가 열려 있는 동안만 다른 선택된 버튼들과 동일하게 배경색이
        바뀌도록 menu의 표시/숨김 시점에 checked 상태를 직접 맞춰준다.
        """
        btn = QToolButton()
        btn.setText(text)
        btn.setIcon(QIcon(str(get_resource_path(f"img/{icon_file}"))))
        btn.setIconSize(QSize(MINI_TOOL_ICON_PX, MINI_TOOL_ICON_PX))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        if menu is not None:
            btn.setMenu(menu)
            btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QToolButton:hover { background-color: #F0F0F0; border: 1px solid #D9D9D9; }"
                "QToolButton:checked { background-color: #E1E1E1; border: 1px solid #C7C7C7; }"
                "QToolButton:checked:hover { background-color: #E1E1E1; border: 1px solid #C7C7C7; }")
            menu.aboutToShow.connect(lambda b=btn: b.setChecked(True))
            menu.aboutToHide.connect(lambda b=btn: b.setChecked(False))
        return btn

    def _populate_effect_menu(self) -> None:
        """'효과' 하위 메뉴(색반전/무채화/모자이크/흐리게/선명하게/밝기·대비/색조·채도)를 구성한다."""
        self._mosaic_percent = DEFAULT_MOSAIC_PERCENT
        self._blur_percent = DEFAULT_BLUR_PERCENT
        self._sharpen_percent = DEFAULT_SHARPEN_PERCENT

        immediate_effects = [("색반전", "invert.png", "invert_colors"), ("무채화", "decolor.png", "grayscale")]
        for text, icon_file, method_name in immediate_effects:
            action = QAction(self._load_menu_icon(icon_file), text, self)
            action.triggered.connect(lambda _checked=False, m=method_name: self._run_canvas_op(m))
            self._effect_menu.addAction(action)

        mosaic_action = QAction(self._load_menu_icon("mosaic.png"), "모자이크", self)
        mosaic_action.triggered.connect(self._open_mosaic_dialog)
        self._effect_menu.addAction(mosaic_action)

        blur_action = QAction(self._load_menu_icon("blur.png"), "흐리게", self)
        blur_action.triggered.connect(self._open_blur_dialog)
        self._effect_menu.addAction(blur_action)

        sharpen_action = QAction(self._load_menu_icon("Clearly.png"), "선명하게", self)
        sharpen_action.triggered.connect(self._open_sharpen_dialog)
        self._effect_menu.addAction(sharpen_action)

        brightness_contrast_action = QAction(self._load_menu_icon("contrast.png"), "밝기/대비", self)
        brightness_contrast_action.triggered.connect(self._open_brightness_contrast_dialog)
        self._effect_menu.addAction(brightness_contrast_action)

        hue_saturation_action = QAction(self._load_menu_icon("saturation.png"), "색조/채도", self)
        hue_saturation_action.triggered.connect(self._open_hue_saturation_dialog)
        self._effect_menu.addAction(hue_saturation_action)

    @staticmethod
    def _load_menu_icon(icon_file: str) -> QIcon:
        """메뉴 항목 높이를 넘지 않는 작은 크기로 스케일한 아이콘을 만든다.

        QMenu는 QToolBar/QToolButton과 달리 setIconSize()가 없어, 스타일의
        기본 아이콘 크기에 원본 픽스맵을 그대로 맡기면 메뉴 행 높이가 커질
        수 있다. 미리 정해진 작은 크기로 스케일해 둔 픽스맵으로 QIcon을
        만들면 어떤 스타일에서도 크기가 일정하게 유지된다.
        """
        pixmap = QPixmap(str(get_resource_path(f"img/{icon_file}")))
        scaled = pixmap.scaled(EFFECT_MENU_ICON_PX, EFFECT_MENU_ICON_PX,
                                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return QIcon(scaled)

    def _open_mosaic_dialog(self) -> None:
        """'모자이크' 팝업을 열어 선택 영역(없으면 캔버스 전체)에 모자이크를 적용한다."""
        v = self.current_view()
        if v is None:
            self.statusBar().showMessage("적용할 캔버스가 없습니다.", 2500)
            return
        dialog = PercentSettingsDialog("모자이크 설정", "모자이크 %", self._mosaic_percent,
                                        MOSAIC_PERCENT_MIN, MOSAIC_PERCENT_MAX, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._mosaic_percent = dialog.percent()
        v.apply_mosaic(self._mosaic_percent)

    def _open_blur_dialog(self) -> None:
        """'흐리게' 팝업을 열어 선택 영역(없으면 캔버스 전체)에 가우시안 블러를 적용한다."""
        v = self.current_view()
        if v is None:
            self.statusBar().showMessage("적용할 캔버스가 없습니다.", 2500)
            return
        dialog = PercentSettingsDialog("흐리게 설정", "흐림 정도 %", self._blur_percent,
                                        BLUR_PERCENT_MIN, BLUR_PERCENT_MAX, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._blur_percent = dialog.percent()
        v.apply_blur(self._blur_percent)

    def _open_sharpen_dialog(self) -> None:
        """'선명하게' 팝업을 열어 선택 영역(없으면 캔버스 전체)에 언샵 마스킹을 적용한다."""
        v = self.current_view()
        if v is None:
            self.statusBar().showMessage("적용할 캔버스가 없습니다.", 2500)
            return
        dialog = PercentSettingsDialog("선명하게 설정", "선명하게 %", self._sharpen_percent,
                                        SHARPEN_PERCENT_MIN, SHARPEN_PERCENT_MAX, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._sharpen_percent = dialog.percent()
        v.apply_sharpen(self._sharpen_percent)

    def _open_brightness_contrast_dialog(self) -> None:
        """'밝기/대비' 팝업을 열어 선택 영역(없으면 캔버스 전체)의 명도/대비를 조절한다.

        모자이크/흐리게/선명하게와 달리 마지막 값을 기억하지 않고 열 때마다
        항상 0/0에서 시작한다.
        """
        v = self.current_view()
        if v is None:
            self.statusBar().showMessage("적용할 캔버스가 없습니다.", 2500)
            return
        dialog = DualSliderDialog("밝기/대비 설정", "명도(Brightness)", "대비(Contrast)",
                                   BRIGHTNESS_CONTRAST_MIN, BRIGHTNESS_CONTRAST_MAX, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        v.apply_brightness_contrast(dialog.value1(), dialog.value2())

    def _open_hue_saturation_dialog(self) -> None:
        """'색조/채도' 팝업을 열어 선택 영역(없으면 캔버스 전체)의 색조/채도를 조절한다.

        밝기/대비와 마찬가지로 마지막 값을 기억하지 않고 열 때마다 항상
        0/0에서 시작한다.
        """
        v = self.current_view()
        if v is None:
            self.statusBar().showMessage("적용할 캔버스가 없습니다.", 2500)
            return
        dialog = DualSliderDialog("색조/채도 설정", "색조(Hue)", "채도(Saturation)",
                                   HUE_SATURATION_MIN, HUE_SATURATION_MAX, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        v.apply_hue_saturation(dialog.value1(), dialog.value2())

    def _populate_rotate_menu(self) -> None:
        """'회전' 하위 메뉴(오른쪽/180도/왼쪽 회전, 자유 각도 회전, 상하/좌우 대칭 이동)를 구성한다."""
        self._rotate_angle = 0.0
        self._rotate_clockwise = True

        rotations = [
            ("오른쪽으로 90도 회전", "rotate-right.png", "rotate_right"),
            ("180도 회전", "rotation180.png", "rotate_180"),
            ("왼쪽으로 90도 회전", "rotate-left.png", "rotate_left"),
        ]
        for text, icon_file, method_name in rotations:
            self._add_canvas_op_action(self._rotate_menu, text, icon_file, method_name)

        self._rotate_menu.addSeparator()

        angle_action = QAction(QIcon(str(get_resource_path("img/userrotate.png"))), "자유로운 각도로 회전", self)
        angle_action.triggered.connect(self._open_rotate_angle_dialog)
        self._rotate_menu.addAction(angle_action)

        self._rotate_menu.addSeparator()

        flips = [
            ("상하 대칭 이동", "horizontal_flip.png", "flip_vertical"),
            ("좌우 대칭 이동", "RL_flip.png", "flip_horizontal"),
        ]
        for text, icon_file, method_name in flips:
            self._add_canvas_op_action(self._rotate_menu, text, icon_file, method_name)

    def _open_rotate_angle_dialog(self) -> None:
        """'자유로운 각도로 회전' 팝업을 열어 선택 영역(없으면 캔버스 전체)을 지정한 방향/각도로 회전한다."""
        v = self.current_view()
        if v is None:
            self.statusBar().showMessage("적용할 캔버스가 없습니다.", 2500)
            return
        dialog = RotateAngleDialog(self._rotate_angle, self._rotate_clockwise, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._rotate_angle = dialog.angle()
        self._rotate_clockwise = dialog.is_clockwise()
        v.rotate_by_angle(self._rotate_angle, self._rotate_clockwise)

    def _populate_resize_menu(self) -> None:
        """'크기 조절' 하위 메뉴(이미지 크기 변경/캔버스 크기 변경)를 구성한다."""
        image_action = QAction("이미지 크기 변경", self)
        image_action.triggered.connect(self._open_image_resize_dialog)
        self._resize_menu.addAction(image_action)

        canvas_action = QAction("캔버스 크기 변경", self)
        canvas_action.triggered.connect(self._open_canvas_size_dialog)
        self._resize_menu.addAction(canvas_action)

    def _open_image_resize_dialog(self) -> None:
        """'이미지 크기 변경' 팝업을 열어 현재 캔버스의 실제 픽셀 크기를 리샘플링한다."""
        v = self.current_view()
        if v is None:
            self.statusBar().showMessage("크기를 변경할 캔버스가 없습니다.", 2500)
            return
        r = v.canvas_rect()
        dialog = ImageResizeDialog(int(round(r.width())), int(round(r.height())), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width, height = dialog.target_size()
        v.resize_image(width, height)
        logger.info("이미지 크기 변경: %dx%d -> %dx%d", int(round(r.width())), int(round(r.height())), width, height)

    def _open_canvas_size_dialog(self) -> None:
        """'캔버스 크기 변경' 팝업을 열어 캔버스 경계(+확장 시 배경색)를 바꾼다."""
        v = self.current_view()
        if v is None:
            self.statusBar().showMessage("크기를 변경할 캔버스가 없습니다.", 2500)
            return
        r = v.canvas_rect()
        dialog = CanvasSizeDialog(int(round(r.width())), int(round(r.height())), self._canvas_size_bg_color, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width, height = dialog.target_size()
        self._canvas_size_bg_color = dialog.background_color()
        self.settings.setValue("canvas_size_bg_color", self._canvas_size_bg_color.name())
        v.resize_canvas(width, height, self._canvas_size_bg_color)
        logger.info("캔버스 크기 변경: %dx%d -> %dx%d", int(round(r.width())), int(round(r.height())), width, height)

    def _add_canvas_op_action(self, menu: QMenu, text: str, icon_file: str, method_name: str) -> None:
        """메뉴에 '현재 캔버스의 method_name()을 실행'하는 액션을 추가한다."""
        action = QAction(QIcon(str(get_resource_path(f"img/{icon_file}"))), text, self)
        action.triggered.connect(lambda _checked=False, m=method_name: self._run_canvas_op(m))
        menu.addAction(action)

    def _run_canvas_op(self, method_name: str) -> None:
        """현재 활성 캔버스에서 지정한 이름의 메서드(회전/대칭 이동 등)를 실행한다."""
        v = self.current_view()
        if v is None:
            self.statusBar().showMessage("적용할 캔버스가 없습니다.", 2500)
            return
        getattr(v, method_name)()

    def _on_text_options_changed(self) -> None:
        """텍스트 설정이 바뀌면 활성 캔버스(및 편집 중인 텍스트 박스)에 반영하고 설정을 저장한다."""
        self.settings.setValue("text_font", self._text_settings.current_font().toString())
        self.settings.setValue("text_color", self._text_settings.color().name())
        self.settings.setValue("text_align_h", self._text_settings.align_h())
        self.settings.setValue("text_align_v", self._text_settings.align_v())
        # _sync_view()는 set_tool()을 거치며 편집 중인 텍스트 박스를 확정해 버리므로,
        # 편집 중 블록한 글자에 서식을 적용할 수 있도록 텍스트 옵션만 전달한다.
        v = self.current_view()
        if v is not None:
            v.set_text_options(self._text_settings.current_font(), self._text_settings.color(),
                               self._text_settings.align_h(), self._text_settings.align_v())

    def _sync_view(self, v: Optional[CanvasView]) -> None:
        """현재 도구·그리기/텍스트 옵션·채우기 허용범위를 지정한 캔버스에 반영한다."""
        if v is None:
            return
        v.set_tool(self._current_tool)
        v.set_draw_options(self._draw_subtool, self._draw_thickness, self._draw_color)
        v.set_shape_subtool(self._shape_subtool)
        v.set_fill_tolerance(self._fill_tolerance)
        v.set_magic_tolerance(self._magic_tolerance)
        v.set_text_options(self._text_settings.current_font(), self._text_settings.color(),
                            self._text_settings.align_h(), self._text_settings.align_v())

    def _set_tool(self, tool: str) -> None:
        """현재 활성 도구를 전환하고, 활성 탭의 캔버스에 반영한다."""
        self._current_tool = tool
        self._sync_view(self.current_view())
        logger.info("도구 전환: %s", tool)

    def _set_draw_subtool(self, subtool: str) -> None:
        """그리기 하위 도구(브러시/지우개/형광펜)를 전환하고 그리기를 활성 도구로 만든다."""
        self._draw_subtool = subtool
        self.settings.setValue("draw_subtool", subtool)
        self._draw_action.setChecked(True)
        self._set_tool("draw")

    def _set_shape_subtool(self, subtool: str) -> None:
        """도형 하위 도구(사각형/타원/.../직선/자유곡선 등)를 전환하고 도형을 활성 도구로 만든다."""
        self._shape_subtool = subtool
        self.settings.setValue("shape_subtool", subtool)
        self._shape_action.setChecked(True)
        self._set_tool("shape")
        self._shape_menu.close()

    def _set_thickness(self, px: int) -> None:
        """선 두께를 설정하고 활성 캔버스에 반영한다."""
        self._draw_thickness = px
        self.settings.setValue("draw_thickness", px)
        self._sync_view(self.current_view())

    def _on_color_changed(self, color: QColor) -> None:
        """팔레트에서 색을 선택하면 그리기 색상을 갱신한다."""
        self._draw_color = QColor(color)
        self.settings.setValue("draw_color", self._draw_color.name())
        self._sync_view(self.current_view())

    def _start_color_picking(self) -> None:
        """색상 추출 도구(그리기 색): 화면 어디서든 다음 클릭 지점의 색을 추출하는 모드로 전환한다."""
        self._color_pick_target = "draw"
        self._begin_color_picking()

    def _start_text_color_picking(self) -> None:
        """색상 추출 도구(텍스트 색): 화면 어디서든 다음 클릭 지점의 색을 추출하는 모드로 전환한다."""
        self._color_pick_target = "text"
        self._begin_color_picking()

    def _begin_color_picking(self) -> None:
        """화면 전체(다른 창 포함)를 대상으로 색상 추출 오버레이를 띄운다.

        메인 윈도우는 숨기지 않고 그 상태 그대로 화면을 그랩한다 — 그래야
        지금 열려 있는 캔버스 내용도 추출 대상에 포함된다. 오버레이는
        그랩해 둔 스냅샷을 그대로 보여주므로, 화면상으로는 아무것도
        가려지거나 바뀌지 않는다.
        """
        if self._color_pick_overlay is not None:
            return
        self._color_pick_overlay = ColorPickOverlay()
        self._color_pick_overlay.picked.connect(self._on_color_picked)
        self._color_pick_overlay.destroyed.connect(self._on_color_pick_overlay_closed)
        self._pick_btn.setChecked(True)
        self.statusBar().showMessage("화면에서 추출할 지점을 클릭하세요 (우클릭/Esc: 취소).", 3000)
        self._color_pick_overlay.show()
        self._color_pick_overlay.activateWindow()
        self._color_pick_overlay.raise_()
        self._color_pick_overlay.setFocus()

    def _on_color_pick_overlay_closed(self) -> None:
        """색상 추출 오버레이가 닫히면(추출 완료/취소 모두) 툴바 버튼 표시를 되돌린다."""
        self._color_pick_overlay = None
        self._pick_btn.setChecked(False)

    def _on_color_picked(self, color: QColor) -> None:
        """화면에서 추출한 색을 추출 시작 위치(그리기/텍스트)에 맞게 반영한다."""
        if self._color_pick_target == "text":
            self._text_settings.add_custom_color(color)
            self._text_settings.set_color(color)
        else:
            self._palette.add_custom_color(color)
            self._palette.set_color(color)

    def _build_menu(self) -> None:
        """옵션 메뉴(단축키 설정, 캡처/편집/저장 하위 메뉴)를 구성한다."""
        # QMenuBar.addMenu()의 반환값을 Python 쪽에서 참조하지 않으면 GC로
        # 실제 QMenu 객체가 삭제되어 메뉴가 비는 문제가 있어 self에 보관한다.
        self._options_menu = self.menuBar().addMenu("☰ 옵션")

        self._open_action = QAction("열기...", self)
        self._open_action.setShortcut(QKeySequence("Ctrl+O"))
        self._open_action.triggered.connect(self.open_files)
        self._options_menu.addAction(self._open_action)
        self._options_menu.addSeparator()

        self._shortcut_settings_action = QAction("캡처 단축키 설정...", self)
        self._shortcut_settings_action.triggered.connect(self._open_shortcut_settings)
        self._options_menu.addAction(self._shortcut_settings_action)

        self._svg_scale_action = QAction("SVG 가져오기 배율...", self)
        self._svg_scale_action.triggered.connect(self._open_svg_scale_dialog)
        self._options_menu.addAction(self._svg_scale_action)

        self._log_folder_action = QAction("Log", self)
        self._log_folder_action.triggered.connect(self._open_log_folder)
        self._options_menu.addAction(self._log_folder_action)
        self._options_menu.addSeparator()

        def add(menu: QMenu, text: str, slot, shortcut: Optional[str] = None) -> QAction:
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            menu.addAction(a)
            return a

        self._capture_menu = self._options_menu.addMenu("캡처")
        # 라벨의 단축키 표기는 설정에서 바뀔 수 있으므로 하드코딩하지 않고
        # _sync_region_capture_label()로 현재 설정값을 반영한다.
        self._region_capture_action = add(self._capture_menu, "", self.start_capture)
        self._sync_region_capture_label()
        add(self._capture_menu, "고정 크기 캡처...", self.start_fixed_capture)
        add(self._capture_menu, "마지막 영역 반복 (Ctrl+Shift+R)", self.repeat_capture)

        self._edit_menu = self._options_menu.addMenu("편집")
        add(self._edit_menu, "붙여넣기", self.paste_into_current, "Ctrl+V")
        add(self._edit_menu, "새 탭으로 붙여넣기", self.paste_as_new_tab, "Ctrl+Shift+V")
        add(self._edit_menu, "여백 +20", lambda: self._margin(20))
        add(self._edit_menu, "여백 -20", lambda: self._margin(-20))
        add(self._edit_menu, "내용에 맞춤", self._fit)

        self._save_menu = self._options_menu.addMenu("저장")
        add(self._save_menu, "저장", self.save_current, "Ctrl+S")
        add(self._save_menu, "다른 이름으로 저장...", self.save_as_current, "Ctrl+Shift+S")
        add(self._save_menu, "폴더 설정...", self.choose_folder)

    def _build_shortcuts(self) -> None:
        """탭/편집/저장에 대응하는 로컬 단축키를 등록한다."""
        # Ctrl+V/Ctrl+Shift+V/Ctrl+S/Ctrl+Shift+S는 옵션 메뉴 액션이 자체
        # 단축키로 소유한다 (중복 등록 시 Qt의 "Ambiguous shortcut" 경고 발생).
        pairs = [
            ("Ctrl+Z", self.undo_current),
            ("Ctrl+Shift+Z", self.redo_current),
            ("Ctrl+C", self.copy_current),
            ("Ctrl+X", self.cut_current),
            ("Ctrl+A", self.select_all_current),
            ("Ctrl+W", lambda: self._close_tab(self.tabs.currentIndex())),
            ("Delete", self.delete_selected_current),
        ]
        for keys, slot in pairs:
            QShortcut(QKeySequence(keys), self).activated.connect(slot)

        # 화살표 키는 길게 눌러 계속 이동할 수 있도록 자동 반복을 그대로 둔다.
        # 반복 입력이 되돌리기 스택을 낱개 이동 기록으로 채우지 않도록,
        # 연속 입력을 하나의 되돌리기 항목으로 묶는 처리와, 사람의 연타를
        # 자동 반복으로 오인하지 않는 판정은 CanvasView.nudge_selected가 담당한다.
        nudges = [
            ("Left", (-1, 0)), ("Right", (1, 0)), ("Up", (0, -1)), ("Down", (0, 1)),
        ]
        for keys, (dx, dy) in nudges:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda dx=dx, dy=dy: self.nudge_selected_current(dx, dy))

        # Ctrl+화살표: 한 번 누를 때마다 정확히 1px. 연속 이동 판정을 아예 거치지
        # 않으므로 아무리 빨리 연타해도 가속이 붙지 않는다. 자동 반복도 끄는데,
        # 켜두면 키를 누르고 있는 동안 1px 이동이 되돌리기 스택(MAX_UNDO=20)을
        # 가득 채워 그 전 편집 기록이 밀려나기 때문이다.
        for keys, (dx, dy) in nudges:
            shortcut = QShortcut(QKeySequence(f"Ctrl+{keys}"), self)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(
                lambda dx=dx, dy=dy: self.nudge_selected_current(dx, dy, single_step=True))

    # ---------- 탭 ---------- #
    def current_view(self) -> Optional[CanvasView]:
        """현재 활성 탭의 CanvasView를 반환한다. 없으면 None."""
        w = self.tabs.currentWidget()
        return w if isinstance(w, CanvasView) else None

    def add_tab(self, image: QImage, title: Optional[str] = None) -> CanvasView:
        """새 캔버스 탭을 추가하고 활성화한다.

        Args:
            image: 탭에 배치할 원본 이미지.
            title: 탭 제목. None이면 캡처 시각을 사용한다.

        Returns:
            생성된 CanvasView.
        """
        view = CanvasView(image)
        self._sync_view(view)
        view.changed.connect(self._update_status)
        view.changed.connect(lambda: self._mark_dirty(view))
        view.viewChanged.connect(self._update_status)
        idx = self.tabs.addTab(view, title or datetime.now().strftime("캡처 %H:%M:%S"))
        self.tabs.tabBar().setTabButton(
            idx, QTabBar.ButtonPosition.LeftSide, self._make_indicator_widget(TAB_UNSAVED_COLOR))
        self.tabs.setCurrentIndex(idx)
        self._update_status()
        return view

    def _make_indicator_widget(self, color_hex: str) -> QLabel:
        """탭 이름 왼쪽에 표시할 저장 상태 색 박스를 만든다."""
        label = QLabel()
        label.setFixedSize(10, 10)
        label.setStyleSheet(f"background-color: {color_hex}; border: 1px solid #999999;")
        return label

    def _set_tab_indicator_color(self, view: CanvasView, color_hex: str) -> None:
        """지정한 탭의 저장 상태 색 박스 색을 바꾼다."""
        idx = self.tabs.indexOf(view)
        if idx < 0:
            return
        indicator = self.tabs.tabBar().tabButton(idx, QTabBar.ButtonPosition.LeftSide)
        if indicator is not None:
            indicator.setStyleSheet(f"background-color: {color_hex}; border: 1px solid #999999;")

    def _mark_dirty(self, view: CanvasView) -> None:
        """캔버스가 변경되면 저장 상태를 미저장으로 표시한다."""
        if not view.is_dirty:
            view.is_dirty = True
            self._set_tab_indicator_color(view, TAB_UNSAVED_COLOR)

    def _mark_saved(self, view: CanvasView, path: str) -> None:
        """저장에 성공하면 탭 이름과 저장 상태 표시를 갱신한다."""
        view.is_dirty = False
        self._set_tab_indicator_color(view, TAB_SAVED_COLOR)
        self.tabs.setTabText(self.tabs.indexOf(view), os.path.basename(path))

    def _close_tab(self, index: int) -> None:
        """지정한 인덱스의 탭을 닫는다.

        저장되지 않은 변경이 있으면 저장/저장 안 함/취소를 먼저 확인한다.
        """
        if index < 0:
            return
        w = self.tabs.widget(index)
        if isinstance(w, CanvasView):
            w.commit_pending_edit()
            if w.is_dirty and not self._confirm_close_dirty_tab(index, w):
                return
        self.tabs.removeTab(index)
        if w:
            w.deleteLater()
        self._update_status()

    def _close_all_tabs(self) -> None:
        """열려 있는 모든 탭을 앞에서부터 차례로 닫는다.

        미저장 탭을 만나면 그 탭으로 전환해 내용을 보여준 뒤 저장 여부를
        묻는다. 'All Save'/'All No'를 고르면 남은 미저장 탭에는 더 묻지 않고
        같은 선택을 적용하고, 'Cancel'을 고르면 그 탭부터는 그대로 남긴다.
        All Save 중 저장이 취소·실패하면 데이터가 조용히 사라지지 않도록
        그 탭부터 작업을 중단한다.
        """
        apply_to_all: Optional[str] = None
        while self.tabs.count() > 0:
            view = self.tabs.widget(0)
            if not isinstance(view, CanvasView):
                self.tabs.removeTab(0)
                continue
            view.commit_pending_edit()
            if view.is_dirty:
                choice = apply_to_all
                if choice is None:
                    # 어떤 탭에 대한 질문인지 눈으로 확인할 수 있게 먼저 보여준다.
                    self.tabs.setCurrentIndex(0)
                    choice = self._ask_close_all_dirty_tab(0)
                    if choice == "cancel":
                        break
                    if choice in ("save_all", "discard_all"):
                        apply_to_all = choice
                if choice in ("save", "save_all"):
                    self.save_current(view)
                    if view.is_dirty:
                        logger.info("모든 탭 닫기 중단: 저장 취소·실패 (%s)", self.tabs.tabText(0))
                        break
            self.tabs.removeTab(0)
            view.deleteLater()
        self._update_status()

    def _make_dirty_close_box(self, index: int) -> QMessageBox:
        """저장되지 않은 탭을 닫기 전 확인 팝업(Save/Don't Save/Cancel)을 만든다.

        '모든 탭 닫기'용 팝업은 여기에 버튼만 더 붙여 쓰므로, 두 팝업의
        공통 부분만 만들어 돌려준다(exec()는 호출한 쪽에서 한다).

        Args:
            index: 확인 대상 탭 인덱스.

        Returns:
            아직 실행하지 않은 QMessageBox.
        """
        name = self.tabs.tabText(index)
        box = QMessageBox(
            QMessageBox.Icon.Warning, APP_NAME, f"'{name}'의 변경 내용을 저장하시겠습니까?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel, self)
        box.button(QMessageBox.StandardButton.Save).setText("Save")
        box.button(QMessageBox.StandardButton.Discard).setText("Don't Save (N)")
        box.button(QMessageBox.StandardButton.Cancel).setText("Cancel")
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        strip_minmax_buttons(box)
        discard_btn = box.button(QMessageBox.StandardButton.Discard)
        QShortcut(QKeySequence(Qt.Key.Key_N), box).activated.connect(discard_btn.click)
        return box

    def _confirm_close_dirty_tab(self, index: int, view: CanvasView) -> bool:
        """저장되지 않은 탭을 닫기 전에 저장/저장 안 함/취소를 묻는다.

        Returns:
            탭을 닫아도 되면 True, 취소하면 False.
        """
        box = self._make_dirty_close_box(index)
        result = box.exec()

        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Discard:
            return True
        self.save_current(view)
        return not view.is_dirty

    def _ask_close_all_dirty_tab(self, index: int) -> str:
        """'모든 탭 닫기' 중 미저장 탭을 만났을 때 처리 방법을 묻는다.

        기본 팝업에 'All Save'(남은 전부 저장)와 'All No'(남은 전부 저장
        안 함) 버튼을 더한다. 제목줄 X로 닫는 것은 Cancel과 같이 본다.

        Args:
            index: 확인 대상 탭 인덱스.

        Returns:
            "save" / "discard" / "save_all" / "discard_all" / "cancel".
        """
        box = self._make_dirty_close_box(index)
        all_save_btn = box.addButton("All Save", QMessageBox.ButtonRole.ActionRole)
        all_no_btn = box.addButton("All No (O)", QMessageBox.ButtonRole.ActionRole)
        QShortcut(QKeySequence(Qt.Key.Key_O), box).activated.connect(all_no_btn.click)
        box.exec()

        # 사용자 정의 버튼이 섞이면 exec()의 반환값이 표준 버튼 값이 아니므로
        # 어떤 버튼이 눌렸는지는 clickedButton()으로 판별해야 한다.
        clicked = box.clickedButton()
        if clicked is None:
            return "cancel"
        if clicked is all_save_btn:
            return "save_all"
        if clicked is all_no_btn:
            return "discard_all"
        standard = box.standardButton(clicked)
        if standard == QMessageBox.StandardButton.Save:
            return "save"
        if standard == QMessageBox.StandardButton.Discard:
            return "discard"
        return "cancel"

    def _on_tab_changed(self, *_args) -> None:
        """탭을 벗어나기 전 편집 중인 텍스트/자유곡선을 반영하고, 새 탭에 도구/옵션을 반영한다."""
        if self._active_view is not None:
            self._active_view.commit_pending_edit()
        self._active_view = self.current_view()
        self._sync_view(self._active_view)
        self._update_status()

    def _update_status(self, *_args) -> None:
        """상태바에 캔버스 크기·배율, 마지막 캡처 영역, 저장 폴더를 표시한다."""
        v = self.current_view()
        has_view = v is not None
        if v:
            r = v.canvas_rect()
            self._canvas_size_label.setText(f"캔버스 {int(round(r.width()))} x {int(round(r.height()))}")
            self._zoom_label.setText(f"{round(v.zoom_percent())}%")
        self._canvas_size_label.setVisible(has_view)
        self._canvas_zoom_divider.setVisible(has_view)
        self._zoom_label.setVisible(has_view)

        has_last_region = self.last_region is not None
        if self.last_region is not None:
            self._last_region_label.setText(
                f"마지막 영역 {self.last_region.width()} x {self.last_region.height()}")
        self._last_region_label.setVisible(has_last_region)
        self._last_region_divider.setVisible(has_last_region)
        self._save_dir_label.setText(f"저장 폴더: {self.save_dir}")

    def _open_zoom_popup(self) -> None:
        """배율 표시를 클릭하면 그 위에 배율(%)을 직접 입력하는 팝업을 띄운다."""
        v = self.current_view()
        if v is None:
            return
        popup = _ZoomPopup(round(v.zoom_percent()), self)

        def apply_and_close() -> None:
            v.set_zoom_percent(popup.spin.value())
            popup.close()

        popup.spin.editingFinished.connect(apply_and_close)
        popup.adjustSize()
        anchor = self._zoom_label.mapToGlobal(QPoint(0, 0))
        popup.move(anchor.x(), anchor.y() - popup.height())
        popup.show()
        popup.spin.setFocus()
        popup.spin.selectAll()

    # ---------- 캡처 ---------- #
    def _open_overlay(self, fixed_size: Optional[tuple[int, int]] = None) -> None:
        """메인 윈도우를 숨기고 영역 캡처 오버레이를 띄운다."""
        self.hide()
        QApplication.processEvents()
        self._overlay = RegionOverlay(fixed_size=fixed_size)
        self._overlay.captured.connect(self._on_captured)
        self._overlay.destroyed.connect(self.show)
        self._overlay.show()
        self._overlay.activateWindow()
        self._overlay.raise_()
        self._overlay.setFocus()

    def start_capture(self) -> None:
        """드래그 영역 캡처를 시작한다."""
        self._open_overlay()

    def start_fixed_capture(self) -> None:
        """너비/높이를 입력받아 고정 크기 캡처를 시작한다 (마지막 입력값을 다음에도 기본값으로 제안)."""
        default_w = int(str(self.settings.value("fixed_capture_width", DEFAULT_FIXED_CAPTURE_WIDTH)))
        default_h = int(str(self.settings.value("fixed_capture_height", DEFAULT_FIXED_CAPTURE_HEIGHT)))
        w, ok = self._get_int("고정 크기 캡처", "너비(px):", default_w, 8, 20000)
        if not ok:
            return
        h, ok = self._get_int("고정 크기 캡처", "높이(px):", default_h, 8, 20000)
        if not ok:
            return
        self.settings.setValue("fixed_capture_width", w)
        self.settings.setValue("fixed_capture_height", h)
        self._open_overlay(fixed_size=(w, h))

    def repeat_capture(self) -> None:
        """직전 영역을 오버레이 없이 그대로 다시 캡처한다."""
        if not self.last_region:
            self.statusBar().showMessage("반복할 영역이 없습니다. 먼저 영역 캡처를 하세요.", 3000)
            return
        self.hide()
        QApplication.processEvents()
        shot = DesktopShot()
        img = shot.crop(self.last_region)
        self.show()
        self.raise_()
        self.add_tab(img, datetime.now().strftime("반복 %H:%M:%S"))

    def _on_captured(self, image: QImage, region: QRect) -> None:
        """오버레이에서 캡처가 확정되면 윈도우를 복원하고 새 탭을 추가한다."""
        self.last_region = region
        self.show()
        self.raise_()
        self.activateWindow()
        self.add_tab(image)

    def _capture_fullscreen(self) -> None:
        """전역 단축키로 전체화면을 캡처해 새 탭에 추가한다."""
        img = screen_capture.capture_fullscreen()
        self.show()
        self.raise_()
        self.activateWindow()
        self.add_tab(img, datetime.now().strftime("전체화면 %H:%M:%S"))

    def _capture_active_window(self) -> None:
        """전역 단축키로 현재 활성 창을 캡처해 새 탭에 추가한다."""
        img = screen_capture.capture_active_window()
        self.show()
        self.raise_()
        self.activateWindow()
        if img is None:
            self.statusBar().showMessage("활성 윈도우를 캡처할 수 없습니다.", 4000)
            return
        self.add_tab(img, datetime.now().strftime("윈도우 %H:%M:%S"))

    # ---------- 단축키 ---------- #
    def _register_hotkeys(self) -> None:
        """설정에 저장된 단축키로 전역 캡처 단축키를 (재)등록한다."""
        callbacks: dict[str, Callable[[], None]] = {
            "region": self.start_capture,
            "fullscreen": self._capture_fullscreen,
            "active_window": self._capture_active_window,
        }
        specs = [
            HotkeySpec(action.action_id, load_shortcut(self.settings, action), callbacks[action.action_id])
            for action in CAPTURE_ACTIONS
        ]
        specs.append(HotkeySpec("repeat", QKeySequence("Ctrl+Shift+R"), self.repeat_capture))

        app = cast(QApplication, QApplication.instance())
        self.hotkey_filter = register_global_hotkeys(app, specs)

    def _sync_region_capture_label(self) -> None:
        """'영역 지정 캡처' 메뉴 라벨에 현재 설정된 전역 단축키를 함께 표시한다.

        단축키를 "없음"으로 둔 경우에는 괄호 없이 이름만 표시한다.
        """
        action = next(a for a in CAPTURE_ACTIONS if a.action_id == "region")
        seq = load_shortcut(self.settings, action)
        text = seq.toString(QKeySequence.SequenceFormat.NativeText)
        self._region_capture_action.setText(f"{action.label} ({text})" if text else action.label)

    def _open_svg_scale_dialog(self) -> None:
        """SVG 가져오기 배율(%)을 입력받아 설정에 저장한다.

        SVG는 벡터라 정해진 픽셀 크기가 없어, 파일의 공칭 크기에 이 배율을
        곱해 래스터화한다. 파일마다 공칭 크기가 크게 다르므로 드롭할 때마다
        묻지 않고 여기서 한 번 정해 계속 재사용한다.
        """
        dialog = PercentSettingsDialog(
            "SVG 가져오기 배율", "배율 %", self._svg_import_scale,
            SVG_IMPORT_SCALE_MIN, SVG_IMPORT_SCALE_MAX, self, step=SVG_IMPORT_SCALE_STEP)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._svg_import_scale = dialog.percent()
        self.settings.setValue("svg_import_scale", self._svg_import_scale)
        self.statusBar().showMessage(
            f"SVG 가져오기 배율: {self._svg_import_scale}% "
            f"(긴 변 최대 {SVG_MAX_LONG_EDGE}px)", 4000)
        logger.info("SVG 가져오기 배율 변경: %d%%", self._svg_import_scale)

    def _open_shortcut_settings(self) -> None:
        """캡처 단축키 설정 다이얼로그를 열고, 저장되면 전역 단축키를 다시 등록한다."""
        dialog = ShortcutSettingsDialog(self.settings, self)
        if dialog.exec() == ShortcutSettingsDialog.DialogCode.Accepted:
            unregister_global_hotkeys(self.hotkey_filter)
            self._register_hotkeys()
            self._sync_region_capture_label()
            self.statusBar().showMessage("캡처 단축키를 저장했습니다.", 3000)

    def _open_log_folder(self) -> None:
        """로그 파일이 저장되는 폴더를 파일 탐색기로 연다."""
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    # ---------- 편집/저장 ---------- #
    def paste_into_current(self) -> None:
        """클립보드 이미지를 현재 탭에 붙여넣는다. 탭이 없으면 새 탭으로 생성한다."""
        v = self.current_view()
        if v is None:
            self.paste_as_new_tab()
            return
        if not v.paste_image():
            self.statusBar().showMessage("클립보드에 이미지가 없습니다.", 2500)
            return
        # 붙여넣은 이미지는 바로 위치를 옮길 수 있어야 하는데, 붙여넣기
        # 직전에 다른 도구(그리기/텍스트 등)가 활성 상태였다면 그 도구가
        # 마우스 입력을 가로채 드래그 이동이 되지 않는다. '이동' 도구로 전환한다.
        self._move_action.setChecked(True)
        self._set_tool("move")

    def paste_as_new_tab(self) -> None:
        """클립보드 이미지를 새 탭으로 추가한다."""
        img = QGuiApplication.clipboard().image()
        if img is None or img.isNull():
            self.statusBar().showMessage("클립보드에 이미지가 없습니다.", 2500)
            return
        self.add_tab(img, datetime.now().strftime("붙여넣기 %H:%M:%S"))

    def copy_current(self) -> None:
        """선택 영역이 있으면 그 부분만, 없으면 캔버스 전체를 클립보드로 복사한다."""
        v = self.current_view()
        if v is None:
            return
        v.commit_pending_edit()
        if v.has_magic_selection():
            img = v.render_magic_selection()
            if img is not None:
                QGuiApplication.clipboard().setImage(img)
                self.statusBar().showMessage("매직툴 선택 영역을 클립보드에 복사했습니다.", 2000)
            return
        if v.has_selection():
            img = v.render_selection()
            if img is not None:
                QGuiApplication.clipboard().setImage(img)
                self.statusBar().showMessage("선택 영역을 클립보드에 복사했습니다.", 2000)
            return
        QGuiApplication.clipboard().setImage(v.render_image())
        self.statusBar().showMessage("전체 캔버스를 클립보드에 복사했습니다.", 2000)

    def cut_current(self) -> None:
        """선택 영역을 클립보드로 복사하고, 원본 이미지에서 해당 영역을 지운다."""
        v = self.current_view()
        if v is None:
            return
        v.commit_pending_edit()
        img = v.cut_magic_selection() if v.has_magic_selection() else v.cut_selection()
        if img is None:
            self.statusBar().showMessage("선택 영역이 없습니다. 먼저 선택 도구로 영역을 지정하세요.", 3000)
            return
        QGuiApplication.clipboard().setImage(img)
        self.statusBar().showMessage("선택 영역을 잘라내 클립보드에 복사했습니다.", 2500)

    def undo_current(self) -> None:
        """현재 탭에서 직전 작업을 한 단계 되돌린다."""
        v = self.current_view()
        if v is None:
            return
        msg = "실행을 취소했습니다." if v.undo() else "더 되돌릴 작업이 없습니다."
        self.statusBar().showMessage(msg, 2000)

    def redo_current(self) -> None:
        """현재 탭에서 되돌린 작업을 한 단계 다시 실행한다."""
        v = self.current_view()
        if v is None:
            return
        msg = "다시 실행했습니다." if v.redo() else "다시 실행할 작업이 없습니다."
        self.statusBar().showMessage(msg, 2000)

    def select_all_current(self) -> None:
        """현재 탭의 모든 아이템을 선택한다."""
        v = self.current_view()
        if v:
            v.select_all()

    def delete_selected_current(self) -> None:
        """현재 탭에서 선택된 아이템을 삭제한다."""
        v = self.current_view()
        if v:
            v.delete_selected()

    def nudge_selected_current(self, dx: int, dy: int, single_step: bool = False) -> None:
        """현재 탭에서 선택된 아이템을 화살표 키로 (dx, dy)px만큼 미세 이동한다.

        Args:
            dx: 가로 이동량(px).
            dy: 세로 이동량(px).
            single_step: True면 가속 없이 항상 1px만 움직인다(Ctrl+화살표).
        """
        v = self.current_view()
        if v:
            v.nudge_selected(dx, dy, single_step=single_step)

    def _margin(self, px: int) -> None:
        """현재 탭 캔버스의 여백을 px만큼 조정한다."""
        v = self.current_view()
        if v:
            v.expand_margin(px)

    def _fit(self) -> None:
        """현재 탭 캔버스를 내용에 맞춘다."""
        v = self.current_view()
        if v:
            v.fit_to_content()

    def choose_folder(self) -> None:
        """즉시 저장에 사용할 폴더를 선택하고 설정에 저장한다."""
        d = QFileDialog.getExistingDirectory(self, "즉시 저장 폴더 선택", self.save_dir)
        if d:
            self.save_dir = d
            self.settings.setValue("save_dir", d)
            self._update_status()
            logger.info("저장 폴더 변경: %s", d)

    def save_current(self, view: Optional[CanvasView] = None) -> None:
        """편집 내용을 저장한다.

        아직 한 번도 저장한 적 없는 탭(캡처 직후/신규 탭)이면 '다른 이름으로
        저장'처럼 파일 대화상자를 띄운다. 이미 저장된 적이 있으면 그 뒤 편집
        여부와 무관하게 같은 경로에 곧바로 저장한다.

        Args:
            view: 저장할 탭. None이면 현재 활성 탭(탭 닫기 확인 등에서는
                닫으려는 탭을 직접 지정한다).
        """
        v = view or self.current_view()
        if v is None:
            return
        v.commit_pending_edit()
        if v.file_path is None:
            self.save_as_current(v)
            return
        fmt = self._format_for_path(v.file_path)
        if fmt is None:
            # 저장된 경로의 확장자를 이 앱이 쓸 수 없는 경우(설정 파일을 손으로
            # 고친 경우 등). 확장자와 다른 내용을 덮어쓰지 않도록 경로를 다시 묻는다.
            self.save_as_current(v)
            return
        self._write_image(v, v.file_path, fmt)

    def save_as_current(self, view: Optional[CanvasView] = None) -> None:
        """파일 대화상자를 통해 경로/형식을 선택해 저장한다.

        Args:
            view: 저장할 탭. None이면 현재 활성 탭.
        """
        v = view or self.current_view()
        if v is None:
            return
        v.commit_pending_edit()
        start = v.file_path or os.path.join(
            self.save_dir, datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".png")
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "다른 이름으로 저장", start, SAVE_FILTERS)
        if not path:
            return
        path = self._ensure_save_extension(path, selected_filter)
        fmt = self._format_for_path(path)
        if fmt is None:
            self._warn("지원하지 않는 저장 형식입니다:\n"
                       f"{os.path.basename(path)}\n\n"
                       "PNG, JPEG, WebP, AVIF, BMP 중 하나의 확장자를 사용하세요.\n"
                       "(SVG는 벡터 형식이라 편집 결과를 되돌려 저장할 수 없습니다.)")
            return
        self._write_image(v, path, fmt)

    @staticmethod
    def _ensure_save_extension(path: str, selected_filter: str) -> str:
        """확장자 없이 파일명만 입력한 경우 대화상자에서 고른 필터의 확장자를 붙인다.

        Qt의 저장 대화상자는 사용자가 확장자를 생략해도 그대로 반환하므로,
        보정하지 않으면 확장자 없는 파일이 만들어진다.

        Args:
            path: 대화상자가 반환한 경로.
            selected_filter: 대화상자에서 선택돼 있던 필터 문자열(예: "PNG (*.png)").

        Returns:
            확장자가 보장된 경로.
        """
        if os.path.splitext(path)[1]:
            return path
        match = re.search(r"\*(\.\w+)", selected_filter)
        return path + (match.group(1) if match else ".png")

    @staticmethod
    def _format_for_path(path: str) -> Optional[str]:
        """파일 경로의 확장자에 대응하는 Qt 이미지 포맷 이름을 반환한다.

        확장자와 실제 파일 내용이 어긋나는 것을 막기 위해, 저장 포맷은 사용자가
        고른 필터가 아니라 항상 최종 경로의 확장자에서 파생시킨다.

        Args:
            path: 저장할 파일 경로.

        SAVE_EXT_TO_FORMAT은 화이트리스트다. "Qt가 쓸 수 있으면 무엇이든 허용"으로
        넓히면 안 된다 - Qt는 pbm/xbm/wbmp를 1비트 흑백으로, pgm을 흑백으로,
        icns/cur를 규격 크기로 조용히 변환해 저장하면서 QImage.save()로는 성공을
        돌려주기 때문에, 사용자가 손실을 알아차릴 방법이 없다.

        Returns:
            Qt 포맷 이름(예: "PNG"). 이 앱이 쓸 수 없는 확장자면 None.
        """
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        if not ext:
            return DEFAULT_SAVE_FORMAT
        return SAVE_EXT_TO_FORMAT.get(ext)

    def _confirm_ico_downscale(self, image: QImage) -> bool:
        """ICO 저장 시 규격 한계로 축소가 일어나면 진행 여부를 확인한다.

        ICO는 한 변이 최대 256px이라 Qt가 그보다 큰 이미지를 조용히 축소해
        저장한다(1920x1080 -> 256x144). 그런데도 QImage.save()는 성공을 반환하므로
        그냥 두면 "저장 완료" 메시지와 함께 원본 해상도가 사라진 것을 사용자가
        알아차릴 수 없다.

        Args:
            image: 저장할 이미지.

        Returns:
            저장을 진행해도 되면 True, 사용자가 취소했으면 False.
        """
        long_edge = max(image.width(), image.height())
        if long_edge <= ICO_MAX_EDGE:
            return True
        scale = ICO_MAX_EDGE / long_edge
        target_w = max(round(image.width() * scale), 1)
        target_h = max(round(image.height() * scale), 1)
        box = QMessageBox(
            QMessageBox.Icon.Warning, APP_NAME,
            f"ICO는 한 변이 최대 {ICO_MAX_EDGE}px입니다.\n"
            f"{image.width()}x{image.height()} 이미지는 "
            f"{target_w}x{target_h}로 축소되어 저장됩니다.\n\n"
            "원본 해상도를 유지하려면 PNG나 WebP로 저장하세요.",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel, self)
        box.button(QMessageBox.StandardButton.Save).setText("축소해서 저장")
        box.button(QMessageBox.StandardButton.Cancel).setText("취소")
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        strip_minmax_buttons(box)
        if box.exec() != QMessageBox.StandardButton.Save:
            logger.info("ICO 저장 취소(축소 거부): %dx%d", image.width(), image.height())
            return False
        logger.warning("ICO 저장으로 해상도 축소: %dx%d -> %dx%d",
                       image.width(), image.height(), target_w, target_h)
        return True

    def _write_image(self, v: CanvasView, path: str, fmt: str) -> None:
        """이미지를 지정 경로/포맷으로 저장하고, 성공하면 저장 상태를 갱신한다."""
        # Qt는 할당 실패 시 예외를 던지지 않고 null QImage를 돌려준다(20000x20000
        # ARGB32 = 1.6GB 캔버스 등). 이 null이 그대로 흘러가면 QImage.save()는
        # False를 돌려줘 "저장 실패"로 처리되지만, AVIF 경로는 constBits()가 None을
        # 반환해 TypeError로 터진다. 그래서 여기서 먼저 걸러낸다.
        image = v.render_image()
        if image.isNull():
            logger.warning("렌더 실패로 저장 중단(메모리 부족 추정): %s", path)
            self._warn(f"저장 실패:\n{path}")
            return
        if fmt == "ICO" and not self._confirm_ico_downscale(image):
            return
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            quality = SAVE_QUALITY.get(fmt, -1)
            if fmt in PILLOW_FORMATS:
                # Qt에 AVIF 플러그인이 없어 QImage.save()로는 저장할 수 없다.
                write_avif(image, path, quality)
                saved = True
            else:
                # PySide6 QImage.save()의 타입 스텁은 format 인자를 bytes로 표기하지만
                # 실제로는 bytes를 넘기면 런타임 오류가 나고 str만 정상 동작한다(스텁 오류).
                saved = image.save(path, fmt, quality)  # type: ignore[call-overload]
        except (OSError, MemoryError):
            # MemoryError는 OSError가 아니라, 큰 캔버스를 저장할 때 이걸 빼면
            # 저장 실패가 예외로 앱까지 올라간다.
            logger.exception("저장 실패: %s", path)
            self._warn(f"저장 실패:\n{path}")
            return
        if saved:
            v.file_path = path
            self._mark_saved(v, path)
            self.statusBar().showMessage(f"저장: {path}", 4000)
            logger.info("저장 완료: %s", path)
        else:
            logger.warning("이미지 저장 실패(포맷/경로 문제): %s", path)
            self._warn(f"저장 실패:\n{path}")

    # ---------- 파일 로딩 ---------- #
    def open_files(self) -> None:
        """파일 대화상자로 고른 이미지들을 각각 새 탭으로 연다.

        여러 파일을 한 번에 고를 수 있다. 이미지로 열 수 없는 파일은 건너뛰고
        나머지를 모두 연 뒤 실패 목록을 한 번에 알려준다(파일 하나마다 경고를
        띄우면 여러 개를 고른 경우 대화상자가 연달아 떠 방해가 된다).
        """
        start = str(self.settings.value("open_dir", self.save_dir))
        paths, _ = QFileDialog.getOpenFileNames(self, "열기", start, OPEN_FILTERS)
        if not paths:
            return
        self.settings.setValue("open_dir", os.path.dirname(paths[0]))

        failed: list[str] = []
        for path in paths:
            image = self._load_image_file(path)
            if image.isNull():
                failed.append(os.path.basename(path))
                logger.warning("열기 실패(이미지로 읽을 수 없음): %s", path)
                continue
            view = self.add_tab(image, os.path.basename(path))
            # 원본을 그대로 덮어써도 잃을 것이 없는 포맷만 경로를 기억해 Ctrl+S가
            # 곧바로 덮어쓰게 한다. "저장할 수 있는가"(_format_for_path)로 판단하면
            # 안 된다 - ICO/TIFF는 저장은 되지만 멀티사이즈/멀티페이지가 단일
            # 이미지로 납작해져, Ctrl+S 한 번에 원본이 파괴된다.
            if os.path.splitext(path)[1].lstrip(".").lower() in OVERWRITE_SAFE_EXTENSIONS:
                view.file_path = path
                self._mark_saved(view, path)
            logger.info("열기: %s (%dx%d)", path, image.width(), image.height())

        if failed:
            self._warn("이미지로 열 수 없어 건너뛴 파일:\n" + "\n".join(failed))

    def _load_image_file(self, path: str) -> QImage:
        """이미지 파일을 QImage로 읽는다.

        AVIF는 Qt 플러그인이 없어 Pillow를 거치고(capture.avif_io), SVG/SVGZ는
        설정된 배율로 래스터화하며, 나머지 포맷은 Qt에 그대로 맡긴다.

        SVG를 QImage로 그냥 열면 공칭 크기(width/height 또는 viewBox) 그대로
        래스터화되어, 24x24 아이콘 SVG는 24x24 비트맵이 되고 캔버스에서 확대하면
        뭉개진다. 그래서 옵션의 '가져오기 배율'을 곱해 읽는다.

        Args:
            path: 읽을 파일의 로컬 경로.

        Returns:
            읽어들인 이미지. 실패하면 isNull()이 True인 빈 QImage.
        """
        if is_avif_path(path):
            # Qt에 AVIF 플러그인이 없어 QImage(path)로는 항상 null이 나온다.
            return read_avif(path)

        if os.path.splitext(path)[1].lower() not in SVG_EXTENSIONS:
            return QImage(path)

        reader = QImageReader(path)
        nominal = reader.size()
        if not nominal.isValid() or nominal.isEmpty():
            logger.warning("SVG 공칭 크기를 확인할 수 없음: %s (%s)", path, reader.errorString())
            return QImage()

        # 배율을 그대로 적용하면 큰 SVG에서 크기가 폭발하므로(원본 3000x2000에
        # 800% = 24000x16000, 약 1.5GB) 긴 변을 4K 해상도로 제한한다.
        scale = self._svg_import_scale / 100.0
        long_edge = max(nominal.width(), nominal.height())
        clamped = long_edge * scale > SVG_MAX_LONG_EDGE
        if clamped:
            scale = SVG_MAX_LONG_EDGE / long_edge
        target = QSize(max(round(nominal.width() * scale), 1),
                       max(round(nominal.height() * scale), 1))

        reader.setScaledSize(target)
        image = reader.read()
        if image.isNull():
            logger.warning("SVG 래스터화 실패: %s (%s)", path, reader.errorString())
            return image

        applied = round(scale * 100)
        note = f" (긴 변 {SVG_MAX_LONG_EDGE}px 상한 적용)" if clamped else ""
        self.statusBar().showMessage(
            f"SVG 가져옴: {nominal.width()}x{nominal.height()} → {applied}%"
            f" → {target.width()}x{target.height()}{note}", 5000)
        logger.info("SVG 가져오기: %s (공칭 %dx%d, 배율 %d%% → %dx%d%s)",
                    path, nominal.width(), nominal.height(), applied,
                    target.width(), target.height(), " [상한 적용]" if clamped else "")
        return image

    # ---------- 드래그&드롭 ---------- #
    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        """이미지 또는 URL을 담은 드래그만 허용한다."""
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:
        """드롭된 이미지나 이미지 파일을 새 탭으로 추가한다."""
        md = e.mimeData()
        if md.hasImage():
            self.add_tab(QImage(md.imageData()))
            return
        for url in md.urls():
            local_path = url.toLocalFile()
            img = self._load_image_file(local_path)
            if img.isNull():
                logger.warning("드롭된 파일을 이미지로 열 수 없음: %s", local_path)
                continue
            view = self.add_tab(img, os.path.basename(local_path))
            # 드롭도 '파일 열기'이므로 Ctrl+O(open_files)와 같은 기준으로 원본
            # 경로를 기억한다. 한쪽만 기억하면 같은 PNG인데도 드롭했을 때는
            # Ctrl+S가 '다른 이름으로 저장'으로, Ctrl+O로 열었을 때는 덮어쓰기로
            # 갈려 동작을 예측할 수 없다.
            if os.path.splitext(local_path)[1].lstrip(".").lower() in OVERWRITE_SAFE_EXTENSIONS:
                view.file_path = local_path
                self._mark_saved(view, local_path)

    # ---------- 종료 ---------- #
    def closeEvent(self, event: QCloseEvent) -> None:
        """창을 닫을 때 다음 실행에 복원할 창 크기/위치를 저장한다."""
        self.settings.setValue("window_geometry", self.saveGeometry())
        super().closeEvent(event)
