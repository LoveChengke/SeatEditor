"""学生名单表格：QAbstractTableModel + QTableView。

列：学号 / 姓名 / 性别 / 标签 / 数值属性 / 已分配座位。
支持点击列头排序（学号自然序、姓名拼音）、多选、把学生拖到座位表。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPoint,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QDrag
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from ...models.project import EV_ASSIGNMENT, EV_STUDENTS, EV_TAGS, Project
from ...models.student import Student
from ..dnd import student_mime
from ..style.theme import Color

COLUMNS = ["学号", "姓名", "性别", "标签", "数值属性", "已分配座位"]
COL_SID, COL_NAME, COL_GENDER, COL_TAGS, COL_ATTRS, COL_SEAT = range(6)

# 列 -> 排序键（与 StudentService.sort_key 对应）
SORT_KEYS = {
    COL_SID: "sid",
    COL_NAME: "name",
    COL_GENDER: "gender",
    COL_TAGS: "tags",
    COL_ATTRS: "attrs",
    COL_SEAT: "assigned",
}


class StudentTableModel(QAbstractTableModel):
    """学生名单模型。"""

    def __init__(self, project: Project, service=None, parent=None) -> None:
        super().__init__(parent)
        self._project = project
        self._service = service
        self._students: List[Student] = []
        self._sort_column = COL_SID
        self._sort_order = Qt.SortOrder.AscendingOrder
        if project is not None:
            project.subscribe(self._on_project_event)

    # ------------------------------------------------------------ 项目
    def _on_project_event(self, event: str, payload) -> None:
        if event in (EV_ASSIGNMENT, EV_STUDENTS, EV_TAGS, "any"):
            self.refresh()

    # ------------------------------------------------------------ 行数据
    def set_students(self, students: Sequence[Student]) -> None:
        self.beginResetModel()
        self._students = list(students or [])
        self._apply_sort()
        self.endResetModel()

    def student_at(self, row: int) -> Optional[Student]:
        if 0 <= row < len(self._students):
            return self._students[row]
        return None

    def row_of_sid(self, sid: str) -> int:
        for row, student in enumerate(self._students):
            if student.sid == sid:
                return row
        return -1

    def refresh(self) -> None:
        """数据变化后重画（不改变过滤结果的行集合）。"""
        if self._students:
            top = self.index(0, 0)
            bottom = self.index(len(self._students) - 1, len(COLUMNS) - 1)
            self.dataChanged.emit(top, bottom)
        if self._service is not None and self._students:
            self._apply_sort()
            self.layoutChanged.emit()

    def _apply_sort(self) -> None:
        if self._service is None or not self._students:
            return
        key = SORT_KEYS.get(self._sort_column, "sid")
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder
        self._students = self._service.sorted_students(self._students, key, reverse)

    # ------------------------------------------------------------ Qt 接口
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._students)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section] if 0 <= section < len(COLUMNS) else ""
        if role == Qt.ItemDataRole.ToolTipRole and section == COL_SEAT:
            return "该学生当前所在的座位"
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        student = self.student_at(index.row())
        if student is None:
            return None
        column = index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if role == Qt.ItemDataRole.ToolTipRole:
                return self._tooltip(student)
            return self._text(student, column)
        if role == Qt.ItemDataRole.UserRole:
            return student.sid
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (COL_GENDER, COL_SEAT):
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and column == COL_SEAT:
            seat = self._seat_text(student)
            if not seat:
                return QColor(Color.TEXT_DISABLED)
            return QColor(self._seat_color(student))
        return None

    def _tooltip(self, student: Student) -> str:
        parts = ["%s（%s）" % (student.name, student.sid)]
        if student.gender:
            parts.append("性别：%s" % student.gender)
        if student.tags:
            parts.append("标签：%s" % "、".join(student.tags))
        if student.attrs:
            parts.append("属性：" + "，".join("%s=%g" % (k, v) for k, v in student.attrs.items()))
        if student.note:
            parts.append("备注：%s" % student.note)
        seat = self._seat_text(student)
        if seat:
            parts.append("座位：%s" % seat)
        return "\n".join(parts)

    def _text(self, student: Student, column: int) -> str:
        if column == COL_SID:
            return student.sid
        if column == COL_NAME:
            return student.name
        if column == COL_GENDER:
            return student.gender or "—"
        if column == COL_TAGS:
            return "、".join(student.tags) if student.tags else "—"
        if column == COL_ATTRS:
            if not student.attrs:
                return "—"
            return "　".join("%s %g" % (k, v) for k, v in student.attrs.items())
        if column == COL_SEAT:
            return self._seat_text(student) or "未分配"
        return ""

    def _seat_text(self, student: Student) -> str:
        project = self._project
        if project is None:
            return ""
        key = None
        for seat_key, sid in project.assignment.items():
            if sid == student.sid:
                key = seat_key
                break
        if key is None:
            return ""
        from ...utils.seat_key import try_parse_key

        coord = try_parse_key(key)
        if coord is None:
            return ""
        g, r, c = coord
        return "%s 第%d排 第%d列" % (project.layout.group_name(g), r + 1, c + 1)

    def _seat_color(self, student: Student) -> str:
        project = self._project
        if project is None or not student.tags:
            return Color.TEXT_SECONDARY
        return project.tag_color(student.tags[0])

    # ------------------------------------------------------------ 排序
    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self._sort_column = int(column)
        self._sort_order = order
        self.beginResetModel()
        self._apply_sort()
        self.endResetModel()

    def sid_list(self) -> List[str]:
        return [s.sid for s in self._students]


class StudentTableView(QTableView):
    """支持多选与拖拽的名单表格。"""

    context_menu_requested = pyqtSignal(QPoint)
    double_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setWordWrap(False)
        self.setShowGrid(False)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu_requested.emit)
        self.doubleClicked.connect(self._on_double_clicked)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(26)
        # 注意：QHeaderView 在还没有 model 时按列设置 resizeMode 会导致 Qt 崩溃，
        # 因此列宽/列模式统一放到 setModel 之后再配置。
        self.horizontalHeader().setStretchLastSection(True)

    # ------------------------------------------------------------ 模型
    def setModel(self, model) -> None:  # noqa: N802 - Qt 命名
        super().setModel(model)
        self._configure_header()

    def _configure_header(self) -> None:
        header = self.horizontalHeader()
        if header is None or header.count() < len(COLUMNS):
            return
        for column, mode in (
            (COL_SID, QHeaderView.ResizeMode.Interactive),
            (COL_NAME, QHeaderView.ResizeMode.Interactive),
            (COL_GENDER, QHeaderView.ResizeMode.ResizeToContents),
            (COL_TAGS, QHeaderView.ResizeMode.Interactive),
            (COL_ATTRS, QHeaderView.ResizeMode.Interactive),
            (COL_SEAT, QHeaderView.ResizeMode.Stretch),
        ):
            header.setSectionResizeMode(column, mode)
        self.setColumnWidth(COL_SID, 78)
        self.setColumnWidth(COL_NAME, 76)
        self.setColumnWidth(COL_TAGS, 110)
        self.setColumnWidth(COL_ATTRS, 120)

    # ------------------------------------------------------------ 拖拽
    def selected_sids(self) -> List[str]:
        model = self.model()
        if model is None:
            return []
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        if not rows:
            rows = sorted({index.row() for index in self.selectionModel().selectedIndexes()})
        result: List[str] = []
        for row in rows:
            student = model.student_at(row) if hasattr(model, "student_at") else None
            if student is not None:
                result.append(student.sid)
        return result

    def startDrag(self, supported_actions) -> None:  # noqa: N802
        sids = self.selected_sids()
        if not sids:
            return
        drag = QDrag(self)
        drag.setMimeData(student_mime(sids))
        pixmap = self.viewport().grab(self.viewport().rect())
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(12, 12))
        drag.exec(Qt.DropAction.CopyAction)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        model = self.model()
        student = model.student_at(index.row()) if hasattr(model, "student_at") else None
        if student is not None:
            self.double_clicked.emit(student.sid)

    # ------------------------------------------------------------ 便捷
    def select_sid(self, sid: str) -> None:
        model = self.model()
        if model is None or not hasattr(model, "row_of_sid"):
            return
        row = model.row_of_sid(sid)
        if row < 0:
            return
        index = model.index(row, COL_NAME)
        self.selectionModel().select(
            index,
            self.selectionModel().SelectionFlag.ClearAndSelect
            | self.selectionModel().SelectionFlag.Rows,
        )
        self.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def reselect(self, sids: Sequence[str]) -> None:
        model = self.model()
        if model is None or not hasattr(model, "row_of_sid"):
            return
        selection_model = self.selectionModel()
        selection_model.clearSelection()
        for sid in sids:
            row = model.row_of_sid(sid)
            if row < 0:
                continue
            index = model.index(row, COL_NAME)
            selection_model.select(
                index,
                selection_model.SelectionFlag.Select | selection_model.SelectionFlag.Rows,
            )
