"""主窗口：菜单 / 工具栏 / 三个面板 / 中央座位表 / 状态栏，以及全部业务编排。

原则：UI 事件 → 服务层原子操作 → 更新 Project → 局部刷新控件。
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTabWidget,
    QToolBar,
    QWidget,
)

from .. import config
from ..models.assignment import seat_key_of, unassigned_students
from ..models.layout import Layout
from ..models.project import (
    EV_ANY,
    EV_ASSIGNMENT,
    EV_HISTORY,
    EV_LAYOUT,
    EV_RULES,
    EV_SELECTIONS,
    EV_STUDENTS,
    EV_TAGS,
    Project,
    new_project,
)
from ..services.export_service import ExportError, ExportService
from ..services.history_service import HistoryService, Snapshot
from ..services.rotation_service import RotationError, RotationPlan, RotationService
from ..services.rule_engine import RuleEngine, describe_violations
from ..services.seat_service import SeatService
from ..services.student_service import StudentService
from ..storage import excel_io
from ..storage.excel_io import ExportOptions
from ..storage.project_store import JsonProjectStore, ProjectStoreError
from ..utils.natural_sort import natural_key
from ..utils.seat_key import make_key, try_parse_key
from ..utils.seat_key import Seat as Coord
from .style.theme import PANEL_RULE_WIDTH, PANEL_STUDENT_WIDTH
from .widgets.seat_grid_view import SeatGridView

MAX_RECENT = 8


class MainWindow(QMainWindow):
    """教室座位编排主窗口。"""

    def __init__(self, project: Optional[Project] = None) -> None:
        super().__init__()
        self.project: Project = project or new_project()
        self.student_service = StudentService(self.project)
        self.history = HistoryService(config.MAX_UNDO)
        self.export_service = ExportService()
        self.rotation_service = RotationService(self.project)

        self._pending_sids: List[str] = []
        self._conflicts: Dict[str, str] = {}
        self._locked_seats: Set[Coord] = set()
        self._last_solution = None
        self._pending_rotation_preview: Optional[RotationPlan] = None
        self._suppress_events = False

        self.setWindowTitle(config.APP_NAME)
        self.setMinimumSize(1100, 720)
        self.resize(1440, 900)

        self._build_central()
        self._build_panels()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        self.project.subscribe(self._on_project_event)
        self.history.subscribe(self._update_history_actions)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(config.AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()

        self._restore_settings()
        self._refresh_all()
        QTimer.singleShot(200, self._maybe_recover)
        QTimer.singleShot(400, self._maybe_welcome)

    # ============================================================ 界面搭建
    def _build_central(self) -> None:
        self.grid = SeatGridView(self)
        self.setCentralWidget(self.grid)
        self.grid.seat_clicked.connect(self._on_seat_clicked)
        self.grid.seat_double_clicked.connect(self._on_seat_double_clicked)
        self.grid.seat_context_requested.connect(self._on_seat_context_menu)
        self.grid.seat_swap_requested.connect(self._on_seat_swap)
        self.grid.student_drop_requested.connect(self._on_student_dropped)
        self.grid.selection_changed.connect(self._on_selection_changed)
        self.grid.set_project(self.project)

    def _build_panels(self) -> None:
        from .panels.rotation_panel import RotationPanel
        from .panels.rule_panel import RulePanel
        from .panels.selection_panel import SelectionPanel
        from .panels.student_panel import StudentPanel

        self.student_panel = StudentPanel(self.project, self)
        self.student_dock = QDockWidget("学生名单", self)
        self.student_dock.setObjectName("StudentDock")
        self.student_dock.setWidget(self.student_panel)
        self.student_dock.setMinimumWidth(PANEL_STUDENT_WIDTH - 40)
        self.student_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.student_dock)

        self.student_panel.selection_changed.connect(self._on_student_selection)
        self.student_panel.import_requested.connect(self.import_excel)
        self.student_panel.add_requested.connect(self.add_student)
        self.student_panel.edit_requested.connect(self.edit_student)
        self.student_panel.delete_requested.connect(self.delete_students)
        self.student_panel.tag_requested.connect(self.batch_tag)
        self.student_panel.export_requested.connect(self.export_roster)
        if hasattr(self.student_panel, "template_requested"):
            self.student_panel.template_requested.connect(self.save_roster_template)
        if hasattr(self.student_panel, "students_imported"):
            self.student_panel.students_imported.connect(self._on_students_imported)
        if hasattr(self.student_panel, "clear_seats_requested"):
            self.student_panel.clear_seats_requested.connect(self._on_clear_students_seats)

        self.rule_panel = RulePanel(self.project, self)
        self.selection_panel = SelectionPanel(self.project, self)
        self.rotation_panel = RotationPanel(self.project, self)

        self.right_tabs = QTabWidget(self)
        self.right_tabs.setObjectName("Panel")
        self.right_tabs.addTab(self.rule_panel, "规则")
        self.right_tabs.addTab(self.selection_panel, "选区")
        self.right_tabs.addTab(self.rotation_panel, "轮换")

        self.right_dock = QDockWidget("规则与选区", self)
        self.right_dock.setObjectName("RightDock")
        self.right_dock.setWidget(self.right_tabs)
        self.right_dock.setMinimumWidth(PANEL_RULE_WIDTH - 30)
        self.right_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.right_dock)
        # 给两侧面板一个合适的初始宽度（用户仍可自由拖动）
        self.resizeDocks([self.student_dock], [PANEL_STUDENT_WIDTH + 50], Qt.Orientation.Horizontal)
        self.resizeDocks([self.right_dock], [PANEL_RULE_WIDTH + 40], Qt.Orientation.Horizontal)

        self.rule_panel.rules_changed.connect(self._on_rules_changed)
        self.selection_panel.apply_requested.connect(self._on_selection_apply)
        self.selection_panel.selection_created.connect(self._on_selection_created)
        self.selection_panel.selection_deleted.connect(self._on_selection_deleted)
        self.selection_panel.selection_renamed.connect(self._on_selection_renamed)
        self.selection_panel.batch_clear_requested.connect(self.clear_seats)
        self.selection_panel.batch_disable_requested.connect(self.toggle_disabled_seats)
        self.selection_panel.batch_assign_requested.connect(self.batch_assign)
        self.rotation_panel.preview_ready.connect(self._on_rotation_preview)
        self.rotation_panel.apply_requested.connect(self._on_rotation_apply)
        self.rotation_panel.rollback_requested.connect(self._on_rotation_rollback)

    def _build_actions(self) -> None:
        def action(text: str, shortcut: str = "", slot=None, tip: str = "", checkable: bool = False) -> QAction:
            act = QAction(text, self)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            if tip:
                act.setStatusTip(tip)
                act.setToolTip(tip)
            if checkable:
                act.setCheckable(True)
            if slot is not None:
                act.triggered.connect(slot)
            return act

        self.act_new = action("新建项目", "Ctrl+N", self.new_project, "清空当前项目，重新开始")
        self.act_open = action("打开项目…", "Ctrl+O", self.open_project, "打开 .seatproj 项目文件")
        self.act_save = action("保存", "Ctrl+S", self.save_project, "保存到当前项目文件")
        self.act_save_as = action("另存为…", "Ctrl+Shift+S", self.save_project_as, "保存到新的项目文件")
        self.act_import = action("导入学生名单…", "Ctrl+I", self.import_excel, "从 Excel 导入名单")
        self.act_import_text = action("粘贴文本导入名单…", "", self.import_text, "从剪贴板/文本框批量粘贴「学号 姓名」")
        self.act_roster_template = action(
            "下载名单导入模板…", "", self.save_roster_template,
            "生成 Excel 名单模板（含填写说明与示例），填好后可直接导入",
        )
        self.act_export_excel = action("导出座位表 (Excel)…", "Ctrl+E", self.export_seat_table, "导出带讲台与过道的座位表")
        self.act_export_png = action("导出座位表 (PNG)…", "Ctrl+Shift+E", self.export_png, "导出座位表图片")
        self.act_export_roster = action("导出学生名单…", "", self.export_roster, "导出当前名单（含标签与数值属性）")
        self.act_quit = action("退出", "Ctrl+Q", self.close, "退出程序")

        self.act_undo = action("撤销", "Ctrl+Z", self.undo, "撤销上一步操作")
        self.act_redo = action("重做", "Ctrl+Y", self.redo, "重做被撤销的操作")
        self.act_clear_seats = action("清空选中座位", "Delete", self._clear_selected, "把选中的学生移回未分配池")
        self.act_toggle_disabled = action("设为 / 取消空置", "Ctrl+D", self._toggle_selected_disabled, "空置座位不参与排位")
        self.act_select_all = action("全选座位", "Ctrl+A", self._select_all_seats, "选中全部座位")
        self.act_assign_pending = action("把选中学生放入第一个空位", "", self._assign_pending_auto, "按顺序自动填空位")
        self.act_lock_seats = action("锁定选中座位", "Ctrl+L", self._lock_selected, "排位时保持这些座位不变")
        self.act_unlock_seats = action("解除全部锁定", "Ctrl+Shift+L", self._unlock_seats, "取消所有座位锁定")

        self.act_layout = action("教室布局…", "Ctrl+B", self.edit_layout, "配置分组、行列、组间距与讲台方向")
        self.act_solve = action("一键排位", "F5", self.solve, "按规则自动排座位")
        self.act_solve_again = action("换一批", "Ctrl+R", self.solve, "重新搜索另一个方案")
        self.act_report = action("查看排位报告", "", self.show_report, "查看硬约束满足情况与软约束得分")
        self.act_clear_all = action("清空全部座位", "", self.clear_all_seats, "把所有学生移回未分配池")

        self.act_tags = action("标签管理…", "Ctrl+T", self.manage_tags, "新增 / 重命名 / 删除标签与配色")

        self.act_show_sid = QAction("显示学号", self)
        self.act_show_sid.setCheckable(True)
        self.act_show_sid.setChecked(True)
        self.act_show_sid.toggled.connect(self._on_show_sid)
        self.act_show_title = QAction("显示组标题", self)
        self.act_show_title.setCheckable(True)
        self.act_show_title.setChecked(True)
        self.act_show_title.toggled.connect(self._on_show_title)
        self.act_show_selection = QAction("显示选区高亮", self)
        self.act_show_selection.setCheckable(True)
        self.act_show_selection.setChecked(True)
        self.act_show_selection.toggled.connect(self._on_show_selection)

        self.size_actions = QActionGroup(self)
        self.act_size: Dict[str, QAction] = {}
        from .style.theme import CARD_SIZE_LABELS

        for name, label in CARD_SIZE_LABELS.items():
            act = QAction("座位卡片：%s" % label, self)
            act.setCheckable(True)
            act.setChecked(name == "medium")
            act.triggered.connect(lambda _checked, n=name: self._on_card_size(n))
            self.size_actions.addAction(act)
            self.act_size[name] = act

        self.act_help = action("快捷键与使用说明", "F1", self.show_help, "查看快捷键与上手步骤")
        self.act_about = action("关于", "", self.show_about, "关于本程序")

    def _build_menus(self) -> None:
        bar = self.menuBar()
        menu_file = bar.addMenu("文件(&F)")
        menu_file.addAction(self.act_new)
        menu_file.addAction(self.act_open)
        self.recent_menu = QMenu("最近打开", self)
        menu_file.addMenu(self.recent_menu)
        menu_file.addSeparator()
        menu_file.addAction(self.act_save)
        menu_file.addAction(self.act_save_as)
        menu_file.addSeparator()
        menu_file.addAction(self.act_import)
        menu_file.addAction(self.act_import_text)
        menu_file.addAction(self.act_roster_template)
        menu_file.addAction(self.act_export_excel)
        menu_file.addAction(self.act_export_png)
        menu_file.addAction(self.act_export_roster)
        menu_file.addSeparator()
        menu_file.addAction(self.act_quit)

        menu_edit = bar.addMenu("编辑(&E)")
        menu_edit.addAction(self.act_undo)
        menu_edit.addAction(self.act_redo)
        menu_edit.addSeparator()
        menu_edit.addAction(self.act_clear_seats)
        menu_edit.addAction(self.act_toggle_disabled)
        menu_edit.addAction(self.act_select_all)
        menu_edit.addAction(self.act_assign_pending)
        menu_edit.addSeparator()
        menu_edit.addAction(self.act_lock_seats)
        menu_edit.addAction(self.act_unlock_seats)
        menu_edit.addSeparator()
        menu_edit.addAction(self.act_layout)
        menu_edit.addAction(self.act_tags)

        menu_view = bar.addMenu("视图(&V)")
        menu_view.addAction(self.act_show_sid)
        menu_view.addAction(self.act_show_title)
        menu_view.addAction(self.act_show_selection)
        menu_size = menu_view.addMenu("座位卡片尺寸")
        for act in self.act_size.values():
            menu_size.addAction(act)
        menu_view.addSeparator()
        menu_view.addAction(self.student_dock.toggleViewAction())
        menu_view.addAction(self.right_dock.toggleViewAction())

        menu_seat = bar.addMenu("排位(&S)")
        menu_seat.addAction(self.act_solve)
        menu_seat.addAction(self.act_solve_again)
        menu_seat.addAction(self.act_report)
        menu_seat.addSeparator()
        menu_seat.addAction(self.act_clear_all)

        menu_help = bar.addMenu("帮助(&H)")
        menu_help.addAction(self.act_help)
        menu_help.addAction(self.act_about)

    def _build_toolbar(self) -> None:
        bar = QToolBar("主工具栏", self)
        bar.setObjectName("MainToolBar")
        bar.setMovable(False)
        bar.setIconSize(bar.iconSize())
        self.addToolBar(bar)
        bar.addAction(self.act_new)
        bar.addAction(self.act_open)
        bar.addAction(self.act_save)
        bar.addSeparator()
        bar.addAction(self.act_import)
        bar.addAction(self.act_export_excel)
        bar.addSeparator()
        bar.addAction(self.act_undo)
        bar.addAction(self.act_redo)
        bar.addSeparator()
        bar.addAction(self.act_layout)
        bar.addAction(self.act_solve)
        bar.addAction(self.act_report)
        self.toolbar = bar

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        self.lbl_summary = QLabel("", self)
        self.lbl_conflict = QLabel("", self)
        self.lbl_conflict.setObjectName("StatusWarn")
        bar.addWidget(self.lbl_summary)
        bar.addPermanentWidget(self.lbl_conflict)

    def toast(self, message: str, timeout: int = 4000) -> None:
        self.statusBar().showMessage(message, timeout)

    # ============================================================ 项目事件
    def _on_project_event(self, event: str, payload) -> None:
        if self._suppress_events:
            return
        if event in (EV_ASSIGNMENT, EV_STUDENTS, EV_TAGS, EV_ANY):
            self._update_status()
        if event == EV_LAYOUT:
            self._update_status()
            self.selection_panel.refresh()
        if event in (EV_RULES, EV_SELECTIONS):
            self.selection_panel.refresh()
        if event == EV_HISTORY:
            self.rotation_panel.refresh()
        self.setWindowTitle(self._window_title())

    def _refresh_all(self) -> None:
        self.grid.rebuild()
        self.grid.set_locked_seats(self._locked_seats)
        self._update_conflicts()
        self.student_panel.refresh()
        self.rule_panel.refresh()
        self.selection_panel.refresh()
        self.rotation_panel.refresh()
        self._update_status()
        self._update_history_actions()
        self._update_recent_menu()
        self.setWindowTitle(self._window_title())

    def _window_title(self) -> str:
        name = os.path.basename(self.project.path) if self.project.path else "未命名项目"
        return "%s%s — %s" % ("*" if self.project.dirty else "", name, config.APP_NAME)

    # ============================================================ 状态
    def _update_status(self) -> None:
        layout = self.project.layout
        assigned = len([v for v in self.project.assignment.values() if v])
        text = "座位 %d（空置 %d） · 学生 %d · 已分配 %d · 未分配 %d" % (
            layout.seat_count(),
            len(layout.disabled_seats),
            len(self.project.students),
            assigned,
            max(0, len(self.project.students) - assigned),
        )
        if self._locked_seats:
            text += " · 已锁定 %d 座位" % len(self._locked_seats)
        self.lbl_summary.setText(text)
        if self._conflicts:
            first = next(iter(self._conflicts.values()))
            self.lbl_conflict.setText("⚠ %d 处冲突：%s" % (len(self._conflicts), first[:48]))
        else:
            self.lbl_conflict.setText("")
        self.setWindowTitle(self._window_title())

    def _update_history_actions(self) -> None:
        can_undo = self.history.can_undo
        can_redo = self.history.can_redo
        self.act_undo.setEnabled(can_undo)
        self.act_redo.setEnabled(can_redo)
        self.act_undo.setToolTip("撤销：%s" % self.history.undo_label() if can_undo else "没有可撤销的操作")
        self.act_redo.setToolTip("重做：%s" % self.history.redo_label() if can_redo else "没有可重做的操作")

    # ============================================================ 历史
    def _snapshot_layout(self) -> Dict[str, Any]:
        return self.project.layout.to_dict()

    def _push_history(self, label: str) -> None:
        self.history.push(self.project.assignment, label, self._snapshot_layout())
        self._update_history_actions()

    def _restore(self, snapshot: Snapshot) -> None:
        self._suppress_events = True
        try:
            if snapshot.layout_snapshot:
                self.project.layout = Layout.from_dict(snapshot.layout_snapshot)
            self.project.assignment = dict(snapshot.assignment)
            self.project.sanitize_assignment()
        finally:
            self._suppress_events = False
        self.project.notify(EV_LAYOUT)
        self.project.notify(EV_ASSIGNMENT)
        self._update_conflicts()
        self.grid.rebuild()
        self.grid.set_locked_seats(self._locked_seats)
        self._update_status()
        self.student_panel.refresh()
        self.selection_panel.refresh()

    def undo(self) -> None:
        snapshot = self.history.undo(self.project.assignment, self._snapshot_layout())
        if snapshot is None:
            self.toast("没有可撤销的操作")
            return
        label = snapshot.label or "上一步操作"
        self._restore(snapshot)
        self.toast("已撤销：%s" % label)

    def redo(self) -> None:
        snapshot = self.history.redo(self.project.assignment, self._snapshot_layout())
        if snapshot is None:
            self.toast("没有可重做的操作")
            return
        self._restore(snapshot)
        self.toast("已重做")

    # ============================================================ 冲突
    def _engine(self) -> RuleEngine:
        return RuleEngine.from_project(self.project)

    def _coords(self, seats) -> List[Coord]:
        """把 ``"g-r-c"`` / ``(g, r, c)`` 混合输入统一成坐标列表（忽略非法值）。"""
        result: List[Coord] = []
        for item in seats or []:
            if item is None:
                continue
            coord = item if isinstance(item, tuple) and len(item) == 3 else try_parse_key(item)
            if coord is None:
                continue
            result.append((int(coord[0]), int(coord[1]), int(coord[2])))
        return result

    def _update_conflicts(self, seats: Optional[Sequence] = None) -> None:
        engine = self._engine()
        focus = None if seats is None else self._coords(seats)
        violations = engine.check_hard(self.project.assignment, focus)
        mapping: Dict[str, str] = {}
        for violation in violations:
            for key in violation.seats:
                mapping.setdefault(key, violation.message)
        if focus is None:
            self._conflicts = mapping
        else:
            affected = {make_key(s) for s in engine.affected_seats(focus)}
            for key in affected:
                self._conflicts.pop(key, None)
            self._conflicts.update(mapping)
        self.grid.set_conflicts(self._conflicts)
        self._update_status()

    def _conflict_message(self) -> str:
        if not self._conflicts:
            return "当前方案没有硬约束冲突 ✅"
        return "当前方案有 %d 处硬约束冲突：\n\n%s" % (
            len(self._conflicts),
            describe_violations(self._engine().check_hard(self.project.assignment), 8),
        )

    # ============================================================ 座位操作
    def _selected_seats(self) -> List[Coord]:
        return sorted(self.grid.selected_seats(), key=lambda s: (s[0], s[1], s[2]))

    def _on_selection_changed(self, seats) -> None:
        self.selection_panel.set_current_seats(set(seats))

    def _on_student_selection(self, sids: List[str]) -> None:
        self._pending_sids = [s for s in (sids or []) if s]
        if self._pending_sids:
            student = self.project.get_student(self._pending_sids[0])
            name = student.name if student else self._pending_sids[0]
            self.toast("已选中 %s%s，点击空座位即可入座" % (
                name, "" if len(self._pending_sids) == 1 else " 等 %d 人" % len(self._pending_sids)))

    def _on_seat_clicked(self, seat, modifiers: int) -> None:
        ctrl = bool(modifiers & int(Qt.KeyboardModifier.ControlModifier.value))
        shift = bool(modifiers & int(Qt.KeyboardModifier.ShiftModifier.value))
        if ctrl or shift:
            return
        if not self._pending_sids:
            return
        occupants = [self.project.assignment.get(make_key(seat), "")]
        if len(self._pending_sids) == 1 and not occupants[0]:
            self.assign_student(self._pending_sids[0], seat)

    def _on_seat_double_clicked(self, seat) -> None:
        sid = self.project.assignment.get(make_key(seat), "")
        if sid:
            self.edit_student(sid)
        else:
            self._assign_pending_auto()

    def _on_seat_swap(self, source, target) -> None:
        self.swap_seats(source, target)

    def _on_student_dropped(self, sid: str, seat) -> None:
        self.assign_student(sid, seat)

    def _on_seat_context_menu(self, seat, global_pos) -> None:
        coord = tuple(seat)
        key = make_key(coord)
        sid = self.project.assignment.get(key, "")
        menu = QMenu(self)
        student = self.project.get_student(sid) if sid else None
        if sid:
            act = menu.addAction("清空座位（%s）" % (student.name if student else sid))
            act.triggered.connect(lambda: self.clear_seats([coord]))
            if student is not None:
                act2 = menu.addAction("编辑学生信息…")
                act2.triggered.connect(lambda: self.edit_student(sid))
        else:
            act = menu.addAction("清空座位")
            act.setEnabled(False)
        if self._pending_sids:
            menu.addAction(
                "放入选中学生（%d 人）" % len(self._pending_sids),
                lambda: self.assign_student(self._pending_sids[0], coord),
            )
        menu.addSeparator()
        disabled = self.project.layout.is_disabled(coord)
        act_dis = menu.addAction("取消空置" if disabled else "设为空置")
        act_dis.triggered.connect(lambda: self.toggle_disabled_seats([coord]))
        locked = coord in self._locked_seats
        act_lock = menu.addAction("解除锁定" if locked else "锁定该座位")
        act_lock.triggered.connect(lambda: self._toggle_lock(coord))
        menu.addSeparator()
        label = "第 %d 组 第 %d 排 第 %d 列" % (coord[0] + 1, coord[1] + 1, coord[2] + 1)
        info = menu.addAction(label)
        info.setEnabled(False)
        menu.exec(global_pos)

    # ------------------------------------------------------------ 原子操作
    def assign_student(self, sid: str, seat) -> bool:
        student = self.project.get_student(sid)
        if student is None:
            self.toast("找不到学生：%s" % sid)
            return False
        coord = try_parse_key(seat)
        if coord is None or not self.project.layout.contains(coord):
            self.toast("无效的座位")
            return False
        if self.project.layout.is_disabled(coord):
            self.toast("该座位已设为空置，请先取消空置")
            return False
        old_key = seat_key_of(self.project.assignment, sid)
        occupant = self.project.assignment.get(make_key(coord), "")
        if old_key == make_key(coord):
            return False
        label = "分配 %s" % student.name
        if occupant and occupant != sid:
            other = self.project.get_student(occupant)
            label = "把 %s 放到 %s 的位置" % (student.name, other.name if other else occupant)
        self._push_history(label)
        service = SeatService(self.project.assignment)
        service.assign(coord, sid)
        self.project.assignment = service.assignment
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh(self._affected(coord, old_key))
        self._after_change(coord, old_key)
        return True

    def swap_seats(self, source, target) -> bool:
        a, b = try_parse_key(source), try_parse_key(target)
        if a is None or b is None or a == b:
            return False
        if self.project.layout.is_disabled(a) or self.project.layout.is_disabled(b):
            self.toast("空置座位不参与交换")
            return False
        sid_a = self.project.assignment.get(make_key(a), "")
        sid_b = self.project.assignment.get(make_key(b), "")
        if not sid_a and not sid_b:
            self.toast("两个座位都是空的")
            return False
        name_a = self.project.student_name(sid_a) if sid_a else "空位"
        name_b = self.project.student_name(sid_b) if sid_b else "空位"
        self._push_history("交换 %s ↔ %s" % (name_a, name_b))
        service = SeatService(self.project.assignment)
        service.swap(a, b)
        self.project.assignment = service.assignment
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh([a, b])
        self._after_change(a, b)
        self.toast("已交换 %s ↔ %s" % (name_a, name_b))
        return True

    def clear_seats(self, seats: Sequence) -> int:
        coords = [try_parse_key(s) for s in (seats or [])]
        coords = [c for c in coords if c is not None]
        if not coords:
            return 0
        removed = [self.project.assignment.get(make_key(c), "") for c in coords]
        removed = [sid for sid in removed if sid]
        if not removed:
            self.toast("选中的座位本来就是空的")
            return 0
        self._push_history("清空 %d 个座位" % len(removed))
        service = SeatService(self.project.assignment)
        service.clear_many(coords)
        self.project.assignment = service.assignment
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh(coords)
        self._after_change(*coords)
        self.toast("已清空 %d 个座位，学生回到未分配池" % len(removed))
        return len(removed)

    def clear_all_seats(self) -> None:
        if not any(self.project.assignment.values()):
            self.toast("当前没有已分配的座位")
            return
        if not self._confirm("确定要清空全部座位吗？所有学生将回到未分配池。"):
            return
        self._push_history("清空全部座位")
        seats = [try_parse_key(k) for k in list(self.project.assignment)]
        self.project.assignment = {}
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh([s for s in seats if s is not None])
        self._update_conflicts()
        self.toast("已清空全部座位")

    def toggle_disabled_seats(self, seats: Sequence) -> None:
        coords = [try_parse_key(s) for s in (seats or [])]
        coords = [c for c in coords if c is not None]
        if not coords:
            return
        target = not all(self.project.layout.is_disabled(c) for c in coords)
        self._push_history("设为空置" if target else "取消空置")
        for coord in coords:
            self.project.layout.set_disabled(coord, target)
            if target:
                self.project.assignment.pop(make_key(coord), None)
        self.project.layout.prune_disabled()
        self.project.notify(EV_LAYOUT)
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh(coords)
        self._update_conflicts(coords)
        self.toast("已把 %d 个座位设为%s" % (len(coords), "空置" if target else "可用"))

    def batch_assign(self, seats: Sequence) -> None:
        coords = sorted(
            [c for c in (try_parse_key(s) for s in (seats or [])) if c is not None],
            key=lambda s: (s[1], s[0], s[2]),
        )
        if not coords:
            self.toast("请先在座位表上选择若干座位")
            return
        sids = list(self._pending_sids)
        if not sids:
            sids = [s.sid for s in sorted(self.project.students, key=lambda s: natural_key(s.sid))]
            sids = unassigned_students(self.project.assignment, sids)
        if not sids:
            self.toast("没有可分配的学生")
            return
        count = min(len(coords), len(sids))
        self._push_history("批量分配 %d 人" % count)
        service = SeatService(self.project.assignment)
        for coord, sid in zip(coords[:count], sids[:count]):
            if self.project.layout.is_disabled(coord):
                continue
            service.assign(coord, sid)
        self.project.assignment = service.assignment
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh(coords[:count])
        self._after_change(*coords[:count])
        self.toast("已批量分配 %d 名学生" % count)

    def _assign_pending_auto(self) -> None:
        seats = self._selected_seats()
        if not seats:
            free = [s for s in self.project.layout.available_seats()
                    if not self.project.assignment.get(make_key(s), "")]
            seats = free[:max(1, len(self._pending_sids) or 1)]
        self.batch_assign(seats)

    def _affected(self, *seats) -> List[Coord]:
        result: List[Coord] = self._coords(seats)
        for coord in list(result):
            result.extend(self.project.layout.neighbors(coord))
        return result

    def _after_change(self, *seats) -> None:
        self._update_conflicts(self._coords(seats))
        self._update_status()
        self.student_panel.refresh()

    # ------------------------------------------------------------ 选区操作
    def _select_all_seats(self) -> None:
        self.grid.select_all()
        self.toast("已选中全部 %d 个座位" % self.grid.seat_count())

    def _clear_selected(self) -> None:
        seats = self._selected_seats()
        if not seats:
            self.toast("请先选择座位（拖拽框选或 Ctrl+点击）")
            return
        self.clear_seats(seats)

    def _toggle_selected_disabled(self) -> None:
        seats = self._selected_seats()
        if not seats:
            self.toast("请先选择座位")
            return
        self.toggle_disabled_seats(seats)

    def _lock_selected(self) -> None:
        seats = self._selected_seats()
        if not seats:
            self.toast("请先选择要锁定的座位")
            return
        self._locked_seats |= set(seats)
        self.grid.set_locked_seats(self._locked_seats)
        self._update_status()
        self.toast("已锁定 %d 个座位，排位时保持不动" % len(self._locked_seats))

    def _unlock_seats(self) -> None:
        if not self._locked_seats:
            self.toast("当前没有锁定的座位")
            return
        self._locked_seats.clear()
        self.grid.set_locked_seats(self._locked_seats)
        self._update_status()
        self.toast("已解除全部座位锁定")

    def _toggle_lock(self, seat) -> None:
        coord = try_parse_key(seat)
        if coord is None:
            return
        coord = (int(coord[0]), int(coord[1]), int(coord[2]))
        if coord in self._locked_seats:
            self._locked_seats.discard(coord)
            self.toast("已解除锁定")
        else:
            self._locked_seats.add(coord)
            self.toast("已锁定该座位")
        self.grid.set_locked_seats(self._locked_seats)
        self._update_status()

    # ============================================================ 学生
    def add_student(self) -> None:
        from .dialogs.student_edit_dialog import StudentEditDialog

        dialog = StudentEditDialog(self.project, None, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        student = getattr(dialog, "result_student", None)
        if student is None:
            return
        self._push_history("添加学生 %s" % student.name)
        ok, message = self.student_service.add(
            student.sid, student.name, student.gender, student.tags, student.attrs, student.note
        )
        if not ok:
            self.history.drop_last()
            QMessageBox.warning(self, "无法添加", message)
            return
        self._refresh_all()
        self.toast("已添加 %s（%s）" % (student.name, student.sid))

    def edit_student(self, sid: str) -> None:
        student = self.project.get_student(sid)
        if student is None:
            self.toast("找不到学生：%s" % sid)
            return
        from .dialogs.student_edit_dialog import StudentEditDialog

        dialog = StudentEditDialog(self.project, student, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        updated = getattr(dialog, "result_student", None)
        if updated is None:
            return
        self._push_history("编辑学生 %s" % student.name)
        ok, message = self.student_service.update(
            sid, sid=updated.sid, name=updated.name, gender=updated.gender,
            tags=updated.tags, attrs=updated.attrs, note=updated.note,
        )
        if not ok:
            self.history.drop_last()
            QMessageBox.warning(self, "无法保存", message)
            return
        self._refresh_all()
        self.toast("已保存 %s 的信息" % updated.name)

    def delete_students(self, sids: Sequence[str]) -> None:
        sids = [s for s in (sids or []) if s]
        if not sids:
            self.toast("请先在名单里选择学生")
            return
        if not self._confirm("确定要删除选中的 %d 名学生吗？此操作不可恢复。" % len(sids)):
            return
        self._push_history("删除 %d 名学生" % len(sids))
        self.student_service.remove(sids)
        self._refresh_all()
        self.toast("已删除 %d 名学生" % len(sids))

    def batch_tag(self, sids: Sequence[str]) -> None:
        sids = [s for s in (sids or []) if s]
        if not sids:
            self.toast("请先在名单里选择学生")
            return
        tags = self.project.tag_names()
        menu = QMenu(self)
        for tag in tags:
            act = menu.addAction("添加标签：%s" % tag)
            act.triggered.connect(lambda _c, t=tag: self._apply_tag(sids, t, True))
        for tag in tags:
            act = menu.addAction("移除标签：%s" % tag)
            act.triggered.connect(lambda _c, t=tag: self._apply_tag(sids, t, False))
        menu.addSeparator()
        act_new = menu.addAction("新建标签…")
        act_new.triggered.connect(lambda: self._apply_tag(sids, "", True))
        menu.exec(self.mapToGlobal(self.rect().center()))

    def _apply_tag(self, sids: Sequence[str], tag: str, add: bool) -> None:
        if not tag:
            tag, ok = QInputDialog.getText(self, "新建标签", "标签名称：")
            if not ok or not tag.strip():
                return
            tag = tag.strip()
        self._push_history("批量%s标签「%s」" % ("添加" if add else "移除", tag))
        if add:
            count = self.student_service.add_tag(sids, tag)
        else:
            count = self.student_service.remove_tag_from(sids, tag)
        self._refresh_all()
        self.toast("已为 %d 名学生%s标签「%s」" % (count, "添加" if add else "移除", tag))

    def manage_tags(self) -> None:
        from .dialogs.tag_manager_dialog import TagManagerDialog

        dialog = TagManagerDialog(self.project, self)
        dialog.exec()
        self._refresh_all()

    # ============================================================ Excel
    def save_roster_template(self) -> None:
        """生成 Excel 名单导入模板；教师填好后走「导入学生名单」读入。"""
        from ..storage import roster_template

        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存名单导入模板",
            self._default_name(roster_template.TEMPLATE_FILENAME),
            config.EXCEL_FILTER,
        )
        if not path:
            return
        try:
            target = roster_template.write_roster_template(path)
        except excel_io.ExcelError as exc:
            QMessageBox.warning(self, "无法生成模板", str(exc))
            return
        self._remember_dir(str(target))
        self.toast("已生成名单模板：%s" % target)
        QMessageBox.information(
            self,
            "模板已生成",
            "名单模板已保存到：\n%s\n\n"
            "在「名单」工作表里从第 2 行开始逐行填写学生，保存后回到程序点「导入学生名单」，"
            "字段会自动对应，直接确认即可。\n\n"
            "「填写说明」页写了每一列怎么填，「示例」页有一份可以照抄的样例。" % target,
        )

    def import_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择学生名单", self._last_dir(), config.EXCEL_FILTER)
        if not path:
            return
        self._remember_dir(path)
        try:
            preview = excel_io.read_preview(path)
        except excel_io.ExcelError as exc:
            QMessageBox.warning(self, "无法读取文件", str(exc))
            return
        from .dialogs.import_mapping_dialog import ImportMappingDialog

        dialog = ImportMappingDialog(preview, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        mapping = getattr(dialog, "mapping", None) or preview.mapping
        skip_invalid = bool(getattr(dialog, "skip_invalid", True))
        try:
            result = excel_io.build_students(
                preview.headers, preview.rows, mapping, skip_invalid,
                existing_sids=self.project.all_sids(),
            )
        except excel_io.ExcelError as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self._finish_import(result)

    def import_text(self) -> None:
        from .dialogs.text_import_dialog import TextImportDialog

        dialog = TextImportDialog(self.project, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._on_students_imported(list(getattr(dialog, "students", []) or []))

    def _on_students_imported(self, students) -> None:
        """文本 / 其他途径导入的学生列表（由学生面板或本窗口触发）。"""
        students = list(students or [])
        if not students:
            self.toast("没有解析到学生数据")
            return
        before = len(self.project.students)
        self._push_history("导入 %d 名学生" % len(students))
        added = self.project.add_students(students)
        for student in students:
            for tag in student.tags:
                self.project.ensure_tag(tag)
        self.project.notify(EV_STUDENTS)
        self._refresh_all()
        skipped = len(students) - added
        if added == 0:
            self.toast("没有新增学生（%d 条与现有名单重复）" % skipped)
        else:
            self.toast("已导入 %d 名学生（名单 %d → %d 人）%s" % (
                added, before, len(self.project.students),
                "，跳过重复 %d 条" % skipped if skipped else ""))

    def _on_clear_students_seats(self, sids) -> None:
        """把选中的学生从座位上移回未分配池。"""
        seats = []
        for sid in sids or []:
            key = seat_key_of(self.project.assignment, str(sid))
            if key:
                coord = try_parse_key(key)
                if coord is not None:
                    seats.append(coord)
        if not seats:
            self.toast("选中的学生都没有座位")
            return
        self.clear_seats(seats)

    def _finish_import(self, result) -> None:
        if not result.students:
            detail = "\n".join("%s（第 %d 行）" % (e.message, e.row) for e in result.errors[:10])
            QMessageBox.warning(self, "没有可导入的数据", detail or "没有读取到有效数据行")
            return
        self._push_history("导入 %d 名学生" % len(result.students))
        added = self.project.add_students(result.students)
        for student in result.students:
            for tag in student.tags:
                self.project.ensure_tag(tag)
        self.project.notify(EV_STUDENTS)
        self._refresh_all()
        message = "成功导入 %d 名学生" % added
        if result.new_attrs:
            message += "\n新增数值属性：%s" % "、".join(result.new_attrs)
        if result.errors:
            message += "\n跳过 %d 行有问题的数据" % len(result.errors)
        QMessageBox.information(self, "导入完成", message)
        self.toast(message.splitlines()[0])

    def export_seat_table(self) -> None:
        self._export_excel()

    def _export_excel(self) -> None:
        from .dialogs.export_dialog import ExportDialog

        if self._conflicts:
            QMessageBox.warning(self, "导出提醒", self._conflict_message())
        dialog = ExportDialog(self.project, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        mode = getattr(dialog, "mode", "excel")
        chosen = str(getattr(dialog, "path", "") or "")
        if mode == "png":
            self._export_png_with(int(getattr(dialog, "png_scale", 1) or 1), chosen)
            return
        path = chosen
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "导出座位表", self._default_name("座位表.xlsx"),
                                                 config.EXCEL_FILTER)
        if not path:
            return
        options = getattr(dialog, "options", None) or ExportOptions()
        try:
            target = self.export_service.export_seat_table(self.project, path, options)
        except ExportError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.toast("已导出座位表：%s" % target)
        QMessageBox.information(self, "导出成功", "座位表已导出到：\n%s" % target)

    def export_png(self) -> None:
        from .dialogs.export_dialog import ExportDialog

        dialog = ExportDialog(self.project, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._export_png_with(
            int(getattr(dialog, "png_scale", 1) or 1),
            str(getattr(dialog, "path", "") or ""),
        )

    def _export_png_with(self, scale: int, path: str = "") -> None:
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "导出座位表图片", self._default_name("座位表.png"),
                                                  config.PNG_FILTER)
        if not path:
            return
        hidden = []
        if self.act_show_selection.isChecked():
            self.act_show_selection.setChecked(False)
            hidden.append(self.act_show_selection)
        self.grid.clear_selection()
        QApplication.processEvents()
        try:
            target = self.export_service.export_png(self.grid, path, scale)
        except ExportError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            for act in hidden:
                act.setChecked(True)
            return
        for act in hidden:
            act.setChecked(True)
        self.toast("已导出图片：%s" % target)
        QMessageBox.information(self, "导出成功", "图片已导出到：\n%s" % target)

    def export_roster(self) -> None:
        if not self.project.students:
            self.toast("名单是空的，无法导出")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出学生名单", self._default_name("学生名单.xlsx"),
                                              config.EXCEL_FILTER)
        if not path:
            return
        try:
            target = self.export_service.export_roster(self.project, path)
        except ExportError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.toast("已导出名单：%s" % target)

    # ============================================================ 布局
    def edit_layout(self) -> None:
        from .dialogs.layout_editor_dialog import LayoutEditorDialog

        dialog = LayoutEditorDialog(self.project, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        new_layout = getattr(dialog, "result_layout", None)
        if new_layout is None:
            return
        self._push_history("修改教室布局")
        self.project.layout = new_layout
        problems = self.project.sanitize_assignment()
        self.project.notify(EV_LAYOUT)
        self.project.notify(EV_ASSIGNMENT)
        self._locked_seats = {s for s in self._locked_seats if self.project.layout.contains(s)}
        self.grid.rebuild()
        self.grid.set_locked_seats(self._locked_seats)
        self._update_conflicts()
        self._update_status()
        self.student_panel.refresh()
        self.selection_panel.refresh()
        if problems:
            QMessageBox.information(self, "布局已更新", "以下座位的分配被清理：\n%s" % "\n".join(problems[:8]))
        self.toast("教室布局已更新：%d 组，共 %d 个座位" % (
            self.project.layout.group_count, self.project.layout.seat_count()))

    # ============================================================ 排位
    def solve(self) -> None:
        if not self.project.students:
            QMessageBox.information(self, "还没有学生", "请先导入或添加学生名单，再执行一键排位。")
            return
        if self.project.layout.available_count() == 0:
            QMessageBox.warning(self, "没有可用座位", "所有座位都被设为空置了，请先取消部分空置座位。")
            return
        from .dialogs.solver_progress_dialog import SolverProgressDialog

        self._push_history("一键排位")
        dialog = SolverProgressDialog(self.project, self, sorted(self._locked_seats))
        if dialog.exec() != dialog.DialogCode.Accepted:
            self.history.drop_last()
            self._update_history_actions()
            return
        solution = getattr(dialog, "solution", None)
        if solution is None:
            self.history.drop_last()
            self._update_history_actions()
            self.toast("排位已取消")
            return
        self.project.previous_assignment = dict(self.project.assignment)
        self.project.assignment = dict(solution.assignment)
        self.project.notify(EV_ASSIGNMENT)
        self._last_solution = solution
        self.grid.refresh()
        self._update_conflicts()
        self._update_status()
        self.student_panel.refresh()
        self.show_report()
        self.toast("排位完成：软约束得分 %.1f，硬约束违反 %d 条" % (solution.soft_score, solution.hard_count))

    def show_report(self) -> None:
        solution = self._last_solution
        if solution is None:
            engine = self._engine()
            from ..models.assignment import Solution

            evaluation = engine.evaluate(self.project.assignment)
            solution = Solution(
                assignment=dict(self.project.assignment),
                score=evaluation.objective,
                soft_score=evaluation.score,
                hard_violations=engine.check_hard(self.project.assignment),
                rule_scores=evaluation.rule_scores,
            )
        from .dialogs.conflict_report_dialog import ConflictReportDialog

        ConflictReportDialog(solution, self.project, self).exec()

    def _on_rules_changed(self) -> None:
        self.rule_panel.refresh()
        self._update_conflicts()
        self._update_status()

    # ============================================================ 选区
    def _on_selection_apply(self, selection_id: str) -> None:
        selection = self.project.get_selection(selection_id)
        if selection is None:
            self.toast("找不到该选区")
            return
        self.grid.set_selected(selection.seats)
        self.toast("已选中选区「%s」（%d 个座位）" % (selection.name, len(selection.seats)))

    def _on_selection_created(self, name: str, seats) -> None:
        if not seats:
            self.toast("请先在座位表上选择座位")
            return
        existing = None
        for selection in self.project.selections:
            if selection.name == name:
                existing = selection
                break
        if existing is not None:
            self.project.update_selection_seats(existing.id, seats)
            self.toast("已更新选区「%s」" % name)
        else:
            self.project.add_selection(name, seats)
            self.toast("已保存选区「%s」（%d 个座位）" % (name, len(set(seats))))
        self.selection_panel.refresh()

    def _on_selection_deleted(self, selection_id: str) -> None:
        if self._confirm("删除该选区？引用它的规则会被停用。"):
            self.project.remove_selection(selection_id)
            self._refresh_all()

    def _on_selection_renamed(self, selection_id: str, name: str) -> None:
        if self.project.rename_selection(selection_id, name):
            self.selection_panel.refresh()
            self.rule_panel.refresh()

    # ============================================================ 轮换
    def _on_rotation_preview(self, plan) -> None:
        self._pending_rotation_preview = plan
        changed = []
        for key, _old, _new in plan.changes:
            coord = try_parse_key(key)
            if coord is not None:
                changed.append(coord)
        if changed:
            self.grid.set_selected(changed)
        self.toast("轮换预览：变动 %d 处%s" % (
            len(plan.changes), "（存在冲突，详见提示）" if plan.warnings else ""))

    def _on_rotation_apply(self, plan) -> None:
        if plan is None:
            return
        if plan.warnings:
            if not self._confirm("轮换后存在问题：\n\n%s\n\n仍然应用吗？" % "\n".join(plan.warnings)):
                return
        self._push_history("应用轮换")
        try:
            record = self.rotation_service.apply(plan, plan.description)
        except RotationError as exc:
            QMessageBox.warning(self, "轮换失败", str(exc))
            return
        self.grid.refresh()
        self._update_conflicts()
        self._update_status()
        self.rotation_panel.refresh()
        self.student_panel.refresh()
        self.toast("已应用轮换，记录为第 %d 周" % record.week)

    def _on_rotation_rollback(self, week: int) -> None:
        if not self._confirm("回退到第 %d 周的座位方案？" % week):
            return
        self._push_history("回退到第 %d 周" % week)
        if self.rotation_service.rollback(int(week)):
            self.grid.refresh()
            self._update_conflicts()
            self._update_status()
            self.toast("已回退到第 %d 周" % week)
        else:
            self.toast("找不到第 %d 周的记录" % week)

    # ============================================================ 视图
    def _on_show_sid(self, flag: bool) -> None:
        self.grid.set_show_sid(flag)

    def _on_show_title(self, flag: bool) -> None:
        self.grid.set_show_group_title(flag)

    def _on_show_selection(self, flag: bool) -> None:
        self.grid.set_selection_visible(flag)

    def _on_card_size(self, name: str) -> None:
        self.grid.set_card_size(name)
        for key, act in self.act_size.items():
            act.setChecked(key == name)

    # ============================================================ 文件
    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        self._rebind_project(new_project())
        self.toast("已新建项目：默认 3 组 × 6 行 × 2 列")

    def open_project(self, path: str = "") -> None:
        if not path:
            if not self._confirm_discard():
                return
            path, _ = QFileDialog.getOpenFileName(self, "打开项目", self._last_dir(), config.PROJECT_FILTER)
            if not path:
                return
        try:
            project = JsonProjectStore.load(path)
        except ProjectStoreError as exc:
            QMessageBox.warning(self, "无法打开", str(exc))
            return
        self._rebind_project(project)
        self._remember_dir(path)
        self._add_recent(path)
        self.toast("已打开 %s（%d 名学生）" % (os.path.basename(path), len(project.students)))

    def save_project(self) -> bool:
        if not self.project.path:
            return self.save_project_as()
        try:
            JsonProjectStore.save(self.project, self.project.path)
        except ProjectStoreError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        JsonProjectStore.clear_autosave()
        self._add_recent(self.project.path)
        self.setWindowTitle(self._window_title())
        self.toast("已保存到 %s" % self.project.path)
        return True

    def save_project_as(self) -> bool:
        default = self.project.path or self._default_name("座位表.seatproj")
        path, _ = QFileDialog.getSaveFileName(self, "另存为", default, config.PROJECT_FILTER)
        if not path:
            return False
        self.project.path = path
        return self.save_project()

    def _rebind_project(self, project: Project) -> None:
        """切换到另一个 Project：解绑旧项目、重建服务与面板绑定。"""
        previous = self.project
        if previous is not None:
            previous.unsubscribe(self._on_project_event)
        self.project = project
        project.subscribe(self._on_project_event)

        self.student_service = StudentService(project)
        self.rotation_service = RotationService(project)
        self.history.reset(project.assignment, "打开项目")
        self._pending_sids = []
        self._conflicts = {}
        self._locked_seats = set()
        self._last_solution = None
        self._pending_rotation_preview = None
        self.grid.set_project(project)
        self._set_panel_project(self.student_panel, self.student_service)
        self._set_panel_project(self.rule_panel, None)
        self._set_panel_project(self.selection_panel, None)
        self._set_panel_project(self.rotation_panel, None)
        self._refresh_all()
        self.grid.set_locked_seats(self._locked_seats)

    def _set_panel_project(self, panel, service=None) -> None:
        """把面板切到当前项目（面板实现 set_project；否则退化为直接赋值 + refresh）。"""
        setter = getattr(panel, "set_project", None)
        if callable(setter):
            try:
                if service is not None:
                    setter(self.project, service)
                else:
                    setter(self.project)
                return
            except TypeError:
                try:
                    setter(self.project)
                    return
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                pass
        for attr, value in (("project", self.project), ("service", service)):
            if value is None:
                continue
            try:
                setattr(panel, attr, value)
            except Exception:  # noqa: BLE001
                pass
        refresh = getattr(panel, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ 最近文件
    def _settings(self) -> QSettings:
        return QSettings(config.ORG_NAME, config.APP_ID)

    def _recent_files(self) -> List[str]:
        value = self._settings().value(config.SK_RECENT_FILES, [])
        if isinstance(value, str):
            value = [value]
        return [str(v) for v in (value or []) if v]

    def _add_recent(self, path: str) -> None:
        items = [p for p in self._recent_files() if os.path.normcase(p) != os.path.normcase(path)]
        items.insert(0, path)
        self._settings().setValue(config.SK_RECENT_FILES, items[:MAX_RECENT])
        self._update_recent_menu()

    def _update_recent_menu(self) -> None:
        self.recent_menu.clear()
        items = [p for p in self._recent_files() if os.path.exists(p)]
        if not items:
            act = self.recent_menu.addAction("（暂无）")
            act.setEnabled(False)
            return
        for path in items:
            act = self.recent_menu.addAction(os.path.basename(path))
            act.setToolTip(path)
            act.triggered.connect(lambda _c, p=path: self.open_project(p))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("清除最近记录", self._clear_recent)

    def _clear_recent(self) -> None:
        self._settings().setValue(config.SK_RECENT_FILES, [])
        self._update_recent_menu()

    def _last_dir(self) -> str:
        return str(self._settings().value(config.SK_LAST_DIR, str(Path.home())))

    def _remember_dir(self, path: str) -> None:
        self._settings().setValue(config.SK_LAST_DIR, str(Path(path).parent))

    def _default_name(self, name: str) -> str:
        return str(Path(self._last_dir()) / name)

    # ------------------------------------------------------------ 自动保存
    def _autosave(self) -> None:
        if not self.project.students and not self.project.assignment:
            return
        JsonProjectStore.autosave(self.project)

    def _maybe_recover(self) -> None:
        info = JsonProjectStore.autosave_info()
        if not info.get("exists"):
            return
        if self.project.students or self.project.assignment:
            return
        answer = QMessageBox.question(
            self, "发现自动保存",
            "检测到 %s 的自动保存内容，是否恢复？" % info.get("time", ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            JsonProjectStore.clear_autosave()
            return
        project = JsonProjectStore.load_autosave()
        if project is None:
            self.toast("自动保存内容已损坏，无法恢复")
            return
        self._rebind_project(project)
        self.toast("已恢复自动保存内容")

    def _maybe_welcome(self) -> None:
        settings = self._settings()
        if settings.value(config.SK_WELCOME_SHOWN, False, type=bool):
            return
        settings.setValue(config.SK_WELCOME_SHOWN, True)
        self.show_help()

    # ------------------------------------------------------------ 设置
    def _restore_settings(self) -> None:
        settings = self._settings()
        geometry = settings.value(config.SK_GEOMETRY)
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = settings.value(config.SK_STATE)
        if state is not None:
            self.restoreState(state)
        self.act_show_sid.setChecked(settings.value(config.SK_SHOW_SID, True, type=bool))
        self.act_show_title.setChecked(settings.value(config.SK_SHOW_GROUP_TITLE, True, type=bool))
        self.grid.set_show_sid(self.act_show_sid.isChecked())
        self.grid.set_show_group_title(self.act_show_title.isChecked())

    def _save_settings(self) -> None:
        settings = self._settings()
        settings.setValue(config.SK_GEOMETRY, self.saveGeometry())
        settings.setValue(config.SK_STATE, self.saveState())
        settings.setValue(config.SK_SHOW_SID, self.act_show_sid.isChecked())
        settings.setValue(config.SK_SHOW_GROUP_TITLE, self.act_show_title.isChecked())

    # ------------------------------------------------------------ 帮助
    def show_help(self) -> None:
        steps = "\n".join(config.WELCOME_STEPS)
        text = (
            "<b>五分钟上手</b><br><pre style='font-family:inherit;'>%s</pre>"
            "<b>常用快捷键</b>"
            "<table cellpadding='3'>"
            "<tr><td>Ctrl+N / Ctrl+O / Ctrl+S</td><td>新建 / 打开 / 保存项目</td></tr>"
            "<tr><td>Ctrl+I</td><td>导入学生名单</td></tr>"
            "<tr><td>Ctrl+E / Ctrl+Shift+E</td><td>导出 Excel / PNG 座位表</td></tr>"
            "<tr><td>Ctrl+Z / Ctrl+Y</td><td>撤销 / 重做</td></tr>"
            "<tr><td>Delete</td><td>清空选中座位</td></tr>"
            "<tr><td>Ctrl+D</td><td>设为 / 取消空置</td></tr>"
            "<tr><td>Ctrl+A</td><td>全选座位</td></tr>"
            "<tr><td>Ctrl+L / Ctrl+Shift+L</td><td>锁定选中座位 / 解除锁定</td></tr>"
            "<tr><td>Ctrl+B</td><td>教室布局设置</td></tr>"
            "<tr><td>F5 / Ctrl+R</td><td>一键排位 / 换一批</td></tr>"
            "<tr><td>F1</td><td>本说明</td></tr>"
            "</table>"
            "<b>鼠标操作</b>"
            "<table cellpadding='3'>"
            "<tr><td>在名单里选中学生 → 点击空座位</td><td>学生入座</td></tr>"
            "<tr><td>从名单拖学生到座位</td><td>学生入座</td></tr>"
            "<tr><td>从座位拖到另一个座位</td><td>两人交换 / 移动到空位</td></tr>"
            "<tr><td>在空白处拖拽框选 / Ctrl+点击</td><td>选择多个座位</td></tr>"
            "<tr><td>右键座位</td><td>清空 / 空置 / 锁定</td></tr>"
            "<tr><td>悬停座位 0.4 秒</td><td>查看学生完整信息</td></tr>"
            "</table>"
        ) % steps
        box = QMessageBox(self)
        box.setWindowTitle("使用说明")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(text)
        box.exec()

    def show_about(self) -> None:
        QMessageBox.about(
            self, "关于 %s" % config.APP_NAME,
            "<b>%s</b> v%s<br><br>"
            "面向中小学教师的单机教室座位编排工具。<br>"
            "全部数据保存在本地项目文件（.seatproj）中，无网络依赖、无账号体系。<br><br>"
            "技术栈：Python + PyQt6 + openpyxl" % (config.APP_NAME, config.VERSION),
        )

    # ------------------------------------------------------------ 杂项
    def _confirm(self, text: str, title: str = "确认") -> bool:
        answer = QMessageBox.question(
            self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_discard(self) -> bool:
        if not self.project.dirty:
            return True
        answer = QMessageBox.question(
            self, "尚未保存",
            "当前项目有未保存的改动，是否先保存？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        if answer == QMessageBox.StandardButton.Discard:
            return True
        return False

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._confirm_discard():
            event.ignore()
            return
        self._save_settings()
        JsonProjectStore.clear_autosave()
        event.accept()
