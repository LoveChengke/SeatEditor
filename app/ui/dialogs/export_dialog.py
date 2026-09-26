"""导出对话框：选择导出格式（Excel 座位表 / PNG 图片）与各项选项。

确定时通过 ``QFileDialog`` 选择保存位置；``.path`` 为用户选择的路径
（用户取消选择时为空字符串，对话框仍然接受）。
"""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGroupBox, QLabel,
    QMessageBox, QRadioButton, QVBoxLayout, QWidget,
)

from ..common import CollapsibleSection, fit_to_screen, hline
from ... import config
from ...storage.excel_io import ExportOptions

MODE_EXCEL = "excel"
MODE_PNG = "png"


class ExportDialog(QDialog):
    """收集导出参数；接受后读取 ``mode`` / ``options`` / ``png_scale`` / ``path``。"""

    def __init__(self, project, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self.mode: str = MODE_EXCEL
        self.options: ExportOptions = ExportOptions()
        self.png_scale: int = 1
        self.path: str = ""
        self.setWindowTitle("导出座位表")
        self.setMinimumWidth(480)
        self._build_ui()
        self._on_mode_changed()
        self.adjustSize()
        fit_to_screen(self)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        title = QLabel("导出座位表")
        title.setObjectName("PanelTitle")
        root.addWidget(title)
        hint = QLabel("选格式 → 选保存位置。空座位会显示为空白。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addWidget(hline())

        format_box = QGroupBox("导出格式")
        format_layout = QVBoxLayout(format_box)
        self._excel_radio = QRadioButton("Excel 座位表（.xlsx）")
        self._png_radio = QRadioButton("PNG 图片（.png）")
        self._excel_radio.setChecked(True)
        group = QButtonGroup(self)
        for radio in (self._excel_radio, self._png_radio):
            group.addButton(radio)
            format_layout.addWidget(radio)
        root.addWidget(format_box)

        self._excel_box = QGroupBox("Excel 选项")
        excel_layout = QVBoxLayout(self._excel_box)
        self._sid_check = QCheckBox("包含学号")
        self._group_check = QCheckBox("包含组标题")
        self._podium_check = QCheckBox("显示讲台")
        for widget in (self._sid_check, self._group_check, self._podium_check):
            widget.setChecked(True)
            excel_layout.addWidget(widget)
        # 附加页属于低频选项，默认折叠
        self._extra_section = CollapsibleSection("附加表格（可选）")
        self._roster_check = QCheckBox("附加「名单」页")
        self._rules_check = QCheckBox("附加「规则说明」页")
        for widget in (self._roster_check, self._rules_check):
            widget.setChecked(True)
            self._extra_section.body_layout.addWidget(widget)
        excel_layout.addWidget(self._extra_section)
        root.addWidget(self._excel_box)

        self._png_box = QGroupBox("PNG 选项")
        png_layout = QFormLayout(self._png_box)
        self._scale1 = QRadioButton("1x（原始尺寸）")
        self._scale2 = QRadioButton("2x（高清，适合打印）")
        self._scale1.setChecked(True)
        scale_group = QButtonGroup(self)
        for radio in (self._scale1, self._scale2):
            scale_group.addButton(radio)
        png_layout.addRow("缩放", self._scale1)
        png_layout.addRow("", self._scale2)
        root.addWidget(self._png_box)
        root.addStretch(1)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = box.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("选择保存位置…")
        ok.setObjectName("Primary")
        ok.setDefault(True)
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self._excel_radio.toggled.connect(self._on_mode_changed)

    def _on_mode_changed(self, *_args) -> None:
        is_excel = self._excel_radio.isChecked()
        self.mode = MODE_EXCEL if is_excel else MODE_PNG
        self.png_scale = 2 if self._scale2.isChecked() else 1
        self._excel_box.setEnabled(is_excel)
        self._png_box.setEnabled(not is_excel)

    # 结果
    def _collect(self) -> None:
        self._on_mode_changed()
        options = self.options
        options.include_sid = self._sid_check.isChecked()
        options.include_group_title = self._group_check.isChecked()
        options.include_roster = self._roster_check.isChecked()
        options.include_rules = self._rules_check.isChecked()
        options.show_podium = self._podium_check.isChecked()

    def _default_path(self) -> str:
        project_path = str(getattr(self.project, "path", "") or "")
        directory = os.path.dirname(project_path) or os.path.expanduser("~")
        base = os.path.splitext(os.path.basename(project_path))[0] or "座位表"
        suffix = "座位表.xlsx" if self.mode == MODE_EXCEL else "座位表.png"
        return os.path.join(directory, "%s_%s" % (base, suffix))

    def _choose_path(self) -> str:
        filter_text = config.EXCEL_FILTER if self.mode == MODE_EXCEL else config.PNG_FILTER
        try:
            path, _selected = QFileDialog.getSaveFileName(
                self, "选择保存位置", self._default_path(), filter_text
            )
        except Exception as exc:  # 文件对话框异常不应崩溃
            QMessageBox.warning(self, "无法选择保存位置", "打开保存对话框失败：%s" % exc)
            return ""
        return str(path or "")

    def accept(self) -> None:
        self._collect()
        self.path = self._choose_path()
        super().accept()
