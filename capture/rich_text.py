#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""텍스트 박스의 서식 있는 문서(QTextDocument) 생성·서식 적용·래스터화 헬퍼.

텍스트 박스는 글자 일부만 크기/색/폰트를 바꾸거나 문단별로 정렬을 달리할 수
있어, 내용을 서식이 포함된 HTML(QTextDocument.toHtml)로 보관한다. HTML의 글자
크기는 항상 화면 배율 1 기준(실제 크기)이며, 확대/축소된 편집칸에 띄울 때만
scale_point_sizes()로 배율을 곱한다.
"""

from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import (QAbstractTextDocumentLayout, QColor, QFont, QPainter, QPalette, QPixmap,
                            QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextOption)

H_ALIGN_FLAGS: dict[str, Qt.AlignmentFlag] = {
    "left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
    "right": Qt.AlignmentFlag.AlignRight,
}


def h_align_flag(align_h: str) -> Qt.AlignmentFlag:
    """'left'/'center'/'right'를 Qt 정렬 플래그로 바꾼다 (알 수 없으면 왼쪽)."""
    return H_ALIGN_FLAGS.get(align_h, Qt.AlignmentFlag.AlignLeft)


def char_format_changes(old_font: QFont, new_font: QFont, old_color: QColor,
                        new_color: QColor) -> QTextCharFormat:
    """설정 패널에서 실제로 바뀐 속성만 담은 글자 서식을 만든다.

    선택 영역에 서식이 섞여 있어도(예: 일부만 큰 글자) 바꾸지 않은 속성은
    그대로 두기 위해, 전체 값이 아닌 차이만 병합(merge)하도록 쓴다.

    Args:
        old_font: 변경 전 폰트.
        new_font: 변경 후 폰트.
        old_color: 변경 전 글자 색.
        new_color: 변경 후 글자 색.

    Returns:
        바뀐 속성만 설정된 QTextCharFormat (바뀐 것이 없으면 빈 서식).
    """
    fmt = QTextCharFormat()
    if old_font.family() != new_font.family():
        fmt.setFontFamilies([new_font.family()])
    if old_font.pointSizeF() != new_font.pointSizeF():
        fmt.setFontPointSize(new_font.pointSizeF())
    if old_font.bold() != new_font.bold():
        fmt.setFontWeight(QFont.Weight.Bold if new_font.bold() else QFont.Weight.Normal)
    if old_font.italic() != new_font.italic():
        fmt.setFontItalic(new_font.italic())
    if old_color != new_color:
        fmt.setForeground(QColor(new_color))
    return fmt


def scaled_char_format(fmt: QTextCharFormat, factor: float) -> QTextCharFormat:
    """fmt에 글자 크기가 있으면 factor배 한 사본을 반환한다."""
    scaled = QTextCharFormat(fmt)
    if fmt.hasProperty(QTextCharFormat.Property.FontPointSize):
        scaled.setFontPointSize(round(fmt.fontPointSize() * factor, 2))
    return scaled


def scale_point_sizes(doc: QTextDocument, factor: float) -> None:
    """문서 안의 명시적 글자 크기(조각·빈 문단)를 모두 factor배 한다 (기본 폰트는 제외).

    편집칸 확대/축소 배율 반영 및 원래 크기 복원에 쓴다. 왕복 시 부동소수
    오차가 쌓이지 않도록 소수 둘째 자리에서 반올림한다.
    """
    fragments: list[tuple[int, int, float]] = []
    blocks: list[tuple[int, float]] = []
    block = doc.begin()
    while block.isValid():
        if block.charFormat().fontPointSize() > 0:
            blocks.append((block.position(), block.charFormat().fontPointSize()))
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().fontPointSize() > 0:
                fragments.append((frag.position(), frag.length(), frag.charFormat().fontPointSize()))
            it += 1
        block = block.next()

    # 조각 경계는 서식 병합 중 합쳐질 수 있어, 순회가 끝난 뒤 위치 기준으로 적용한다.
    cursor = QTextCursor(doc)
    for pos, length, size in fragments:
        cursor.setPosition(pos)
        cursor.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setFontPointSize(round(size * factor, 2))
        cursor.mergeCharFormat(fmt)
    for pos, size in blocks:
        cursor.setPosition(pos)
        fmt = QTextCharFormat()
        fmt.setFontPointSize(round(size * factor, 2))
        cursor.mergeBlockCharFormat(fmt)


def build_document(text: str, html: str | None, font: QFont, color: QColor,
                   align_h: str) -> QTextDocument:
    """텍스트 박스 메타 정보로 실제 크기 기준 문서를 만든다.

    Args:
        text: 순수 텍스트 (html이 없을 때 사용).
        html: 서식이 포함된 HTML. 없으면 text 전체에 font/color/align_h를 적용한다.
        font: 박스 기본 폰트.
        color: 박스 기본 글자 색.
        align_h: 박스 기본 가로 정렬.

    Returns:
        새 QTextDocument (호출 측 소유).
    """
    doc = QTextDocument()
    doc.setDefaultFont(QFont(font))
    if html:
        doc.setHtml(html)
        return doc
    doc.setPlainText(text)
    cursor = QTextCursor(doc)
    cursor.select(QTextCursor.SelectionType.Document)
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    cursor.mergeCharFormat(fmt)
    set_document_alignment(doc, align_h)
    return doc


def set_document_alignment(doc: QTextDocument, align_h: str) -> None:
    """문서의 모든 문단 가로 정렬을 align_h로 맞춘다."""
    cursor = QTextCursor(doc)
    cursor.select(QTextCursor.SelectionType.Document)
    block_fmt = QTextBlockFormat()
    block_fmt.setAlignment(h_align_flag(align_h))
    cursor.mergeBlockFormat(block_fmt)


def apply_to_whole_document(doc: QTextDocument, fmt: QTextCharFormat, align_h: str | None) -> None:
    """문서 전체에 바뀐 글자 서식을 병합하고, align_h가 있으면 모든 문단 정렬을 바꾼다."""
    if not fmt.isEmpty():
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeCharFormat(fmt)
    if align_h is not None:
        set_document_alignment(doc, align_h)


def rasterize_document(doc: QTextDocument, color: QColor, align_v: str, size: QSizeF) -> QPixmap:
    """문서를 지정 크기의 투명 배경 픽스맵에 그린다.

    Args:
        doc: 실제 크기 기준 문서 (텍스트 폭이 바뀌므로 호출 후 재사용하지 않는다).
        color: 글자 색이 지정되지 않은 부분에 쓸 기본 색.
        align_v: 'top'/'middle'/'bottom'. 박스 높이 대비 문서 전체의 세로 위치.
        size: 픽스맵 크기(px).

    Returns:
        렌더링된 픽스맵.
    """
    w = max(int(round(size.width())), 1)
    h = max(int(round(size.height())), 1)
    doc.setDocumentMargin(0)
    option = doc.defaultTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    doc.setDefaultTextOption(option)
    doc.setTextWidth(w)

    # 내용이 박스보다 길면 위쪽 정렬은 아래가, 아래쪽 정렬은 위가 잘린다 (기존 drawText와 동일).
    free = h - doc.size().height()
    offset = {"middle": free / 2, "bottom": free}.get(align_v, 0.0)

    pixmap = QPixmap(w, h)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.translate(0, offset)
    context = QAbstractTextDocumentLayout.PaintContext()
    context.palette.setColor(QPalette.ColorRole.Text, QColor(color))
    context.clip = QRectF(0, -offset, w, h)
    doc.documentLayout().draw(painter, context)
    painter.end()
    return pixmap
