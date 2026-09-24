"""单个座位卡片控件（自绘）。

状态：默认 / 悬停 / 选中 / 冲突 / 空置 / 放置目标高亮（PRD 3.5）。
交互：单击、双击、右键、拖出学生、接收座位或学生拖入、400ms 悬停信息卡。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QDrag, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from ..dnd import MIME_SEAT, MIME_STUDENT, decode_seat, decode_students, seat_mime
from ..style.theme import (
    Color,
    FONT_SEAT_NAME,
    FONT_SEAT_SID,
    TAG_STRIPE_WIDTH,
    seat_size,
)

HOVER_DELAY_MS = 400


class SeatHoverCard(QFrame):
    """鼠标悬停在座位上 400ms 后弹出的信息卡。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setObjectName("HoverCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(
            "QFrame#HoverCard { background: #FFFFFF; border: 1px solid %s; border-radius: 8px; }"
            "QLabel { background: transparent; }" % Color.BORDER
        )
        self._label = QLabel(self)
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(True)
        self._label.setMinimumWidth(200)
        self._label.setMaximumWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self._label)

    def set_html(self, html: str) -> None:
        self._label.setText(html)
        self.adjustSize()

    def popup_at(self, global_pos: QPoint) -> None:
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        self.adjustSize()
        x, y = global_pos.x() + 14, global_pos.y() + 14
        if screen is not None:
            available = screen.availableGeometry()
            if x + self.width() > available.right():
                x = max(available.left(), global_pos.x() - self.width() - 14)
            if y + self.height() > available.bottom():
                y = max(available.top(), available.bottom() - self.height())
        self.move(x, y)
        self.show()
        self.raise_()


def build_hover_html(
    student,
    seat_text: str,
    tag_colors: Optional[Dict[str, str]] = None,
    conflict_tip: str = "",
) -> str:
    """构造悬停信息卡的 HTML。"""
    tag_colors = tag_colors or {}
    rows: List[str] = []
    rows.append(
        '<div style="font-size:13px;font-weight:600;color:%s;">%s</div>' % (Color.TEXT_PRIMARY, _esc(student.name))
    )
    meta = ["学号 %s" % _esc(student.sid)]
    if student.gender:
        meta.append(_esc(student.gender))
    rows.append('<div style="color:%s;font-size:11px;">%s</div>' % (Color.TEXT_SECONDARY, " · ".join(meta)))
    rows.append('<div style="color:%s;font-size:11px;">%s</div>' % (Color.TEXT_DISABLED, _esc(seat_text)))
    if student.tags:
        chips = []
        for tag in student.tags:
            color = tag_colors.get(tag, Color.TAG_UNKNOWN)
            chips.append(
                '<span style="background:%s;color:#FFFFFF;border-radius:6px;padding:1px 6px;font-size:10px;">%s</span>'
                % (color, _esc(tag))
            )
        rows.append('<div style="margin-top:4px;">%s</div>' % " ".join(chips))
    if student.attrs:
        attrs = "　".join("%s：%g" % (_esc(k), v) for k, v in student.attrs.items())
        rows.append('<div style="color:%s;font-size:11px;margin-top:4px;">%s</div>' % (Color.TEXT_SECONDARY, attrs))
    if student.note:
        rows.append('<div style="color:%s;font-size:11px;margin-top:4px;">备注：%s</div>'
                    % (Color.TEXT_SECONDARY, _esc(student.note)))
    if conflict_tip:
        rows.append(
            '<div style="color:%s;font-size:11px;margin-top:6px;">⚠ %s</div>' % (Color.DANGER, _esc(conflict_tip))
        )
    return "".join(rows)


