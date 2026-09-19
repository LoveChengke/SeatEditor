"""主窗口侧边面板：学生名单 / 规则 / 选区 / 自动轮换。"""

from __future__ import annotations

from .rotation_panel import RotationPanel
from .rule_panel import RulePanel
from .selection_panel import SelectionPanel
from .student_panel import StudentPanel

__all__ = ["StudentPanel", "RulePanel", "SelectionPanel", "RotationPanel"]
