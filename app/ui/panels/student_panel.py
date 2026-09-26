"""学生名单面板：实时搜索、标签多选筛选（交集 / 并集）、性别与分配状态筛选、
学生表格（多选 + 可拖到座位表）、人数统计与底部操作按钮。

面板只**读取** :class:`Project`，所有写操作都通过信号交给主窗口执行。
"""

from __future__ import annotations

from typing import List, Optional, Set

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QRadioButton, QToolButton,
    QVBoxLayout, QWidget, QWidgetAction,
)

from ..common import button, confirm, hline, warn
from .base import ProjectPanel
from ..dnd import MIME_SEAT, decode_seat
from ...models.project import EV_ANY, EV_ASSIGNMENT, EV_STUDENTS, EV_TAGS, Project
from ...services.student_service import (
    ASSIGN_ALL, ASSIGN_ASSIGNED, ASSIGN_UNASSIGNED, TAG_MODE_ALL, TAG_MODE_ANY,
    StudentFilter, StudentService,
)
from ..style.theme import PANEL_STUDENT_WIDTH
from ..widgets.student_table import StudentTableModel, StudentTableView
from ...utils.seat_key import make_key

SEARCH_DEBOUNCE_MS = 150


class StudentPanel(ProjectPanel):
    """学生名单面板。"""

    selection_changed = pyqtSignal(list)      # 选中的 sid 列表
    import_requested = pyqtSignal()           # Excel 导入（主窗口走文件对话框）
    add_requested = pyqtSignal()
    edit_requested = pyqtSignal(str)          # sid
    delete_requested = pyqtSignal(list)       # sids
    tag_requested = pyqtSignal(list)          # sids
    export_requested = pyqtSignal()
    template_requested = pyqtSignal()         # 下载 Excel 名单导入模板
    clear_seat_requested = pyqtSignal(str)    # 座位 key：把座位上的学生拖回名单（取消入座）
    # 契约之外的补充信号：面板自带对话框的结果 / 右键清空座位
    students_imported = pyqtSignal(list)      # 文本导入对话框返回的学生列表
    clear_seats_requested = pyqtSignal(list)  # sids

    def __init__(self, project: Project, parent: Optional[QWidget] = None) -> None:
        super().__init__(project, parent)
        self._service = StudentService(project)
        self._model = StudentTableModel(project, self._service, self)
        self._selected_sids: List[str] = []
        self._checked_tags: Set[str] = set()
        self._updating = False
        self._tag_populating = False

        self.setObjectName("SidePanel")
        self.setMinimumWidth(max(240, PANEL_STUDENT_WIDTH - 60))
        self.setAcceptDrops(True)          # 支持把座位上的学生拖回名单

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._apply_filter)

        self._build_ui()
        self.refresh()
        project.subscribe(self._on_project_event)

    # 构建界面
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # 不再重复画标题：停靠面板自带的标题栏已经写着「学生名单」，
        # 两行同样的字叠在一起只会显得杂乱。
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索学号 / 姓名 / 标签")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        root.addWidget(self._search)

        # ---- 标签筛选 + 交集 / 并集
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        self._tag_button = QToolButton()
        self._tag_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._tag_button.setText("标签筛选")
        self._tag_button.setToolTip("多选标签；配合右侧交集 / 并集使用")
        self._tag_menu = self._build_tag_menu()
        self._tag_button.setMenu(self._tag_menu)
        filter_row.addWidget(self._tag_button, 1)

        self._union_radio = QRadioButton("并集")
        self._union_radio.setToolTip("至少命中一个已勾选标签")
        self._inter_radio = QRadioButton("交集")
        self._inter_radio.setToolTip("必须命中全部已勾选标签")
        self._union_radio.setChecked(True)
        self._tag_mode_group = QButtonGroup(self)
        self._tag_mode_group.addButton(self._union_radio)
        self._tag_mode_group.addButton(self._inter_radio)
        self._union_radio.toggled.connect(lambda _checked: self._apply_filter())
        filter_row.addWidget(self._union_radio)
        filter_row.addWidget(self._inter_radio)
        root.addLayout(filter_row)

        # ---- 性别 / 分配状态
        state_row = QHBoxLayout()
        state_row.setSpacing(6)
        self._gender_combo = QComboBox()
        self._gender_combo.addItem("全部性别", "")
        self._gender_combo.addItem("男", "男")
        self._gender_combo.addItem("女", "女")
        self._gender_combo.currentIndexChanged.connect(lambda _index: self._apply_filter())
        state_row.addWidget(self._gender_combo, 1)

        self._assign_combo = QComboBox()
        self._assign_combo.addItem("全部分配状态", ASSIGN_ALL)
        self._assign_combo.addItem("已分配", ASSIGN_ASSIGNED)
        self._assign_combo.addItem("未分配", ASSIGN_UNASSIGNED)
        self._assign_combo.currentIndexChanged.connect(lambda _index: self._apply_filter())
        state_row.addWidget(self._assign_combo, 1)
        root.addLayout(state_row)

        # ---- 表格
        self._view = StudentTableView(self)
        self._view.setModel(self._model)
        self._view.setMinimumHeight(150)
        self._view.double_clicked.connect(self._on_double_clicked)
        self._view.context_menu_requested.connect(self._on_context_menu)
        self._view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._view, 1)

        self._stats_label = QLabel("共 0 人 · 已分配 0")
        self._stats_label.setObjectName("Hint")
        root.addWidget(self._stats_label)
        root.addWidget(hline())

        # ---- 底部按钮：只留主流程用得到的动作，其余收进「更多」
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.addWidget(
            button("导入 Excel 名单", self.import_requested.emit, "Primary",
                   "从 Excel 导入名单（Ctrl+I）"),
            0, 0, 1, 2,
        )
        grid.addWidget(button("添加", self.add_requested.emit, tooltip="手动添加一名学生"), 1, 0)
        grid.addWidget(button("编辑", self._on_edit, tooltip="编辑选中学生（双击表格亦可）"), 1, 1)
        grid.addWidget(button("删除", self._on_delete, "Danger", "删除选中的学生"), 2, 0)
        grid.addWidget(button("批量标签", self._on_tag, tooltip="给选中学生批量添加 / 移除标签"), 2, 1)

        # 用 QPushButton + 菜单（而不是 QToolButton）：跟上面几个按钮同一套 QSS，
        # 高度 / 内边距完全一致，倒三角也不会压在文字上。
        self._more_button = button("更多名单操作", None, "MenuButton",
                                   "粘贴文本导入 / 导出名单 / 名单模板")
        more_menu = QMenu(self)
        more_menu.addAction("粘贴文本导入…", self._on_text_import)
        more_menu.addAction("导出当前名单…",
                            lambda _checked=False: self.export_requested.emit())
        more_menu.addAction("下载名单导入模板…",
                            lambda _checked=False: self.template_requested.emit())
        self._more_button.setMenu(more_menu)
        grid.addWidget(self._more_button, 3, 0, 1, 2)
        root.addLayout(grid)

        self._view.seat_drop_requested.connect(self.clear_seat_requested.emit)

    def _build_tag_menu(self) -> QMenu:
        menu = QMenu(self)
        holder = QWidget(menu)
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(4, 4, 4, 4)
        holder_layout.setSpacing(2)
        self._tag_list = QListWidget(holder)
        self._tag_list.setMinimumWidth(180)
        self._tag_list.setMaximumHeight(200)
        self._tag_list.itemChanged.connect(self._on_tag_item_changed)
        holder_layout.addWidget(self._tag_list)
        action = QWidgetAction(menu)
        action.setDefaultWidget(holder)
        menu.addAction(action)
        menu.addSeparator()
        clear_action = menu.addAction("清除全部勾选")
        clear_action.triggered.connect(self._clear_tag_checks)
        return menu

    # 对外接口
    def _on_project_change(self, project: Project,
                           service: Optional[StudentService] = None) -> None:
        """重建表格模型；旧模型也要退订旧项目，否则两套数据会互相刷新。"""
        old_project, old_model = self._project, self._model
        if old_project is not None:
            try:
                old_project.unsubscribe(old_model._on_project_event)
            except Exception:
                pass
        self._service = service if service is not None else StudentService(project)
        self._selected_sids = []
        self._checked_tags = set()
        self._debounce.stop()

        old_model.setParent(None)
        old_model.deleteLater()
        self._model = StudentTableModel(project, self._service, self)
        self._view.setModel(self._model)
        self._view.selectionModel().selectionChanged.connect(self._on_selection_changed)

    def refresh(self) -> None:
        """按当前筛选条件重建列表与标签菜单。"""
        self._rebuild_tag_menu()
        self._apply_filter()

    def selected_sids(self) -> list:
        return list(self._selected_sids)

    def current_sid(self) -> str:
        sids = self.selected_sids()
        return sids[0] if sids else ""

    def assign_filter(self) -> str:
        """当前「分配状态」筛选（ASSIGN_ALL / ASSIGN_ASSIGNED / ASSIGN_UNASSIGNED）。"""
        return str(self._assign_combo.currentData() or ASSIGN_ALL)

    def clear_selection(self) -> None:
        self._updating = True
        try:
            self._view.clearSelection()
        finally:
            self._updating = False
        if self._selected_sids:
            self._selected_sids = []
            self.selection_changed.emit([])

    # 筛选
    def _tag_mode(self) -> str:
        return TAG_MODE_ALL if self._inter_radio.isChecked() else TAG_MODE_ANY

    def _on_search_changed(self, _text: str) -> None:
        self._debounce.start()

    def _apply_filter(self) -> None:
        if self._project is None:
            return
        previous = list(self._selected_sids)
        self._updating = True
        try:
            condition = StudentFilter(
                keyword=self._search.text().strip(),
                tags=set(self._checked_tags),
                tag_mode=self._tag_mode(),
                gender=self._gender_combo.currentData() or "",
                assign_state=self._assign_combo.currentData() or ASSIGN_ALL,
            )
            students = self._service.filter(condition)
            self._view.clearSelection()
            self._model.set_students(students)
        except Exception as exc:  # 过滤失败不应崩溃
            self._warn("筛选名单失败：%s" % exc)
        finally:
            self._updating = False
        self._restore_selection(previous)
        self._update_stats()

    def _restore_selection(self, previous: List[str]) -> None:
        visible = set(self._model.sid_list())
        keep = [sid for sid in previous if sid in visible]
        self._selected_sids = keep
        if keep:
            self._updating = True
            try:
                self._view.reselect(keep)
            finally:
                self._updating = False
        if keep != previous:
            self.selection_changed.emit(list(keep))

    def _update_stats(self) -> None:
        total = len(self._project.students)
        assigned = len([sid for sid in self._project.assignment.values() if sid])
        text = "共 %d 人 · 已分配 %d" % (total, assigned)
        shown = self._model.rowCount()
        if shown != total:
            text += " · 筛选出 %d 人" % shown
        self._stats_label.setText(text)

    # 标签筛选
    def _rebuild_tag_menu(self) -> None:
        self._tag_populating = True
        try:
            self._tag_list.clear()
            if self._project is not None:
                for tag in self._project.tags:
                    item = QListWidgetItem(tag.name)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.CheckState.Checked if tag.name in self._checked_tags else Qt.CheckState.Unchecked
                    )
                    item.setForeground(QColor(tag.color))
                    self._tag_list.addItem(item)
        except Exception:
            pass
        finally:
            self._tag_populating = False
        self._update_tagbutton()

    def _update_tagbutton(self) -> None:
        count = len(self._checked_tags)
        self._tag_button.setText("标签筛选 (%d)" % count if count else "标签筛选")

    def _on_tag_item_changed(self, item: QListWidgetItem) -> None:
        if self._tag_populating:
            return
        name = item.text()
        if item.checkState() == Qt.CheckState.Checked:
            self._checked_tags.add(name)
        else:
            self._checked_tags.discard(name)
        self._update_tagbutton()
        self._apply_filter()

    def _clear_tag_checks(self) -> None:
        self._checked_tags = set()
        self._rebuild_tag_menu()
        self._apply_filter()

    # 选择
    def _on_selection_changed(self, *_args) -> None:
        if self._updating:
            return
        sids = self._view.selected_sids()
        if sids == self._selected_sids:
            return
        self._selected_sids = list(sids)
        self.selection_changed.emit(list(sids))

    # 操作
    def _on_double_clicked(self, sid: str) -> None:
        if sid:
            self.edit_requested.emit(sid)

    def _on_edit(self) -> None:
        sid = self.current_sid()
        if not sid:
            self._warn("请先在名单中选择一名学生。")
            return
        self.edit_requested.emit(sid)

    def _on_delete(self) -> None:
        sids = self.selected_sids()
        if not sids:
            self._warn("请先在名单中选择要删除的学生。")
            return
        if not self._confirm("确定删除选中的 %d 名学生吗？" % len(sids), "删除学生"):
            return
        self.delete_requested.emit(list(sids))

    def _on_tag(self) -> None:
        sids = self.selected_sids()
        if not sids:
            self._warn("请先在名单中选择要打标签的学生。")
            return
        self.tag_requested.emit(list(sids))

    def _on_text_import(self) -> None:
        try:
            from ..dialogs.text_import_dialog import TextImportDialog
        except Exception as exc:  # 对话框缺失不影响其余功能
            self._warn("文本导入功能不可用：%s" % exc)
            return
        try:
            dialog = TextImportDialog(self._project, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            students = list(dialog.students or [])
        except Exception as exc:
            self._warn("文本导入失败：%s" % exc)
            return
        if students:
            self.students_imported.emit(students)

    # 右键菜单
    def _on_context_menu(self, pos: QPoint) -> None:
        index = self._view.indexAt(pos)
        sids = self.selected_sids()
        if index.isValid():
            student = self._model.student_at(index.row())
            if student is not None and student.sid not in sids:
                self._view.select_sid(student.sid)
                sids = [student.sid]
                self._selected_sids = list(sids)

        menu = QMenu(self)
        act_edit = menu.addAction("编辑")
        act_delete = menu.addAction("删除")
        menu.addSeparator()
        act_tag = menu.addAction("批量打标签")
        act_clear = menu.addAction("清空座位")
        menu.addSeparator()
        act_add = menu.addAction("添加学生")
        has_selection = bool(sids)
        act_edit.setEnabled(len(sids) == 1)
        act_delete.setEnabled(has_selection)
        act_tag.setEnabled(has_selection)
        act_clear.setEnabled(has_selection)

        chosen = menu.exec(self._view.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_edit:
            self.edit_requested.emit(sids[0])
        elif chosen is act_delete:
            self._on_delete()
        elif chosen is act_tag:
            self.tag_requested.emit(list(sids))
        elif chosen is act_clear:
            self.clear_seats_requested.emit(list(sids))
        elif chosen is act_add:
            self.add_requested.emit()

    # 项目事件
    def _on_project_event(self, event: str, _payload) -> None:
        if event not in (EV_STUDENTS, EV_TAGS, EV_ASSIGNMENT, EV_ANY):
            return
        self._schedule_refresh()

    # 拖回名单 = 取消入座（面板空白处也能接住）
    def _seat_key_of(self, event) -> str:
        mime = event.mimeData() if hasattr(event, "mimeData") else None
        if mime is None or not mime.hasFormat(MIME_SEAT):
            return ""
        data = decode_seat(mime)
        coord = data.get("seat")
        return make_key(coord) if coord is not None else ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._seat_key_of(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._seat_key_of(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        seat_key = self._seat_key_of(event)
        if seat_key:
            self.clear_seat_requested.emit(seat_key)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    # 工具
    def _confirm(self, text: str, title: str) -> bool:
        return confirm(self, text, title)

    def _warn(self, text: str, title: str = "提示") -> None:
        warn(self, text, title)
