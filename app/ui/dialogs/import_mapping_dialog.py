"""Excel 导入字段映射对话框。

表头一行一个下拉框，选项为 ``excel_io.FIELD_LABELS`` 的全部字段，
外加每个表头对应的 ``attr:<推测名字>`` 选项；底部可勾选「跳过错误行继续导入」。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QGridLayout, QHeaderView, QLabel, QMessageBox,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..common import hline
from ...storage import excel_io
from ...storage.excel_io import FIELD_LABELS, F_NAME, F_SID

PREVIEW_ROWS = 8


def _cell_text(value) -> str:
    """把单元格值转成适合显示的文本。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _guess_attr_name(header: str) -> str:
    """优先使用 excel_io 的推测函数，缺失时回退为表头原文。"""
    guess = getattr(excel_io, "_guess_attr_name", None)
    if callable(guess):
        try:
            return str(guess(header) or header)
        except Exception:  # noqa: BLE001 - 推测失败不影响映射
            return str(header)
    return str(header)


class ImportMappingDialog(QDialog):
    """字段映射；接受后 ``mapping`` 为 ``{表头: 字段键}``。"""

    def __init__(self, preview, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.preview = preview
        self.mapping: Dict[str, str] = {}
        self.skip_invalid: bool = True
        self._combos: Dict[str, QComboBox] = {}
        self.setWindowTitle("导入学生名单")
        self.setMinimumWidth(680)
        self._build_ui()
        self.adjustSize()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        title = QLabel("字段映射")
        title.setObjectName("PanelTitle")
        root.addWidget(title)

        hint = QLabel("%s · 工作表「%s」 · 共 %d 行数据"
                      % (self._short_path(), getattr(self.preview, "sheet", ""), self._total_rows()))
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        tip = QLabel("请为每一列选择对应的系统字段；未识别为「数值属性」的列会自动创建属性。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        root.addWidget(tip)
        root.addWidget(hline())
        root.addWidget(self._build_mapping_area(), 1)
        root.addWidget(self._build_table(), 1)

        self._skip_check = QCheckBox("跳过错误行继续导入")
        self._skip_check.setChecked(True)
        self._skip_check.setToolTip("取消勾选时，只要有一行数据有问题就整体放弃导入")
        root.addWidget(self._skip_check)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = box.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("开始导入")
        ok.setObjectName("Primary")
        ok.setDefault(True)
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    def _build_mapping_area(self) -> QWidget:
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        headers: List[str] = list(getattr(self.preview, "headers", []) or [])
        mapping: Dict[str, str] = dict(getattr(self.preview, "mapping", {}) or {})
        for row, header in enumerate(headers):
            label = QLabel(str(header))
            label.setToolTip(str(header))
            combo = QComboBox()
            combo.setMinimumWidth(200)
            for key, text in FIELD_LABELS.items():
                combo.addItem(text, key)
            attr_name = _guess_attr_name(header)
            combo.addItem("数值属性：%s" % attr_name, excel_io.F_ATTR_PREFIX + attr_name)
            current = str(mapping.get(header, "") or "")
            index = combo.findData(current)
            if index < 0 and current:
                combo.addItem("（原有）%s" % current, current)
                index = combo.count() - 1
            combo.setCurrentIndex(max(0, index))
            self._combos[header] = combo
            grid.addWidget(label, row, 0)
            grid.addWidget(combo, row, 1)
        if not headers:
            empty = QLabel("没有读取到表头，请检查文件内容。")
            empty.setObjectName("Hint")
            grid.addWidget(empty, 0, 0, 1, 2)
        grid.setRowStretch(len(headers), 1)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(host)
        area.setMinimumHeight(120)
        return area

    def _build_table(self) -> QWidget:
        headers: List[str] = list(getattr(self.preview, "headers", []) or [])
        rows: List[List] = list(getattr(self.preview, "rows", []) or [])[:PREVIEW_ROWS]
        table = QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels([str(h) for h in headers])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for r, row in enumerate(rows):
            for c, value in enumerate(list(row)[: len(headers)]):
                table.setItem(r, c, QTableWidgetItem(_cell_text(value)))
        table.setMinimumHeight(120)
        table.setMaximumHeight(180)
        return table

    def _short_path(self) -> str:
        path = str(getattr(self.preview, "path", "") or "")
        return path.replace("\\", "/").rsplit("/", 1)[-1] or path or "（未知文件）"

    def _total_rows(self) -> int:
        total = int(getattr(self.preview, "total_rows", 0) or 0)
        return total or len(list(getattr(self.preview, "rows", []) or []))

    # ------------------------------------------------------------ 结果
    def _collect(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for header, combo in self._combos.items():
            data = combo.currentData()
            mapping[header] = str(data) if data else ""
        return mapping

    def accept(self) -> None:
        mapping = self._collect()
        values = set(mapping.values())
        missing = []
        if F_SID not in values:
            missing.append("「学号」")
        if F_NAME not in values:
            missing.append("「姓名」")
        if missing:
            QMessageBox.warning(self, "映射未完成",
                                "请先为 %s 列选择对应的系统字段。" % "、".join(missing))
            return
        self.mapping = mapping
        self.skip_invalid = self._skip_check.isChecked()
        super().accept()
