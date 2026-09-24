"""选区面板：选区列表（名称 + 座位数 + 颜色块）、用座位表框选创建选区、
重命名 / 删除 / 应用高亮、批量操作（清空 / 设为空置 / 批量分配）与
常用快捷选区（按分组 / 按行范围 / 按列范围）。

面板不直接修改项目，全部通过信号交给主窗口落库。
"""

from __future__ import annotations

from typing import Optional, Set

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QVBoxLayout, QWidget,
)

from ..common import button, confirm, hline, warn
from .base import ProjectPanel
from ...models.project import EV_ANY, EV_SELECTIONS, Project
from ...utils.seat_key import Seat as Coord
from ..style.theme import PANEL_RULE_WIDTH, Color


def _color_icon(color: str) -> QIcon:
    """选区颜色块。"""
    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(color or Color.PRIMARY))
    return QIcon(pixmap)


class SelectionPanel(ProjectPanel):
    """座位选区面板。"""

    apply_requested = pyqtSignal(str)         # selection id：高亮该选区
    batch_clear_requested = pyqtSignal(set)   # set[Coord]
    batch_disable_requested = pyqtSignal(set)
    batch_assign_requested = pyqtSignal(set)
    selection_created = pyqtSignal(str, set)  # name, seats
    selection_deleted = pyqtSignal(str)
    selection_renamed = pyqtSignal(str, str)  # id, new name

    def __init__(self, project: Project, parent: Optional[QWidget] = None) -> None:
        super().__init__(project, parent)
        self._current_seats: Set[Coord] = set()

        self.setObjectName("Panel")
        self.setMinimumWidth(max(220, PANEL_RULE_WIDTH - 60))

        self._build_ui()
        self.refresh()
        project.subscribe(self._on_project_event)

    # 构建界面
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel("座位选区")
        title.setObjectName("PanelTitle")
        root.addWidget(title)

        self._hint_label = QLabel("座位表当前选中 0 个座位")
        self._hint_label.setObjectName("Hint")
        self._hint_label.setWordWrap(True)
        root.addWidget(self._hint_label)

        self._list = QListWidget(self)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setMinimumHeight(120)
        self._list.itemDoubleClicked.connect(lambda _item: self._apply_current())
        root.addWidget(self._list, 1)
        root.addWidget(hline())

        grid = QGridLayout()
        grid.setSpacing(6)
        grid.addWidget(
            button("用当前选中座位新建选区", self._create_from_seats, "Primary", "把座位表当前框选保存为选区"),
            0, 0, 1, 2,
        )
        grid.addWidget(button("应用高亮", self._apply_current, tooltip="在座位表上高亮该选区"), 1, 0)
        grid.addWidget(button("重命名", self._rename_current), 1, 1)
        grid.addWidget(button("删除", self._delete_current, "Danger", "删除该选区"), 2, 0)
        grid.addWidget(button("清空座位", self._batch_clear, tooltip="清空当前选中座位上的学生"), 2, 1)
        grid.addWidget(button("设为空置", self._batch_disable, tooltip="当前选中座位不参与排位"), 3, 0)
        grid.addWidget(button("批量分配", self._batch_assign, tooltip="把未分配学生依次放入这些座位"), 3, 1)
        root.addLayout(grid)

        quick_hint = QLabel("快捷选区")
        quick_hint.setObjectName("Hint")
        root.addWidget(quick_hint)
        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)
        quick_row.addWidget(button("按分组", self._quick_by_group, "Ghost"))
        quick_row.addWidget(button("按行范围", self._quick_by_row, "Ghost"))
        quick_row.addWidget(button("按列范围", self._quick_by_col, "Ghost"))
        root.addLayout(quick_row)

    # 对外接口
    def _on_project_change(self, project: Project, service=None) -> None:
        self._current_seats = set()

    def refresh(self) -> None:
        """按 ``project.selections`` 重建选区列表。"""
        if self._project is None:
            return
        current_id = self._current_id()
        self._list.clear()
        try:
            for selection in self._project.selections:
                item = QListWidgetItem(_color_icon(selection.color), "%s · %d 座" % (selection.name, len(selection.seats)))
                item.setData(Qt.ItemDataRole.UserRole, selection.id)
                item.setToolTip("%s\n共 %d 个座位" % (selection.name, len(selection.seats)))
                self._list.addItem(item)
        except Exception as exc:  # 刷新失败不应崩溃
            QMessageBox.warning(self, "提示", "选区列表刷新失败：%s" % exc)
        if current_id:
            self._select_id(current_id)
        self._update_hint()

    def set_current_seats(self, seats: set) -> None:
        """记录座位表当前选中的座位（供「新建选区」与批量操作使用）。"""
        result: Set[Coord] = set()
        for seat in seats or ():
            try:
                g, r, c = seat
                result.add((int(g), int(r), int(c)))
            except (TypeError, ValueError):
                continue
        self._current_seats = result
        self._update_hint()

    # 选中项
    def _current_id(self) -> str:
        item = self._list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else ""

    def _select_id(self, selection_id: str) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole)) == selection_id:
                self._list.setCurrentItem(item)
                return

    def _current_selection(self):
        selection_id = self._current_id()
        if not selection_id or self._project is None:
            return None
        return self._project.get_selection(selection_id)

    def _update_hint(self) -> None:
        count = len(self._current_seats)
        if count:
            self._hint_label.setText("座位表当前选中 %d 个座位" % count)
        else:
            self._hint_label.setText("座位表当前选中 0 个座位（可先框选座位）")

    # 选区操作
    def _create_from_seats(self) -> None:
        seats = self._require_seats()
        if seats is None:
            return
        total = len(self._project.selections) if self._project is not None else 0
        name, ok = QInputDialog.getText(
            self, "新建选区", "选区名称：", QLineEdit.EchoMode.Normal, "选区 %d" % (total + 1)
        )
        if not ok or not str(name).strip():
            return
        self.selection_created.emit(str(name).strip(), set(seats))

    def _apply_current(self) -> None:
        selection = self._current_selection()
        if selection is None:
            self._warn("请先在上方列表中选择一个选区。")
            return
        self.apply_requested.emit(selection.id)

    def _rename_current(self) -> None:
        selection = self._current_selection()
        if selection is None:
            self._warn("请先在上方列表中选择一个选区。")
            return
        name, ok = QInputDialog.getText(
            self, "重命名选区", "新的选区名称：", QLineEdit.EchoMode.Normal, selection.name
        )
        if not ok or not str(name).strip():
            return
        new_name = str(name).strip()
        if new_name == selection.name:
            return
        self.selection_renamed.emit(selection.id, new_name)

    def _delete_current(self) -> None:
        selection = self._current_selection()
        if selection is None:
            self._warn("请先在上方列表中选择一个选区。")
            return
        if not self._confirm("确定删除选区「%s」吗？" % selection.name, "删除选区"):
            return
        self.selection_deleted.emit(selection.id)

    # 批量操作
    def _require_seats(self) -> Optional[Set[Coord]]:
        if not self._current_seats:
            self._warn("请先在座位表中选择座位（框选或 Ctrl + 点击）。")
            return None
        return set(self._current_seats)

    def _batch_clear(self) -> None:
        seats = self._require_seats()
        if seats is None:
            return
        if not self._confirm("确定清空选中的 %d 个座位吗？" % len(seats), "清空座位"):
            return
        self.batch_clear_requested.emit(seats)

    def _batch_disable(self) -> None:
        seats = self._require_seats()
        if seats is None:
            return
        self.batch_disable_requested.emit(seats)

    def _batch_assign(self) -> None:
        seats = self._require_seats()
        if seats is None:
            return
        self.batch_assign_requested.emit(seats)

    # 快捷选区
    def _quick_by_group(self) -> None:
        layout = self._project.layout if self._project is not None else None
        if layout is None or layout.group_count <= 0:
            self._warn("当前布局没有分组，请先在「布局」中配置教室。")
            return
        names = [layout.group_name(index) for index in range(layout.group_count)]
        name, ok = QInputDialog.getItem(self, "按分组新建选区", "选择分组：", names, 0, False)
        if not ok or not name:
            return
        index = names.index(name)
        self.selection_created.emit(name, set(layout.seats_in_group(index)))

    def _quick_by_row(self) -> None:
        layout = self._project.layout if self._project is not None else None
        max_rows = max([group.rows for group in layout.groups], default=0) if layout is not None else 0
        if max_rows <= 0:
            self._warn("当前布局没有可用座位。")
            return
        start, ok = QInputDialog.getInt(self, "按行范围新建选区", "起始排（从 1 开始）：", 1, 1, max_rows, 1)
        if not ok:
            return
        end, ok = QInputDialog.getInt(
            self, "按行范围新建选区", "结束排：", min(start + 1, max_rows), 1, max_rows, 1
        )
        if not ok:
            return
        low, high = min(start, end) - 1, max(start, end) - 1
        seats = set(layout.row_range(low, high))
        self._ask_name_and_create(seats, "第 %d–%d 排" % (low + 1, high + 1))

    def _quick_by_col(self) -> None:
        layout = self._project.layout if self._project is not None else None
        max_cols = max([group.cols for group in layout.groups], default=0) if layout is not None else 0
        if max_cols <= 0:
            self._warn("当前布局没有可用座位。")
            return
        start, ok = QInputDialog.getInt(self, "按列范围新建选区", "起始列（从 1 开始）：", 1, 1, max_cols, 1)
        if not ok:
            return
        end, ok = QInputDialog.getInt(
            self, "按列范围新建选区", "结束列：", min(start + 1, max_cols), 1, max_cols, 1
        )
        if not ok:
            return
        low, high = min(start, end) - 1, max(start, end) - 1
        seats = set(layout.col_range(low, high))
        self._ask_name_and_create(seats, "第 %d–%d 列" % (low + 1, high + 1))

    def _ask_name_and_create(self, seats: Set[Coord], default_name: str) -> None:
        if not seats:
            self._warn("该范围内没有座位。")
            return
        name, ok = QInputDialog.getText(
            self, "命名选区", "选区名称：", QLineEdit.EchoMode.Normal, default_name
        )
        if not ok or not str(name).strip():
            return
        self.selection_created.emit(str(name).strip(), set(seats))

    # 项目事件
    def _on_project_event(self, event: str, _payload) -> None:
        if event not in (EV_SELECTIONS, EV_ANY):
            return
        self._schedule_refresh()

    # 工具
    def _confirm(self, text: str, title: str) -> bool:
        return confirm(self, text, title)

    def _warn(self, text: str, title: str = "提示") -> None:
        warn(self, text, title)
