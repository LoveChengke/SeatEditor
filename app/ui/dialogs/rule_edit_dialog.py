"""规则编辑对话框：表单由 ``models.rule.RULE_SPECS[kind].fields`` 动态生成。

支持全部 12 种规则；控件类型由 ``F_*`` 常量决定，新增规则种类无需改这里。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QFrame, QLabel, QLineEdit, QMessageBox, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ...models.rule import (
    F_ATTR, F_BOOL, F_CHOICE, F_INT, F_SELECTION, F_SEAT, F_STUDENT, F_TAG, F_TEXT,
    HARD_KINDS, RULE_SPECS, SOFT_KINDS, Rule, make_rule,
)
from ...utils.natural_sort import natural_key
from ...utils.seat_key import make_key


def _hline() -> QFrame:
    """1px 分隔线（QSS 中的 ``HLine``）。"""
    line = QFrame()
    line.setObjectName("HLine")
    line.setFixedHeight(1)
    return line


class RuleEditDialog(QDialog):
    """新增 / 编辑一条规则；接受后 ``result_rule`` 为 ``Rule``。"""

    def __init__(self, project, rule: Optional[Rule] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self.rule = rule
        self.result_rule: Optional[Rule] = None
        self._widgets: Dict[str, QWidget] = {}
        self.setWindowTitle("编辑规则" if rule is not None else "添加规则")
        self.setMinimumWidth(480)
        self._build_ui()
        self._rebuild_fields()
        self.adjustSize()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        title = QLabel("编辑规则" if self.rule is not None else "添加规则")
        title.setObjectName("PanelTitle")
        root.addWidget(title)
        root.addWidget(_hline())

        head = QFormLayout()
        head.setSpacing(6)
        self._kind_combo = QComboBox()
        for kind in list(HARD_KINDS) + list(SOFT_KINDS):
            spec = RULE_SPECS.get(kind)
            if spec is None:
                continue
            self._kind_combo.addItem(
                ("硬约束 · " if spec.is_hard else "软约束 · ") + spec.label, kind
            )
        if self.rule is not None:
            index = self._kind_combo.findData(self.rule.kind)
            if index >= 0:
                self._kind_combo.setCurrentIndex(index)
            self._kind_combo.setEnabled(False)
        self._kind_combo.currentIndexChanged.connect(self._rebuild_fields)
        head.addRow("规则类型", self._kind_combo)
        self._desc_label = QLabel("")
        self._desc_label.setObjectName("Hint")
        self._desc_label.setWordWrap(True)
        head.addRow("", self._desc_label)
        root.addLayout(head)

        self._fields_host = QWidget()
        self._form = QFormLayout(self._fields_host)
        self._form.setSpacing(8)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self._fields_host)
        area.setMinimumHeight(220)
        root.addWidget(area, 1)

        tail = QFormLayout()
        tail.setSpacing(6)
        self._weight_spin = QDoubleSpinBox()
        self._weight_spin.setRange(0.0, 99.0)
        self._weight_spin.setSingleStep(0.1)
        self._weight_spin.setDecimals(2)
        self._weight_spin.setValue(float(getattr(self.rule, "weight", 1.0) or 1.0))
        self._weight_label = QLabel("权重")
        tail.addRow(self._weight_label, self._weight_spin)
        self._enabled_check = QCheckBox("启用该规则")
        self._enabled_check.setChecked(bool(getattr(self.rule, "enabled", True)))
        tail.addRow("", self._enabled_check)
        root.addLayout(tail)

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

    def _current_kind(self) -> str:
        data = self._kind_combo.currentData()
        return str(data) if data else ""

    def _base_rule(self) -> Optional[Rule]:
        kind = self._current_kind()
        if self.rule is not None and self.rule.kind == kind:
            return self.rule
        return make_rule(kind)

    # ------------------------------------------------------------ 动态表单
    def _rebuild_fields(self, *_args) -> None:
        while self._form.count():
            item = self._form.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._widgets = {}

        spec = RULE_SPECS.get(self._current_kind())
        if spec is None:
            return
        self._desc_label.setText(spec.description)
        self._weight_label.setVisible(spec.has_weight)
        self._weight_spin.setVisible(spec.has_weight)
        if spec.has_weight and self.rule is None:
            self._weight_spin.setValue(float(spec.default_weight or 1.0))

        base = self._base_rule()
        params: Dict[str, Any] = dict(base.params) if base is not None else {}
        if not spec.fields:
            hint = QLabel("该规则不需要额外参数，直接确定即可。")
            hint.setObjectName("Hint")
            self._form.addRow(hint)
            return
        for field in spec.fields:
            widget = self._make_widget(field, params.get(field.key))
            self._widgets[field.key] = widget
            label = QLabel(field.label)
            if field.hint:
                label.setToolTip(field.hint)
            self._form.addRow(label, widget)

    def _pairs(self, field) -> List[Tuple[str, str]]:
        """下拉框的 ``(显示文本, 数据)`` 列表。"""
        blank = "（未指定）" if field.kind in (F_STUDENT, F_SEAT) else "（不使用）"
        leading = [(blank, "")] if field.optional else []
        if field.kind == F_STUDENT:
            students = sorted(self.project.students, key=lambda s: natural_key(s.sid))
            return leading + [("%s（%s）" % (s.name, s.sid), s.sid) for s in students]
        if field.kind == F_TAG:
            return leading + [(name, name) for name in self.project.tag_names()]
        if field.kind == F_SELECTION:
            return leading + [
                ("%s（%d 座）" % (sel.name, len(sel)), sel.id) for sel in self.project.selections
            ]
        if field.kind == F_ATTR:
            return leading + [(name, name) for name in self.project.attr_names()]
        if field.kind == F_CHOICE:
            return list(field.choices)
        if field.kind == F_SEAT:
            pairs = []
            for gi, group in enumerate(self.project.layout.groups):
                for row in range(group.rows):
                    for col in range(group.cols):
                        pairs.append(("第 %d 组 第 %d 排 第 %d 列" % (gi + 1, row + 1, col + 1),
                                      make_key((gi, row, col))))
            return leading + pairs
        return []

    def _make_widget(self, field, value: Any) -> QWidget:
        if field.kind == F_INT:
            spin = QSpinBox()
            maximum = int(field.maximum)
            if field.key == "rows":
                maximum = max(1, min(maximum, int(self.project.layout.max_rows)))
            spin.setRange(int(field.minimum), max(int(field.minimum), maximum))
            try:
                spin.setValue(int(value if value is not None else field.default))
            except (TypeError, ValueError):
                spin.setValue(int(field.default or field.minimum))
            return spin
        if field.kind == F_BOOL:
            check = QCheckBox()
            check.setChecked(bool(value))
            return check
        if field.kind == F_TEXT:
            edit = QLineEdit()
            edit.setText("" if value is None else str(value))
            return edit
        combo = QComboBox()
        combo.setMinimumWidth(200)
        for text, data in self._pairs(field):
            combo.addItem(text, data)
        current = "" if value is None else str(value)
        index = combo.findData(current)
        if index < 0 and current:
            combo.addItem("（已失效）%s" % current, current)
            index = combo.count() - 1
        combo.setCurrentIndex(max(0, index))
        return combo

    # ------------------------------------------------------------ 结果
    def _value_of(self, field, widget: QWidget) -> Any:
        if field.kind == F_INT:
            return int(widget.value())  # type: ignore[attr-defined]
        if field.kind == F_BOOL:
            return bool(widget.isChecked())
        if field.kind == F_TEXT:
            return str(widget.text()).strip()  # type: ignore[attr-defined]
        data = widget.currentData()  # type: ignore[attr-defined]
        return "" if data is None else str(data)

    def _collect_rule(self) -> Optional[Rule]:
        spec = RULE_SPECS.get(self._current_kind())
        base = self._base_rule()
        if spec is None or base is None:
            return None
        params: Dict[str, Any] = {}
        for field in spec.fields:
            widget = self._widgets.get(field.key)
            if widget is not None:
                params[field.key] = self._value_of(field, widget)
        weight = float(base.weight)
        if spec.has_weight:
            weight = float(self._weight_spin.value()) or float(spec.default_weight or 1.0)
        return Rule(
            id=base.id, type=base.type, kind=base.kind, params=params,
            enabled=self._enabled_check.isChecked(), weight=weight, name=base.name,
        )

    def accept(self) -> None:
        rule = self._collect_rule()
        if rule is None:
            QMessageBox.warning(self, "无法保存", "未知的规则类型，请重新选择。")
            return
        errors: List[str] = rule.validate()
        if errors:
            QMessageBox.warning(self, "规则不完整", "\n".join("· %s" % e for e in errors))
            return
        self.result_rule = rule
        super().accept()
