"""排位算法：随机重启 + 爬山法（局部交换）。

* 不使用多线程；``iterate(steps)`` 让 UI 用 ``QTimer`` 分片驱动，界面不卡。
* 交换评估用 :class:`RuleEngine` 的增量评估（focus = 两个座位），
  因此单次评估代价与座位总数基本无关。

座位占用集合在整个求解过程固定（固定座位 / 锁定座位 / 空座位都不变），
只有学生之间的相对位置被搜索——这正好符合教师“座位布局已定”的心智模型。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..config import DEFAULT_IDLE_LIMIT, DEFAULT_TIME_LIMIT
from ..models.assignment import Solution
from ..models.layout import Layout
from ..models.rule import RuleKind
from ..models.student import Student
from ..utils.seat_key import make_key, try_parse_key
from ..utils.seat_key import Seat as Coord
from .rule_engine import RuleEngine


class SolverError(Exception):
    """排位前检失败（面向用户的可读消息）。"""


@dataclass
class SolveReport:
    """求解过程的统计信息。"""

    restarts: int = 0
    iterations: int = 0
    accepted: int = 0
    rejected: int = 0
    elapsed: float = 0.0
    finished: bool = False
    reason: str = ""


class Solver:
    """随机重启 + 爬山法求解器。"""

    def __init__(
        self,
        engine: RuleEngine,
        students: Sequence[Student],
        time_limit: float = DEFAULT_TIME_LIMIT,
        locked_seats: Optional[Sequence[Coord]] = None,
        idle_limit: int = DEFAULT_IDLE_LIMIT,
        seed: Optional[int] = None,
        keep_current: bool = True,
    ) -> None:
        self.engine = engine
        self.layout: Layout = engine.layout
        self.students: List[Student] = list(students)
        self.time_limit = float(time_limit)
        self.idle_limit = max(20, int(idle_limit))
        self.random = random.Random(seed)
        self.report = SolveReport()
        self.keep_current = keep_current

        self.locked: Set[Coord] = {tuple(int(v) for v in s) for s in (locked_seats or [])}
        self.fixed: Dict[Coord, str] = {coord: sid for coord, sid in _fixed_of(engine)}

        self._base: Dict[str, str] = {}
        self._assignment: Dict[str, str] = {}
        self._best: Dict[str, str] = {}
        self._best_obj = float("-inf")
        self._max_raw: Dict[str, float] = {}
        self._movable: List[Coord] = []
        self._free_sids: List[str] = []
        self._objective = 0.0
        self._idle = 0
        self._start = 0.0
        self._deadline = 0.0
        self._finished = False
        self._prepared = False

    # 准备
    def prepare(self, initial: Optional[Mapping[str, str]] = None) -> None:
        """校验规模、确定座位占用集合、生成初始解。"""
        problems = self.engine.precheck()
        if problems:
            raise SolverError("\n".join(problems))

        layout = self.layout
        available = layout.available_seats()
        available_set = set(available)
        if len(self.students) > len(available):
            raise SolverError(
                "学生人数（%d）超过可用座位数（%d），请增加座位或取消部分空置座位"
                % (len(self.students), len(available))
            )

        sids = [s.sid for s in self.students]
        sid_set = set(sids)

        cleaned: Dict[str, str] = {}
        for key, sid in dict(initial or {}).items():
            coord = try_parse_key(key)
            if coord is None or coord not in available_set or sid not in sid_set:
                continue
            cleaned[make_key(coord)] = sid
        initial = cleaned

        # 1) 固定座位（规则）落位
        seated: Dict[Coord, str] = {}
        used_sids: Set[str] = set()
        for coord, sid in sorted(self.fixed.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])):
            if coord not in available_set or sid in used_sids:
                continue
            seated[coord] = sid
            used_sids.add(sid)

        # 2) 锁定座位（用户“锁定当前满意的座位再排位”）保持原位
        for coord in sorted(self.locked, key=lambda s: (s[0], s[1], s[2])):
            if coord in seated or coord not in available_set:
                continue
            sid = initial.get(make_key(coord), "")
            if sid and sid in sid_set and sid not in used_sids:
                seated[coord] = sid
                used_sids.add(sid)

        # 3) 沿用当前方案（已经排过位时才沿用，避免把“随机旧数据”当初始解）
        if self.keep_current and _should_keep(self.engine, initial):
            for coord in available:
                if coord in seated or coord in self.locked:
                    continue
                sid = initial.get(make_key(coord), "")
                if sid and sid in sid_set and sid not in used_sids:
                    seated[coord] = sid
                    used_sids.add(sid)

        free_sids = [sid for sid in sids if sid not in used_sids]
        movable = [s for s in available if s not in seated and s not in self.locked]
        # 让空座位落在靠后的位置：优先占用靠前的座位
        movable.sort(key=lambda s: (layout.front_row_index(s), s[0], s[2]))
        if len(free_sids) > len(movable):
            raise SolverError("可用座位不足，无法安排全部学生（可用 %d，需要 %d）" % (len(movable), len(free_sids)))
        chosen = self._pick_seats(movable, seated, len(free_sids))
        self._movable = sorted(chosen, key=lambda s: (s[0], s[1], s[2]))
        self._free_sids = free_sids

        self._base = {make_key(coord): sid for coord, sid in seated.items()}

        # 4) 初始解 + 预热的满分基准
        self._assignment = self._randomize()
        self._max_raw = self.engine.max_raw(self._assignment)
        self._objective = self.engine.objective(self._assignment, max_raw=self._max_raw)
        self._best_obj = self._objective
        self._best = dict(self._assignment)

        self.report = SolveReport()
        self._idle = 0
        self._start = 0.0
        self._deadline = 0.0
        self._finished = False
        self._prepared = True

    def _pick_seats(self, movable: List[Coord], seated: Mapping[Coord, str], count: int) -> List[Coord]:
        """从（已按“靠前优先”排好序的）候选座位里挑出这次要占用的座位。

        默认就是原行为 ``movable[:count]``。但「每组人数上限」和「各组人数均衡」
        管的是“每组占几个座位”，而搜索期间**占用的座位集合是固定的**——
        不在这一步体现，它们对一键排位就完全没有作用。
        """
        limit = self._group_limit()
        if limit is None and not self._wants_balance():
            return movable[:count]

        used: Dict[int, int] = {}
        for coord in seated:
            used[coord[0]] = used.get(coord[0], 0) + 1
        room: Dict[int, int] = {}
        for coord in movable:
            room[coord[0]] = room.get(coord[0], 0) + 1

        quota: Dict[int, int] = {}
        for group, free in room.items():
            if limit is None:
                quota[group] = free
            else:
                quota[group] = max(0, min(free, limit - used.get(group, 0)))
        if self._wants_balance():
            quota = self._balance_quota(quota, used, count)

        chosen: List[Coord] = []
        for seat in movable:
            group = seat[0]
            if quota.get(group, 0) <= 0:
                continue
            quota[group] -= 1
            chosen.append(seat)
            if len(chosen) >= count:
                break
        if len(chosen) < count:
            # 名额不够就退回原行为：不静默把学生挤掉，原因由 precheck 说出来
            return movable[:count]
        return chosen

    def _group_limit(self) -> Optional[int]:
        """所有「每组人数上限」规则里最严格的那个上限。"""
        limits: List[int] = []
        for rule in self.engine.hard_rules:
            if rule.kind != RuleKind.GROUP_SIZE_LIMIT:
                continue
            try:
                limits.append(max(1, int(rule.params.get("limit", 8))))
            except (TypeError, ValueError):
                limits.append(8)
        return min(limits) if limits else None

    def _wants_balance(self) -> bool:
        return any(rule.kind == RuleKind.GROUP_BALANCE for rule in self.engine.soft_rules)

    def _balance_quota(self, quota: Dict[int, int], used: Mapping[int, int], count: int) -> Dict[int, int]:
        """把 count 个名额在各组间尽量摊平（组间人数差 ≤ 1），且不超过各组上限。

        每轮把名额给「已占 + 已分配」最少的组，所以已有的占用也会被算进去。
        """
        result: Dict[int, int] = {group: 0 for group in quota}
        remaining = count
        while remaining > 0:
            candidates = [g for g in sorted(quota) if result[g] < quota[g]]
            if not candidates:
                break
            target = min(candidates, key=lambda g: (used.get(g, 0) + result[g], g))
            result[target] += 1
            remaining -= 1
        return result

    def _randomize(self) -> Dict[str, str]:
        """随机初始化（固定 / 锁定座位先落位）。"""
        assignment = dict(self._base)
        pool = list(self._free_sids)
        self.random.shuffle(pool)
        for coord, sid in zip(self._movable, pool):
            assignment[make_key(coord)] = sid
        return assignment

    # 求解
    def solve(self, initial: Optional[Mapping[str, str]] = None) -> Solution:
        if not self._prepared:
            self.prepare(initial)
        self._start = time.time()
        self._deadline = self._start + self.time_limit
        guard = 0
        while not self.iterate(200):
            guard += 1
            if guard > 100000:  # 兜底
                break
        return self.best_solution()

    def iterate(self, steps: int = 50) -> bool:
        """推进 ``steps`` 次交换评估；返回是否已结束。"""
        if not self._prepared:
            self.prepare()
        if self._finished:
            return True
        if self._start <= 0:
            self._start = time.time()
            self._deadline = self._start + self.time_limit

        for _ in range(max(1, int(steps))):
            if time.time() >= self._deadline:
                self._finished = True
                self.report.reason = "达到时间上限"
                break
            if not self._movable or len(self._movable) < 2:
                self._finished = True
                self.report.reason = "没有可交换的座位"
                break
            if self._idle >= self.idle_limit:
                self._restart()
            self._step()
        self.report.elapsed = time.time() - self._start
        self.report.finished = self._finished
        return self._finished

    def _restart(self) -> None:
        self.report.restarts += 1
        self._assignment = self._randomize()
        self._objective = self.engine.objective(self._assignment, max_raw=self._max_raw)
        self._idle = 0
        if self._objective > self._best_obj:
            self._best_obj = self._objective
            self._best = dict(self._assignment)

    def _step(self) -> None:
        s1, s2 = self.random.sample(self._movable, 2)
        k1, k2 = make_key(s1), make_key(s2)
        v1, v2 = self._assignment.get(k1, ""), self._assignment.get(k2, "")
        if v1 == v2:
            return
        focus = {s1, s2}
        before = self.engine.objective(self._assignment, focus=focus, max_raw=self._max_raw)
        self._assignment[k1], self._assignment[k2] = v2, v1
        after = self.engine.objective(self._assignment, focus=focus, max_raw=self._max_raw)
        self.report.iterations += 1
        if after >= before:
            self._objective += after - before
            self.report.accepted += 1
            if after > before:
                self._idle = 0
                if self._objective > self._best_obj:
                    self._consider_objective()
            else:
                self._idle += 1
        else:
            self._assignment[k1], self._assignment[k2] = v1, v2
            self.report.rejected += 1
            self._idle += 1

    def _consider_objective(self) -> None:
        """当前解优于历史最优时记下来（用全量评估确认，避免累计误差）。"""
        value = self.engine.objective(self._assignment, max_raw=self._max_raw)
        if value > self._best_obj:
            self._best_obj = value
            self._best = dict(self._assignment)
            self._objective = value

    # 结果
    @property
    def best_assignment(self) -> Dict[str, str]:
        return dict(self._best or self._assignment)

    def progress(self) -> float:
        """0.0 ~ 1.0 的进度（按时间估算）。"""
        if self.time_limit <= 0:
            return 1.0
        elapsed = time.time() - self._start if self._start else 0.0
        return max(0.0, min(1.0, elapsed / self.time_limit))

    def best_solution(self) -> Solution:
        assignment = self.best_assignment
        evaluation = self.engine.evaluate(assignment)
        violations = self.engine.check_hard(assignment)
        return Solution(
            assignment=assignment,
            score=evaluation.objective,
            soft_score=evaluation.score,
            hard_violations=violations,
            rule_scores=evaluation.rule_scores,
            restarts=self.report.restarts,
            iterations=self.report.iterations,
            elapsed=self.report.elapsed or (time.time() - self._start if self._start else 0.0),
            time_limit=self.time_limit,
            locked_seats=[make_key(s) for s in sorted(self.locked)],
        )


def _fixed_of(engine: RuleEngine) -> List[Tuple[Coord, str]]:
    """从引擎的规则里提取固定座位。"""
    from ..models.rule import RuleKind

    result: List[Tuple[Coord, str]] = []
    for rule in engine.hard_rules:
        if rule.kind != RuleKind.FIXED_SEAT:
            continue
        coord = try_parse_key(rule.params.get("seat"))
        sid = rule.target_sid()
        if coord is not None and sid:
            result.append((coord, sid))
    return result


def _should_keep(engine: RuleEngine, initial: Mapping[str, str]) -> bool:
    """当前方案是否“已经排过位”（至少一半人已入座）。"""
    if not initial:
        return False
    seated = len([v for v in initial.values() if v])
    total = len(getattr(engine, "students", {}) or {})
    return seated >= max(1, total // 2)


