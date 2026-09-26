"""排位进度对话框：用 ``QTimer`` 分片驱动 ``Solver.iterate()``，不使用线程。

显示进度条、重启次数、当前软约束得分与耗时；「停止」按钮或关闭窗口都会停止搜索
并保留当前最优解（``self.solution``）。
"""

from __future__ import annotations

import time
from typing import List, Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
    QWidget,
)

from ..common import fit_to_screen, hline
from ...config import DEFAULT_TIME_LIMIT, SOLVER_CHUNK
from ...models.assignment import Solution
from ...services.rule_engine import RuleEngine
from ...services.solver import Solver, SolverError


class SolverProgressDialog(QDialog):
    """分片执行排位搜索；完成后 ``solution`` 为 ``Solution``（失败为 ``None``）。"""

    def __init__(self, project, parent: Optional[QWidget] = None, locked_seats=None) -> None:
        super().__init__(parent)
        self.project = project
        self.locked_seats: List = list(locked_seats or [])
        self.solution: Optional[Solution] = None
        self._engine: Optional[RuleEngine] = None
        self._solver: Optional[Solver] = None
        self._started = False
        self._cancelled = False
        self._start_time = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._tick)
        self.setWindowTitle("智能排位")
        self.setMinimumWidth(440)
        self._build_ui()
        self.adjustSize()
        fit_to_screen(self)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        title = QLabel("正在搜索最优方案…")
        title.setObjectName("PanelTitle")
        root.addWidget(title)
        hint = QLabel("排位在界面线程里分片执行，随时可以停止；时间上限约 %.0f 秒。" % DEFAULT_TIME_LIMIT)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        root.addWidget(self._progress)
        root.addWidget(hline())

        form = QFormLayout()
        form.setSpacing(6)
        self._restart_label = QLabel("0")
        self._score_label = QLabel("—")
        self._elapsed_label = QLabel("0.0 秒")
        form.addRow("已重启次数", self._restart_label)
        form.addRow("当前软约束得分", self._score_label)
        form.addRow("已用时", self._elapsed_label)
        root.addLayout(form)
        root.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._stop_btn = QPushButton("停止")
        self._stop_btn.setObjectName("Primary")
        self._stop_btn.setToolTip("停止搜索并采用当前找到的最优方案")
        self._stop_btn.clicked.connect(self._stop_by_user)
        buttons.addWidget(self._stop_btn)
        root.addLayout(buttons)

    # 生命周期
    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        if not self._started and not self._cancelled:
            QTimer.singleShot(0, self._start)

    def _start(self) -> None:
        if self._started or self._cancelled:
            return
        self._started = True
        self._start_time = time.time()
        try:
            self._engine = RuleEngine.from_project(self.project)
            self._solver = Solver(self._engine, self.project.students,
                                  time_limit=DEFAULT_TIME_LIMIT, locked_seats=self.locked_seats)
            self._solver.prepare(self.project.assignment)
        except SolverError as exc:
            QMessageBox.warning(self, "无法开始排位", str(exc))
            self.reject()
            return
        except Exception as exc:  # 任何异常都转成友好提示
            QMessageBox.warning(self, "无法开始排位", "排位初始化失败：%s" % exc)
            self.reject()
            return
        self._timer.start()
        self._tick()

    def _tick(self) -> None:
        solver = self._solver
        if solver is None or self._cancelled:
            return
        try:
            finished = solver.iterate(SOLVER_CHUNK)
        except Exception as exc:
            self._timer.stop()
            QMessageBox.warning(self, "排位中断", "排位过程出现异常：%s" % exc)
            self.reject()
            return
        self._update_labels()
        if finished:
            self._finish()

    def _update_labels(self) -> None:
        solver = self._solver
        if solver is None:
            return
        report = solver.report
        try:
            self._progress.setValue(int(solver.progress() * 100))
        except Exception:
            pass
        self._restart_label.setText(str(report.restarts))
        self._score_label.setText(self._current_score(solver))
        elapsed = report.elapsed or max(0.0, time.time() - self._start_time)
        self._elapsed_label.setText("%.1f 秒" % elapsed)

    def _current_score(self, solver: Solver) -> str:
        if self._engine is None or not solver.best_assignment:
            return "—"
        try:
            return "%.1f 分" % self._engine.evaluate(solver.best_assignment).score
        except Exception:
            return "—"

    def _capture_best(self) -> None:
        """尽力保存当前最优解（未成功初始化时保持 ``None``）。"""
        solver = self._solver
        if solver is None or not self._started:
            return
        try:
            if solver.best_assignment:
                self.solution = solver.best_solution()
        except Exception:
            pass

    def _stop(self) -> None:
        self._cancelled = True
        self._timer.stop()
        self._stop_btn.setEnabled(False)

    def _finish(self) -> None:
        solver = self._solver
        self._timer.stop()
        if solver is not None:
            try:
                self.solution = solver.best_solution()
            except Exception:
                self.solution = None
        self._progress.setValue(100)
        self._stop_btn.setEnabled(False)
        self.accept()

    # 交互
    def _stop_by_user(self) -> None:
        self._stop()
        self._capture_best()
        self.accept()

    def reject(self) -> None:
        # Esc / 触发 reject 时同样视为「停止」，保留当前最优解
        if self._started:
            self._stop()
            self._capture_best()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        # 关闭窗口 = 停止，并把已算出的最优解带回主窗口
        event.ignore()
        self._stop_by_user()
