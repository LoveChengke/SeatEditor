"""文本导入对话框：粘贴名单 → ``StudentService.parse_text`` 解析成学生列表。"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QGroupBox,
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QVBoxLayout, QWidget,
)

from ..common import hline
from ...models.student import Student
from ...services.student_service import StudentService

MAX_PROBLEMS = 5
HINT = "每行一位：学号 姓名 性别（性别可省略）"
SAMPLE = "示例：\n1001 张三 男\n1002 李四 女\n1003 王五"


class TextImportDialog(QDialog):
    """粘贴名单导入；接受后 ``students`` 为解析出的 ``Student`` 列表。"""

    def __init__(self, project, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self.students: List[Student] = []
        self._service = StudentService(project)
        self.setWindowTitle("粘贴名单导入")
        self.setMinimumWidth(520)
        self._build_ui()
        self._parse()
        self.adjustSize()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        title = QLabel("粘贴名单导入")
        title.setObjectName("PanelTitle")
        root.addWidget(title)
        hint = QLabel("%s\n%s" % (HINT, SAMPLE))
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addWidget(hline())

        self._text = QPlainTextEdit()
        self._text.setPlaceholderText("在此粘贴名单，一行一位学生…")
        self._text.setMinimumHeight(200)
        self._text.textChanged.connect(self._parse)
        root.addWidget(self._text, 1)

        gender_box = QGroupBox("默认性别（未写出性别时使用）")
        gender_row = QHBoxLayout(gender_box)
        gender_row.setSpacing(6)
        self._gender_combo = QComboBox()
        for value, label in (("", "（不填）"), ("男", "男"), ("女", "女")):
            self._gender_combo.addItem(label, value)
        self._gender_combo.currentIndexChanged.connect(self._parse)
        gender_row.addWidget(self._gender_combo)
        gender_row.addStretch(1)
        root.addWidget(gender_box)

        self._result_label = QLabel("")
        self._result_label.setObjectName("StatusOk")
        self._result_label.setWordWrap(True)
        root.addWidget(self._result_label)
        self._problem_label = QLabel("")
        self._problem_label.setObjectName("Hint")
        self._problem_label.setWordWrap(True)
        root.addWidget(self._problem_label)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = box.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("导入")
        ok.setObjectName("Primary")
        ok.setDefault(True)
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    # 解析
    def _parse(self, *_args) -> List[Student]:
        try:
            students, problems = StudentService.parse_text(
                self._text.toPlainText(), str(self._gender_combo.currentData() or "")
            )
        except Exception as exc:  # 解析异常转成友好提示
            self._result_label.setText("解析失败：%s" % exc)
            self._problem_label.setText("")
            return []
        existing = {s.sid for s in self.project.students}
        duplicates = [s.sid for s in students if s.sid in existing]
        if duplicates:
            problems.append("名单中已有（导入时自动跳过）：%s" % "、".join(duplicates[:5]))
        self._result_label.setText("已识别 %d 位学生" % len(students))
        if not problems:
            self._problem_label.setText("没有发现问题行。")
        else:
            head = problems[:MAX_PROBLEMS]
            text = "需要注意：\n" + "\n".join("· %s" % p for p in head)
            if len(problems) > MAX_PROBLEMS:
                text += "\n· …还有 %d 条" % (len(problems) - MAX_PROBLEMS)
            self._problem_label.setText(text)
        return students

    def accept(self) -> None:
        students = self._parse()
        if not students:
            QMessageBox.warning(self, "没有可导入的数据", "请先粘贴名单，每行格式为「学号 姓名 性别」。")
            return
        self.students = students
        super().accept()
