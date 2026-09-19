"""模型层：纯数据类，不依赖 Qt。"""

from __future__ import annotations

from .assignment import Assignment, Solution, is_valid, sanitize
from .layout import LAYOUT_TEMPLATES, Layout, Seat, SeatGroup, template_layout
from .project import (
    EV_ANY,
    EV_ASSIGNMENT,
    EV_HISTORY,
    EV_LAYOUT,
    EV_RULES,
    EV_SELECTIONS,
    EV_STUDENTS,
    EV_TAGS,
    Project,
    RotationRecord,
    Tag,
    new_project,
)
from .rule import (
    HARD,
    SOFT,
    RULE_SPECS,
    Rule,
    RuleScore,
    RuleSpec,
    Violation,
    describe_rule,
    make_rule,
    spec_of,
)
from .selection import Selection, make_selection_id
from .student import Student, attr_names

__all__ = [
    "Student", "attr_names",
    "Layout", "SeatGroup", "Seat", "LAYOUT_TEMPLATES", "template_layout",
    "Selection", "make_selection_id",
    "Rule", "RuleSpec", "RuleScore", "Violation", "RULE_SPECS",
    "HARD", "SOFT", "make_rule", "spec_of", "describe_rule",
    "Assignment", "Solution", "is_valid", "sanitize",
    "Project", "Tag", "RotationRecord", "new_project",
    "EV_LAYOUT", "EV_STUDENTS", "EV_TAGS", "EV_SELECTIONS",
    "EV_RULES", "EV_ASSIGNMENT", "EV_HISTORY", "EV_ANY",
]
