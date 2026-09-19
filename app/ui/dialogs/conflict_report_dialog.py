"""冲突报告对话框：上半部分硬约束清单，下半部分软约束得分明细。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGridLayout, QGroupBox, QLabel,
    QListWidget, QListWidgetItem, QProgressBar, QScrollArea, QSplitter,
    QVBoxLayout, QWidget,
)

OK_TEXT = "✅ 全部满足"
WARN_TEXT = "⚠️ %d 条硬约束未满足"


def _hline() -> QFrame:
    """1px 分隔线（QSS 中的 ``HLine``）。"""
    line = QFrame()
    line.setObjectName("HLine")
    line.setFixedHeight(1)
    return line


class ConflictReportDialog(QDialog):
    """展示一次排位结果：硬约束是否满足 + 每条软约束的满足度。"""

    def __init__(self, solution, project, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.solution = solution
        self.project = project
        self.setWindowTitle("排位结果报告")
        self.setMinimumWidth(560)
        self.setMinimumHeight(480)
        self._build_ui()
        self.resize(620, 560)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        title = QLabel("排位结果报告")
        title.setObjectName("PanelTitle")
        root.addWidget(title)

        if self.solution is None:
            hint = QLabel("没有可展示的排位结果，请先执行「一键排位」。")
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            root.addWidget(hint)
            root.addStretch(1)
            root.addWidget(self._close_box())
            return

        summary = QLabel(
            "耗时 %.1f 秒 · 重启 %d 次 · 迭代 %d 次"
            % (float(getattr(self.solution, "elapsed", 0.0) or 0.0),
               int(getattr(self.solution, "restarts", 0) or 0),
               int(getattr(self.solution, "iterations", 0) or 0))
        )
        summary.setObjectName("Hint")
        root.addWidget(summary)
        root.addWidget(_hline())
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._build_hard_box())
        splitter.addWidget(self._build_soft_box())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)
        root.addWidget(self._close_box())

    def _close_box(self) -> QWidget:
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close = box.button(QDialogButtonBox.StandardButton.Close)
        close.setText("关闭")
        close.setObjectName("Primary")
        box.rejected.connect(self.reject)
        return box

    def _build_hard_box(self) -> QWidget:
        box = QGroupBox("硬约束")
        layout = QVBoxLayout(box)
        layout.setSpacing(6)
        violations = list(getattr(self.solution, "hard_violations", []) or [])
        status = QLabel(OK_TEXT if not violations else WARN_TEXT % len(violations))
        status.setObjectName("StatusOk" if not violations else "StatusWarn")
        layout.addWidget(status)

        if not violations:
            hint = QLabel("所有硬约束均已满足，可以放心导出座位表。")
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            layout.addStretch(1)
            return box

        listing = QListWidget()
        for violation in violations:
            message = str(getattr(violation, "message", "") or violation)
            label = str(getattr(violation, "rule_label", "") or "")
            item = QListWidgetItem("⚠️ %s%s" % (("%s：" % label) if label else "", message))
            seats = list(getattr(violation, "seats", []) or [])
            students = list(getattr(violation, "students", []) or [])
            detail = []
            if seats:
                detail.append("座位：%s" % "、".join(self._seat_text(s) for s in seats))
            if students:
                detail.append("学生：%s" % "、".join(self._student_name(s) for s in students))
            if detail:
                item.setToolTip("\n".join(detail))
            listing.addItem(item)
        layout.addWidget(listing, 1)
        return box

    def _build_soft_box(self) -> QWidget:
        box = QGroupBox("软约束得分")
        layout = QVBoxLayout(box)
        layout.setSpacing(6)
        score = float(getattr(self.solution, "soft_score", 0.0) or 0.0)
        total = QLabel("综合得分：%.1f 分（满分 100 分）" % score)
        total.setObjectName("PanelTitle")
        layout.addWidget(total)

        scores = list(getattr(self.solution, "rule_scores", []) or [])
        if not scores:
            hint = QLabel("本次排位没有启用任何软约束。")
            hint.setObjectName("Hint")
            layout.addWidget(hint)
            layout.addStretch(1)
            return box

        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        for row, rule_score in enumerate(scores):
            label = str(getattr(rule_score, "label", "") or "规则")
            weight = float(getattr(rule_score, "weight", 1.0) or 0.0)
            satisfaction = max(0.0, min(1.0, float(getattr(rule_score, "satisfaction", 0.0) or 0.0)))
            percent = int(round(satisfaction * 100))
            name = QLabel("%s（权重 %.2f）" % (label, weight))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(percent)
            bar.setTextVisible(False)
            tip = "%s：满足度 %d%%" % (label, percent)
            name.setToolTip(tip)
            bar.setToolTip(tip)
            grid.addWidget(name, row, 0)
            grid.addWidget(bar, row, 1)
            grid.addWidget(QLabel("%d%%" % percent), row, 2)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(host)
        layout.addWidget(area, 1)
        return box

    # ------------------------------------------------------------ 文案
    def _seat_text(self, seat_key) -> str:
        parts = str(seat_key or "").split("-")
        if len(parts) != 3:
            return str(seat_key or "")
        try:
            group, row, col = (int(p) + 1 for p in parts)
        except ValueError:
            return str(seat_key)
        return "第 %d 组 第 %d 排 第 %d 列" % (group, row, col)

    def _student_name(self, sid) -> str:
        sid_text = str(sid or "")
        try:
            name = self.project.student_name(sid_text)
        except Exception:  # noqa: BLE001
            name = ""
        if name and name != sid_text:
            return "%s（%s）" % (name, sid_text)
        return name or sid_text