def _esc(text: Any) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class SeatWidget(QFrame):
    """一个座位。"""

    clicked = pyqtSignal(object, int)               # (seat, modifiers)
    double_clicked = pyqtSignal(object)             # (seat,)
    context_requested = pyqtSignal(object, object)  # (seat, global QPoint)
    seat_dropped = pyqtSignal(object, object)       # (src_seat, dst_seat)
    student_dropped = pyqtSignal(str, object)       # (sid, dst_seat)
    drag_started = pyqtSignal(object)               # (seat,)

    def __init__(self, seat, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._seat: Tuple[int, int, int] = (int(seat[0]), int(seat[1]), int(seat[2]))
        self._student = None
        self._tag_color = ""
        self._tag_colors: Dict[str, str] = {}
        self._group_name = ""
        self._card_size = "medium"
        self._width, self._height, self._radius = seat_size(self._card_size)
        self._show_sid = True
        self._disabled = False
        self._conflict = False
        self._conflict_tip = ""
        self._selected = False
        self._locked = False
        self._hover = False
        self._highlight = False
        self._press_pos = QPoint()

        self.setObjectName("SeatWidget")
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._apply_size()

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(HOVER_DELAY_MS)
        self._hover_timer.timeout.connect(self._show_hover_card)
        self._hover_card: Optional[SeatHoverCard] = None

    # ------------------------------------------------------------ 属性
    @property
    def seat(self) -> Tuple[int, int, int]:
        return self._seat

    def _apply_size(self) -> None:
        self.setFixedSize(QSize(self._width, self._height))

    # ------------------------------------------------------------ 配置
    def set_group_name(self, name: str) -> None:
        self._group_name = str(name or "")
        self.update()

    def set_card_size(self, size_name: str) -> None:
        self._card_size = size_name or "medium"
        self._width, self._height, self._radius = seat_size(self._card_size)
        self._apply_size()
        self.update()

    def set_show_sid(self, flag: bool) -> None:
        self._show_sid = bool(flag)
        self.update()

    def bind(self, student, tag_color: str = "", tag_colors: Optional[Dict[str, str]] = None) -> None:
        """更新座位显示的学生。``student=None`` 表示空座。"""
        self._student = student
        self._tag_color = tag_color or ""
        if tag_colors is not None:
            self._tag_colors = dict(tag_colors)
        elif student is not None and student.tags and tag_color:
            self._tag_colors = {student.tags[0]: tag_color}
        self.update()

    def set_disabled(self, flag: bool) -> None:
        self._disabled = bool(flag)
        if self._disabled:
            self.hide_hover_card()
        self.update()

    def set_conflict(self, flag: bool, tip: str = "") -> None:
        self._conflict = bool(flag)
        if tip:
            self._conflict_tip = str(tip)
        elif not flag:
            self._conflict_tip = ""
        self.update()

    def set_selected(self, flag: bool) -> None:
        self._selected = bool(flag)
        self.update()

    def set_highlight(self, flag: bool) -> None:
        self._highlight = bool(flag)
        self.update()

    def set_locked(self, flag: bool) -> None:
        """锁定座位（“锁定当前满意的座位再排位”）。"""
        self._locked = bool(flag)
        self.update()

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, float(self._radius), float(self._radius))

        # 背景
        if self._disabled:
            background = QColor(Color.SEAT_DISABLED)
        elif self._conflict:
            background = QColor(Color.SEAT_CONFLICT)
        elif self._selected:
            background = QColor(Color.SEAT_SELECTED)
        elif self._highlight or self._hover:
            background = QColor(Color.SEAT_HOVER)
        else:
            background = QColor(Color.SEAT_DEFAULT)
        painter.fillPath(path, background)

        # 左侧标签色条
        if self._tag_color and self._student is not None and not self._disabled:
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(
                QRect(int(rect.left()) - 1, int(rect.top()) - 1, TAG_STRIPE_WIDTH, int(rect.height()) + 2),
                QColor(self._tag_color),
            )
            painter.restore()

        # 边框
        if self._disabled:
            pen = QPen(QColor(Color.DASHED))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidth(1)
        elif self._conflict:
            pen = QPen(QColor(Color.DANGER))
            pen.setWidth(2)
        elif self._selected:
            pen = QPen(QColor(Color.PRIMARY))
            pen.setWidth(2)
        elif self._highlight:
            pen = QPen(QColor(Color.PRIMARY))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidth(2)
        elif self._hover:
            pen = QPen(QColor(Color.PRIMARY))
            pen.setWidth(1)
        else:
            pen = QPen(QColor(Color.BORDER))
            pen.setWidth(1)
        painter.setPen(pen)
        if pen.width() > 1:
            inner = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
            inner_path = QPainterPath()
            inner_path.addRoundedRect(inner, float(self._radius), float(self._radius))
            painter.drawPath(inner_path)
        else:
            painter.drawPath(path)

        # 文本
        text_rect = self.rect().adjusted(
            TAG_STRIPE_WIDTH + 4 if self._tag_color else 4, 2, -4, -2
        )
        if self._disabled:
            self._draw_text(painter, "空置", text_rect, Color.TEXT_DISABLED, FONT_SEAT_SID, center=True)
        elif self._student is not None:
            show_sid = self._show_sid and self._height >= 48
            name_rect = QRect(text_rect)
            sid_rect = QRect(text_rect)
            if show_sid:
                name_rect.setBottom(text_rect.center().y() + 1)
                sid_rect.setTop(text_rect.center().y() - 1)
            self._draw_text(painter, self._student.name, name_rect, Color.TEXT_PRIMARY,
                            FONT_SEAT_NAME, center=True, bold=True)
            if show_sid:
                self._draw_text(painter, self._student.sid_tail(4), sid_rect,
                                Color.TEXT_SECONDARY, FONT_SEAT_SID, center=True)

        # 冲突角标
        if self._conflict:
            painter.setPen(QColor(Color.DANGER))
            font = QFont()
            font.setPointSize(9)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                QRect(self.width() - 16, 1, 14, 14),
                int(Qt.AlignmentFlag.AlignCenter),
                "⚠",
            )
        # 锁定角标
        if self._locked:
            font = QFont()
            font.setPointSize(8)
            painter.setFont(font)
            painter.setPen(QColor(Color.PRIMARY))
            painter.drawText(QRect(2, 1, 14, 13), int(Qt.AlignmentFlag.AlignCenter), "🔒")
        painter.end()

    def _draw_text(
        self,
        painter: QPainter,
        text: str,
        rect: QRect,
        color: str,
        size: int,
        center: bool = True,
        bold: bool = False,
    ) -> None:
        font = QFont()
        font.setPixelSize(max(8, int(size)))
        font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(color))
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(str(text or ""), Qt.TextElideMode.ElideRight, max(10, rect.width()))
        align = int(Qt.AlignmentFlag.AlignCenter) if center else int(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        painter.drawText(rect, align, elided)

    # ------------------------------------------------------------ 鼠标
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self.clicked.emit(self._seat, int(event.modifiers().value))
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._seat)
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._student is None or self._disabled:
            return
        delta = (event.position().toPoint() - self._press_pos).manhattanLength()
        if delta < QApplication.startDragDistance():
            return
        self.hide_hover_card()
        drag = QDrag(self)
        drag.setMimeData(seat_mime(self._seat, self._student.sid, "seat"))
        drag.setPixmap(self.grab())
        drag.setHotSpot(event.position().toPoint())
        self.drag_started.emit(self._seat)
        drag.exec(Qt.DropAction.MoveAction)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.context_requested.emit(self._seat, event.globalPos())

    # ------------------------------------------------------------ 悬停
    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        if self._student is not None and not self._disabled:
            self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        self.hide_hover_card()
        super().leaveEvent(event)

    def hide_hover_card(self) -> None:
        self._hover_timer.stop()
        if self._hover_card is not None and self._hover_card.isVisible():
            self._hover_card.hide()

    def _show_hover_card(self) -> None:
        if self._student is None:
            return
        if self._hover_card is None:
            self._hover_card = SeatHoverCard()
        seat_text = "%s 第%d排 第%d列" % (
            self._group_name or "第 %d 组" % (self._seat[0] + 1),
            self._seat[1] + 1,
            self._seat[2] + 1,
        )
        self._hover_card.set_html(build_hover_html(self._student, seat_text, self._tag_colors, self._conflict_tip))
        self._hover_card.popup_at(self.mapToGlobal(QPoint(self.width(), 0)))

    # ------------------------------------------------------------ 拖放
    def _accepts(self, mime) -> bool:
        return mime is not None and (mime.hasFormat(MIME_SEAT) or mime.hasFormat(MIME_STUDENT))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()
            self.set_highlight(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._accepts(event.mimeData()):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.set_highlight(False)
        mime = event.mimeData()
        data = decode_seat(mime)
        if data:
            source = data.get("seat")
            if source is not None and tuple(source) != self._seat:
                self.seat_dropped.emit(tuple(source), self._seat)
            event.acceptProposedAction()
            return
        sids = decode_students(mime)
        if sids:
            self.student_dropped.emit(sids[0], self._seat)
            event.acceptProposedAction()
            return
        event.ignore()
