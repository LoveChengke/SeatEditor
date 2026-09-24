"""自动轮换：区域轮换 / 平移轮换（PRD F5）。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ..models.assignment import Assignment
from ..models.layout import Layout
from ..models.project import Project, RotationRecord
from ..models.selection import Selection
from ..utils.seat_key import make_key, try_parse_key
from ..utils.seat_key import Seat as Coord


class RotationError(Exception):
    """轮换参数错误。"""


@dataclass
class RotationOptions:
    """轮换参数。"""

    keep_relative: bool = True     # 区域内是否保持相对位置
    wrap: bool = True              # 平移时是否回绕
    delta_row: int = 1
    delta_col: int = 0
    skip_disabled: bool = True


@dataclass
class RotationPlan:
    """一次轮换的预览结果。"""

    assignment: Assignment = field(default_factory=dict)
    moved: int = 0
    kept: int = 0
    description: str = ""
    warnings: List[str] = field(default_factory=list)
    changes: List[Tuple[str, str, str]] = field(default_factory=list)  # (seat, from_sid, to_sid)

    def to_dict(self) -> Dict[str, object]:
        return {"moved": self.moved, "kept": self.kept, "description": self.description}


class RotationService:
    """基于项目的轮换服务。"""

    def __init__(self, project: Project) -> None:
        self.project = project

    # ------------------------------------------------------------ 工具
    def _ordered(self, selection: Selection) -> List[Coord]:
        return sorted(selection.seats, key=lambda s: (s[1], s[0], s[2]))

    def _restricted_roles(self) -> Dict[str, Set[str]]:
        """提取“固定座位”等硬约束信息，轮换时提示冲突。"""
        from ..models.rule import RuleKind

        fixed: Dict[str, Set[str]] = {"sid": set(), "selection": set()}
        for rule in self.project.hard_rules():
            if rule.kind == RuleKind.FIXED_SEAT:
                if rule.target_sid():
                    fixed["sid"].add(rule.target_sid())
            elif rule.selection_id():
                fixed["selection"].add(rule.selection_id())
        return fixed

    def _check(self, assignment: Assignment) -> List[str]:
        """轮换后硬约束冲突提示。"""
        from .rule_engine import RuleEngine, describe_violations

        engine = RuleEngine.from_project(self.project)
        violations = engine.check_hard(assignment)
        if not violations:
            return []
        return ["轮换后存在 %d 条硬约束冲突：%s" % (len(violations), describe_violations(violations, 3))]

    # ------------------------------------------------------------ 区域轮换
    def region_rotate(
        self,
        selection_ids: Sequence[str],
        options: Optional[RotationOptions] = None,
    ) -> RotationPlan:
        """学生按区域整体循环：区域1 → 区域2 → ... → 区域N → 区域1。"""
        options = options or RotationOptions()
        selections: List[Selection] = []
        for selection_id in selection_ids:
            selection = self.project.get_selection(selection_id)
            if selection is None:
                raise RotationError("找不到选区：%s" % selection_id)
            if not selection.seats:
                raise RotationError("选区「%s」是空的" % selection.name)
            selections.append(selection)
        if len(selections) < 2:
            raise RotationError("区域轮换至少需要 2 个选区")

        source = dict(self.project.assignment)
        layout = self.project.layout
        warnings: List[str] = []
        restricted = self._restricted_roles()

        # 每个区域内的“已占用座位 + 学生”（按座位顺序，忽略空位）
        seats_of: List[List[Coord]] = []
        sids_of: List[List[str]] = []
        for selection in selections:
            seats = [s for s in self._ordered(selection) if layout.contains(s)]
            occupied = [s for s in seats if source.get(make_key(s), "")]
            seats_of.append(occupied)
            sids_of.append([source[make_key(s)] for s in occupied])

        count = len(selections)
        # 先把目标座位 -> 学生 的映射算完，再统一落盘（避免边改边读导致学生丢失）
        target_of: Dict[Coord, str] = {}
        for i in range(count):
            if options.keep_relative:
                # 整体搬到下一个区域：区域 i 的学生按原顺序坐进区域 i+1 的座位
                dst_seats = seats_of[(i + 1) % count]
                src_sids = sids_of[i]
            else:
                # 区域内重排：本区域座位接收下一个区域的学生名单
                dst_seats = seats_of[i]
                src_sids = sids_of[(i + 1) % count]
            for seat, sid in zip(dst_seats, src_sids):
                if options.skip_disabled and layout.is_disabled(seat):
                    continue
                target_of[seat] = sid

        affected: Set[Coord] = set()
        for seats in seats_of:
            affected.update(seats)
        assignment = {
            key: sid for key, sid in source.items()
            if try_parse_key(key) not in affected
        }
        for seat, sid in target_of.items():
            assignment[make_key(seat)] = sid
        missing = self._rescue_missing(source, assignment, affected, layout)
        if missing:
            warnings.append("有 %d 名学生因选区容量不足未能安排到目标座位" % missing)

        moved = sum(len(s) for s in sids_of)
        if restricted["sid"]:
            warnings.append(
                "有 %d 名学生被「固定座位」规则约束，轮换可能使其离开固定座位" % len(restricted["sid"])
            )
        plan = RotationPlan(
            assignment=assignment,
            moved=moved,
            kept=0,
            description="区域轮换：%s" % " → ".join(s.name for s in selections),
            warnings=warnings,
            changes=self._diff(assignment),
        )
        plan.warnings.extend(self._check(assignment))
        return plan

    # ------------------------------------------------------------ 平移轮换
    def shift(
        self,
        delta_row: int = 1,
        delta_col: int = 0,
        scope: Optional[Iterable[Coord]] = None,
        options: Optional[RotationOptions] = None,
    ) -> RotationPlan:
        """按 ``(Δrow, Δcol)`` 平移学生；可选 ``scope`` 限制参与座位。"""
        options = options or RotationOptions()
        layout = self.project.layout
        delta_row, delta_col = int(delta_row), int(delta_col)
        if delta_row == 0 and delta_col == 0:
            raise RotationError("平移向量不能是 (0, 0)")

        scope_set: Optional[Set[Coord]] = None
        if scope is not None:
            scope_set = set()
            for seat in scope:
                coord = try_parse_key(seat)
                if coord is not None:
                    scope_set.add(coord)

        source = dict(self.project.assignment)
        warnings: List[str] = []

        # 第一步：算出“目标座位 -> 学生”，同时做越界 / 空置校验
        target_of: Dict[Coord, str] = {}
        kept_sources: Set[Coord] = set()
        for key, sid in source.items():
            if not sid:
                continue
            coord = try_parse_key(key)
            if coord is None:
                continue
            if scope_set is not None and coord not in scope_set:
                continue
            g, r, c = coord
            if not (0 <= g < layout.group_count):
                continue
            group = layout.groups[g]
            nr, nc = r + delta_row, c + delta_col
            if options.wrap:
                nr = nr % group.rows
                nc = nc % group.cols
            elif not (0 <= nr < group.rows and 0 <= nc < group.cols):
                raise RotationError(
                    "平移后座位越界：%s（可勾选“边缘回绕”或减小位移）" % make_key(coord)
                )
            target: Coord = (g, nr, nc)
            if layout.is_disabled(target):
                if options.skip_disabled:
                    continue
                raise RotationError("平移后落在空置座位上：%s" % make_key(target))
            if scope_set is not None and target not in scope_set:
                continue
            target_of[target] = sid
            kept_sources.add(coord)

        # 第二步：统一重建（先清空所有会移动的源座位，再放人）
        affected = set(target_of) | kept_sources
        assignment = {
            key: value for key, value in source.items()
            if try_parse_key(key) not in affected
        }
        for seat, sid in target_of.items():
            assignment[make_key(seat)] = sid
        missing = self._rescue_missing(source, assignment, affected, layout)
        if missing:
            warnings.append("有 %d 名学生因目标座位被占用而未能平移" % missing)

        plan = RotationPlan(
            assignment=assignment,
            moved=len([v for v in assignment.values() if v]),
            kept=0,
            description="平移轮换：Δ排 %+d，Δ列 %+d" % (delta_row, delta_col),
            warnings=warnings,
            changes=self._diff(assignment),
        )
        plan.warnings.extend(self._check(assignment))
        return plan

    @staticmethod
    def _rescue_missing(
        source: Mapping[str, str], assignment: Dict[str, str], affected: Set[Coord], layout: Layout
    ) -> int:
        """兜底：任何“消失”的学生放回原座位或同区域内任意空位，绝不静默丢人。"""
        present = set(assignment.values())
        missing = [sid for sid in source.values() if sid and sid not in present]
        if not missing:
            return 0
        free = [
            seat for seat in sorted(affected)
            if not assignment.get(make_key(seat), "") and not layout.is_disabled(seat)
        ]
        rescued = 0
        for sid in missing:
            old_key = next((k for k, v in source.items() if v == sid), "")
            old_seat = try_parse_key(old_key) if old_key else None
            if old_seat is not None and not assignment.get(old_key, ""):
                assignment[old_key] = sid
                if old_seat in free:
                    free.remove(old_seat)
                rescued += 1
            elif free:
                seat = free.pop(0)
                assignment[make_key(seat)] = sid
                rescued += 1
        return len(missing) - rescued

    # ------------------------------------------------------------ 差异
    def _diff(self, assignment: Mapping[str, str]) -> List[Tuple[str, str, str]]:
        before = self.project.assignment
        changes: List[Tuple[str, str, str]] = []
        keys = set(before) | set(assignment)
        for key in sorted(keys, key=lambda k: (try_parse_key(k) or (0, 0, 0))):
            old = before.get(key, "")
            new = assignment.get(key, "")
            if old != new:
                changes.append((key, old, new))
        return changes

    # ------------------------------------------------------------ 应用
    def apply(self, plan: RotationPlan, label: str = "") -> RotationRecord:
        """把轮换方案写入项目并记录历史（第 N 周）。

        历史记录保存的是**轮换之前**的座位方案，也就是“第 N 周当时的排法”，
        因此 :meth:`rollback` 可以直接回到任意一周。当前（轮换后）的方案
        由主窗口的撤销栈负责回退。
        """
        project = self.project
        record = project.push_history(label or plan.description)
        project.previous_assignment = dict(project.assignment)
        project.assignment = dict(plan.assignment)
        project.notify("assignment")
        return record

    def rollback(self, week: int) -> bool:
        """回退到第 N 周。"""
        record = self.project.get_history(week)
        if record is None:
            return False
        self.project.previous_assignment = dict(self.project.assignment)
        self.project.assignment = dict(record.assignment)
        self.project.notify("assignment")
        return True
