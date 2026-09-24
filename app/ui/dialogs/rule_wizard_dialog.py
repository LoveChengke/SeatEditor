"""自定义规则向导：按「谁 → 要求 → 怎么样」拼出一条规则。

**不做表达式解析**：只是把教师选的组合映射到**已有的规则种类**上，
所以结果可解释、可校验，也能在规则面板里照常编辑。

这里的预览文案一律由 ``models.rule.describe_rule()`` 生成，绝不自己拼一套中文——
否则"预览说 A、引擎做 B"这类错位没有任何自检抓得住。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QMessageBox, QSpinBox, QVBoxLayout, QWidget,
)

from ..common import hline
from ...models.rule import HARD, RULE_SPECS, SOFT, Rule, describe_rule, make_rule
from ...utils.natural_sort import natural_key


# 「怎么样」的可选目标。字段含义：
#   kind      —— 映射到的规则种类
#   subject   —— 对象参数的后缀（"" = tag/sid，"a" = tag_a/sid_a）
#   need      —— 还需要填的目标参数，取值见 _PARAM_FIELDS
#   fixed     —— 固定写死的参数
#   tags_only —— 只支持按标签选对象（该规则的对象参数本来就是标签类型）
GOALS: Tuple[Dict[str, Any], ...] = (
    {"key": "in_region", "label": "必须在某个选区内", "kind": "region_required", "need": ("selection",)},
    {"key": "out_region", "label": "不得进入某个选区", "kind": "region_forbidden", "need": ("selection",)},
    {"key": "front_rows", "label": "必须坐在讲台侧的前 N 排", "kind": "front_required", "need": ("rows",)},
    {"key": "must_desk", "label": "必须与…同桌", "kind": "must_desk", "subject": "a", "need": ("object_b",)},
    {"key": "forbid_desk", "label": "不得与…同桌", "kind": "forbid_desk", "subject": "a", "need": ("object_b",)},
    {"key": "must_adjacent", "label": "必须与…前后左右相邻", "kind": "must_adjacent", "subject": "a", "need": ("object_b",)},
    {"key": "forbid_adjacent", "label": "不得与…前后左右相邻", "kind": "forbid_adjacent_pair",
     "subject": "a", "need": ("object_b",)},
    {"key": "same_group", "label": "必须与…在同一个组", "kind": "same_area", "subject": "a",
     "need": ("object_b",), "fixed": {"mode": "group"}},
    {"key": "front_prefer", "label": "尽量坐前排", "kind": "front_prefer"},
    {"key": "back_prefer", "label": "尽量坐后排", "kind": "back_prefer"},
    {"key": "aisle_prefer", "label": "尽量靠过道", "kind": "aisle_prefer", "fixed": {"mode": "both"}},
    {"key": "near_prefer", "label": "尽量与…靠近", "kind": "near_prefer", "subject": "a", "need": ("object_b",)},
    {"key": "desk_pair", "label": "尽量与…同桌", "kind": "desk_pair", "subject": "a",
     "need": ("object_b",), "fixed": {"mode": "same"}, "tags_only": True},
    {"key": "tag_disperse", "label": "尽量分散开", "kind": "tag_disperse", "tags_only": True},
    {"key": "tag_cluster", "label": "尽量聚在一起", "kind": "tag_cluster", "tags_only": True},
)


class RuleWizardDialog(QDialog):
    """拼装一条自定义规则；接受后 ``result_rule`` 为 ``Rule``。"""

    def __init__(self, project, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self.result_rule: Optional[Rule] = None
        self._updating = False
        self._param_widgets: Dict[str, QWidget] = {}
        self.setWindowTitle("自定义规则")
        self.setMinimumWidth(540)
        self._build_ui()
        self._rebuild()
        self.adjustSize()
        self.setMinimumSize(max(540, self.width()), self.height())

    # 界面
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        title = QLabel("自定义规则")
        title.setObjectName("PanelTitle")
        root.addWidget(title)
        root.addWidget(hline())
        hint = QLabel("按「谁 → 要求 → 怎么样」拼一句话，向导会自动挑好对应的规则种类，"
                      "确定后还能在规则面板里照常编辑。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._form = QFormLayout()
        self._form.setSpacing(8)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._subject_kind = QComboBox()
        self._subject_kind.addItem("标签", "tag")
        self._subject_kind.addItem("指定学生", "student")
        self._subject_kind.currentIndexChanged.connect(self._rebuild)
        self._form.addRow("对象是", self._subject_kind)

        self._subject_value = QComboBox()
        self._subject_value.setMinimumWidth(220)
        self._subject_value.currentIndexChanged.connect(self._rebuild)
        self._form.addRow("哪一些", self._subject_value)

        self._require = QComboBox()
        self._require.addItem("必须满足", HARD)
        self._require.addItem("尽量满足", SOFT)
        self._require.currentIndexChanged.connect(self._rebuild)
        self._form.addRow("要求", self._require)

        self._goal = QComboBox()
        self._goal.setMinimumWidth(260)
        self._goal.currentIndexChanged.connect(self._rebuild)
        self._form.addRow("怎么样", self._goal)

        self._param_host = QWidget()
        self._param_form = QFormLayout(self._param_host)
        self._param_form.setSpacing(8)
        self._param_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._form.addRow("", self._param_host)

        self._note = QLabel("")
        self._note.setObjectName("Hint")
        self._note.setWordWrap(True)
        self._form.addRow("", self._note)
        root.addLayout(self._form)
        root.addStretch(1)

        self._preview = QLabel("")
        self._preview.setObjectName("Hint")
        self._preview.setWordWrap(True)
        self._preview.setMinimumHeight(40)
        root.addWidget(self._preview)
        root.addWidget(hline())

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = box.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("确定")
        ok.setObjectName("Primary")
        ok.setDefault(True)
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    def _uses_tag(self) -> bool:
        return str(self._subject_kind.currentData() or "tag") == "tag"

    def _current_goal(self) -> Optional[Dict[str, Any]]:
        key = self._goal.currentData()
        for goal in GOALS:
            if goal["key"] == key:
                return goal
        return None

    def _goals_for(self, require: str) -> List[Dict[str, Any]]:
        """按「必须 / 尽量」筛出可选目标；再剔除当前对象类型表达不了的。"""
        result: List[Dict[str, Any]] = []
        for goal in GOALS:
            spec = RULE_SPECS.get(goal["kind"])
            if spec is None:
                continue
            if spec.is_hard != (require == HARD):
                continue
            if goal.get("tags_only") and not self._uses_tag():
                continue
            result.append(goal)
        return result

    def _fill_values(self, combo: QComboBox, use_tag: bool, current: str) -> None:
        combo.clear()
        if use_tag:
            for tag in self.project.tag_names():
                combo.addItem(tag, tag)
        else:
            for student in sorted(self.project.students, key=lambda s: natural_key(s.sid)):
                combo.addItem("%s（%s）" % (student.name, student.sid), student.sid)
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _rebuild(self) -> None:
        """任一控件变化后重建：目标列表、参数行、预览。"""
        if self._updating:
            return
        self._updating = True
        try:
            self._fill_values(self._subject_value, self._uses_tag(),
                              str(self._subject_value.currentData() or ""))
            require = str(self._require.currentData() or HARD)
            goals = self._goals_for(require)
            previous = str(self._goal.currentData() or "")
            self._goal.clear()
            for goal in goals:
                self._goal.addItem(goal["label"], goal["key"])
            index = self._goal.findData(previous)
            self._goal.setCurrentIndex(index if index >= 0 else 0)

            blocked = [g for g in GOALS if g.get("tags_only")]
            if blocked and not self._uses_tag():
                self._note.setText("「%s」这类目标只能按标签挑对象，换成「标签」后才可选。"
                                   % blocked[0]["label"])
            else:
                self._note.setText("")

            self._rebuild_params()
            self._update_preview()
        finally:
            self._updating = False

    def _rebuild_params(self) -> None:
        while self._param_form.count():
            item = self._param_form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._param_widgets = {}
        goal = self._current_goal()
        if goal is None:
            return
        for name in goal.get("need", ()):
            if name == "selection":
                combo = QComboBox()
                combo.setMinimumWidth(220)
                for selection in self.project.selections:
                    combo.addItem("%s（%d 座）" % (selection.name, len(selection.seats)), selection.id)
                combo.currentIndexChanged.connect(self._update_preview)
                self._param_widgets["selection"] = combo
                self._param_form.addRow("选区", combo)
            elif name == "rows":
                spin = QSpinBox()
                spin.setRange(1, max(1, int(self.project.layout.max_rows)))
                spin.setValue(min(2, max(1, int(self.project.layout.max_rows))))
                spin.valueChanged.connect(self._update_preview)
                self._param_widgets["rows"] = spin
                self._param_form.addRow("前 N 排", spin)
            elif name == "object_b":
                kind_combo = QComboBox()
                kind_combo.addItem("标签", "tag")
                kind_combo.addItem("指定学生", "student")
                if goal.get("tags_only"):
                    kind_combo.setCurrentIndex(0)
                    kind_combo.setEnabled(False)
                kind_combo.currentIndexChanged.connect(self._rebuild_other_values)
                self._param_widgets["object_b_kind"] = kind_combo
                value_combo = QComboBox()
                value_combo.setMinimumWidth(220)
                value_combo.currentIndexChanged.connect(self._update_preview)
                self._param_widgets["object_b_value"] = value_combo
                self._param_form.addRow("另一个对象", kind_combo)
                self._param_form.addRow("", value_combo)
                self._rebuild_other_values()

    def _rebuild_other_values(self, *_args: Any) -> None:
        combo = self._param_widgets.get("object_b_value")
        kind_combo = self._param_widgets.get("object_b_kind")
        if not isinstance(combo, QComboBox) or not isinstance(kind_combo, QComboBox):
            return
        use_tag = str(kind_combo.currentData() or "tag") == "tag"
        previous = str(combo.currentData() or "")
        blocked = self._updating
        self._updating = True
        try:
            self._fill_values(combo, use_tag, previous)
        finally:
            self._updating = blocked
        self._update_preview()

    # 收集
    def _collect(self) -> Optional[Rule]:
        goal = self._current_goal()
        if goal is None:
            return None
        rule = make_rule(goal["kind"])
        if rule is None:
            return None
        suffix = str(goal.get("subject") or "")
        subject_key = ("tag" if self._uses_tag() else "sid") + ("_" + suffix if suffix else "")
        rule.params[subject_key] = str(self._subject_value.currentData() or "")

        for name in goal.get("need", ()):
            if name == "selection":
                widget = self._param_widgets.get("selection")
                rule.params["selection"] = str(widget.currentData() or "") if widget else ""
            elif name == "rows":
                widget = self._param_widgets.get("rows")
                rule.params["rows"] = int(widget.value()) if isinstance(widget, QSpinBox) else 2
            elif name == "object_b":
                kind_combo = self._param_widgets.get("object_b_kind")
                value_combo = self._param_widgets.get("object_b_value")
                use_tag = isinstance(kind_combo, QComboBox) and str(kind_combo.currentData()) == "tag"
                other_key = ("tag" if use_tag else "sid") + "_b"
                rule.params[other_key] = (
                    str(value_combo.currentData() or "") if isinstance(value_combo, QComboBox) else "")
        rule.params.update(goal.get("fixed", {}))
        return rule

    def _update_preview(self, *_args: Any) -> None:
        """刷新预览。刻意不检查 ``_updating``：重建的最后一步就是刷新预览，
        那时防重入标志还立着，检查了会把预览永远留空。"""
        rule = self._collect()
        if rule is None:
            self._preview.setText("")
            return
        try:
            text = describe_rule(rule, self.project.student_name, self.project.selection_name)
        except Exception as exc:  # 预览失败不该拦住保存
            text = "（预览生成失败：%s）" % exc
        weight = RULE_SPECS[rule.kind].default_weight if rule.is_soft else None
        if weight is not None:
            text = "%s　（权重 %g）" % (text, weight)
        self._preview.setText("这条规则是：" + text)

    # 保存
    def accept(self) -> None:
        rule = self._collect()
        if rule is None:
            QMessageBox.warning(self, "无法保存", "请先选择要做的事情。")
            return
        errors = rule.validate()
        if errors:
            QMessageBox.warning(self, "规则不完整", "\n".join("· %s" % e for e in errors))
            return
        self.result_rule = rule
        super().accept()
