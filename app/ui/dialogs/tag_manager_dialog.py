"""标签管理对话框：新增 / 重命名 / 改色 / 删除项目标签。

按契约允许直接修改 ``project``（``add_tag`` / ``rename_tag`` / ``set_tag_color`` /
``remove_tag``）；使用次数取自 ``StudentService.tag_usage()``。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from ..common import fit_to_screen, hline
from ...config import TAG_PALETTE
from ...services.student_service import StudentService
from ..style.theme import Color

SWATCH_COLUMNS = 6


def _swatch(color: str) -> QIcon:
    """用纯色块作为列表项图标。"""
    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class TagManagerDialog(QDialog):
    """维护项目标签库；所有改动立即写入 ``project.tags``。"""

    def __init__(self, project, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self._service = StudentService(project)
        self.setWindowTitle("标签管理")
        self.setMinimumWidth(460)
        self._build_ui()
        self._refresh()
        self.adjustSize()
        fit_to_screen(self)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        title = QLabel("标签管理")
        title.setObjectName("PanelTitle")
        root.addWidget(title)
        hint = QLabel("删除标签会同时从所有学生身上移除该标签；颜色用于座位卡片的标签色条。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addWidget(hline())

        self._list = QListWidget()
        self._list.setIconSize(QSize(12, 12))
        self._list.setMinimumHeight(180)
        root.addWidget(self._list, 1)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("输入新标签名，例如：视力差")
        self._name_edit.returnPressed.connect(self._add_tag)
        self._add_btn = QPushButton("添加标签")
        self._add_btn.setObjectName("Primary")
        self._add_btn.clicked.connect(self._add_tag)
        add_row.addWidget(self._name_edit, 1)
        add_row.addWidget(self._add_btn)
        root.addLayout(add_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        rename_btn = QPushButton("重命名")
        rename_btn.clicked.connect(self._rename_tag)
        self._del_btn = QPushButton("删除")
        self._del_btn.setObjectName("Danger")
        self._del_btn.clicked.connect(self._remove_tag)
        action_row.addWidget(rename_btn)
        action_row.addWidget(self._del_btn)
        action_row.addStretch(1)
        self._usage_label = QLabel("")
        self._usage_label.setObjectName("Hint")
        action_row.addWidget(self._usage_label)
        root.addLayout(action_row)

        color_box = QGroupBox("标签颜色（点选后应用到当前标签）")
        grid = QGridLayout(color_box)
        grid.setSpacing(6)
        for index, color in enumerate(TAG_PALETTE):
            button = QPushButton()
            button.setFixedSize(28, 22)
            button.setToolTip(color)
            button.setStyleSheet(
                "QPushButton { background: %s; border: 1px solid %s; border-radius: 5px; }"
                % (color, Color.BORDER)
            )
            button.clicked.connect(lambda _checked=False, value=color: self._set_color(value))
            grid.addWidget(button, index // SWATCH_COLUMNS, index % SWATCH_COLUMNS)
        root.addWidget(color_box)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close = box.button(QDialogButtonBox.StandardButton.Close)
        close.setText("关闭")
        close.setObjectName("Primary")
        box.rejected.connect(self.reject)
        root.addWidget(box)

    # 数据
    def _usage(self) -> dict:
        try:
            return dict(self._service.tag_usage())
        except Exception:  # 统计失败不应崩溃
            return {}

    def _refresh(self, select: str = "") -> None:
        usage = self._usage()
        current = select or self._selected_name()
        self._list.clear()
        for tag in self.project.tags:
            count = int(usage.get(tag.name, 0) or 0)
            item = QListWidgetItem(_swatch(tag.color), "%s　（%d 人）" % (tag.name, count))
            item.setData(Qt.ItemDataRole.UserRole, tag.name)
            item.setToolTip("颜色 %s，%d 名学生使用" % (tag.color, count))
            self._list.addItem(item)
        if self._list.count():
            rows = [self._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._list.count())]
            self._list.setCurrentRow(rows.index(current) if current in rows else 0)
        self._usage_label.setText("共 %d 个标签" % self._list.count())
        self._del_btn.setEnabled(bool(self.project.tags))

    def _selected_name(self) -> str:
        item = self._list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item is not None else ""

    def _require_selection(self) -> str:
        name = self._selected_name()
        if not name:
            QMessageBox.information(self, "请先选择", "请先在列表中选择一个标签。")
        return name

    # 操作
    def _add_tag(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.information(self, "请输入标签名", "标签名不能为空。")
            return
        if self.project.get_tag(name) is not None:
            QMessageBox.information(self, "标签已存在", "标签「%s」已经存在。" % name)
            return
        try:
            ok = self.project.add_tag(name)
        except Exception as exc:
            QMessageBox.warning(self, "添加失败", "无法新增标签：%s" % exc)
            return
        if not ok:
            QMessageBox.information(self, "添加失败", "标签「%s」无法新增。" % name)
            return
        self._name_edit.clear()
        self._refresh(name)

    def _rename_tag(self) -> None:
        old = self._require_selection()
        if not old:
            return
        text, ok = QInputDialog.getText(self, "重命名标签", "新名称：", QLineEdit.EchoMode.Normal, old)
        new = str(text).strip()
        if not ok or not new or new == old:
            return
        if not self.project.rename_tag(old, new):
            QMessageBox.information(self, "重命名失败", "标签「%s」已存在或名称无效。" % new)
            return
        self._refresh(new)

    def _set_color(self, color: str) -> None:
        name = self._require_selection()
        if not name:
            return
        if not self.project.set_tag_color(name, color):
            QMessageBox.information(self, "设置失败", "找不到标签「%s」。" % name)
            return
        self._refresh(name)

    def _remove_tag(self) -> None:
        name = self._require_selection()
        if not name:
            return
        count = int(self._usage().get(name, 0) or 0)
        answer = QMessageBox.question(
            self, "删除标签",
            "确定删除标签「%s」吗？\n该标签会从 %d 名学生身上移除。" % (name, count),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.project.remove_tag(name):
            QMessageBox.information(self, "删除失败", "找不到标签「%s」。" % name)
            return
        self._refresh()
