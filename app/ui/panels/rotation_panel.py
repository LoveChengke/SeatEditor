"""自动轮换面板（PRD F5）。

模式选择（区域轮换 / 按排平移 / 按列平移 / 自定义向量）、参数控件、
「预览」生成 :class:`RotationPlan`、「应用轮换」、轮换历史与回退。

面板只做**预览**：``RotationService`` 生成方案后发 ``preview_ready``，
应用与回退都由主窗口执行。
"""

from __future__ import annotations

import time
from typing import List, Optional, Set

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ..common import button, confirm, hline, warn
from .base import ProjectPanel
from ...models.project import EV_ANY, EV_ASSIGNMENT, EV_HISTORY, EV_SELECTIONS, Project
from ...services.rotation_service import RotationError, RotationOptions, RotationService
from ..style.theme import PANEL_RULE_WIDTH, Color

MODE_REGION = "region"
MODE_ROWS = "rows"
MODE_COLS = "cols"
MODE_CUSTOM = "custom"

MODE_ITEMS = (
    ("区域轮换", MODE_REGION),
    ("按排平移", MODE_ROWS),
    ("按列平移", MODE_COLS),
    ("自定义向量", MODE_CUSTOM),
)


class RotationPanel(ProjectPanel):
    """自动轮换面板。"""

    preview_ready = pyqtSignal(object)        # RotationPlan
    apply_requested = pyqtSignal(object)      # RotationPlan
    rollback_requested = pyqtSignal(int)      # week

    def __init__(self, project: Project, parent: Optional[QWidget] = None) -> None:
        super().__init__(project, parent)
        self._service = RotationService(project)
        self._plan = None
        self._checked_ids: Set[str] = set()
        self._populating = False

        self.setObjectName("Panel")
        self.setMinimumWidth(max(220, PANEL_RULE_WIDTH - 60))

        self._build_ui()
        self.refresh()
        project.subscribe(self._on_project_event)

    # ------------------------------------------------------------ 构建界面
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel("自动轮换")
        title.setObjectName("PanelTitle")
        root.addWidget(title)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("RotationBody")
        body.setStyleSheet("background: transparent;")
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        form = QVBoxLayout(body)
        form.setContentsMargins(0, 0, 4, 0)
        form.setSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        mode_row.addWidget(QLabel("轮换方式"))
        self._mode_combo = QComboBox()
        for label, value in MODE_ITEMS:
            self._mode_combo.addItem(label, value)
        self._mode_combo.currentIndexChanged.connect(lambda _index: self._on_mode_changed())
        mode_row.addWidget(self._mode_combo, 1)
        form.addLayout(mode_row)

        self._build_region_host(form)
        self._build_shift_host(form)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        action_row.addWidget(button("预览", self._on_preview, "Primary", "生成轮换方案（不修改座位）"))
        action_row.addWidget(button("应用轮换", self._on_apply, tooltip="把预览方案写入座位表并记入历史"))
        form.addLayout(action_row)

        self._info_label = QLabel("")
        self._info_label.setObjectName("Hint")
        self._info_label.setWordWrap(True)
        form.addWidget(self._info_label)

        form.addWidget(hline())
        history_title = QLabel("轮换历史")
        history_title.setObjectName("PanelTitle")
        form.addWidget(history_title)

        self._history_list = QListWidget()
        self._history_list.setMinimumHeight(90)
        self._history_list.setMaximumHeight(170)
        form.addWidget(self._history_list)
        form.addWidget(button("回退到选中周", self._rollback, tooltip="恢复该周的座位方案"))
        form.addStretch(1)

        self._on_mode_changed()

    def _build_region_host(self, form: QVBoxLayout) -> None:
        self._region_host = QWidget()
        layout = QVBoxLayout(self._region_host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        hint = QLabel("勾选 2 个以上选区，学生按顺序整体轮换到下一个区域。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._selection_list = QListWidget()
        self._selection_list.setMinimumHeight(96)
        self._selection_list.setMaximumHeight(170)
        self._selection_list.itemChanged.connect(self._on_selection_item_changed)
        layout.addWidget(self._selection_list)

        self._keep_check = QCheckBox("保持区域内相对位置")
        self._keep_check.setChecked(True)
        self._keep_check.setToolTip("勾选：整片学生平移到下一区域；取消：把下一区域名单搬进本区域座位")
        self._keep_check.toggled.connect(lambda _checked: self._invalidate_plan())
        layout.addWidget(self._keep_check)
        form.addWidget(self._region_host)

    def _build_shift_host(self, form: QVBoxLayout) -> None:
        self._shift_host = QWidget()
        grid = QGridLayout(self._shift_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        self._row_label = QLabel("Δ 排")
        self._row_spin = QSpinBox()
        self._row_spin.setRange(-11, 11)
        self._row_spin.setValue(1)
        self._row_spin.valueChanged.connect(lambda _value: self._invalidate_plan())
        grid.addWidget(self._row_label, 0, 0)
        grid.addWidget(self._row_spin, 0, 1)

        self._col_label = QLabel("Δ 列")
        self._col_spin = QSpinBox()
        self._col_spin.setRange(-7, 7)
        self._col_spin.setValue(1)
        self._col_spin.valueChanged.connect(lambda _value: self._invalidate_plan())
        grid.addWidget(self._col_label, 1, 0)
        grid.addWidget(self._col_spin, 1, 1)

        self._wrap_check = QCheckBox("边缘自动回绕")
        self._wrap_check.setChecked(True)
        self._wrap_check.setToolTip("勾选：移出边界的同学回到该组另一侧")
        self._wrap_check.toggled.connect(lambda _checked: self._invalidate_plan())
        grid.addWidget(self._wrap_check, 2, 0, 1, 2)

        self._shift_hint = QLabel("按 (Δ排, Δ列) 平移全部学生；Δ 为负数表示向前 / 向左。")
        self._shift_hint.setObjectName("Hint")
        self._shift_hint.setWordWrap(True)
        grid.addWidget(self._shift_hint, 3, 0, 1, 2)
        form.addWidget(self._shift_host)

    # ------------------------------------------------------------ 对外接口
    def set_project(self, project: Project, service=None) -> None:
        """切换到另一个 :class:`Project`（新建 / 打开项目时由主窗口调用）。"""
        if project is None:
            return
        if self._project is not None:
            try:
                self._project.unsubscribe(self._on_project_event)
            except Exception:  # noqa: BLE001
                pass
        self._project = project
        self._service = RotationService(project)
        self._checked_ids = set()
        self._plan = None
        self._refresh_pending = False
        project.subscribe(self._on_project_event)
        self.refresh()

    def refresh(self) -> None:
        """按项目重建选区列表与轮换历史。"""
        if self._project is None:
            return
        self._plan = None
        self._rebuild_selections()
        self._rebuild_history()
        self._set_info("")

    def _rebuild_selections(self) -> None:
        self._populating = True
        try:
            self._selection_list.clear()
            selections = list(self._project.selections)
            if not selections:
                empty = QListWidgetItem("暂无选区，请先在「选区」页创建")
                empty.setFlags(Qt.ItemFlag.NoItemFlags)
                self._selection_list.addItem(empty)
                self._checked_ids = set()
                return
            for selection in selections:
                item = QListWidgetItem(selection.name)
                item.setData(Qt.ItemDataRole.UserRole, selection.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if selection.id in self._checked_ids else Qt.CheckState.Unchecked
                )
                item.setToolTip("%s（%d 座）" % (selection.name, len(selection.seats)))
                self._selection_list.addItem(item)
            self._checked_ids &= {selection.id for selection in selections}
        except Exception as exc:  # noqa: BLE001 - 刷新失败不应崩溃
            self._set_info("选区列表刷新失败：%s" % exc, error=True)
        finally:
            self._populating = False

    def _rebuild_history(self) -> None:
        self._history_list.clear()
        records = sorted(list(self._project.history), key=lambda record: record.week, reverse=True)
        if not records:
            empty = QListWidgetItem("暂无轮换记录")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._history_list.addItem(empty)
            return
        for record in records:
            try:
                stamp = time.strftime("%m-%d %H:%M", time.localtime(record.timestamp or 0))
            except (OverflowError, OSError, ValueError):
                stamp = "—"
            text = "第 %d 周" % record.week
            if record.label:
                text += " · %s" % record.label
            assigned = len([sid for sid in record.assignment.values() if sid])
            item = QListWidgetItem("%s（%s）" % (text, stamp))
            item.setData(Qt.ItemDataRole.UserRole, int(record.week))
            item.setToolTip("%s\n共 %d 个已分配座位" % (text, assigned))
            self._history_list.addItem(item)

    # ------------------------------------------------------------ 模式 / 参数
    def _on_mode_changed(self) -> None:
        mode = self._mode_combo.currentData()
        is_region = mode == MODE_REGION
        self._region_host.setVisible(is_region)
        self._shift_host.setVisible(not is_region)
        self._row_label.setVisible(mode in (MODE_ROWS, MODE_CUSTOM))
        self._row_spin.setVisible(mode in (MODE_ROWS, MODE_CUSTOM))
        self._col_label.setVisible(mode in (MODE_COLS, MODE_CUSTOM))
        self._col_spin.setVisible(mode in (MODE_COLS, MODE_CUSTOM))
        self._invalidate_plan()

    def _invalidate_plan(self) -> None:
        self._plan = None
        self._set_info("")

    def _on_selection_item_changed(self, item: QListWidgetItem) -> None:
        if self._populating:
            return
        selection_id = item.data(Qt.ItemDataRole.UserRole)
        if not selection_id:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._checked_ids.add(str(selection_id))
        else:
            self._checked_ids.discard(str(selection_id))
        self._invalidate_plan()

    def _checked_selection_ids(self) -> List[str]:
        result: List[str] = []
        for row in range(self._selection_list.count()):
            item = self._selection_list.item(row)
            selection_id = item.data(Qt.ItemDataRole.UserRole)
            if selection_id and item.checkState() == Qt.CheckState.Checked:
                result.append(str(selection_id))
        return result

    # ------------------------------------------------------------ 预览 / 应用
    def _build_plan(self):
        if self._project is None:
            self._set_info("当前没有打开的项目。", error=True)
            return None
        mode = self._mode_combo.currentData()
        options = RotationOptions(
            keep_relative=self._keep_check.isChecked(),
            wrap=self._wrap_check.isChecked(),
            skip_disabled=True,
        )
        try:
            if mode == MODE_REGION:
                selection_ids = self._checked_selection_ids()
                if len(selection_ids) < 2:
                    self._set_info("区域轮换至少需要勾选 2 个选区。", error=True)
                    return None
                return self._service.region_rotate(selection_ids, options)
            if mode == MODE_ROWS:
                return self._service.shift(self._row_spin.value(), 0, options=options)
            if mode == MODE_COLS:
                return self._service.shift(0, self._col_spin.value(), options=options)
            return self._service.shift(self._row_spin.value(), self._col_spin.value(), options=options)
        except RotationError as exc:
            self._set_info("轮换参数有误：%s" % exc, error=True)
            return None
        except Exception as exc:  # noqa: BLE001 - 服务异常不应崩溃界面
            self._set_info("轮换失败：%s" % exc, error=True)
            return None

    def _on_preview(self) -> None:
        plan = self._build_plan()
        if plan is None:
            return
        self._plan = plan
        lines = [plan.description or "轮换方案"]
        lines.append("影响 %d 个座位 · 共 %d 处变动" % (plan.moved, len(plan.changes)))
        if plan.warnings:
            lines.extend("⚠ %s" % warning for warning in plan.warnings)
            self._set_info("\n".join(lines), error=True)
        else:
            lines.append("✓ 未发现硬约束冲突")
            self._set_info("\n".join(lines))
        self.preview_ready.emit(plan)

    def _on_apply(self) -> None:
        if self._plan is None:
            self._warn("请先点击「预览」生成轮换方案。")
            return
        plan = self._plan
        if not self._confirm("确定应用该轮换方案吗？\n%s" % (plan.description or ""), "应用轮换"):
            return
        self.apply_requested.emit(plan)

    def _rollback(self) -> None:
        item = self._history_list.currentItem()
        week = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if week is None:
            self._warn("暂无轮换记录可回退。")
            return
        if not self._confirm("确定回退到第 %d 周的座位方案吗？" % int(week), "回退轮换"):
            return
        self.rollback_requested.emit(int(week))

    # ------------------------------------------------------------ 项目事件
    def _on_project_event(self, event: str, _payload) -> None:
        if event not in (EV_SELECTIONS, EV_HISTORY, EV_ASSIGNMENT, EV_ANY):
            return
        self._schedule_refresh()

    # ------------------------------------------------------------ 工具
    def _set_info(self, text: str, error: bool = False) -> None:
        self._info_label.setText(text)
        self._info_label.setStyleSheet("color: %s;" % (Color.DANGER if error else Color.TEXT_SECONDARY))

    def _confirm(self, text: str, title: str) -> bool:
        return confirm(self, text, title)

    def _warn(self, text: str, title: str = "提示") -> None:
        warn(self, text, title)
