"""规则面板。

「硬约束 / 软约束」两个分组列表，每项带勾选框与「人话描述」；
工具栏提供「添加规则」（按 ``HARD_KINDS`` / ``SOFT_KINDS`` 分组）、
「编辑」、「删除」。勾选 / 取消勾选直接切换 ``rule.enabled``。

这是契约里唯一允许面板直接改项目的例外：只做
``project.add_rule`` / ``project.remove_rule`` / ``project.notify("rules")``。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMenu, QToolButton,
    QVBoxLayout, QWidget,
)

from ..common import button, confirm, hline, warn
from .base import ProjectPanel
from ...models.project import EV_ANY, EV_RULES, EV_SELECTIONS, EV_STUDENTS, EV_TAGS, Project
from ...models.rule import (
    HARD, HARD_KINDS, RULE_SPECS, SOFT, SOFT_KINDS, Rule, describe_rule, make_rule,
)
from ..style.theme import PANEL_RULE_WIDTH


class RulePanel(ProjectPanel):
    """硬约束 / 软约束列表面板。"""

    rules_changed = pyqtSignal()

    def __init__(self, project: Project, parent: Optional[QWidget] = None) -> None:
        super().__init__(project, parent)
        self._updating = False
        self._lists: Dict[str, QListWidget] = {}

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

        title = QLabel("排位规则")
        title.setObjectName("PanelTitle")
        root.addWidget(title)

        hint = QLabel("勾选启用规则，双击编辑；硬约束必须满足，软约束按权重打分。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self._add_button = QToolButton()
        self._add_button.setText("添加规则")
        self._add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._add_button.setMenu(self._build_add_menu())
        toolbar.addWidget(self._add_button, 1)
        toolbar.addWidget(button("编辑", self._edit_rule))
        toolbar.addWidget(button("删除", self._delete_rule, "Danger", "删除选中规则"))
        root.addLayout(toolbar)
        root.addWidget(hline())

        self._hard_title = QLabel("硬约束")
        self._hard_title.setObjectName("PanelTitle")
        root.addWidget(self._hard_title)
        self._hard_list = self._make_list(HARD)
        root.addWidget(self._hard_list, 1)

        self._soft_title = QLabel("软约束")
        self._soft_title.setObjectName("PanelTitle")
        root.addWidget(self._soft_title)
        self._soft_list = self._make_list(SOFT)
        root.addWidget(self._soft_list, 1)

        self._error_label = QLabel("")
        self._error_label.setObjectName("Hint")
        self._error_label.setWordWrap(True)
        root.addWidget(self._error_label)

    def _make_list(self, rule_type: str) -> QListWidget:
        widget = QListWidget(self)
        widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        widget.setMinimumHeight(90)
        widget.setAlternatingRowColors(False)
        widget.itemChanged.connect(self._on_item_changed)
        widget.itemDoubleClicked.connect(lambda _item: self._edit_rule())
        self._lists[rule_type] = widget
        return widget

    def _build_add_menu(self) -> QMenu:
        menu = QMenu(self)
        for title, kinds in (("硬约束", HARD_KINDS), ("软约束", SOFT_KINDS)):
            menu.addSection(title)
            for kind in kinds:
                spec = RULE_SPECS.get(kind)
                if spec is None:
                    continue
                action = menu.addAction(spec.label)
                action.setToolTip(spec.description)
                action.triggered.connect(lambda _checked=False, k=kind: self._add_rule(k))
        return menu

    # 对外接口
    def refresh(self) -> None:
        """按 ``project.rules`` 重建两个列表（尽量保留原选中项）。"""
        if self._project is None:
            return
        selected = self._current_rule_id()
        self._updating = True
        try:
            rules = list(self._project.rules)
            self._fill(self._hard_list, [r for r in rules if r.is_hard])
            self._fill(self._soft_list, [r for r in rules if r.is_soft])
            self._hard_title.setText("硬约束（%d）" % self._hard_list.count())
            self._soft_title.setText("软约束（%d）" % self._soft_list.count())
        except Exception as exc:  # 刷新失败不应崩溃
            self._error_label.setText("规则列表刷新失败：%s" % exc)
        finally:
            self._updating = False
        if selected:
            self._select_rule(selected)

    def _fill(self, widget: QListWidget, rules: List[Rule]) -> None:
        widget.clear()
        for rule in rules:
            item = QListWidgetItem(self._describe(rule))
            item.setData(Qt.ItemDataRole.UserRole, rule.id)
            spec = rule.spec
            if spec is not None:
                item.setToolTip(spec.description)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
            widget.addItem(item)

    def _describe(self, rule: Rule) -> str:
        try:
            text = describe_rule(rule, self._project.student_name, self._project.selection_name)
        except Exception:
            text = rule.label
        if rule.is_soft:
            text = "%s　（权重 %g）" % (text, rule.weight)
        return text

    # 选中项
    def _rule_of_item(self, item: Optional[QListWidgetItem]) -> Optional[Rule]:
        if item is None or self._project is None:
            return None
        rule_id = item.data(Qt.ItemDataRole.UserRole)
        return self._project.get_rule(str(rule_id)) if rule_id else None

    def _active_list(self) -> Optional[QListWidget]:
        for widget in (self._hard_list, self._soft_list):
            if widget.hasFocus() and widget.currentItem() is not None:
                return widget
        for widget in (self._hard_list, self._soft_list):
            if widget.currentItem() is not None:
                return widget
        return None

    def _current_rule(self) -> Optional[Rule]:
        widget = self._active_list()
        return self._rule_of_item(widget.currentItem() if widget is not None else None)

    def _current_rule_id(self) -> str:
        rule = self._current_rule()
        return rule.id if rule is not None else ""

    def _select_rule(self, rule_id: str) -> None:
        for widget in (self._hard_list, self._soft_list):
            for row in range(widget.count()):
                item = widget.item(row)
                if str(item.data(Qt.ItemDataRole.UserRole)) == rule_id:
                    widget.setCurrentItem(item)
                    return

    # 勾选
    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._updating:
            return
        rule = self._rule_of_item(item)
        if rule is None:
            return
        enabled = item.checkState() == Qt.CheckState.Checked
        if rule.enabled == enabled:
            return
        rule.enabled = enabled
        try:
            self._project.notify(EV_RULES)
        except Exception as exc:
            self._error_label.setText("规则状态保存失败：%s" % exc)
        self.rules_changed.emit()

    # 增删改
    def _add_rule(self, kind: str) -> None:
        rule = make_rule(kind)
        if rule is None:
            self._warn("未知的规则类型：%s" % kind)
            return
        result = self._run_dialog(rule)
        if result is None:
            return
        try:
            if not self._project.add_rule(result):
                self._warn("规则添加失败（可能是 ID 冲突）。")
                return
        except Exception as exc:
            self._warn("规则添加失败：%s" % exc)
            return
        self._error_label.setText("")
        self.rules_changed.emit()
        self.refresh()

    def _edit_rule(self) -> None:
        rule = self._current_rule()
        if rule is None:
            self._warn("请先在上方列表中选择一条规则。")
            return
        result = self._run_dialog(rule)
        if result is None:
            return
        try:
            if result is rule:
                self._project.notify(EV_RULES)
            else:
                self._project.remove_rule(rule.id)
                if not self._project.add_rule(result):
                    self._project.add_rule(rule)   # 回滚，避免规则丢失
                    self._warn("规则保存失败，已还原原有规则。")
                    return
        except Exception as exc:
            self._warn("规则保存失败：%s" % exc)
            return
        self._error_label.setText("")
        self.rules_changed.emit()
        self.refresh()

    def _delete_rule(self) -> None:
        rule = self._current_rule()
        if rule is None:
            self._warn("请先在上方列表中选择一条规则。")
            return
        if not self._confirm("确定删除规则「%s」吗？" % self._describe(rule), "删除规则"):
            return
        try:
            if not self._project.remove_rule(rule.id):
                self._warn("该规则已不存在。")
                return
        except Exception as exc:
            self._warn("删除规则失败：%s" % exc)
            return
        self._error_label.setText("")
        self.rules_changed.emit()
        self.refresh()

    def _run_dialog(self, rule: Rule) -> Optional[Rule]:
        """懒加载规则编辑对话框；缺失时给出提示而不是崩溃。"""
        try:
            from ..dialogs.rule_edit_dialog import RuleEditDialog
        except Exception as exc:
            self._warn("规则编辑功能不可用：%s" % exc)
            return None
        try:
            dialog = RuleEditDialog(self._project, rule, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            result = dialog.result_rule
        except Exception as exc:
            self._warn("规则编辑失败：%s" % exc)
            return None
        if result is None:
            return None
        return result

    # 项目事件
    def _on_project_event(self, event: str, _payload) -> None:
        if event not in (EV_RULES, EV_TAGS, EV_SELECTIONS, EV_STUDENTS, EV_ANY):
            return
        self._schedule_refresh()

    # 工具
    def _confirm(self, text: str, title: str) -> bool:
        return confirm(self, text, title)

    def _warn(self, text: str, title: str = "提示") -> None:
        warn(self, text, title)
