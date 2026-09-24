"""座位表容器：按 Layout 渲染多个分组 + 讲台，处理选区与冲突高亮。"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, Tuple

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QRubberBand,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...models.project import EV_ASSIGNMENT, EV_LAYOUT, EV_STUDENTS, EV_TAGS, Project
from ...utils.seat_key import make_key, try_parse_key
from ..style.theme import (
    FONT_PANEL_TITLE,
    GRID_MARGIN,
    GRID_SPACING,
    PODIUM_GAP,
    Color,
    aisle_width,
    seat_size,
)
from .podium_widget import PodiumWidget
from .seat_widget import SeatWidget

Coord = Tuple[int, int, int]


def _clear_layout(layout) -> None:
    """递归清空布局并销毁控件。"""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        child_layout = item.layout()
        if child_layout is not None:
            _clear_layout(child_layout)
            child_layout.deleteLater()
            continue
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


class GroupBox(QWidget):
    """一个分组的容器：标题 + 座位网格。"""

    def __init__(self, name: str, show_title: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.title_label = QLabel(name, self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(
            "color: %s; font-size: %dpx; font-weight: 500;" % (Color.TEXT_SECONDARY, FONT_PANEL_TITLE)
        )
        self.title_label.setVisible(show_title)
        self.grid = None
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(0, 0, 0, 0)
        self.layout_box.setSpacing(4)
        self.layout_box.addWidget(self.title_label)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class SeatGridView(QWidget):
    """座位表。中央区域由 QHBoxLayout 包裹每个分组的 QGridLayout 组成。"""

    seat_clicked = pyqtSignal(object, int)
    seat_double_clicked = pyqtSignal(object)
    seat_context_requested = pyqtSignal(object, object)
    seat_swap_requested = pyqtSignal(object, object)
    student_drop_requested = pyqtSignal(str, object)
    selection_changed = pyqtSignal(set)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._project: Optional[Project] = None
        self._seat_widgets: Dict[Coord, SeatWidget] = {}
        self._conflicts: Dict[str, str] = {}
        self._selected: Set[Coord] = set()
        self._locked: Set[Coord] = set()
        self._show_sid = True
        self._show_group_title = True
        self._selection_visible = True
        self._card_size = "medium"
        self._rubber_active = False
        self._rubber_origin = QPoint()
        self._rubber_additive = False

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._canvas = QWidget()
        self._canvas.setObjectName("Canvas")
        self._canvas.installEventFilter(self)
        self._scroll.setWidget(self._canvas)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)

        self._root = QVBoxLayout(self._canvas)
        self._root.setContentsMargins(GRID_MARGIN, GRID_MARGIN, GRID_MARGIN, GRID_MARGIN)
        self._root.setSpacing(0)

        self._rubber = QRubberBand(QRubberBand.Shape.Rectangle, self._canvas)
        self._rubber.setStyleSheet(
            "QRubberBand { border: 1px dashed %s; background: rgba(47,107,255,40); }" % Color.PRIMARY
        )

        self._podium_top: Optional[PodiumWidget] = None
        self._podium_bottom: Optional[PodiumWidget] = None

    # ------------------------------------------------------------ 项目
    def set_project(self, project: Optional[Project]) -> None:
        if self._project is not None:
            self._project.unsubscribe(self._on_project_event)
        self._project = project
        if project is not None:
            project.subscribe(self._on_project_event)
            self._show_sid = True
            self._card_size = project.layout.card_size
            self._show_group_title = project.layout.show_group_title
        self.rebuild()

    def _on_project_event(self, event: str, payload) -> None:
        if event == EV_LAYOUT:
            self.rebuild()
        elif event in (EV_ASSIGNMENT, EV_STUDENTS, EV_TAGS):
            self.refresh()
        elif event == "any":
            self.refresh()

    # ------------------------------------------------------------ 构建
    def rebuild(self) -> None:
        """按当前 layout 重建整张座位表。"""
        _clear_layout(self._root)
        self._seat_widgets.clear()
        self._podium_top = None
        self._podium_bottom = None
        project = self._project
        if project is None:
            return
        layout = project.layout
        self._show_group_title = layout.show_group_title
        self._card_size = layout.card_size

        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.addStretch(1)
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        center.addLayout(content)
        center.addStretch(1)

        if layout.podium_side == "top":
            self._podium_top = PodiumWidget()
            content.addWidget(self._podium_top)
            content.addSpacing(PODIUM_GAP)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for gi, group in enumerate(layout.groups):
            box = GroupBox(group.name, layout.show_group_title)
            grid = QVBoxLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(GRID_SPACING)
            from PyQt6.QtWidgets import QGridLayout

            inner = QGridLayout()
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(GRID_SPACING)
            for r in range(group.rows):
                for c in range(group.cols):
                    seat_widget = SeatWidget((gi, r, c))
                    seat_widget.set_card_size(self._card_size)
                    seat_widget.set_show_sid(self._show_sid)
                    seat_widget.set_group_name(group.name)
                    seat_widget.clicked.connect(self._on_seat_clicked)
                    seat_widget.double_clicked.connect(self.seat_double_clicked.emit)
                    seat_widget.context_requested.connect(self.seat_context_requested.emit)
                    seat_widget.seat_dropped.connect(self._on_seat_dropped)
                    seat_widget.student_dropped.connect(self._on_student_dropped)
                    inner.addWidget(seat_widget, r, c)
                    self._seat_widgets[(gi, r, c)] = seat_widget
            grid.addLayout(inner)
            box.layout_box.addLayout(grid)
            row.addWidget(box)
            if gi < len(layout.groups) - 1:
                row.addSpacing(aisle_width(group.gap_after))
        content.addLayout(row)

        if layout.podium_side == "bottom":
            content.addSpacing(PODIUM_GAP)
            self._podium_bottom = PodiumWidget()
            content.addWidget(self._podium_bottom)

        self._root.addLayout(center)
        self._root.addStretch(1)
        self.refresh()

    # ------------------------------------------------------------ 刷新
    def refresh(self, seats: Optional[Iterable] = None) -> None:
        """刷新座位显示；``seats`` 为 None 时刷新全部（局部刷新用）。"""
        project = self._project
        if project is None:
            return
        if seats is None:
            targets: List[Coord] = list(self._seat_widgets.keys())
        else:
            targets = []
            for item in seats:
                coord = item if isinstance(item, tuple) and len(item) == 3 else try_parse_key(item)
                if coord is not None:
                    targets.append((int(coord[0]), int(coord[1]), int(coord[2])))

        tag_color_cache: Dict[str, str] = {}
        for seat in targets:
            widget = self._seat_widgets.get(seat)
            if widget is None:
                continue
            key = make_key(seat)
            sid = project.assignment.get(key, "")
            student = project.get_student(sid) if sid else None
            tag_color = ""
            tag_colors: Dict[str, str] = {}
            if student is not None and student.tags:
                for tag in student.tags:
                    if tag not in tag_color_cache:
                        tag_color_cache[tag] = project.tag_color(tag)
                    tag_colors[tag] = tag_color_cache[tag]
                tag_color = tag_colors[student.tags[0]]
            widget.bind(student, tag_color, tag_colors)
            widget.set_disabled(project.layout.is_disabled(seat))
            tip = self._conflicts.get(key, "")
            widget.set_conflict(bool(tip), tip)
            widget.set_selected(self._selection_visible and seat in self._selected)
            widget.set_locked(seat in self._locked)

    def set_show_sid(self, flag: bool) -> None:
        self._show_sid = bool(flag)
        for widget in self._seat_widgets.values():
            widget.set_show_sid(self._show_sid)

    def set_show_group_title(self, flag: bool) -> None:
        self._show_group_title = bool(flag)
        for box in self._canvas.findChildren(GroupBox):
            box.title_label.setVisible(self._show_group_title)

    def set_card_size(self, size_name: str) -> None:
        self._card_size = size_name or "medium"
        for widget in self._seat_widgets.values():
            widget.set_card_size(self._card_size)

    def set_conflicts(self, mapping: Dict[str, str]) -> None:
        """设置冲突座位映射 ``{seat_key: 文案}``。"""
        self._conflicts = dict(mapping or {})
        self.refresh()

    def set_selection_visible(self, flag: bool) -> None:
        self._selection_visible = bool(flag)
        self._apply_selection_style()

    # ------------------------------------------------------------ 锁定
    def set_locked_seats(self, seats: Iterable) -> None:
        """设置被锁定的座位（排位时保持不动）。"""
        result: Set[Coord] = set()
        for item in seats or []:
            coord = item if isinstance(item, tuple) and len(item) == 3 else try_parse_key(item)
            if coord is not None:
                result.add((int(coord[0]), int(coord[1]), int(coord[2])))
        self._locked = result
        self.refresh()

    def locked_seats(self) -> Set[Coord]:
        return set(self._locked)

    # ------------------------------------------------------------ 选区
    def selected_seats(self) -> Set[Coord]:
        return set(self._selected)

    def set_selected(self, seats: Iterable) -> None:
        result: Set[Coord] = set()
        for item in seats or []:
            coord = item if isinstance(item, tuple) and len(item) == 3 else try_parse_key(item)
            if coord is not None:
                result.add((int(coord[0]), int(coord[1]), int(coord[2])))
        self._selected = result
        self._apply_selection_style()
        self.selection_changed.emit(self.selected_seats())

    def select_all(self) -> None:
        self.set_selected(self._seat_widgets.keys())

    def clear_selection(self) -> None:
        self.set_selected([])

    def toggle_seat(self, seat) -> None:
        coord = seat if isinstance(seat, tuple) else try_parse_key(seat)
        if coord is None:
            return
        coord = (int(coord[0]), int(coord[1]), int(coord[2]))
        selection = set(self._selected)
        if coord in selection:
            selection.discard(coord)
        else:
            selection.add(coord)
        self.set_selected(selection)

    def _apply_selection_style(self) -> None:
        for seat, widget in self._seat_widgets.items():
            widget.set_selected(self._selection_visible and seat in self._selected)

    # ------------------------------------------------------------ 查询
    def widget_at(self, seat) -> Optional[SeatWidget]:
        coord = seat if isinstance(seat, tuple) else try_parse_key(seat)
        if coord is None:
            return None
        return self._seat_widgets.get((int(coord[0]), int(coord[1]), int(coord[2])))

    def seat_at_pos(self, pos: QPoint) -> Optional[Coord]:
        """按坐标（相对座位表控件）查找座位。"""
        canvas_pos = self._canvas.mapFrom(self, pos)
        for seat, widget in self._seat_widgets.items():
            top_left = widget.mapTo(self._canvas, QPoint(0, 0))
            if QRect(top_left, widget.size()).contains(canvas_pos):
                return seat
        return None

    def seat_count(self) -> int:
        return len(self._seat_widgets)

    # ------------------------------------------------------------ 交互
    def _on_seat_clicked(self, seat, modifiers: int) -> None:
        ctrl = bool(modifiers & int(Qt.KeyboardModifier.ControlModifier.value))
        shift = bool(modifiers & int(Qt.KeyboardModifier.ShiftModifier.value))
        if ctrl or shift:
            self.toggle_seat(seat)
        else:
            self.set_selected([seat])
        self.seat_clicked.emit(seat, modifiers)

    def _on_seat_dropped(self, source, target) -> None:
        self.seat_swap_requested.emit(tuple(source), tuple(target))

    def _on_student_dropped(self, sid: str, seat) -> None:
        self.student_drop_requested.emit(str(sid), tuple(seat))

    # ------------------------------------------------------------ 框选
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._canvas:
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._rubber_active = True
                self._rubber_origin = event.position().toPoint()
                self._rubber_additive = bool(
                    event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    or event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                )
                self._rubber.setGeometry(QRect(self._rubber_origin, QSize()))
                self._rubber.show()
                if not self._rubber_additive:
                    self.set_selected([])
                return True
            if etype == QEvent.Type.MouseMove and self._rubber_active:
                rect = QRect(self._rubber_origin, event.position().toPoint()).normalized()
                self._rubber.setGeometry(rect)
                self._apply_rubber(rect)
                return True
            if etype == QEvent.Type.MouseButtonRelease and self._rubber_active:
                self._rubber_active = False
                self._rubber.hide()
                return True
        return super().eventFilter(obj, event)

    def _apply_rubber(self, rect: QRect) -> None:
        selection = set(self._selected) if self._rubber_additive else set()
        for seat, widget in self._seat_widgets.items():
            top_left = widget.mapTo(self._canvas, QPoint(0, 0))
            if rect.intersects(QRect(top_left, widget.size())):
                selection.add(seat)
        self.set_selected(selection)

    # ------------------------------------------------------------ 尺寸
    def sizeHint(self) -> QSize:  # noqa: N802
        project = self._project
        if project is None or not project.layout.groups:
            return QSize(480, 320)
        width, height, _ = seat_size(self._card_size)
        layout = project.layout
        rows = max([g.rows for g in layout.groups], default=1)
        cols = sum(g.cols for g in layout.groups) + sum(
            max(1, g.gap_after) for g in layout.groups[:-1]
        )
        return QSize(
            cols * (width + GRID_SPACING) + GRID_MARGIN * 2 + 40,
            rows * (height + GRID_SPACING) + GRID_MARGIN * 2 + 160,
        )
