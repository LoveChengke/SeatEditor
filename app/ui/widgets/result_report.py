"""排位结果报告的内容块：上半「必须满足」清单，下半「尽量满足」得分明细。

两处在用，所以抽成工厂函数而不是对话框的内部方法：
- 底部面板的「排位结果」页（主路径：排完位就在窗口里看，不用再关弹窗）；
- ``ConflictReportDialog``（想放大看、想打印时开新窗口）。
一份渲染逻辑两个出口，样式不会走样。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGridLayout, QGroupBox, QLabel, QListWidget, QListWidgetItem,
    QProgressBar, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

OK_TEXT = "全部满足"
WARN_TEXT = "有 %d 条「必须满足」没做到"


def seat_text(seat_key) -> str:
    """座位键 ``组-排-列``（0 起）→ 老师看得懂的说法。"""
    parts = str(seat_key or "").split("-")
    if len(parts) != 3:
        return str(seat_key or "")
    try:
        group, row, col = (int(p) + 1 for p in parts)
    except ValueError:
        return str(seat_key)
    return "第 %d 组 第 %d 排 第 %d 列" % (group, row, col)


def student_name(project, sid) -> str:
    sid_text = str(sid or "")
    try:
        name = project.student_name(sid_text)
    except Exception:
        name = ""
    if name and name != sid_text:
        return "%s（%s）" % (name, sid_text)
    return name or sid_text


def build_result_report(solution, project, parent: Optional[QWidget] = None) -> QWidget:
    """给一次求解结果生成报告控件（``solution`` 为 None 时给一句提示）。"""
    host = QWidget(parent)
    root = QVBoxLayout(host)
    root.setContentsMargins(10, 8, 10, 8)
    root.setSpacing(8)

    if solution is None:
        hint = QLabel("还没有排位结果。按 F5 或点「一键排位」跑一次就有了。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)
        return host

    summary = QLabel("耗时 %.1f 秒 · 重启 %d 次 · 迭代 %d 次" % (
        float(getattr(solution, "elapsed", 0.0) or 0.0),
        int(getattr(solution, "restarts", 0) or 0),
        int(getattr(solution, "iterations", 0) or 0)))
    summary.setObjectName("Hint")
    root.addWidget(summary)

    splitter = QSplitter(Qt.Orientation.Vertical, host)
    splitter.addWidget(_hard_box(solution, project, splitter))
    splitter.addWidget(_soft_box(solution, splitter))
    splitter.setStretchFactor(0, 1)
    splitter.setStretchFactor(1, 1)
    root.addWidget(splitter, 1)
    return host


def _hard_box(solution, project, parent: QWidget) -> QWidget:
    box = QGroupBox("必须满足的要求", parent)
    layout = QVBoxLayout(box)
    layout.setSpacing(6)
    violations = list(getattr(solution, "hard_violations", []) or [])
    status = QLabel(OK_TEXT if not violations else WARN_TEXT % len(violations))
    status.setObjectName("StatusOk" if not violations else "StatusWarn")
    layout.addWidget(status)

    if not violations:
        hint = QLabel("所有「必须满足」的要求都做到了，可以放心导出座位表。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return box

    listing = QListWidget(box)
    for violation in violations:
        message = str(getattr(violation, "message", "") or violation)
        label = str(getattr(violation, "rule_label", "") or "")
        item = QListWidgetItem("%s%s" % (("%s：" % label) if label else "", message))
        seats = list(getattr(violation, "seats", []) or [])
        students = list(getattr(violation, "students", []) or [])
        detail = []
        if seats:
            detail.append("座位：%s" % "、".join(seat_text(s) for s in seats))
        if students:
            detail.append("学生：%s" % "、".join(student_name(project, s) for s in students))
        if detail:
            item.setToolTip("\n".join(detail))
        listing.addItem(item)
    layout.addWidget(listing, 1)
    return box


def _soft_box(solution, parent: QWidget) -> QWidget:
    box = QGroupBox("尽量满足的情况", parent)
    layout = QVBoxLayout(box)
    layout.setSpacing(6)
    score = float(getattr(solution, "soft_score", 0.0) or 0.0)
    total = QLabel("综合得分：%.1f 分（满分 100 分）" % score)
    total.setObjectName("PanelTitle")
    layout.addWidget(total)

    scores = list(getattr(solution, "rule_scores", []) or [])
    if not scores:
        hint = QLabel("本次排位没有设置「尽量满足」类的要求。")
        hint.setObjectName("Hint")
        layout.addWidget(hint)
        layout.addStretch(1)
        return box

    host = QWidget(box)
    grid = QGridLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(5)
    grid.setColumnStretch(1, 1)
    for row, rule_score in enumerate(scores):
        label = str(getattr(rule_score, "label", "") or "规则")
        weight = float(getattr(rule_score, "weight", 1.0) or 0.0)
        satisfaction = max(0.0, min(1.0, float(getattr(rule_score, "satisfaction", 0.0) or 0.0)))
        percent = int(round(satisfaction * 100))
        name = QLabel("%s（重要程度 %g）" % (label, weight))
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

    area = QScrollArea(box)
    area.setWidgetResizable(True)
    area.setWidget(host)
    layout.addWidget(area, 1)
    return box
