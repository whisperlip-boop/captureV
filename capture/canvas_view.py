#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""탭 하나에 대응하는 편집 캔버스."""

import logging
import math
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QImage, QKeyEvent,
                            QMouseEvent, QPainter, QPainterPath, QPen, QPixmap,
                            QResizeEvent, QShowEvent, QTextCharFormat, QTextCursor, QTransform,
                            QWheelEvent)
from PySide6.QtWidgets import (QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QTextEdit,
                                QToolButton, QWidget)
from scipy import ndimage

from capture.config import (ACCENT, BLUR_SIGMA_SCALE, CANVAS_SURROUND_COLOR, CHECKER_DARK_COLOR,
                             CHECKER_LIGHT_COLOR, CHECKER_SQUARE_PX, CURSORS, DEFAULT_DRAW_COLOR,
                             DEFAULT_FILL_TOLERANCE, DEFAULT_SHAPE_SUBTOOL, DEFAULT_TEXT_COLOR,
                             DEFAULT_TEXT_FONT_SIZE, DEFAULT_THICKNESS, HANDLE_PX, HANDLES,
                             HIGHLIGHTER_ALPHA, MIN_CANVAS, MIN_SELECTION, SHARPEN_AMOUNT_SCALE,
                             SHARPEN_SIGMA, ZOOM_PERCENT_MAX, ZOOM_PERCENT_MIN)
from capture.shapes import (ARROW_KINDS, FREEHAND_KINDS, arrowhead_length, draw_bbox_shape,
                             draw_bezier_kind, draw_line_kind, is_line_kind, lock_square,
                             snap_line_angle)

logger = logging.getLogger(__name__)


