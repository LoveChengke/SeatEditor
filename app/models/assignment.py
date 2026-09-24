"""分配结果（assignment）工具。

``assignment`` 是 ``{seat_key: sid}`` 的字典；未出现的座位表示空座。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from ..utils.seat_key import make_key, try_parse_key
from ..utils.seat_key import Seat as Coord

Assignment = Dict[str, str]


def seat_of(assignment: Mapping[str, str], sid: str) -> Optional[Coord]:
    """学生当前所在座位（未分配返回 None）。"""
    if not sid:
        return None
    for key, value in assignment.items():
        if value == sid:
            coord = try_parse_key(key)
            if coord is not None:
                return coord
    return None


def seat_key_of(assignment: Mapping[str, str], sid: str) -> Optional[str]:
    if not sid:
        return None
    for key, value in assignment.items():
        if value == sid:
            return key
    return None


def unassigned_students(assignment: Mapping[str, str], all_sids: Iterable[str]) -> List[str]:
    assigned = set(assignment.values())
    return [sid for sid in all_sids if sid not in assigned]


def is_valid(assignment: Mapping[str, str], layout) -> List[str]:
    """结构校验：座位是否存在、是否空置、是否有学生重复入座。"""
    problems: List[str] = []
    seen: Dict[str, str] = {}
    for key, sid in (assignment or {}).items():
        coord = try_parse_key(key)
        if coord is None:
            problems.append("非法座位键：%s" % key)
            continue
        if not layout.contains(coord):
            problems.append("座位越界：%s" % key)
            continue
        if layout.is_disabled(coord):
            problems.append("座位已空置但仍分配了学生：%s" % key)
        if not sid:
            continue
        if sid in seen:
            problems.append("学生 %s 被分配到多个座位（%s / %s）" % (sid, seen[sid], key))
        else:
            seen[sid] = key
    return problems


def sanitize(assignment: Mapping[str, str], layout, valid_sids: Optional[Iterable[str]] = None) -> Assignment:
    """清洗分配结果：剔除越界 / 空置座位，去掉重复学生。"""
    allowed = set(valid_sids) if valid_sids is not None else None
    result: Assignment = {}
    seen: Set[str] = set()
    for key, sid in (assignment or {}).items():
        coord = try_parse_key(key)
        if coord is None or not layout.contains(coord) or layout.is_disabled(coord):
            continue
        if not sid:
            continue
        if allowed is not None and sid not in allowed:
            continue
        if sid in seen:
            continue
        seen.add(sid)
        result[make_key(coord)] = sid
    return result


@dataclass
class Solution:
    """一次排位的结果。"""

    assignment: Assignment = field(default_factory=dict)
    score: float = 0.0                 # 综合目标值（越大越好）
    soft_score: float = 0.0            # 软约束得分 0~100
    hard_violations: List[Any] = field(default_factory=list)
    rule_scores: List[Any] = field(default_factory=list)
    restarts: int = 0
    iterations: int = 0
    elapsed: float = 0.0
    time_limit: float = 3.0
    locked_seats: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.hard_violations

    @property
    def hard_count(self) -> int:
        return len(self.hard_violations)
