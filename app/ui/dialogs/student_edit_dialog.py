"""学生编辑对话框：学号 / 姓名 / 性别 / 标签 / 数值属性 / 备注。

接受时 ``result_student`` 为新的 ``Student``，且标签已通过 ``project.ensure_tag``
登记到项目标签库。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..common import fit_to_screen, hline
from ...models.student import Student

TAG_SPLIT = re.compile(r"[,，;；、|/\s]+")
GENDERS = (("", "（未填）"), ("男", "男"), ("女", "女"))


def _split_tags(text: str) -> List[str]:
    """把逗号分隔的标签文本拆成去重列表。"""
    result: List[str] = []
    for part in TAG_SPLIT.split(str(text or "")):
        name = part.strip()
        if name and name not in result:
            result.append(name)
    return result


class StudentEditDialog(QDialog):
    """新增 / 编辑一名学生；接受后 ``result_student`` 为 ``Student``。"""

    def __init__(self, project, student: Optional[Student] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self.student = student
        self.result_student: Optional[Student] = None
        self.setWindowTitle("编辑学生" if student is not None else "添加学生")
        self.setMinimumWidth(460)
        self._build_ui()
        self._load()
        self.adjustSize()
        fit_to_screen(self)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        title = QLabel("编辑学生信息" if self.student is not None else "添加学生")
        title.setObjectName("PanelTitle")
        root.addWidget(title)
        root.addWidget(hline())

        host = QWidget()
        body = QVBoxLayout(host)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(8)
        self._sid_edit = QLineEdit()
        self._sid_edit.setPlaceholderText("必填，唯一")
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("必填")
        self._gender_combo = QComboBox()
        for value, label in GENDERS:
            self._gender_combo.addItem(label, value)
        self._tag_edit = QLineEdit()
        self._tag_edit.setPlaceholderText("多个标签用逗号分隔，例如：班干部，视力差")
        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("可留空")
        form.addRow("学号", self._sid_edit)
        form.addRow("姓名", self._name_edit)
        form.addRow("性别", self._gender_combo)
        form.addRow("标签", self._build_tag_row())
        form.addRow("备注", self._note_edit)
        body.addLayout(form)

        body.addWidget(self._build_attr_box())
        tip = QLabel("学号重复、姓名为空、属性值无法解析都会在确定时提示。")
        tip.setObjectName("Hint")
        body.addWidget(tip)
        body.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

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

    def _build_tag_row(self) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._tag_edit, 1)
        self._tag_combo = QComboBox()
        self._tag_combo.addItem("选择已有标签…", "")
        for name in self.project.tag_names():
            self._tag_combo.addItem(name, name)
        self._tag_combo.setMinimumWidth(120)
        self._tag_combo.activated.connect(self._append_tag)
        layout.addWidget(self._tag_combo)
        return holder

    def _build_attr_box(self) -> QWidget:
        box = QGroupBox("数值属性")
        layout = QVBoxLayout(box)
        layout.setSpacing(6)
        hint = QLabel("例如 身高 168、视力 4.8；数值无法解析时会提示。")
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        self._attr_table = QTableWidget(0, 2)
        self._attr_table.setHorizontalHeaderLabels(["属性名", "数值"])
        header = self._attr_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._attr_table.verticalHeader().setVisible(False)
        self._attr_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._attr_table.setMinimumHeight(110)
        self._attr_table.setMaximumHeight(160)
        layout.addWidget(self._attr_table)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        add_btn = QPushButton("添加属性")
        del_btn = QPushButton("删除选中")
        del_btn.setObjectName("Ghost")
        add_btn.clicked.connect(lambda: self._add_attr_row("", ""))
        del_btn.clicked.connect(self._remove_attr_rows)
        buttons.addWidget(add_btn)
        buttons.addWidget(del_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return box

    def _append_tag(self, _index: int) -> None:
        name = self._tag_combo.currentData()
        if not name:
            return
        tags = _split_tags(self._tag_edit.text())
        if name not in tags:
            tags.append(name)
        self._tag_edit.setText("，".join(tags))

    def _add_attr_row(self, name, value) -> None:
        row = self._attr_table.rowCount()
        self._attr_table.insertRow(row)
        self._attr_table.setItem(row, 0, QTableWidgetItem(str(name)))
        self._attr_table.setItem(row, 1, QTableWidgetItem(str(value)))

    def _remove_attr_rows(self) -> None:
        rows = sorted({index.row() for index in self._attr_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._attr_table.removeRow(row)

    # 数据
    def _load(self) -> None:
        self._attr_table.setRowCount(0)
        if self.student is None:
            for name in self.project.attr_names()[:6]:
                self._add_attr_row(name, "")
            return
        student = self.student
        self._sid_edit.setText(student.sid)
        self._name_edit.setText(student.name)
        self._gender_combo.setCurrentIndex(max(0, self._gender_combo.findData(student.gender)))
        self._tag_edit.setText("，".join(student.tags))
        self._note_edit.setText(student.note)
        for name, value in student.attrs.items():
            self._add_attr_row(name, str(int(value)) if float(value).is_integer() else str(value))

    def _collect_attrs(self) -> Optional[Dict[str, float]]:
        attrs: Dict[str, float] = {}
        problems: List[str] = []
        for row in range(self._attr_table.rowCount()):
            name_item = self._attr_table.item(row, 0)
            value_item = self._attr_table.item(row, 1)
            name = (name_item.text() if name_item is not None else "").strip()
            text = (value_item.text() if value_item is not None else "").strip()
            if not name and not text:
                continue
            if not name:
                problems.append("第 %d 行缺少属性名" % (row + 1))
            elif text:
                try:
                    attrs[name] = float(text)
                except ValueError:
                    problems.append("第 %d 行「%s」的数值无法识别：%s" % (row + 1, name, text))
        if problems:
            QMessageBox.warning(self, "数值属性有误", "\n".join("· %s" % p for p in problems))
            return None
        return attrs

    def accept(self) -> None:
        sid = self._sid_edit.text().strip()
        name = self._name_edit.text().strip()
        if not sid:
            QMessageBox.warning(self, "信息不完整", "学号不能为空。")
            return
        if not name:
            QMessageBox.warning(self, "信息不完整", "姓名不能为空。")
            return
        existing = self.project.get_student(sid)
        if existing is not None and (self.student is None or existing.sid != self.student.sid):
            QMessageBox.warning(self, "学号重复", "学号 %s 已被「%s」占用。" % (sid, existing.name))
            return
        attrs = self._collect_attrs()
        if attrs is None:
            return
        tags = _split_tags(self._tag_edit.text())
        for tag in tags:
            self.project.ensure_tag(tag)
        self.result_student = Student(
            sid=sid, name=name, gender=str(self._gender_combo.currentData() or ""),
            tags=tags, attrs=attrs, note=self._note_edit.text().strip(),
        )
        super().accept()