class _OverlayTextEdit(QTextEdit):
    """텍스트 편집 오버레이 내부용 QTextEdit. Esc를 부모에 알리기 위해서만 존재한다."""

    escapePressed = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Esc는 편집 취소로 위임하고, 나머지는 기본 동작을 그대로 따른다."""
        if event.key() == Qt.Key.Key_Escape:
            self.escapePressed.emit()
            return
        super().keyPressEvent(event)


class _TextEditOverlay(QWidget):
    """텍스트 박스 편집 중 표시되는, 전체가 입력칸인 오버레이.

    영역 전체가 QTextEdit이고, 우측 상단에 편집을 닫는 X 버튼만 둔다.
    """

    closed = Signal()      # X 클릭 등 '편집 닫기' (내용 반영)
    cancelled = Signal()    # Esc (내용 반영하지 않고 취소)

    def __init__(self, parent: QWidget) -> None:
        """Args:
            parent: 오버레이를 얹을 뷰포트 위젯.
        """
        super().__init__(parent)
        self.text_edit = _OverlayTextEdit(self)
        self.text_edit.setAcceptRichText(False)
        self.text_edit.setFrameStyle(0)
        self.text_edit.setStyleSheet(
            "QTextEdit { background-color: rgba(255, 255, 255, 235); border: 1px solid #2d9cff; }")
        self.text_edit.escapePressed.connect(self.cancelled.emit)

        self._close_btn = QToolButton(self)
        self._close_btn.setText("×")
        self._close_btn.setFixedSize(16, 16)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet(
            "QToolButton { background-color: #2d9cff; color: white; border: none; "
            "font-weight: bold; border-radius: 8px; }"
            "QToolButton:hover { background-color: #1c7fd6; }")
        self._close_btn.clicked.connect(self.closed.emit)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """텍스트 편집칸을 전체 크기로, X 버튼은 우측 상단에 겹쳐 배치한다."""
        self.text_edit.setGeometry(0, 0, self.width(), self.height())
        self._close_btn.move(max(self.width() - self._close_btn.width() - 2, 0), 2)
        self._close_btn.raise_()
        super().resizeEvent(event)


class CanvasView(QGraphicsView):
    """sceneRect 를 캔버스로 사용하는 편집 뷰.

    핸들 드래그로 여백을 확장하며, 원점이 음수여도 무방하다.
    저장 시 sceneRect 영역만 렌더링하므로 여백 확장 시 아이템 좌표를 옮길 필요가 없다.

    도구('이동'/'선택')에 따라 캔버스 드래그의 의미가 달라진다. '이동' 도구에서는
    QGraphicsView 기본 동작(아이템 드래그 이동, 빈 공간 러버밴드 선택)을 그대로
    쓰고, '선택' 도구에서는 픽셀 영역을 마퀴로 지정해 잘라내기/복사에 사용한다.
    """

    changed = Signal()
    viewChanged = Signal()      # 확대/축소 등 문서 내용과 무관한 뷰 상태 변경 (상태바 갱신용, dirty 표시 없음)

    MAX_UNDO = 20
    _NUDGE_TICK_MS = 15             # 화살표 키를 계속 누르고 있을 때 일정한 속도로 이동시키는 간격
    _NUDGE_HOLD_CONFIRM_MS = 700    # 처음 누른 뒤 이만큼 안에 다시 입력되면 '계속 누르고 있음'으로 간주
    _NUDGE_RELEASE_TIMEOUT_MS = 120  # 계속 이동 중 이만큼 입력이 없으면 키를 뗀 것으로 간주

    def __init__(self, image: QImage, parent=None) -> None:
        """캔버스를 생성하고 원본 이미지를 배경 아이템으로 추가한다.

        Args:
            image: 캔버스에 배치할 원본 이미지.
            parent: 부모 위젯.
        """
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(CANVAS_SURROUND_COLOR))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # QGraphicsView는 생성자에서 자신과 뷰포트에 accept-drops를 기본으로
        # 켜 둔다(씬 안 아이템 간 드래그앤드롭용). 이 앱은 그 기능을 쓰지
        # 않는데, 켜져 있으면 외부 파일 드롭이 여기서 소리 없이 삼켜져 부모
        # MainWindow의 dropEvent(새 탭으로 열기)까지 올라가지 못한다.
        self.setAcceptDrops(False)
        # 마우스 버튼을 누르지 않은 순수 hover 상태에서도 mouseMoveEvent가 와야
        # 캔버스 경계 핸들 위에서 커서 모양이 바뀐다 (기본값은 드래그 중에만 옴).
        self.setMouseTracking(True)

        self._scene.setSceneRect(0, 0, max(image.width(), 1), max(image.height(), 1))
        self.base_item: QGraphicsPixmapItem = self._add_pixmap(QPixmap.fromImage(image), QPoint(0, 0), movable=False)
        self.draw_item: QGraphicsPixmapItem = self._add_draw_layer()

        # 배경이 투명한 PNG를 불러온 경우, 캔버스 빈 영역(여백 확장 등)과
        # 화면 표시/저장 시 흰색 대신 투명을 유지한다. 캔버스 전체를 하나로
        # 합치는 연산(_replace_with_flattened) 때마다 결과물 기준으로 다시
        # 판정한다.
        self._transparent_background: bool = self._has_transparency(image)
        self._checker_brush: QBrush = self._make_checker_brush()

        # 캡처 이미지는 물리 픽셀 원본 해상도로 저장되지만(고DPI 배율 보존),
        # 화면에 표시할 때 배율 1.0(줌 100%)을 곧이곧대로 논리 픽셀 1:1로
        # 적용하면 이 화면 자체의 배율만큼 실제보다 커 보인다. "줌 100%"가
        # 실제 원본 크기로 보이도록, 첫 표시 시점(showEvent)에 이 화면의
        # devicePixelRatio 역수를 기준 배율로 잡는다.
        self._dpi_base_scale: float = 1.0
        self._zoom_initialized: bool = False

        self._drag_handle: Optional[tuple[int, int]] = None
        self._drag_start_view: Optional[QPointF] = None
        self._drag_start_rect: Optional[QRectF] = None
        self._canvas_resize_preview: Optional[QRectF] = None
        self.file_path: Optional[str] = None
        self.is_dirty: bool = True     # 저장 이후 변경 여부 (탭 저장 상태 표시에 사용)

        self.tool: str = "move"
        self._select_rect: QRectF = QRectF()
        self._select_state: str = "idle"          # idle | dragging | adjust
        self._select_origin: Optional[QPointF] = None
        self._select_drag_handle: Optional[tuple[int, int] | str] = None
        self._select_drag_ref: Optional[tuple[QPointF, QRectF]] = None

        self.draw_subtool: str = "brush"          # brush | eraser | highlighter
        self.draw_thickness: int = DEFAULT_THICKNESS
        self.draw_color: QColor = QColor(DEFAULT_DRAW_COLOR)
        self._stroke_path: Optional[QPainterPath] = None
        self._stroke_backup: Optional[QPixmap] = None
        self._stroke_last_point: Optional[QPointF] = None

        self.fill_tolerance: int = DEFAULT_FILL_TOLERANCE

        # shape_subtool: rectangle | rounded_rect | ellipse | circle | triangle | diamond |
        # pentagon | hexagon | line | line_arrow | freehand | freehand_arrow
        self.shape_subtool: str = DEFAULT_SHAPE_SUBTOOL
        self._shape_state: str = "idle"           # idle | dragging
        self._shape_origin: Optional[QPointF] = None
        self._shape_rect: QRectF = QRectF()
        # 자유곡선(freehand/freehand_arrow) 편집 중인 3차 베지에 4개 제어점
        # (시작/제어1/제어2/끝, 씬 좌표). 편집 중이 아니면 빈 리스트.
        self._curve_points: list[QPointF] = []
        self._curve_drag_index: Optional[int] = None
        # id(item) -> {kind, subtool, color, thickness, pad, geometry}. kind별 geometry:
        # bbox -> QSizeF(content w,h) / line -> (p1, p2) 콘텐츠-상대 좌표(원점 0,0 기준) /
        # curve -> 4개 콘텐츠-상대 제어점. pad는 마지막으로 래스터화했을 때의 여백으로,
        # item.pos()가 이동해도 pos() + pad가 콘텐츠 좌상단(씬 좌표)이 되도록 유지한다.
        self._shape_meta: dict[int, dict] = {}

        self.text_font: QFont = QFont()
        self.text_font.setPointSize(DEFAULT_TEXT_FONT_SIZE)
        self.text_color: QColor = QColor(DEFAULT_TEXT_COLOR)
        self.text_align_h: str = "left"
        self.text_align_v: str = "top"
        self._text_state: str = "idle"            # idle | dragging
        self._text_origin: Optional[QPointF] = None
        self._text_rect: QRectF = QRectF()
        self._text_overlay: Optional[_TextEditOverlay] = None
        self._text_editing_item: Optional[QGraphicsPixmapItem] = None
        self._text_new_rect: Optional[QRectF] = None
        self._text_meta: dict[int, dict] = {}      # id(item) -> {text, font, color, align_h, align_v}
        self._text_drag_item: Optional[QGraphicsPixmapItem] = None
        self._text_drag_start_scene: Optional[QPointF] = None
        self._text_drag_item_start_pos: Optional[QPointF] = None

        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._pending_move_snapshot: Optional[dict] = None
        self._pending_move_positions: Optional[dict[int, QPointF]] = None

        self._nudge_states: dict[tuple[int, int], dict] = {}   # (dx, dy) -> 화살표 키 연속 이동 상태

        # '이동' 도구에서 선택된 아이템이 하나뿐일 때, PicPick처럼 그 테두리에
        # 크기 조절 핸들을 보여주고 드래그로 크기를 바꿀 수 있게 한다.
        self._item_resize_item: Optional[QGraphicsPixmapItem] = None
        self._item_resize_handle: Optional[tuple[int, int]] = None
        self._item_resize_drag_ref: Optional[tuple[QPointF, QRectF]] = None
        self._item_resize_source_pixmap: Optional[QPixmap] = None
        self._item_resize_pending_snapshot: Optional[dict] = None

        # 선택 영역 테두리를 움직이는 점선("marching ants")으로 표시하기 위한
        # 애니메이션 phase. 선택이 없을 때는 갱신해도 다시 그릴 필요가 없으므로
        # _tick_marching_ants에서 그 경우엔 update()를 생략해 불필요한 반복
        # 렌더링을 피한다.
        self._marching_ants_phase: float = 0.0
        self._marching_ants_timer = QTimer(self)
        self._marching_ants_timer.timeout.connect(self._tick_marching_ants)
        self._marching_ants_timer.start(80)

    def _tick_marching_ants(self) -> None:
        """선택 영역이 있을 때만 점선 애니메이션을 한 걸음 진행시키고 다시 그린다."""
        has_rect_selection = self.tool == "select" and self.has_selection()
        if not has_rect_selection and not self._scene.selectedItems():
            return
        self._marching_ants_phase = (self._marching_ants_phase + 1.0) % 8.0
        self.viewport().update()

    def _draw_marching_ants(self, painter: QPainter, rect: QRectF, scale: float) -> None:
        """검은색/흰색 점선을 번갈아 그려 움직이는 선택 테두리("marching ants")를 그린다."""
        dash_pen = QPen(Qt.GlobalColor.black)
        dash_pen.setWidthF(1.0 / scale)
        dash_pen.setDashPattern([4, 4])
        dash_pen.setDashOffset(self._marching_ants_phase)
        painter.setPen(dash_pen)
        painter.drawRect(rect)
        dash_pen.setColor(Qt.GlobalColor.white)
        dash_pen.setDashOffset(self._marching_ants_phase + 4)
        painter.setPen(dash_pen)
        painter.drawRect(rect)

    def _add_pixmap(self, pixmap: QPixmap, pos: QPoint, movable: bool = True) -> QGraphicsPixmapItem:
        """씬에 선택 가능한 픽스맵 아이템을 추가한다.

        movable=False(배경 원본 캡처 이미지)는 캔버스 밖으로 드래그되어
        벗어나면 안 되므로 ItemIsMovable을 주지 않는다.
        """
        item = QGraphicsPixmapItem(pixmap)
        flags = QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable
        if movable:
            flags |= QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable
        item.setFlags(flags)
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setPos(pos)
        item.setZValue(len(self._scene.items()))
        self._scene.addItem(item)
        self.changed.emit()
        return item

    def _add_draw_layer(self) -> QGraphicsPixmapItem:
        """그리기(브러시/지우개/형광펜) 전용 투명 레이어를 씬 크기에 맞춰 추가한다.

        이동/선택 대상이 되지 않도록 base_item/붙여넣은 이미지와 달리
        ItemIsMovable/ItemIsSelectable 플래그를 주지 않는다.
        """
        r = self._scene.sceneRect()
        pm = QPixmap(max(int(round(r.width())), 1), max(int(round(r.height())), 1))
        pm.fill(Qt.GlobalColor.transparent)
        item = QGraphicsPixmapItem(pm)
        item.setPos(r.topLeft())
        item.setZValue(len(self._scene.items()))
        self._scene.addItem(item)
        return item

    def _resize_draw_layer(self, new_rect: QRectF, old_rect: QRectF) -> None:
        """씬 크기가 바뀔 때 그리기 레이어를 새 크기로 만들고 기존 내용을 그대로 옮긴다."""
        new_pm = QPixmap(max(int(round(new_rect.width())), 1), max(int(round(new_rect.height())), 1))
        new_pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(new_pm)
        painter.drawPixmap(old_rect.topLeft() - new_rect.topLeft(), self.draw_item.pixmap())
        painter.end()
        self.draw_item.setPixmap(new_pm)
        self.draw_item.setPos(new_rect.topLeft())

    # ---------- 실행 취소/다시 실행 ---------- #
    def _snapshot(self) -> dict:
        """현재 씬의 모든 아이템과 캔버스 크기를 스냅샷으로 캡처한다."""
        items = []
        for it in self._scene.items():
            if isinstance(it, QGraphicsPixmapItem):
                entry = {
                    "pixmap": QPixmap(it.pixmap()),
                    "pos": QPointF(it.pos()),
                    "z": it.zValue(),
                    "is_base": it is self.base_item,
                    "is_draw": it is self.draw_item,
                }
                meta = self._text_meta.get(id(it))
                if meta is not None:
                    entry["text_meta"] = dict(meta)
                shape_meta = self._shape_meta.get(id(it))
                if shape_meta is not None:
                    entry["shape_meta"] = dict(shape_meta)
                items.append(entry)
        return {"items": items, "scene_rect": QRectF(self._scene.sceneRect()),
                "select_rect": QRectF(self._select_rect),
                "transparent_background": self._transparent_background}

    def _push_undo(self) -> None:
        """실행 취소를 위해 현재 상태를 스택에 기록하고, 다시 실행 스택을 비운다."""
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > self.MAX_UNDO:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _restore(self, snapshot: dict) -> None:
        """스냅샷으로 씬 아이템과 캔버스 크기를 복원한다."""
        for it in list(self._scene.items()):
            self._scene.removeItem(it)
        self._text_meta = {}
        self._shape_meta = {}
        for entry in sorted(snapshot["items"], key=lambda e: e["z"]):
            item = QGraphicsPixmapItem(entry["pixmap"])
            if not entry.get("is_draw"):
                flags = QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable
                if not entry.get("is_base"):
                    flags |= QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable
                item.setFlags(flags)
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            item.setPos(entry["pos"])
            item.setZValue(entry["z"])
            self._scene.addItem(item)
            if entry["is_base"]:
                self.base_item = item
            if entry.get("is_draw"):
                self.draw_item = item
            if "text_meta" in entry:
                item.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
                self._text_meta[id(item)] = dict(entry["text_meta"])
            if "shape_meta" in entry:
                self._shape_meta[id(item)] = dict(entry["shape_meta"])
        self._scene.setSceneRect(snapshot["scene_rect"])
        self._select_rect = QRectF(snapshot.get("select_rect", QRectF()))
        self._transparent_background = snapshot.get("transparent_background", self._transparent_background)
        self.changed.emit()
        self.viewport().update()

    def undo(self) -> bool:
        """직전 상태로 한 단계 되돌린다.

        Returns:
            실제로 되돌렸는지 여부 (더 되돌릴 내역이 없으면 False).
        """
        self.commit_pending_edit()
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())
        return True

    def redo(self) -> bool:
        """되돌린 작업을 한 단계 다시 실행한다.

        Returns:
            실제로 다시 실행했는지 여부 (내역이 없으면 False).
        """
        self.commit_pending_edit()
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())
        return True

    def paste_image(self, image: Optional[QImage] = None) -> bool:
        """클립보드(또는 전달된) 이미지를 지금 화면에 보이는 캔버스 영역 중앙에 붙여넣는다.

        캔버스를 크게 늘려 스크롤한 상태에서 캔버스 중앙에 붙여넣으면 화면
        밖에 놓여 사용자가 찾지 못하므로, 보이는 영역(뷰포트 ∩ 캔버스)을
        기준으로 한다. 다만 붙여넣는 이미지가 캔버스 안에 들어가는 크기면
        캔버스 경계를 넘지 않도록 위치를 당긴다. 이 보정 덕분에 캔버스와
        크기가 똑같은 이미지는 스크롤/줌 상태와 무관하게 항상 딱 맞게
        (0, 0) 기준으로 붙는다.

        Args:
            image: 붙여넣을 이미지. None이면 클립보드 이미지를 사용한다.

        Returns:
            성공적으로 붙여넣었는지 여부.
        """
        if image is None:
            image = QGuiApplication.clipboard().image()
        if image is None or image.isNull():
            return False
        self._push_undo()
        scene_rect = self._scene.sceneRect()
        visible = self.mapToScene(self.viewport().rect()).boundingRect().intersected(scene_rect)
        if visible.isEmpty():
            visible = scene_rect
        center = visible.center()
        x = center.x() - image.width() / 2
        y = center.y() - image.height() / 2
        if image.width() <= scene_rect.width():
            x = min(max(x, scene_rect.left()), scene_rect.right() - image.width())
        if image.height() <= scene_rect.height():
            y = min(max(y, scene_rect.top()), scene_rect.bottom() - image.height())
        pos = QPoint(int(round(x)), int(round(y)))
        item = self._add_pixmap(QPixmap.fromImage(image), pos)
        self._scene.clearSelection()
        item.setSelected(True)
        return True

    def select_all(self) -> None:
        """씬의 모든 아이템을 선택하고, 캔버스 전체를 선택 영역으로 지정한다.

        잘라내기/복사(cut_selection/render_selection/has_selection)는 아이템의
        setSelected 여부가 아니라 이 선택 영역(_select_rect)을 기준으로 동작하므로,
        이것을 설정하지 않으면 Ctrl+A 후 Ctrl+X가 "선택 영역 없음"으로 처리되어
        아무 일도 일어나지 않는다.
        """
        for it in self._scene.items():
            it.setSelected(True)
        self._select_rect = self.canvas_rect()
        self._select_state = "adjust"
        self.viewport().update()

    def delete_selected(self) -> None:
        """선택된 아이템을 삭제한다 (배경 아이템은 제외)."""
        targets = [it for it in self._scene.selectedItems() if it is not self.base_item]
        if not targets:
            return
        self._push_undo()
        for it in targets:
            self._scene.removeItem(it)
            self._text_meta.pop(id(it), None)
            self._shape_meta.pop(id(it), None)
        self.changed.emit()

    def _nudge_state(self, dx: int, dy: int) -> dict:
        """(dx, dy) 방향의 화살표 키 연속 이동 상태를 반환한다(없으면 새로 만든다).

        방향별로 상태를 따로 두어, 두 방향키를 동시에 눌러 대각선으로
        이동하는 경우에도 각자 독립적으로 '계속 누르고 있음'을 추적한다.
        """
        state = self._nudge_states.get((dx, dy))
        if state is not None:
            return state
        timer = QTimer(self)
        timer.setInterval(self._NUDGE_TICK_MS)
        timer.timeout.connect(lambda: self._apply_nudge(dx, dy))
        watchdog = QTimer(self)
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(lambda: self._on_nudge_release(dx, dy))
        state = {"phase": "idle", "timer": timer, "watchdog": watchdog}
        self._nudge_states[(dx, dy)] = state
        return state

    def _apply_nudge(self, dx: int, dy: int) -> None:
        """선택된 아이템들을 (dx, dy)px만큼 실제로 옮긴다(되돌리기 기록은 하지 않는다)."""
        targets = [it for it in self._scene.selectedItems() if isinstance(it, QGraphicsPixmapItem)]
        if not targets:
            return
        for it in targets:
            it.setPos(it.pos() + QPointF(dx, dy))
        self.changed.emit()

    def _on_nudge_release(self, dx: int, dy: int) -> None:
        """일정 시간 입력이 없으면 (dx, dy) 방향키를 뗀 것으로 보고 연속 이동을 멈춘다."""
        state = self._nudge_states.get((dx, dy))
        if state is None:
            return
        state["timer"].stop()
        state["phase"] = "idle"

    def nudge_selected(self, dx: int, dy: int) -> None:
        """선택된 아이템들을 화살표 키로 (dx, dy)px만큼 미세 이동한다.

        마우스 드래그로는 정확한 위치 맞추기가 어려운 것을 보완하기 위한
        기능이다. PicPick과 동일하게 두 단계로 동작한다:
        1) 짧게 한 번 누르면(탭) 그 자체로 하나의 되돌리기 항목이 되는
           1px 이동을 한다.
        2) 계속 눌러 OS 키 반복이 시작되면(_NUDGE_HOLD_CONFIRM_MS 이내에
           다음 입력이 이어지면) 그때부터는 되돌리기 항목 하나를 새로
           열어두고, 실제 이동은 OS의 (불규칙할 수 있는) 반복 속도가
           아니라 내부 타이머(_NUDGE_TICK_MS)로 일정한 속도로 계속한다.
           키를 떼서 입력이 _NUDGE_RELEASE_TIMEOUT_MS 이상 끊기면 이동을
           멈춘다. 즉, 20px을 눌러 이동했다면 되돌리기는 '탭 1px' +
           '계속 이동 19px' 두 항목으로 남아, 한 번의 되돌리기로 19px만큼
           되돌아간다.
        """
        targets = [it for it in self._scene.selectedItems() if isinstance(it, QGraphicsPixmapItem)]
        if not targets:
            return
        state = self._nudge_state(dx, dy)
        if state["phase"] == "idle":
            self._push_undo()
            self._apply_nudge(dx, dy)
            state["phase"] = "pending"
            state["watchdog"].setInterval(self._NUDGE_HOLD_CONFIRM_MS)
        elif state["phase"] == "pending":
            self._push_undo()
            self._apply_nudge(dx, dy)
            state["phase"] = "continuous"
            state["timer"].start()
            state["watchdog"].setInterval(self._NUDGE_RELEASE_TIMEOUT_MS)
        # "continuous": 내부 타이머가 이미 이동을 담당하므로 여기서는 움직이지 않고
        # 아래에서 워치독만 갱신해 '아직 누르고 있음'을 알린다.
        state["watchdog"].start()

    def canvas_rect(self) -> QRectF:
        """현재 캔버스(씬) 사각형을 반환한다(여백 조절 드래그 중이면 미리보기 크기)."""
        return self._canvas_resize_preview if self._canvas_resize_preview is not None else self._scene.sceneRect()

    def showEvent(self, event: QShowEvent) -> None:
        """처음 표시되는 시점에 이 화면의 배율을 기준으로 "줌 100%"를 보정한다."""
        super().showEvent(event)
        if not self._zoom_initialized:
            self._zoom_initialized = True
            screen = self.screen() or QGuiApplication.primaryScreen()
            self._dpi_base_scale = 1.0 / ((screen.devicePixelRatio() if screen else 1.0) or 1.0)
            self.resetTransform()
            self.scale(self._dpi_base_scale, self._dpi_base_scale)
            self.viewChanged.emit()

    def zoom_percent(self) -> float:
        """사용자에게 보여줄 확대/축소 배율(%)을 반환한다(이 화면 실제 배율 보정 포함)."""
        return self.transform().m11() / self._dpi_base_scale * 100.0

    def set_zoom_percent(self, percent: float) -> None:
        """확대/축소 배율을 정확한 퍼센트 값으로 맞춘다(ZOOM_PERCENT_MIN~MAX로 제한)."""
        percent = max(ZOOM_PERCENT_MIN, min(ZOOM_PERCENT_MAX, percent))
        target_scale = self._dpi_base_scale * percent / 100.0
        current_scale = self.transform().m11() or 1.0
        factor = target_scale / current_scale
        self.scale(factor, factor)
        self.viewport().update()
        self.viewChanged.emit()

    def expand_margin(self, px: int) -> None:
        """캔버스 네 방향 여백을 px만큼 확장(음수면 축소)한다."""
        old = QRectF(self._scene.sceneRect())
        r = QRectF(old)
        r.adjust(-px, -px, px, px)
        if r.width() < MIN_CANVAS or r.height() < MIN_CANVAS:
            return
        self._push_undo()
        self._resize_draw_layer(r, old)
        self._scene.setSceneRect(r)
        self.changed.emit()

    def fit_to_content(self) -> None:
        """캔버스 크기를 모든 아이템(그리기 레이어 제외)을 포함하는 최소 영역으로 맞춘다.

        그리기 레이어는 항상 캔버스 전체 크기의 투명 픽스맵이라, 포함하면
        '내용에 맞춤'이 항상 현재 캔버스 크기 그대로가 되어버리므로 제외한다.
        """
        rects = []
        for it in self._scene.items():
            if it is self.draw_item:
                continue
            if isinstance(it, QGraphicsPixmapItem):
                rects.append(QRectF(it.pos(), QSizeF(it.pixmap().size())))
            else:
                rects.append(it.sceneBoundingRect())
        if not rects:
            return
        br = rects[0]
        for r in rects[1:]:
            br = br.united(r)
        old = QRectF(self._scene.sceneRect())
        self._push_undo()
        self._resize_draw_layer(br, old)
        self._scene.setSceneRect(br)
        self.changed.emit()

    # ---------- 회전/대칭 이동 ---------- #
    def _replace_with_flattened(self, image: QImage) -> None:
        """씬의 모든 아이템을 지우고 주어진 이미지 하나로 캔버스를 통째로 교체한다.

        회전/대칭 이동처럼 배경·그린 것·붙여넣은 이미지·텍스트 상자를 모두
        포함해 캔버스 전체를 하나의 결과물로 합쳐야 하는 연산에 쓴다. 이후에는
        개별 텍스트 상자를 다시 편집하거나 붙여넣은 이미지만 따로 선택/이동할
        수 없다 (모두 하나의 배경으로 합쳐짐).
        """
        self._push_undo()
        for it in list(self._scene.items()):
            self._scene.removeItem(it)
        self._text_meta = {}
        self._shape_meta = {}
        self._scene.setSceneRect(0, 0, max(image.width(), 1), max(image.height(), 1))
        self.base_item = self._add_pixmap(QPixmap.fromImage(image), QPoint(0, 0), movable=False)
        self.draw_item = self._add_draw_layer()
        self._transparent_background = self._has_transparency(image)
        self.changed.emit()

    def _target_pixel_rect(self, image: QImage) -> tuple[int, int, int, int]:
        """효과를 적용할 대상 사각형을 정수 픽셀 좌표 (x, y, w, h)로 반환한다.

        선택 영역이 있으면 그 영역(캔버스 경계와 교차한 부분), 없으면 캔버스
        전체를 대상으로 한다. 색반전/무채화/모자이크/회전/대칭 이동 등
        '선택 있으면 그 영역만, 없으면 전체'로 동작하는 모든 효과가 공유한다.
        image는 render_image()로 얻은, 씬과 동일한 크기의 이미지여야 한다.
        """
        scene_rect = self._scene.sceneRect()
        target = self._select_rect.intersected(scene_rect) if self.has_selection() else scene_rect
        if target.isEmpty():
            return 0, 0, 0, 0
        x0 = int(round(target.left() - scene_rect.left()))
        y0 = int(round(target.top() - scene_rect.top()))
        w = min(int(round(target.width())), image.width() - x0)
        h = min(int(round(target.height())), image.height() - y0)
        return x0, y0, w, h

    def _paste_transformed_region(self, transform: Callable[[QImage], QImage]) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 전체)에 transform을 적용해 같은 자리에 그려 넣는다.

        회전 180도/대칭 이동처럼 가로세로 크기가 바뀌지 않는 변형에 쓴다.
        """
        image = self.render_image()
        x0, y0, w, h = self._target_pixel_rect(image)
        if w <= 0 or h <= 0:
            return
        transformed = transform(image.copy(x0, y0, w, h))
        painter = QPainter(image)
        # 기본 합성 모드(SourceOver)는 알파 블렌딩이라, 변형 결과의 투명한
        # 부분에는 그 자리에 남아있던 원본 픽셀이 그대로 비쳐 보인다(대칭
        # 이동/회전 전후 이미지가 겹쳐 보이는 원인). Source로 지정해 해당
        # 영역을 완전히 덮어써야 한다.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(x0, y0, transformed)
        painter.end()
        self._replace_with_flattened(image)

    def _rotate_by_degrees(self, degrees: float) -> None:
        """대상 영역을 임의의 각도로 회전한다 (양수는 시계 방향, 음수는 반시계 방향).

        선택 영역이 없으면 캔버스 전체(이미지+캔버스 크기)를 함께 회전한다.
        선택 영역이 있으면 PicPick과 동일하게, 선택 영역 자체를 회전된
        내용의 가로/세로에 맞춰 좌상단은 그대로 두고 함께 바꾼다(회전 결과가
        그대로 온전히 담긴다). 캔버스 크기는 바꾸지 않으므로, 회전 후
        선택 영역이 캔버스 밖으로 나가는 부분은 잘리고 그만큼 주변 내용을
        덮어쓸 수 있다.
        """
        if not self.has_selection():
            self._replace_with_flattened(self.render_image().transformed(QTransform().rotate(degrees)))
            return
        image = self.render_image()
        x0, y0, w, h = self._target_pixel_rect(image)
        if w <= 0 or h <= 0:
            return
        rotated = image.copy(x0, y0, w, h).transformed(QTransform().rotate(degrees))
        new_w = min(rotated.width(), image.width() - x0)
        new_h = min(rotated.height(), image.height() - y0)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(x0, y0, rotated)
        painter.end()
        self._replace_with_flattened(image)
        self._select_rect = QRectF(x0, y0, new_w, new_h)

    def rotate_right(self) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)을 오른쪽(시계 방향)으로 90도 회전한다."""
        self._rotate_by_degrees(90)

    def rotate_180(self) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)을 180도 회전한다."""
        self._paste_transformed_region(lambda img: img.transformed(QTransform().rotate(180)))

    def rotate_left(self) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)을 왼쪽(반시계 방향)으로 90도 회전한다."""
        self._rotate_by_degrees(-90)

    def rotate_by_angle(self, degrees: float, clockwise: bool) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)을 지정한 각도만큼 회전한다.

        Args:
            degrees: 0.0~359.9 사이의 회전 각도(방향 무관 크기).
            clockwise: True면 시계 방향, False면 반시계 방향으로 회전한다.
        """
        self._rotate_by_degrees(degrees if clockwise else -degrees)

    def flip_vertical(self) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)을 상하로 대칭 이동한다."""
        self._paste_transformed_region(lambda img: img.mirrored(False, True))

    def flip_horizontal(self) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)을 좌우로 대칭 이동한다."""
        self._paste_transformed_region(lambda img: img.mirrored(True, False))

    def resize_image(self, width: int, height: int) -> None:
        """캔버스 전체(이미지+캔버스 크기)를 지정한 픽셀 크기로 확대/축소한다.

        회전/대칭 이동과 동일하게 배경·그린 것·붙여넣은 이미지·텍스트 상자를
        모두 하나의 이미지로 합친 뒤 그 결과물을 새 크기로 리샘플링한다.
        """
        width = max(width, 1)
        height = max(height, 1)
        scaled = self.render_image().scaled(
            width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self._replace_with_flattened(scaled)

    def resize_canvas(self, width: int, height: int, bg_color: QColor) -> None:
        """캔버스 경계만 지정한 크기로 바꾼다 (이미지 내용은 확대/축소하지 않음).

        '이미지 크기 변경'과 달리 리샘플링하지 않고, 기존 내용을 좌상단(0,0)에
        고정한 채 새 크기가 더 크면 초과 영역을 bg_color로 채우고, 더 작으면
        우측/하단을 잘라낸다.
        """
        width = max(width, 1)
        height = max(height, 1)
        new_image = QImage(width, height, QImage.Format.Format_ARGB32)
        new_image.fill(bg_color)
        painter = QPainter(new_image)
        painter.drawImage(0, 0, self.render_image())
        painter.end()
        self._replace_with_flattened(new_image)

    def invert_colors(self) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)의 색을 반전한다.

        R/G/B 각 채널을 255에서 뺀 값으로 바꾸고, 알파는 유지한다.
        """
        image = self.render_image()
        x0, y0, w, h = self._target_pixel_rect(image)
        if w <= 0 or h <= 0:
            return
        sub = image.copy(x0, y0, w, h)
        sub.invertPixels(QImage.InvertMode.InvertRgb)
        painter = QPainter(image)
        painter.drawImage(x0, y0, sub)
        painter.end()
        self._replace_with_flattened(image)

    def grayscale(self) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)을 흑백(그레이스케일)으로 바꾼다.

        단순 RGB 평균이 아니라, 사람 눈이 색상별 밝기를 다르게 인지하는
        특성을 반영한 휘도(luminance) 공식(ITU-R BT.601: 0.299R + 0.587G +
        0.114B)으로 계산한 밝기 값을 R/G/B에 동일하게 넣어 색만 지운다
        (알파는 유지).
        """
        image = self.render_image().convertToFormat(QImage.Format.Format_ARGB32)
        x0, y0, w, h = self._target_pixel_rect(image)
        if w <= 0 or h <= 0:
            return
        arr = self._image_array(image)
        region = arr[y0:y0 + h, x0:x0 + w]

        b = region[:, :, 0].astype(np.float32)
        g = region[:, :, 1].astype(np.float32)
        r = region[:, :, 2].astype(np.float32)
        luminance = np.round(0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8)
        region[:, :, 0] = luminance
        region[:, :, 1] = luminance
        region[:, :, 2] = luminance

        self._replace_with_flattened(image)

    def apply_mosaic(self, percent: int) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)에 모자이크 효과를 적용한다.

        대상 영역을 블록 격자로 나눈 뒤, 블록 안 픽셀들의 평균색으로 블록
        전체를 덮어씌운다. percent(1~30)는 대상 영역의 짧은 변 길이에 대한
        비율로 블록 크기를 정해(값이 클수록 블록이 커져 더 뭉개진 모자이크가
        된다), 이미지 해상도와 무관하게 항상 비슷한 정도로 보이게 한다.
        """
        image = self.render_image().convertToFormat(QImage.Format.Format_ARGB32)
        x0, y0, w, h = self._target_pixel_rect(image)
        if w <= 0 or h <= 0:
            return
        block = max(1, round(min(w, h) * percent / 100))

        arr = self._image_array(image)
        region = arr[y0:y0 + h, x0:x0 + w]
        self._mosaic_region(region, block)

        self._replace_with_flattened(image)

    def apply_blur(self, percent: int) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)에 가우시안 블러를 적용한다.

        각 픽셀을 주변 픽셀과 가우스 분포 가중치로 평균 내는 표준적인
        가우시안 블러를 scipy.ndimage.gaussian_filter로 채널별(R/G/B)로
        적용한다(채널 축은 sigma=0으로 둬 서로 섞이지 않게 한다). percent
        (1~30)는 모자이크와 같은 방식으로 대상 영역의 짧은 변 길이에 대한
        비율로 표준편차(sigma)를 정해(BLUR_SIGMA_SCALE로 축소), 값이 클수록
        더 흐려지되 이미지 해상도와 무관하게 비슷한 정도로 보이게 한다.
        """
        image = self.render_image().convertToFormat(QImage.Format.Format_ARGB32)
        x0, y0, w, h = self._target_pixel_rect(image)
        if w <= 0 or h <= 0:
            return
        sigma = min(w, h) * percent / 100 * BLUR_SIGMA_SCALE
        if sigma <= 0:
            return

        arr = self._image_array(image)
        region = arr[y0:y0 + h, x0:x0 + w]
        blurred = ndimage.gaussian_filter(region[:, :, :3].astype(np.float32), sigma=(sigma, sigma, 0))
        region[:, :, :3] = np.round(blurred).astype(np.uint8)

        self._replace_with_flattened(image)

    def apply_sharpen(self, percent: int) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)에 선명하게(언샵 마스킹)를 적용한다.

        가우시안 블러로 만든 흐릿한 버전을 원본에서 빼 경계(고주파) 성분만
        뽑아낸 뒤, 그 성분을 원본에 다시 더해 경계를 뚜렷하게 만드는 언샵
        마스킹 기법을 쓴다. 블러와 달리 여기서 쓰는 블러 반경(SHARPEN_SIGMA)은
        '경계 검출 범위'라 이미지 해상도에 비례시키지 않고 몇 픽셀 수준으로
        고정한다. percent(1~30)는 검출한 경계 성분을 얼마나 강하게 더할지
        (amount)를 정해, 값이 클수록 더 또렷해진다.
        """
        image = self.render_image().convertToFormat(QImage.Format.Format_ARGB32)
        x0, y0, w, h = self._target_pixel_rect(image)
        if w <= 0 or h <= 0:
            return
        amount = percent * SHARPEN_AMOUNT_SCALE

        arr = self._image_array(image)
        region = arr[y0:y0 + h, x0:x0 + w]
        original = region[:, :, :3].astype(np.float32)
        blurred = ndimage.gaussian_filter(original, sigma=(SHARPEN_SIGMA, SHARPEN_SIGMA, 0))
        sharpened = original + amount * (original - blurred)
        region[:, :, :3] = np.clip(sharpened, 0, 255).astype(np.uint8)

        self._replace_with_flattened(image)

    def apply_brightness_contrast(self, brightness: int, contrast: int) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)의 명도/대비를 조절한다.

        명도(-100~100)는 각 채널에 그대로 더하는 오프셋이다. 대비(-100~100)는
        중간값 128을 기준으로 (100+contrast)/100배만큼 밀어내는 배율이라,
        -100이면 완전히 평평한 회색(배율 0), 0이면 변화 없음(배율 1),
        100이면 대비가 2배가 된다. 명도를 먼저 더한 뒤 대비를 적용한다.
        """
        if brightness == 0 and contrast == 0:
            return
        image = self.render_image().convertToFormat(QImage.Format.Format_ARGB32)
        x0, y0, w, h = self._target_pixel_rect(image)
        if w <= 0 or h <= 0:
            return

        arr = self._image_array(image)
        region = arr[y0:y0 + h, x0:x0 + w]
        pixels = region[:, :, :3].astype(np.float32)
        pixels += brightness
        factor = (100 + contrast) / 100
        pixels = (pixels - 128) * factor + 128
        region[:, :, :3] = np.clip(pixels, 0, 255).astype(np.uint8)

        self._replace_with_flattened(image)

    def apply_hue_saturation(self, hue: int, saturation: int) -> None:
        """대상 영역(선택 있으면 그 영역, 없으면 캔버스 전체)의 색조/채도를 조절한다.

        RGB를 HSV로 바꿔 H(색조)는 색상환 위에서 회전시키고 S(채도)는
        배율로 조절한 뒤 다시 RGB로 되돌린다. hue(-100~100)는 -180~180도
        회전에 대응하고, saturation(-100~100)은 명도/대비의 대비와 같은
        방식으로 (100+saturation)/100배(-100=완전 무채색, 0=변화 없음,
        100=채도 2배)를 곱한다.
        """
        if hue == 0 and saturation == 0:
            return
        image = self.render_image().convertToFormat(QImage.Format.Format_ARGB32)
        x0, y0, w, h = self._target_pixel_rect(image)
        if w <= 0 or h <= 0:
            return

        arr = self._image_array(image)
        region = arr[y0:y0 + h, x0:x0 + w]
        rgb = region[:, :, [2, 1, 0]].astype(np.float32) / 255.0     # B,G,R -> R,G,B, 0~1
        hsv = self._rgb_to_hsv(rgb)
        hsv[:, :, 0] = (hsv[:, :, 0] + hue / 200.0) % 1.0
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * ((100 + saturation) / 100), 0, 1)
        rgb_new = np.clip(self._hsv_to_rgb(hsv) * 255.0, 0, 255)
        region[:, :, 2] = np.round(rgb_new[:, :, 0]).astype(np.uint8)     # R
        region[:, :, 1] = np.round(rgb_new[:, :, 1]).astype(np.uint8)     # G
        region[:, :, 0] = np.round(rgb_new[:, :, 2]).astype(np.uint8)     # B

        self._replace_with_flattened(image)

    @staticmethod
    def _rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
        """(..., 3) RGB(0~1) 배열을 (..., 3) HSV(0~1) 배열로 바꾼다 (colorsys.rgb_to_hsv와 동일한 공식의 벡터화 버전)."""
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        maxc = np.max(rgb, axis=-1)
        minc = np.min(rgb, axis=-1)
        v = maxc
        delta = maxc - minc
        safe_delta = np.where(delta == 0, 1.0, delta)
        s = np.where(maxc == 0, 0.0, delta / np.where(maxc == 0, 1.0, maxc))
        rc = (maxc - r) / safe_delta
        gc = (maxc - g) / safe_delta
        bc = (maxc - b) / safe_delta
        h = np.select([r == maxc, g == maxc], [bc - gc, 2.0 + rc - bc], default=4.0 + gc - rc)
        h = (h / 6.0) % 1.0
        h = np.where(delta == 0, 0.0, h)
        return np.stack([h, s, v], axis=-1)

    @staticmethod
    def _hsv_to_rgb(hsv: np.ndarray) -> np.ndarray:
        """(..., 3) HSV(0~1) 배열을 (..., 3) RGB(0~1) 배열로 바꾼다 (colorsys.hsv_to_rgb와 동일한 공식의 벡터화 버전)."""
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        i = np.floor(h * 6.0)
        f = h * 6.0 - i
        p = v * (1.0 - s)
        q = v * (1.0 - s * f)
        t = v * (1.0 - s * (1.0 - f))
        i = i.astype(np.int64) % 6
        conditions = [i == 0, i == 1, i == 2, i == 3, i == 4, i == 5]
        r = np.select(conditions, [v, q, p, p, t, v])
        g = np.select(conditions, [t, v, v, q, p, p])
        b = np.select(conditions, [p, p, t, v, v, q])
        r = np.where(s == 0, v, r)
        g = np.where(s == 0, v, g)
        b = np.where(s == 0, v, b)
        return np.stack([r, g, b], axis=-1)

    @staticmethod
    def _image_array(image: QImage) -> np.ndarray:
        """ARGB32 QImage를 (H, W, 4) uint8 numpy 배열(B,G,R,A 순서)로 감싼다.

        배열을 수정하면 image의 실제 픽셀 데이터도 함께 바뀐다(같은 메모리를
        공유하는 뷰).
        """
        w, h = image.width(), image.height()
        stride = image.bytesPerLine()
        buf = np.frombuffer(image.bits(), dtype=np.uint8, count=stride * h)
        return buf.reshape(h, stride)[:, :w * 4].reshape(h, w, 4)

    @staticmethod
    def _has_transparency(image: QImage) -> bool:
        """완전히 불투명하지 않은 픽셀이 하나라도 있는지 검사한다.

        포맷상 알파 채널이 있어도(예: 배경색으로 채워 평탄화한 ARGB32) 실제로
        모든 픽셀이 불투명(255)이면 False를 반환해, "형식"이 아니라 "실제
        내용"을 기준으로 투명 배경 여부를 판정한다.
        """
        if not image.hasAlphaChannel():
            return False
        argb = image.convertToFormat(QImage.Format.Format_ARGB32)
        arr = CanvasView._image_array(argb)
        return bool(np.any(arr[:, :, 3] < 255))

    @staticmethod
    def _make_checker_brush() -> QBrush:
        """투명 배경을 나타내는 체커보드 무늬 브러시를 만든다."""
        size = CHECKER_SQUARE_PX
        tile = QPixmap(size * 2, size * 2)
        painter = QPainter(tile)
        painter.fillRect(tile.rect(), CHECKER_LIGHT_COLOR)
        painter.fillRect(0, 0, size, size, CHECKER_DARK_COLOR)
        painter.fillRect(size, size, size, size, CHECKER_DARK_COLOR)
        painter.end()
        return QBrush(tile)

    @staticmethod
    def _mosaic_region(region: np.ndarray, block: int) -> None:
        """region(H, W, 4) 배열의 R/G/B를 block x block 격자 평균색으로 제자리에서 바꾼다."""
        h, w = region.shape[:2]
        pad_h, pad_w = (-h) % block, (-w) % block
        channels = region[:, :, :3].astype(np.float32)
        if pad_h or pad_w:
            channels = np.pad(channels, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
        ph, pw = channels.shape[:2]
        blocks = channels.reshape(ph // block, block, pw // block, block, 3)
        means = blocks.mean(axis=(1, 3), keepdims=True)
        mosaic = np.broadcast_to(means, blocks.shape).reshape(ph, pw, 3)[:h, :w]
        region[:, :, :3] = np.round(mosaic).astype(np.uint8)

    # ---------- 도구 ---------- #
    def set_tool(self, tool: str) -> None:
        """활성 도구를 전환한다 ('move', 'select', 'draw', 'fill', 'text', 'shape').

        '선택' 도구를 벗어나면 진행 중이던 선택 영역을 지우고, 편집 중인
        텍스트 박스가 있으면 먼저 반영하고 닫는다.
        """
        self._commit_text_overlay()
        if tool != "shape" and self._curve_points:
            self._commit_curve()
        self.tool = tool
        if tool != "select":
            self.clear_selection()
        if tool != "draw":
            self._stroke_path = None
            self._stroke_backup = None
            self._stroke_last_point = None
        if tool != "text":
            self._text_state = "idle"
            self._text_rect = QRectF()
            self._text_drag_item = None
            self._text_drag_start_scene = None
            self._text_drag_item_start_pos = None
        if tool != "shape":
            self._shape_state = "idle"
            self._shape_origin = None
            self._shape_rect = QRectF()
            self._curve_drag_index = None
        if tool != "move":
            self._item_resize_item = None
            self._item_resize_handle = None
            self._item_resize_drag_ref = None
            self._item_resize_source_pixmap = None
            self._item_resize_pending_snapshot = None
        self.viewport().update()

    def set_draw_options(self, subtool: str, thickness: int, color: QColor) -> None:
        """그리기 도구의 하위 도구('brush'/'eraser'/'highlighter'), 두께, 색상을 설정한다."""
        unchanged = self.draw_thickness == thickness and self.draw_color == color
        self.draw_subtool = subtool
        self.draw_thickness = thickness
        self.draw_color = QColor(color)
        # 값이 실제로 바뀐 경우에만 재래스터화한다 (탭 전환 등 반복 호출 시
        # 선택된 도형을 불필요하게 다시 그리거나 실행취소에 쌓지 않기 위함).
        if not unchanged:
            self._restyle_selected_shape_items()

    def set_shape_subtool(self, subtool: str) -> None:
        """도형 도구의 하위 종류(사각형/타원/.../직선/자유곡선 등)를 설정한다.

        자유곡선을 편집(핸들 조정)하는 중에 다른 하위 도구로 바뀌면, 그
        시점 모양 그대로 캔버스에 반영한 뒤 전환한다.
        """
        if subtool == self.shape_subtool:
            return
        if self._curve_points:
            self._commit_curve()
        self.shape_subtool = subtool

    def set_fill_tolerance(self, tolerance_pct: int) -> None:
        """채우기 도구의 색상 허용 범위(0~100%)를 설정한다."""
        self.fill_tolerance = tolerance_pct

    def set_text_options(self, font: QFont, color: QColor, align_h: str, align_v: str) -> None:
        """텍스트 도구의 폰트/색/정렬 기본값을 설정한다.

        편집 중인 텍스트 박스가 있으면 즉시 반영한다 (세로 정렬은 QTextEdit이
        내용 세로 정렬을 지원하지 않아 편집 중에는 항상 위쪽 기준으로 보이고,
        편집을 마칠 때 최종 렌더링에만 반영된다).
        """
        unchanged = (self.text_font == font and self.text_color == color
                     and self.text_align_h == align_h and self.text_align_v == align_v)
        self.text_font = QFont(font)
        self.text_color = QColor(color)
        self.text_align_h = align_h
        self.text_align_v = align_v
        if self._text_overlay is not None:
            self._style_text_edit(self._text_overlay.text_edit, self.text_font, self.text_color,
                                   self.text_align_h)
            return
        # 값이 실제로 바뀐 경우에만 재래스터화한다. 탭 전환 등으로 이 메서드가
        # 동일한 값으로 반복 호출될 때마다 선택된 텍스트 박스를 다시 그리고
        # 실행취소 스택에 쌓는 것을 방지한다.
        if not unchanged:
            self._restyle_selected_text_items()

    def _restyle_selected_text_items(self) -> None:
        """편집을 마치고 확정된 텍스트 박스가 선택되어 있으면, 방금 바뀐
        폰트/색/정렬로 다시 래스터화해 즉시 반영한다."""
        targets = [it for it in self._scene.selectedItems() if id(it) in self._text_meta]
        if not targets:
            return
        self._push_undo()
        for item in targets:
            meta = self._text_meta[id(item)]
            pixmap = self._rasterize_text(meta["text"], self.text_font, self.text_color,
                                           self.text_align_h, self.text_align_v,
                                           item.pixmap().size())
            item.setPixmap(pixmap)
            meta["font"] = QFont(self.text_font)
            meta["color"] = QColor(self.text_color)
            meta["align_h"] = self.text_align_h
            meta["align_v"] = self.text_align_v
        self.changed.emit()

    def has_selection(self) -> bool:
        """유효한 선택 영역이 있는지 여부."""
        return self._select_rect.width() > 0 and self._select_rect.height() > 0

    def clear_selection(self) -> None:
        """선택 영역을 지운다."""
        self._select_rect = QRectF()
        self._select_state = "idle"
        self.viewport().update()

    def render_selection(self) -> Optional[QImage]:
        """선택 영역의 픽셀을 렌더링해 반환한다. 선택이 없으면 None."""
        if not self.has_selection():
            return None
        r = self._select_rect
        img = QImage(max(int(round(r.width())), 1), max(int(round(r.height())), 1),
                     QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        self._scene.clearSelection()
        painter = QPainter(img)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self._scene.render(painter, QRectF(img.rect()), r)
        painter.end()
        return img

    def cut_selection(self, fill_color: Optional[QColor] = None) -> Optional[QImage]:
        """선택 영역을 잘라낸다.

        선택 영역의 픽셀을 렌더링해 반환하고, 선택 영역과 겹치는 모든 픽스맵
        아이템(원본 캡처 이미지, 그리기 레이어, 붙여넣은 이미지, 텍스트/도형
        상자)에서 겹치는 부분을 fill_color로 채운다. 아이템을 삭제하지는
        않고 겹친 부분만 지우므로, 붙여넣은 이미지 위에서 잘라내도(선택
        영역이 base_item이 아닌 다른 아이템 위에 있어도) 화면에서 실제로
        사라진다.

        Args:
            fill_color: 잘라낸 자리를 채울 색. None이면 배경이 투명인
                캔버스는 투명으로, 그렇지 않으면 흰색으로 채운다.

        Returns:
            잘라낸 영역의 이미지. 선택이 없으면 None.
        """
        img = self.render_selection()
        if img is None:
            return None
        if fill_color is None:
            fill_color = QColor(Qt.GlobalColor.transparent if self._transparent_background
                                 else Qt.GlobalColor.white)

        cleared = False
        for item in self._scene.items():
            if not isinstance(item, QGraphicsPixmapItem):
                continue
            item_rect = self._item_pixmap_rect(item)
            fill_rect = self._select_rect.intersected(item_rect).translated(-item.pos())
            if fill_rect.isEmpty():
                continue
            if not cleared:
                self._push_undo()
                cleared = True
            pm = QPixmap(item.pixmap())
            painter = QPainter(pm)
            # 기본 SourceOver 블렌딩에서는 완전 투명한 색으로 fillRect해도
            # 알파가 0이라 기존 픽셀이 그대로 남는다. Source 모드로 덮어써야
            # 실제로 투명해진다 (불투명 색을 채우는 기존 경우는 결과가 같다).
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(fill_rect, fill_color)
            painter.end()
            item.setPixmap(pm)

        self.clear_selection()
        if cleared:
            self.changed.emit()
        return img

    # ---------- 핸들 공통 ---------- #
    def _handle_size_scene(self) -> float:
        """뷰 배율을 반영한 씬 좌표계에서의 핸들 크기."""
        scale = self.transform().m11() or 1.0
        return HANDLE_PX / scale

    @staticmethod
    def _handles_for(rect: QRectF, size: float) -> dict[tuple[int, int], QRectF]:
        """rect의 8방향 조절 핸들 사각형을 계산한다."""
        out = {}
        for dx, dy in HANDLES:
            cx = rect.left() + (rect.width() / 2 if dx == 0 else (0 if dx < 0 else rect.width()))
            cy = rect.top() + (rect.height() / 2 if dy == 0 else (0 if dy < 0 else rect.height()))
            out[(dx, dy)] = QRectF(cx - size / 2, cy - size / 2, size, size)
        return out

    # ---------- 캔버스 경계 핸들(여백 조절) ---------- #
    def _canvas_handle_rects(self) -> dict[tuple[int, int], QRectF]:
        """캔버스 경계의 8개 조절 핸들 사각형을 계산한다."""
        return self._handles_for(self._scene.sceneRect(), self._handle_size_scene())

    def _canvas_handle_at(self, view_pos: QPoint) -> Optional[tuple[int, int]]:
        """뷰 좌표 view_pos 에 해당하는 캔버스 경계 핸들 키를 찾는다. 없으면 None."""
        sp = self.mapToScene(view_pos)
        for key, hr in self._canvas_handle_rects().items():
            if hr.contains(sp):
                return key
        return None

    # ---------- 선택 영역 핸들 ---------- #
    def _select_handle_rects(self) -> dict[tuple[int, int], QRectF]:
        """선택 영역의 8개 조절 핸들 사각형을 계산한다."""
        return self._handles_for(self._select_rect, self._handle_size_scene())

    def _select_handle_at(self, view_pos: QPoint) -> Optional[tuple[int, int]]:
        """조절 모드에서 view_pos 에 해당하는 선택 핸들 키를 찾는다. 없으면 None."""
        if self._select_state != "adjust":
            return None
        sp = self.mapToScene(view_pos)
        for key, hr in self._select_handle_rects().items():
            if hr.contains(sp):
                return key
        return None

    # ---------- 아이템 크기 조절 핸들 ---------- #
    def _resizable_selected_item(self) -> Optional[QGraphicsPixmapItem]:
        """'이동' 도구에서 크기 조절 핸들을 보여줄 대상을 반환한다.

        붙여넣기/텍스트/도형 등으로 놓인 아이템이 정확히 하나만 선택되어
        있을 때만 PicPick처럼 테두리에 크기 조절 핸들을 보여준다. 여러
        개를 함께 선택했을 때는(예: Ctrl+A) 항목별 크기가 다를 수 있어
        핸들을 보여주지 않는다.
        """
        if self.tool != "move":
            return None
        selected = [it for it in self._scene.selectedItems() if isinstance(it, QGraphicsPixmapItem)]
        return selected[0] if len(selected) == 1 else None

    def _movable_item_at(self, view_pos: QPoint) -> Optional[QGraphicsPixmapItem]:
        """view_pos 아래에 이동 가능한(붙여넣기/텍스트/도형) 아이템이 있으면 반환한다."""
        item = self.itemAt(view_pos)
        if isinstance(item, QGraphicsPixmapItem) and bool(
            item.flags() & QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable
        ):
            return item
        return None

    @staticmethod
    def _item_pixmap_rect(item: QGraphicsPixmapItem) -> QRectF:
        """item의 실제 픽스맵 사각형(씬 좌표)을 반환한다.

        QGraphicsPixmapItem.sceneBoundingRect()는 SmoothTransformation
        보간 여백으로 사방이 0.5px씩 더 넓게 나와(예: 50x50 픽스맵이
        (-0.5,-0.5,51,51)), 이 값을 그대로 setPos()에 되먹이면 매 크기
        조절마다 위치가 조금씩 밀린다. item.pos()+pixmap 크기 그대로
        쓰는 이 사각형이 텍스트 편집 오버레이 등 다른 곳에서도 이미
        '아이템의 진짜 위치/크기'로 쓰는 값이라 여기서도 이걸 기준으로
        삼는다.
        """
        return QRectF(item.pos(), QSizeF(item.pixmap().size()))

    def _item_resize_handle_rects(self, item: QGraphicsPixmapItem) -> dict[tuple[int, int], QRectF]:
        """item의 8방향 크기 조절 핸들 사각형을 계산한다."""
        return self._handles_for(self._item_pixmap_rect(item), self._handle_size_scene())

    def _item_resize_handle_at(self, item: QGraphicsPixmapItem, view_pos: QPoint) -> Optional[tuple[int, int]]:
        """view_pos 에 해당하는 item의 크기 조절 핸들 키를 찾는다. 없으면 None."""
        sp = self.mapToScene(view_pos)
        for key, hr in self._item_resize_handle_rects(item).items():
            if hr.contains(sp):
                return key
        return None

    def _item_resize_move(self, view_pos: QPoint) -> None:
        """이동 도구: 아이템 크기 조절 드래그를 갱신한다(픽스맵을 다시 스케일).

        드래그 중에는 매번 드래그 시작 시점의 원본 픽스맵(_item_resize_source_pixmap)
        에서부터 다시 스케일해, 이미 축소된 픽스맵을 반복해서 재스케일하며
        품질이 계속 저하되는 것을 막는다.
        """
        item = self._item_resize_item
        handle = self._item_resize_handle
        if item is None or handle is None or self._item_resize_drag_ref is None:
            return
        pixmap = self._item_resize_source_pixmap
        if pixmap is None or pixmap.isNull():
            return
        sp = self.mapToScene(view_pos)
        start, rect0 = self._item_resize_drag_ref
        hx, hy = handle
        d = sp - start
        left, top, right, bottom = rect0.left(), rect0.top(), rect0.right(), rect0.bottom()
        if hx < 0:
            left = min(left + d.x(), right - MIN_SELECTION)
        elif hx > 0:
            right = max(right + d.x(), left + MIN_SELECTION)
        if hy < 0:
            top = min(top + d.y(), bottom - MIN_SELECTION)
        elif hy > 0:
            bottom = max(bottom + d.y(), top + MIN_SELECTION)
        new_rect = QRectF(left, top, right - left, bottom - top)
        w = max(int(round(new_rect.width())), 1)
        h = max(int(round(new_rect.height())), 1)
        item.setPixmap(pixmap.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
        item.setPos(new_rect.topLeft())
        self.viewport().update()

    def _item_resize_release(self) -> None:
        """이동 도구: 아이템 크기 조절 드래그를 마치고, 실제로 크기가 바뀌었으면 되돌리기에 기록한다."""
        item = self._item_resize_item
        snapshot = self._item_resize_pending_snapshot
        drag_ref = self._item_resize_drag_ref
        self._item_resize_item = None
        self._item_resize_handle = None
        self._item_resize_drag_ref = None
        self._item_resize_source_pixmap = None
        self._item_resize_pending_snapshot = None
        if item is None or snapshot is None or drag_ref is None:
            return
        _, original_rect = drag_ref
        if self._item_pixmap_rect(item) == original_rect:
            return
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > self.MAX_UNDO:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self.changed.emit()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        """뷰포트 배경과 캔버스 영역을 그린다(투명 배경이면 체커보드, 아니면 흰색)."""
        painter.fillRect(rect, self.backgroundBrush())
        if self._transparent_background:
            painter.fillRect(self._scene.sceneRect(), self._checker_brush)
        else:
            painter.fillRect(self._scene.sceneRect(), QColor(0xff, 0xff, 0xff))

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        """캔버스 밖으로 삐져나온 내용을 가리고, 테두리·조절 핸들·선택 영역을 그린다."""
        r = self._scene.sceneRect()
        scale = self.transform().m11() or 1.0

        # 아이템(배경 이미지 등)은 sceneRect로 자동으로 잘리지 않아, 캔버스를
        # 축소하면 실제 경계 밖까지 그대로 보여 캔버스가 아니라 이미지 자체가
        # 줄어드는 것처럼 보인다. 아이템 데이터는 그대로 두고, 화면에 보이는
        # 부분만 경계 밖을 배경색으로 덮어 실제로 잘린 것처럼 보이게 한다
        # (다시 캔버스를 늘리면 가려졌던 부분이 그대로 다시 나타난다).
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.backgroundBrush())
        outside = QPainterPath()
        outside.addRect(rect)
        inside = QPainterPath()
        inside.addRect(r)
        painter.drawPath(outside.subtracted(inside))
        painter.restore()

        painter.save()
        pen = QPen(QColor(0x2d, 0x7d, 0xd2))
        pen.setWidthF(1.0 / scale)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)
        painter.setBrush(QBrush(Qt.GlobalColor.white))
        for hr in self._canvas_handle_rects().values():
            painter.drawRect(hr)
        painter.restore()

        if self._canvas_resize_preview is not None:
            painter.save()
            pen = QPen(QColor(0x2d, 0x7d, 0xd2))
            pen.setWidthF(1.0 / scale)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._canvas_resize_preview)
            painter.restore()

        selected_items = self._scene.selectedItems()
        if selected_items:
            # Ctrl+A(전체 선택) 등 Qt 기본 아이템 선택은 원래 각 아이템이 자체
            # 파선 테두리를 그리지만, 캔버스 경계와 좌표가 겹치면 위의 캔버스
            # 테두리(파란 실선)에 완전히 가려져 버린다. drawForeground는 모든
            # 아이템을 그린 "뒤"에 호출되므로, 여기서 다시 그려야 항상 위에 보인다.
            bounds = QRectF()
            for it in selected_items:
                bounds = bounds.united(it.sceneBoundingRect())
            painter.save()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            self._draw_marching_ants(painter, bounds, scale)
            painter.restore()

        resize_item = self._resizable_selected_item()
        if resize_item is not None:
            painter.save()
            painter.setPen(QPen(QColor(0x33, 0x33, 0x33), 1.0 / scale))
            painter.setBrush(QBrush(Qt.GlobalColor.white))
            for hr in self._item_resize_handle_rects(resize_item).values():
                painter.drawRect(hr)
            painter.restore()

        if self.tool == "select" and self.has_selection():
            painter.save()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            self._draw_marching_ants(painter, self._select_rect, scale)
            if self._select_state == "adjust":
                painter.setBrush(QBrush(Qt.GlobalColor.white))
                for hr in self._select_handle_rects().values():
                    painter.drawRect(hr)
            painter.restore()

        if self.tool == "text" and self._text_state == "dragging":
            painter.save()
            pen = QPen(ACCENT)
            pen.setWidthF(1.0 / scale)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._text_rect)
            painter.restore()

        if self.tool == "shape" and self._shape_state == "dragging":
            painter.save()
            pen = QPen(ACCENT)
            pen.setWidthF(1.0 / scale)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if is_line_kind(self.shape_subtool):
                painter.drawLine(self._shape_rect.topLeft(), self._shape_rect.bottomRight())
            else:
                draw_bbox_shape(painter, self.shape_subtool, self._shape_rect)
            painter.restore()

        if self.tool == "shape" and self._curve_points:
            painter.save()
            painter.setPen(self._shape_pen())
            painter.setBrush(Qt.BrushStyle.NoBrush)
            draw_bezier_kind(painter, self.shape_subtool, self._curve_points, self.draw_thickness)

            guide_pen = QPen(ACCENT)
            guide_pen.setWidthF(1.0 / scale)
            guide_pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(guide_pen)
            p0, p1, p2, p3 = self._curve_points
            painter.drawLine(p0, p1)
            painter.drawLine(p3, p2)

            handle_size = self._handle_size_scene()
            painter.setPen(QPen(QColor(0x33, 0x33, 0x33), 1.0 / scale))
            painter.setBrush(QBrush(QColor(0xff, 0xdd, 0x00)))
            for p in self._curve_points:
                painter.drawRect(QRectF(p.x() - handle_size / 2, p.y() - handle_size / 2,
                                         handle_size, handle_size))
            painter.restore()

    def _clamp_to_scene(self, rect: QRectF) -> QRectF:
        """선택 사각형을 씬 범위 안으로 밀어넣는다."""
        r = QRectF(rect).normalized()
        bounds = self._scene.sceneRect()
        if r.width() > bounds.width():
            r.setWidth(bounds.width())
        if r.height() > bounds.height():
            r.setHeight(bounds.height())
        dx = min(0.0, bounds.right() - r.right()) or max(0.0, bounds.left() - r.left())
        dy = min(0.0, bounds.bottom() - r.bottom()) or max(0.0, bounds.top() - r.top())
        r.translate(dx, dy)
        return r

    # ---------- 마우스 ---------- #
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """캔버스 경계 핸들 클릭을 최우선 처리하고, 이후 도구별 동작을 위임한다.

        편집 중인 텍스트 오버레이 바깥을 클릭하면(오버레이 안쪽 클릭은 오버레이
        위젯이 직접 받아 이 메서드까지 오지 않는다) 먼저 편집 내용을 반영한다.
        """
        if self._text_overlay is not None:
            self._commit_text_overlay()
        if event.button() == Qt.MouseButton.LeftButton and self._curve_points:
            idx = self._curve_handle_at(event.position().toPoint())
            if idx is not None:
                self._curve_drag_index = idx
                event.accept()
                return
            # 핸들이 아닌 곳을 클릭하면 편집 중인 곡선을 그 모양대로 확정하고,
            # 아래 일반 처리로 넘어가 이 클릭이 자유곡선이면 새 곡선을 바로 시작한다.
            self._commit_curve()
        if event.button() == Qt.MouseButton.LeftButton:
            h = self._canvas_handle_at(event.position().toPoint())
            if h:
                self._push_undo()
                self._drag_handle = h
                self._drag_start_view = event.position()
                self._drag_start_rect = QRectF(self._scene.sceneRect())
                event.accept()
                return
            if self.tool == "select":
                self._select_press(event.position().toPoint())
                event.accept()
                return
            if self.tool == "draw":
                self._draw_press(event.position().toPoint())
                event.accept()
                return
            if self.tool == "fill":
                self.fill_at(event.position().toPoint())
                event.accept()
                return
            if self.tool == "text":
                self._text_press(event.position().toPoint())
                event.accept()
                return
            if self.tool == "shape":
                self._shape_press(event.position().toPoint())
                event.accept()
                return
            # '이동' 도구: 선택된 아이템이 하나뿐이고 그 크기 조절 핸들 위를
            # 눌렀으면 크기 조절을 시작하고, 뒤이은 기본 아이템 드래그(이동)
            # 처리로 넘어가지 않도록 여기서 끝낸다.
            resize_item = self._resizable_selected_item()
            if resize_item is not None:
                handle = self._item_resize_handle_at(resize_item, event.position().toPoint())
                if handle is not None:
                    self._item_resize_item = resize_item
                    self._item_resize_handle = handle
                    self._item_resize_drag_ref = (self.mapToScene(event.position().toPoint()),
                                                   self._item_pixmap_rect(resize_item))
                    self._item_resize_source_pixmap = QPixmap(resize_item.pixmap())
                    self._item_resize_pending_snapshot = self._snapshot()
                    event.accept()
                    return
            # '이동' 도구: 아이템 드래그가 실제로 위치를 바꿀 경우에만 되돌리기
            # 항목으로 기록하기 위해, 드래그 시작 시점의 상태를 미리 잡아둔다.
            self._pending_move_snapshot = self._snapshot()
            self._pending_move_positions = {
                id(it): QPointF(it.pos()) for it in self._scene.items()
                if isinstance(it, QGraphicsPixmapItem)
            }
        super().mousePressEvent(event)

    def _select_press(self, view_pos: QPoint) -> None:
        """선택 도구: 드래그 시작, 핸들 잡기, 이동 시작을 처리한다."""
        sp = self.mapToScene(view_pos)
        h = self._select_handle_at(view_pos)
        if h:
            self._select_drag_handle = h
            self._select_drag_ref = (sp, QRectF(self._select_rect))
            return
        if self._select_state == "adjust" and self._select_rect.contains(sp):
            self._select_drag_handle = "move"
            self._select_drag_ref = (sp, QRectF(self._select_rect))
            return
        self._select_state = "dragging"
        self._select_origin = sp
        self._select_rect = QRectF(sp, QSizeF(0, 0))
        self.viewport().update()

    # ---------- 텍스트 ---------- #
    def _text_press(self, view_pos: QPoint) -> None:
        """텍스트 도구: 기존 텍스트 박스 위를 누르면 그 박스를 이동시키고,
        빈 곳을 누르면 새 텍스트 박스가 들어갈 영역 드래그를 시작한다."""
        item = self.itemAt(view_pos)
        if isinstance(item, QGraphicsPixmapItem) and id(item) in self._text_meta:
            self._text_state = "moving"
            self._text_drag_item = item
            self._text_drag_start_scene = self.mapToScene(view_pos)
            self._text_drag_item_start_pos = QPointF(item.pos())
            self._pending_move_snapshot = self._snapshot()
            self._pending_move_positions = {
                id(it): QPointF(it.pos()) for it in self._scene.items()
                if isinstance(it, QGraphicsPixmapItem)
            }
            return
        sp = self.mapToScene(view_pos)
        self._text_state = "dragging"
        self._text_origin = sp
        self._text_rect = QRectF(sp, QSizeF(0, 0))
        self.viewport().update()

    def _text_move(self, view_pos: QPoint) -> None:
        """텍스트 도구: 박스 이동 드래그 또는 새 영역 드래그를 갱신한다."""
        if self._text_state == "moving" and self._text_drag_item is not None:
            sp = self.mapToScene(view_pos)
            delta = sp - self._text_drag_start_scene
            self._text_drag_item.setPos(self._text_drag_item_start_pos + delta)
            self.viewport().update()
            return
        if self._text_state == "dragging" and self._text_origin is not None:
            sp = self.mapToScene(view_pos)
            self._text_rect = QRectF(self._text_origin, sp).normalized()
            self.viewport().update()

    def _text_release(self) -> None:
        """텍스트 도구: 박스 이동 드래그를 확정하거나, 새 영역 드래그를 마치면
        지정한 영역에 편집 오버레이를 연다."""
        if self._text_state == "moving":
            self._text_state = "idle"
            self._text_drag_item = None
            self._text_drag_start_scene = None
            self._text_drag_item_start_pos = None
            self._commit_pending_move()
            return
        if self._text_state != "dragging":
            return
        self._text_state = "idle"
        rect = self._clamp_to_scene(self._text_rect)
        self._text_rect = QRectF()
        self.viewport().update()
        if rect.width() < MIN_SELECTION or rect.height() < MIN_SELECTION:
            return
        self._open_text_editor(rect=rect)

    def _open_text_editor(self, rect: Optional[QRectF] = None,
                           existing_item: Optional[QGraphicsPixmapItem] = None) -> None:
        """지정한 영역(신규) 또는 기존 텍스트 아이템 위에 편집 오버레이를 연다."""
        if self._text_overlay is not None:
            self._commit_text_overlay()

        if existing_item is not None:
            rect = QRectF(existing_item.pos(), QSizeF(existing_item.pixmap().size()))
            meta = self._text_meta.get(id(existing_item), {})
            text = meta.get("text", "")
            font = QFont(meta.get("font", self.text_font))
            color = QColor(meta.get("color", self.text_color))
            align_h = meta.get("align_h", self.text_align_h)
        else:
            text = ""
            font = QFont(self.text_font)
            color = QColor(self.text_color)
            align_h = self.text_align_h

        if rect is None:
            return
        self._text_editing_item = existing_item
        self._text_new_rect = QRectF(rect) if existing_item is None else None

        overlay = _TextEditOverlay(self.viewport())
        top_left = self.mapFromScene(rect.topLeft())
        bottom_right = self.mapFromScene(rect.bottomRight())
        size = QSize(max(bottom_right.x() - top_left.x(), 1), max(bottom_right.y() - top_left.y(), 1))
        overlay.setGeometry(QRect(top_left, size))
        overlay.text_edit.setPlainText(text)
        self._style_text_edit(overlay.text_edit, font, color, align_h)
        overlay.closed.connect(self._commit_text_overlay)
        overlay.cancelled.connect(self._discard_text_overlay)
        self._text_overlay = overlay
        overlay.show()
        overlay.raise_()
        overlay.text_edit.setFocus()
        overlay.text_edit.selectAll()

    def _style_text_edit(self, text_edit: QTextEdit, font: QFont, color: QColor, align_h: str) -> None:
        """편집 중인 텍스트칸에 폰트/색/가로 정렬을 실시간으로 반영한다.

        세로 정렬은 QTextEdit이 내용 세로 정렬을 지원하지 않아 여기서는
        반영하지 않고, 최종 래스터화(_rasterize_text) 시점에만 적용한다.

        편집칸은 확대/축소 배율과 무관한 일반 위젯이지만, 최종 텍스트는
        래스터화된 픽스맵으로 캔버스에 얹혀 화면 배율만큼 함께 확대/축소된다.
        편집 중 보이는 글자 크기가 완성 후 크기와 다르게 느껴지지 않도록,
        여기서도 현재 화면 배율을 곱해 같은 크기로 보이게 맞춘다.
        """
        scale = self.transform().m11() or 1.0
        display_font = QFont(font)
        display_font.setPointSizeF(max(font.pointSizeF(), 1.0) * scale)
        text_edit.setFont(display_font)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor = text_edit.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeCharFormat(fmt)
        text_edit.mergeCurrentCharFormat(fmt)
        h_flags = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
                   "right": Qt.AlignmentFlag.AlignRight}
        text_edit.setAlignment(h_flags.get(align_h, Qt.AlignmentFlag.AlignLeft))

    def commit_text_editing(self) -> None:
        """편집 중인 텍스트 오버레이가 있으면 반영하고 닫는다 (없으면 아무 동작 없음)."""
        self._commit_text_overlay()

    def commit_pending_edit(self) -> None:
        """편집 중인 텍스트나 자유곡선이 있으면 그 시점 상태로 캔버스에 반영한다.

        저장/복사/잘라내기/탭 전환/탭 닫기/실행취소처럼 캔버스 내용을 최종
        이미지로 다루기 전에 호출해, 아직 래스터화되지 않은 편집 중인 내용이
        누락되지 않게 한다. 확대/축소(wheelEvent)처럼 자유곡선 편집을 방해할
        필요가 없는 곳에서는 commit_text_editing()만 쓴다.
        """
        self._commit_text_overlay()
        if self._curve_points:
            self._commit_curve()

    def _commit_text_overlay(self) -> None:
        """편집 오버레이를 닫고, 입력된 텍스트를 래스터화해 씬에 반영한다.

        내용이 비어 있으면: 신규 박스는 그냥 버리고, 기존 박스는 삭제한다.
        """
        if self._text_overlay is None:
            return
        overlay = self._text_overlay
        text = overlay.text_edit.toPlainText()
        existing = self._text_editing_item
        rect = (QRectF(existing.pos(), QSizeF(existing.pixmap().size()))
                if existing is not None else self._text_new_rect)

        self._text_overlay = None
        self._text_editing_item = None
        self._text_new_rect = None
        overlay.setParent(None)
        overlay.deleteLater()

        if not text.strip():
            if existing is not None:
                self._push_undo()
                self._scene.removeItem(existing)
                self._text_meta.pop(id(existing), None)
                self.changed.emit()
            return

        if rect is None:
            return
        pixmap = self._rasterize_text(text, self.text_font, self.text_color,
                                       self.text_align_h, self.text_align_v, rect.size())
        meta = {"text": text, "font": QFont(self.text_font), "color": QColor(self.text_color),
                "align_h": self.text_align_h, "align_v": self.text_align_v}
        self._push_undo()
        if existing is not None:
            existing.setPixmap(pixmap)
            existing.setZValue(len(self._scene.items()))
            self._text_meta[id(existing)] = meta
            self.changed.emit()
        else:
            item = self._add_pixmap(pixmap, rect.topLeft().toPoint())
            # 텍스트는 대부분 투명 배경이라, 기본 마스크 기반 히트 테스트로는
            # 글자가 없는 빈 공간을 클릭(더블클릭 재편집 포함)했을 때 반응하지
            # 않는다. 상자 전체 영역을 클릭 대상으로 삼도록 바꾼다.
            item.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
            self._text_meta[id(item)] = meta

    def _discard_text_overlay(self) -> None:
        """편집 내용을 반영하지 않고 오버레이만 닫는다 (Esc)."""
        if self._text_overlay is None:
            return
        overlay = self._text_overlay
        self._text_overlay = None
        self._text_editing_item = None
        self._text_new_rect = None
        overlay.setParent(None)
        overlay.deleteLater()

    @staticmethod
    def _rasterize_text(text: str, font: QFont, color: QColor, align_h: str, align_v: str,
                         size: QSizeF) -> QPixmap:
        """텍스트를 지정한 폰트/색/정렬로 지정 크기의 투명 배경 픽스맵에 그린다."""
        w = max(int(round(size.width())), 1)
        h = max(int(round(size.height())), 1)
        pixmap = QPixmap(w, h)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(font)
        painter.setPen(QColor(color))
        h_flags = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
                   "right": Qt.AlignmentFlag.AlignRight}[align_h]
        v_flags = {"top": Qt.AlignmentFlag.AlignTop, "middle": Qt.AlignmentFlag.AlignVCenter,
                   "bottom": Qt.AlignmentFlag.AlignBottom}[align_v]
        painter.drawText(pixmap.rect(), int(h_flags | v_flags | Qt.TextFlag.TextWordWrap), text)
        painter.end()
        return pixmap

    # ---------- 도형/선 ---------- #
    def _shape_press(self, view_pos: QPoint) -> None:
        """도형 도구: 바운딩 박스 도형, 직선, 또는 자유곡선의 첫 직선 드래그를 시작한다.

        자유곡선도 처음에는 직선과 똑같이 드래그로 시작하고(아래 _shape_release
        참고), 이후 4개 제어점을 드래그로 조정하는 편집 모드로 들어간다.
        """
        sp = self.mapToScene(view_pos)
        self._shape_state = "dragging"
        self._shape_origin = sp
        self._shape_rect = QRectF(sp, QSizeF(0, 0))
        self.viewport().update()

    def _shape_move(self, view_pos: QPoint, shift: bool) -> None:
        """도형 도구: 드래그 중인 미리보기 또는 자유곡선 제어점 드래그를 갱신한다.

        Shift를 누른 채면 바운딩 박스 도형은 가로세로 비율 1:1로 고정되고,
        직선/자유곡선(첫 드래그 구간)은 각도가 45도 단위(수평/수직/대각선)로
        스냅된다. '원'은 항상 정사각형 박스로 고정되어 Shift 없이도 원이 된다.
        """
        sp = self.mapToScene(view_pos)
        if self._curve_drag_index is not None:
            self._curve_points[self._curve_drag_index] = sp
            self.viewport().update()
            return
        if self._shape_state != "dragging" or self._shape_origin is None:
            return
        if is_line_kind(self.shape_subtool):
            end = snap_line_angle(self._shape_origin, sp) if shift else sp
            self._shape_rect = QRectF(self._shape_origin, end)
        elif shift or self.shape_subtool == "circle":
            self._shape_rect = lock_square(self._shape_origin, sp)
        else:
            self._shape_rect = QRectF(self._shape_origin, sp).normalized()
        self.viewport().update()

    def _shape_release(self) -> None:
        """도형 도구: 드래그를 마친다.

        도형/직선은 곧바로 캔버스에 반영하고, 자유곡선은 시작-1/3-2/3-끝
        4개 제어점을 만들어 핸들로 조정하는 편집 모드로 들어간다(캔버스
        반영은 _commit_curve가 담당). 자유곡선 제어점을 드래그하던 중이면
        드래그만 끝내고 편집 모드는 계속 유지한다.
        """
        if self._curve_drag_index is not None:
            self._curve_drag_index = None
            return
        if self._shape_state != "dragging":
            return
        rect = QRectF(self._shape_rect)
        self._shape_state = "idle"
        self._shape_origin = None
        self._shape_rect = QRectF()
        self.viewport().update()
        p0, p3 = rect.topLeft(), rect.bottomRight()
        if (p0 - p3).manhattanLength() < MIN_SELECTION:
            return
        if self.shape_subtool in FREEHAND_KINDS:
            self._curve_points = [p0, p0 + (p3 - p0) / 3.0, p0 + (p3 - p0) * 2.0 / 3.0, p3]
            self.viewport().update()
            return
        if is_line_kind(self.shape_subtool):
            self._commit_line_shape(p0, p3)
            return
        bbox = self._clamp_to_scene(rect)
        if bbox.width() >= MIN_SELECTION and bbox.height() >= MIN_SELECTION:
            self._commit_bbox_shape(bbox)

    def _curve_handle_rects(self) -> list[QRectF]:
        """편집 중인 자유곡선의 4개 조절점(시작/제어1/제어2/끝) 사각형을 계산한다."""
        size = self._handle_size_scene()
        return [QRectF(p.x() - size / 2, p.y() - size / 2, size, size) for p in self._curve_points]

    def _curve_handle_at(self, view_pos: QPoint) -> Optional[int]:
        """뷰 좌표 view_pos에 해당하는 자유곡선 조절점 인덱스를 찾는다. 없으면 None."""
        sp = self.mapToScene(view_pos)
        for i, hr in enumerate(self._curve_handle_rects()):
            if hr.contains(sp):
                return i
        return None

    def _commit_curve(self) -> None:
        """편집 중인 자유곡선(베지에)을 그 시점 모양대로 래스터화해 새 아이템으로 추가한다."""
        points = self._curve_points
        self._curve_points = []
        self._curve_drag_index = None
        self.viewport().update()
        if len(points) != 4:
            return
        pad = self._shape_pad() + self._arrowhead_margin()
        xs, ys = [p.x() for p in points], [p.y() for p in points]
        content_origin = QPointF(min(xs), min(ys))
        left, top = content_origin.x() - pad, content_origin.y() - pad
        w, h = max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad
        pixmap = QPixmap(max(int(round(w)), 1), max(int(round(h)), 1))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(self._shape_pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        points_local = [p - content_origin for p in points]
        draw_bezier_kind(painter, self.shape_subtool, [p + QPointF(pad, pad) for p in points_local],
                          self.draw_thickness)
        painter.end()
        self._push_undo()
        item = self._add_pixmap(pixmap, QPoint(int(round(left)), int(round(top))))
        self._shape_meta[id(item)] = {
            "kind": "curve", "subtool": self.shape_subtool, "color": QColor(self.draw_color),
            "thickness": self.draw_thickness, "pad": pad, "geometry": points_local,
        }

    @staticmethod
    def _shape_pad_for(thickness: int) -> int:
        """도형 획(pen) 두께가 픽스맵 경계에서 잘리지 않도록 필요한 여백."""
        return int(math.ceil(thickness / 2)) + 2

    def _shape_pad(self) -> int:
        return self._shape_pad_for(self.draw_thickness)

    def _shape_pen(self) -> QPen:
        """도형/선 그리기에 쓸 pen (현재 두께/색, 둥근 이음새)을 만든다."""
        pen = QPen(QColor(self.draw_color))
        pen.setWidthF(max(self.draw_thickness, 1))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def _commit_bbox_shape(self, rect: QRectF) -> None:
        """드래그로 정의된 바운딩 박스 도형을 래스터화해 새(이동 가능한) 아이템으로 추가한다."""
        pad = self._shape_pad()
        w, h = max(int(round(rect.width())), 1), max(int(round(rect.height())), 1)
        pixmap = QPixmap(w + 2 * pad, h + 2 * pad)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(self._shape_pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        draw_bbox_shape(painter, self.shape_subtool, QRectF(pad, pad, w, h))
        painter.end()
        self._push_undo()
        item = self._add_pixmap(pixmap, (rect.topLeft() - QPointF(pad, pad)).toPoint())
        self._shape_meta[id(item)] = {
            "kind": "bbox", "subtool": self.shape_subtool, "color": QColor(self.draw_color),
            "thickness": self.draw_thickness, "pad": pad, "geometry": QSizeF(w, h),
        }

    @staticmethod
    def _arrowhead_margin_for(subtool: str, thickness: int) -> int:
        """화살표 날개가 픽스맵 밖으로 잘리지 않도록 필요한 추가 여백."""
        if subtool not in ARROW_KINDS:
            return 0
        return int(math.ceil(arrowhead_length(thickness))) + 2

    def _arrowhead_margin(self) -> int:
        return self._arrowhead_margin_for(self.shape_subtool, self.draw_thickness)

    def _commit_line_shape(self, p1: QPointF, p2: QPointF) -> None:
        """드래그로 정의된 직선(화살표 포함 가능)을 래스터화해 새 아이템으로 추가한다."""
        pad = self._shape_pad() + self._arrowhead_margin()
        content_origin = QPointF(min(p1.x(), p2.x()), min(p1.y(), p2.y()))
        left, top = content_origin.x() - pad, content_origin.y() - pad
        w = abs(p2.x() - p1.x()) + 2 * pad
        h = abs(p2.y() - p1.y()) + 2 * pad
        pixmap = QPixmap(max(int(round(w)), 1), max(int(round(h)), 1))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(self._shape_pen())
        p1_local, p2_local = p1 - content_origin, p2 - content_origin
        draw_line_kind(painter, self.shape_subtool, p1_local + QPointF(pad, pad),
                        p2_local + QPointF(pad, pad), self.draw_thickness)
        painter.end()
        self._push_undo()
        item = self._add_pixmap(pixmap, QPoint(int(round(left)), int(round(top))))
        self._shape_meta[id(item)] = {
            "kind": "line", "subtool": self.shape_subtool, "color": QColor(self.draw_color),
            "thickness": self.draw_thickness, "pad": pad, "geometry": (p1_local, p2_local),
        }

    def _restyle_selected_shape_items(self) -> None:
        """이미 확정된 도형/선/자유곡선이 선택되어 있으면, 방금 바뀐 두께/색으로
        다시 래스터화해 즉시 반영한다 (화면상 위치는 그대로 유지).

        item.pos()가 마지막 래스터화 시점의 pad만큼 콘텐츠 좌상단에서
        안쪽으로 들어가 있다는 불변식을 이용해, 도형이 그 뒤 이동됐어도
        content_top_left(씬 좌표)를 정확히 복원한 뒤 새 pad로 다시 배치한다.
        """
        targets = [it for it in self._scene.selectedItems() if id(it) in self._shape_meta]
        if not targets:
            return
        self._push_undo()
        pen = self._shape_pen()
        for item in targets:
            meta = self._shape_meta[id(item)]
            kind = meta["kind"]
            subtool = meta["subtool"]
            content_top_left = item.pos() + QPointF(meta["pad"], meta["pad"])

            if kind == "bbox":
                size: QSizeF = meta["geometry"]
                pad = self._shape_pad()
                w, h = max(int(round(size.width())), 1), max(int(round(size.height())), 1)
                pixmap = QPixmap(w + 2 * pad, h + 2 * pad)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                draw_bbox_shape(painter, subtool, QRectF(pad, pad, w, h))
                painter.end()
            elif kind == "line":
                p1_local, p2_local = meta["geometry"]
                pad = self._shape_pad() + self._arrowhead_margin_for(subtool, self.draw_thickness)
                w = abs(p2_local.x() - p1_local.x()) + 2 * pad
                h = abs(p2_local.y() - p1_local.y()) + 2 * pad
                pixmap = QPixmap(max(int(round(w)), 1), max(int(round(h)), 1))
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setPen(pen)
                draw_line_kind(painter, subtool, p1_local + QPointF(pad, pad),
                                p2_local + QPointF(pad, pad), self.draw_thickness)
                painter.end()
            else:  # curve
                points_local: list[QPointF] = meta["geometry"]
                pad = self._shape_pad() + self._arrowhead_margin_for(subtool, self.draw_thickness)
                xs = [p.x() for p in points_local]
                ys = [p.y() for p in points_local]
                w, h = max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad
                pixmap = QPixmap(max(int(round(w)), 1), max(int(round(h)), 1))
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                draw_bezier_kind(painter, subtool, [p + QPointF(pad, pad) for p in points_local],
                                  self.draw_thickness)
                painter.end()

            item.setPixmap(pixmap)
            item.setPos(content_top_left - QPointF(pad, pad))
            meta["color"] = QColor(self.draw_color)
            meta["thickness"] = self.draw_thickness
            meta["pad"] = pad
        self.changed.emit()

    # ---------- 그리기(브러시/지우개/형광펜) ---------- #
    def _pixel_align(self, point: QPointF) -> QPointF:
        """선이 픽셀 경계에 걸쳐 안티앨리어싱으로 번지지 않도록 좌표를 보정한다.

        홀수 두께(1, 3, 5...)는 픽셀 중앙(x.5)에 맞춰야, 짝수 두께는 픽셀
        경계(정수)에 맞춰야 안티앨리어싱 없이 딱 지정한 두께만큼만 그려진다.
        맞추지 않으면 선이 두 픽셀 행/열에 반투명하게 걸쳐 그려져, 예를 들어
        1px 지정이 2px처럼(양쪽에 반투명 1px씩), 5px 지정이 6px처럼 보인다.
        """
        if self.draw_thickness % 2 == 1:
            return QPointF(math.floor(point.x()) + 0.5, math.floor(point.y()) + 0.5)
        return QPointF(round(point.x()), round(point.y()))

    def _draw_press(self, view_pos: QPoint) -> None:
        """그리기 도구: 새 스트로크를 시작한다."""
        self._push_undo()
        self.draw_item.setZValue(len(self._scene.items()))
        sp = self._pixel_align(self.mapToScene(view_pos) - self.draw_item.pos())
        self._stroke_path = QPainterPath()
        self._stroke_path.moveTo(sp)
        self._stroke_last_point = sp
        if self.draw_subtool != "eraser":
            self._stroke_backup = QPixmap(self.draw_item.pixmap())
        self._draw_dot(sp)

    def _draw_dot(self, local_point: QPointF) -> None:
        """스트로크 시작점 등 한 점만 찍힌 경우에도 보이도록 점을 그린다."""
        if self.draw_subtool == "eraser":
            self._erase_segment(local_point, local_point)
        else:
            self._paint_stroke()

    def _draw_move(self, view_pos: QPoint) -> None:
        """그리기 도구: 스트로크를 이어 그린다."""
        if self._stroke_path is None:
            return
        sp = self._pixel_align(self.mapToScene(view_pos) - self.draw_item.pos())
        if self.draw_subtool == "eraser":
            self._erase_segment(self._stroke_last_point, sp)
            self._stroke_last_point = sp
        else:
            self._stroke_path.lineTo(sp)
            self._paint_stroke()
        self.changed.emit()

    def _draw_release(self) -> None:
        """그리기 도구: 스트로크를 종료한다."""
        self._stroke_path = None
        self._stroke_backup = None
        self._stroke_last_point = None

    def _paint_stroke(self) -> None:
        """브러시/형광펜: 백업 위에 현재까지의 전체 경로를 다시 그려 자기 겹침으로
        인한 불필요한 진해짐 없이, 스트로크끼리는 겹칠수록 짙어지게 한다."""
        pm = QPixmap(self._stroke_backup)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(self.draw_color)
        color.setAlphaF(HIGHLIGHTER_ALPHA if self.draw_subtool == "highlighter" else 1.0)
        pen = QPen(color)
        pen.setWidthF(max(self.draw_thickness, 1))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._stroke_path)
        painter.end()
        self.draw_item.setPixmap(pm)

    def _erase_segment(self, p1: QPointF, p2: QPointF) -> None:
        """지우개: 그리기 레이어에서 p1-p2 구간을 투명하게 지운다."""
        pm = QPixmap(self.draw_item.pixmap())
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        pen = QPen(Qt.GlobalColor.black)
        pen.setWidthF(max(self.draw_thickness, 1))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(p1, p2)
        painter.end()
        self.draw_item.setPixmap(pm)

    # ---------- 채우기 ---------- #
    def _item_cover_mask(self, item: QGraphicsPixmapItem, w: int, h: int,
                         scene_rect: QRectF) -> np.ndarray:
        """아이템이 화면을 실제로 덮는 픽셀(알파>0)을 캔버스 크기 bool 마스크로 반환한다.

        Args:
            item: 대상 픽스맵 아이템.
            w: 캔버스(렌더 이미지) 너비.
            h: 캔버스(렌더 이미지) 높이.
            scene_rect: 현재 캔버스 영역. 마스크 좌표의 원점 기준이다.

        Returns:
            (h, w) 모양의 bool 배열. 아이템이 캔버스 밖에 있으면 전부 False.
        """
        img = item.pixmap().toImage().convertToFormat(QImage.Format.Format_ARGB32)
        iw, ih = img.width(), img.height()
        mask = np.zeros((h, w), dtype=bool)
        if iw == 0 or ih == 0:
            return mask
        stride = img.bytesPerLine()
        buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=stride * ih)
        alpha = buf.reshape(ih, stride)[:, :iw * 4].reshape(ih, iw, 4)[:, :, 3] > 0
        ox = int(round(item.pos().x() - scene_rect.left()))
        oy = int(round(item.pos().y() - scene_rect.top()))
        x0, y0 = max(ox, 0), max(oy, 0)
        x1, y1 = min(ox + iw, w), min(oy + ih, h)
        if x0 >= x1 or y0 >= y1:
            return mask
        mask[y0:y1, x0:x1] = alpha[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
        return mask

    def fill_at(self, view_pos: QPoint) -> bool:
        """클릭 지점과 연결된, 허용 범위 내의 인접 색상 영역을 draw_color로 채운다.

        영역 판정은 화면에 실제로 보이는 색(원본 이미지 + 그리기 레이어 +
        붙여넣은 이미지가 합쳐진 결과)을 기준으로 하되, 채우는 범위와 대상은
        '클릭 지점에서 보이는 최상단 아이템' 하나로 한정한다. 그 아이템이
        가려지지 않은 부분만 채우고, 결과도 그 아이템의 픽스맵에 직접 그린다.

        예전에는 결과를 항상 그리기 레이어에 그린 뒤 그 레이어를 최상단으로
        올렸는데, 허용 범위 안의 색이 캔버스 배경까지 이어지는 경우(밝은 UI
        스크린샷은 대개 그렇다) 붙여넣은 다른 이미지들까지 통째로 덮여 사라졌다.

        Args:
            view_pos: 뷰(위젯) 좌표의 클릭 지점.

        Returns:
            실제로 채웠는지 여부 (클릭 지점이 캔버스 밖이면 False).
        """
        scene_rect = self._scene.sceneRect()
        sp = self.mapToScene(view_pos)
        if not scene_rect.contains(sp):
            return False

        composed = self.render_image().convertToFormat(QImage.Format.Format_ARGB32)
        w, h = composed.width(), composed.height()
        x = int(sp.x() - scene_rect.left())
        y = int(sp.y() - scene_rect.top())
        if not (0 <= x < w and 0 <= y < h):
            return False

        stride = composed.bytesPerLine()
        buf = np.frombuffer(composed.constBits(), dtype=np.uint8, count=stride * h)
        arr = buf.reshape(h, stride)[:, :w * 4].reshape(h, w, 4).astype(np.int16)
        # 완전 투명 픽셀의 RGB는 합성 과정에서 임의값(보통 0)이 되어 의미가
        # 없으므로 0으로 정규화한 뒤, 알파를 네 번째 비교 채널로 함께 쓴다.
        # RGB만 비교하면 알파만 다른 투명 배경과 같은 색 도형(예: 검은 아이콘
        # + 투명 배경)이 한 영역으로 이어져 배경까지 함께 채워진다.
        arr[arr[:, :, 3] == 0, :3] = 0

        target = arr[y, x]
        threshold = self.fill_tolerance / 100 * 255
        mask = np.all(np.abs(arr - target) <= threshold, axis=2)
        labeled, _ = ndimage.label(mask)
        region = labeled == labeled[y, x]

        # 클릭 지점에서 보이는 최상단 아이템을 찾고, 그 아이템이 위 아이템에
        # 가려지지 않은 부분으로 채울 영역을 제한한다. 아무 아이템도 없는 빈
        # 캔버스 배경을 클릭했으면 그리기 레이어에 그리되, 아이템이 덮은 곳은
        # 건드리지 않는다.
        items = sorted((it for it in self._scene.items() if isinstance(it, QGraphicsPixmapItem)),
                       key=lambda it: it.zValue(), reverse=True)
        masks = {id(it): self._item_cover_mask(it, w, h, scene_rect) for it in items}
        target_item: Optional[QGraphicsPixmapItem] = None
        above = np.zeros((h, w), dtype=bool)
        for it in items:
            if masks[id(it)][y, x]:
                target_item = it
                break
            above |= masks[id(it)]
        if target_item is None:
            target_item = self.draw_item
            allowed = np.ones((h, w), dtype=bool)
            for it in items:
                if it is not self.draw_item:
                    allowed &= ~masks[id(it)]
        else:
            allowed = masks[id(target_item)] & ~above
        region &= allowed
        pixel_count = int(region.sum())
        if pixel_count == 0:
            return False

        fill_img = QImage(w, h, QImage.Format.Format_ARGB32)
        fill_img.fill(Qt.GlobalColor.transparent)
        fill_stride = fill_img.bytesPerLine()
        fill_buf = np.frombuffer(fill_img.bits(), dtype=np.uint8, count=fill_stride * h)
        fill_arr = fill_buf.reshape(h, fill_stride)[:, :w * 4].reshape(h, w, 4)
        c = QColor(self.draw_color)
        fill_arr[region] = [c.blue(), c.green(), c.red(), 255]

        self._push_undo()
        pm = QPixmap(target_item.pixmap())
        painter = QPainter(pm)
        # 씬 크기 이미지를 아이템 로컬 좌표로 옮겨 그린다. 아이템 픽스맵
        # 경계에서 자동으로 잘리므로 다른 아이템으로 번지지 않는다.
        painter.drawImage(scene_rect.topLeft() - target_item.pos(), fill_img)
        painter.end()
        target_item.setPixmap(pm)
        self.changed.emit()
        kind = ("배경" if target_item is self.base_item
                else "그리기 레이어" if target_item is self.draw_item else "이미지")
        logger.info("채우기: (%d, %d) %s 대상, %d픽셀, 허용범위=%d%%",
                    x, y, kind, pixel_count, self.fill_tolerance)
        return True

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """여백 조절 드래그 중이면 캔버스 크기를 갱신하고, 아니면 도구별 동작으로 위임한다."""
        if self._drag_handle and self._drag_start_view is not None and self._drag_start_rect is not None:
            # 드래그 중에는 미리보기 사각형만 갱신하고, 실제 sceneRect는 건드리지
            # 않는다. 뷰포트보다 작은 씬은 가운데로 재정렬되므로, 드래그 중에
            # sceneRect를 계속 바꾸면 화면상 이미지 위치가 매 이동마다 같이
            # 밀려서(픽픽과 달리) 캔버스가 반대 방향으로 움직이는 것처럼 보인다.
            # 실제 크기 반영은 mouseReleaseEvent에서 한 번만 한다.
            scale = self.transform().m11() or 1.0
            dx = (event.position().x() - self._drag_start_view.x()) / scale
            dy = (event.position().y() - self._drag_start_view.y()) / scale
            hx, hy = self._drag_handle
            r = QRectF(self._drag_start_rect)
            left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()
            if hx < 0:
                left = min(left + dx, right - MIN_CANVAS)
            elif hx > 0:
                right = max(right + dx, left + MIN_CANVAS)
            if hy < 0:
                top = min(top + dy, bottom - MIN_CANVAS)
            elif hy > 0:
                bottom = max(bottom + dy, top + MIN_CANVAS)
            self._canvas_resize_preview = QRectF(left, top, right - left, bottom - top)
            self.viewport().update()
            self.viewChanged.emit()     # 상태바의 캔버스 크기 표시만 실시간 갱신 (dirty 표시 없음)
            event.accept()
            return

        pos = event.position().toPoint()
        # 어떤 도구를 선택했든, 실제로 버튼을 눌러 그 도구 동작을 드래그하는
        # 중이 아니라면(순수 hover) 먼저 캔버스 테두리 핸들 위인지 확인해
        # 크기 조절 커서로 바꾼다. 도구별 처리(_select_move 등)가 이어서
        # 자기 커서를 덮어씌울 수도 있다(예: 선택 조절 핸들 위일 때).
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            h = self._canvas_handle_at(pos)
            if h is None:
                resize_item = self._resizable_selected_item()
                if resize_item is not None:
                    h = self._item_resize_handle_at(resize_item, pos)
            if h is not None:
                self.viewport().setCursor(CURSORS[h])
            elif self.tool == "move" and self._movable_item_at(pos) is not None:
                # 붙여넣은/텍스트/도형 아이템 내부: 드래그로 이동 가능함을 사방
                # 화살표 커서로 미리 알려준다.
                self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        if self._item_resize_item is not None:
            self._item_resize_move(pos)
            event.accept()
            return

        if self.tool == "select":
            self._select_move(pos)
            event.accept()
            return

        if self.tool == "draw" and self._stroke_path is not None:
            self._draw_move(pos)
            event.accept()
            return

        if self.tool == "fill":
            event.accept()
            return

        if self.tool == "text":
            self._text_move(pos)
            event.accept()
            return

        if self.tool == "shape":
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._shape_move(pos, shift)
            event.accept()
            return

        super().mouseMoveEvent(event)
        if self.tool == "move" and (event.buttons() & Qt.MouseButton.LeftButton):
            # 선택 테두리의 점선(marching ants)은 실제 QGraphicsItem이 아니라
            # drawForeground에서 매 프레임 새 위치에 직접 그리는 것이라, Qt의
            # 최소 갱신(dirty region) 추적이 아이템 이동분만 지우고 이전 프레임의
            # 점선 잔상은 못 지운다. 아이템을 드래그하는 동안은 뷰포트 전체를
            # 다시 그려 잔상이 남지 않게 한다.
            self.viewport().update()

    def _select_move(self, view_pos: QPoint) -> None:
        """선택 도구: 이동/조절 드래그 또는 일반 드래그, 커서 갱신을 처리한다."""
        sp = self.mapToScene(view_pos)

        if self._select_drag_handle == "move":
            if self._select_drag_ref is None:
                return
            start, rect0 = self._select_drag_ref
            r = QRectF(rect0)
            r.translate(sp - start)
            self._select_rect = self._clamp_to_scene(r)
            self.viewport().update()
            return

        if self._select_drag_handle:
            if self._select_drag_ref is None or isinstance(self._select_drag_handle, str):
                return
            start, rect0 = self._select_drag_ref
            hx, hy = self._select_drag_handle
            d = sp - start
            left, top, right, bottom = rect0.left(), rect0.top(), rect0.right(), rect0.bottom()
            if hx < 0:
                left = min(left + d.x(), right - MIN_SELECTION)
            elif hx > 0:
                right = max(right + d.x(), left + MIN_SELECTION)
            if hy < 0:
                top = min(top + d.y(), bottom - MIN_SELECTION)
            elif hy > 0:
                bottom = max(bottom + d.y(), top + MIN_SELECTION)
            self._select_rect = self._clamp_to_scene(QRectF(left, top, right - left, bottom - top))
            self.viewport().update()
            return

        if self._select_state == "dragging":
            if self._select_origin is not None:
                self._select_rect = QRectF(self._select_origin, sp).normalized()
        elif self._select_state == "adjust":
            h = self._select_handle_at(view_pos)
            if h is None:
                h = self._canvas_handle_at(view_pos)
            self.viewport().setCursor(CURSORS[h] if h is not None else Qt.CursorShape.ArrowCursor)
        self.viewport().update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """캔버스 여백 조절 드래그 또는 도구별 드래그를 종료한다."""
        if self._drag_handle:
            if self._canvas_resize_preview is not None:
                new_rect = self._canvas_resize_preview
                old_rect = QRectF(self._scene.sceneRect())
                # 그리기 레이어도 새 크기로 맞춰야, 손잡이로 캔버스를 넓힌 뒤 그
                # 새로 늘어난 영역에 그리기/채우기가 실제로 반영된다 (레이어 크기가
                # 예전 그대로면 그 영역에 그린 내용이 화면 밖처럼 잘려 사라진다).
                self._resize_draw_layer(new_rect, old_rect)
                self._scene.setSceneRect(new_rect)
                self.changed.emit()
            self._drag_handle = None
            self._canvas_resize_preview = None
            self.viewport().update()
            event.accept()
            return
        if self._item_resize_item is not None:
            self._item_resize_release()
            event.accept()
            return
        if self.tool == "select":
            self._select_release()
            event.accept()
            return
        if self.tool == "draw":
            self._draw_release()
            event.accept()
            return
        if self.tool == "fill":
            event.accept()
            return
        if self.tool == "text":
            self._text_release()
            event.accept()
            return
        if self.tool == "shape":
            self._shape_release()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._commit_pending_move()

    def _commit_pending_move(self) -> None:
        """드래그로 아이템 위치가 실제로 바뀌었으면 되돌리기 항목으로 확정한다."""
        snapshot, before = self._pending_move_snapshot, self._pending_move_positions
        self._pending_move_snapshot = None
        self._pending_move_positions = None
        if snapshot is None or before is None:
            return
        after = {id(it): it.pos() for it in self._scene.items() if isinstance(it, QGraphicsPixmapItem)}
        if before != after:
            self._undo_stack.append(snapshot)
            if len(self._undo_stack) > self.MAX_UNDO:
                self._undo_stack.pop(0)
            self._redo_stack.clear()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """텍스트 박스를 더블클릭하면 (현재 도구와 무관하게) 편집 오버레이를 다시 연다."""
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if isinstance(item, QGraphicsPixmapItem) and id(item) in self._text_meta:
                self._open_text_editor(existing_item=item)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _select_release(self) -> None:
        """선택 도구: 드래그/조절 종료를 처리하고 필요 시 adjust 상태로 전환한다."""
        if self._select_drag_handle:
            self._select_drag_handle = None
            self._select_drag_ref = None
            return
        if self._select_state == "dragging":
            if self._select_rect.width() < MIN_SELECTION or self._select_rect.height() < MIN_SELECTION:
                self._select_rect = QRectF()
                self._select_state = "idle"
            else:
                self._select_state = "adjust"
            self.viewport().update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """선택 도구에서 Esc로 선택 영역을 취소한다."""
        if self.tool == "select" and event.key() == Qt.Key.Key_Escape and self.has_selection():
            self.clear_selection()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Ctrl+휠로 뷰를 확대/축소한다.

        확대/축소하면 편집 오버레이의 화면 위치가 캔버스와 어긋나므로 먼저 반영하고 닫는다.
        """
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.commit_text_editing()
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom_percent(self.zoom_percent() * factor)
            event.accept()
            return
        super().wheelEvent(event)

    def render_image(self) -> QImage:
        """sceneRect 영역만 렌더링하여 QImage로 반환한다."""
        r = self._scene.sceneRect()
        img = QImage(max(int(round(r.width())), 1), max(int(round(r.height())), 1),
                     QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent if self._transparent_background else Qt.GlobalColor.white)
        self._scene.clearSelection()
        painter = QPainter(img)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self._scene.render(painter, QRectF(img.rect()), r)
        painter.end()
        return img
