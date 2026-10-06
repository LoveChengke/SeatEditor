"""冲突报告对话框：把底部「排位结果」页的内容放进独立窗口看（放大 / 投屏 / 打印）。

内容渲染本身在 ``widgets/result_report.py``（底部面板用的是同一份），
这里只负责加标题、给个关闭按钮——两处的排版永远不会走样。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from ..common import polish_dialog
from ..widgets.result_report import build_result_report


class ConflictReportDialog(QDialog):
    """展示一次排位结果：硬约束是否满足 + 每条软约束的满足度。"""

    def __init__(self, solution, project, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.solution = solution
        self.project = project
        self.setWindowTitle("排位结果报告")
        self.setMinimumWidth(560)
        self.setMinimumHeight(440)
        self._build_ui()
        self.resize(640, 560)
        polish_dialog(self)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("排位结果报告")
        title.setObjectName("PanelTitle")
        root.addWidget(title)

        root.addWidget(build_result_report(self.solution, self.project, self), 1)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close = box.button(QDialogButtonBox.StandardButton.Close)
        close.setText("关闭")
        close.setObjectName("Primary")
        box.rejected.connect(self.reject)
        root.addWidget(box)
