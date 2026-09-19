"""服务层。"""

from __future__ import annotations

from .export_service import ExportError, ExportService
from .history_service import HistoryService, Snapshot
from .rotation_service import RotationError, RotationOptions, RotationPlan, RotationService
from .rule_engine import (
    Evaluation,
    HardTerm,
    RuleEngine,
    SoftTerm,
    describe_violations,
    normalize_gender,
)
from .seat_service import SeatService, assign_student, clear_seat, swap_students
from .solver import SolveReport, Solver, SolverError, solve_once
from .student_service import (
    ASSIGN_ALL,
    ASSIGN_ASSIGNED,
    ASSIGN_UNASSIGNED,
    TAG_MODE_ALL,
    TAG_MODE_ANY,
    StudentFilter,
    StudentService,
)

__all__ = [
    "RuleEngine", "Evaluation", "HardTerm", "SoftTerm", "describe_violations", "normalize_gender",
    "Solver", "SolverError", "SolveReport", "solve_once",
    "SeatService", "swap_students", "assign_student", "clear_seat",
    "StudentService", "StudentFilter",
    "TAG_MODE_ANY", "TAG_MODE_ALL", "ASSIGN_ALL", "ASSIGN_ASSIGNED", "ASSIGN_UNASSIGNED",
    "HistoryService", "Snapshot",
    "RotationService", "RotationPlan", "RotationOptions", "RotationError",
    "ExportService", "ExportError",
]
