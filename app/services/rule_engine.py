"""规则引擎：硬约束校验 + 软约束评分。

设计要点
--------
每条规则被展开成若干 **term**，每个 term 只依赖「自己的座位 + 少量邻居座位」
（``key`` 就是这些座位的集合）。于是：

* 全量评估 = 汇总所有 term；
* 增量评估 = 只汇总 ``key`` 与“变动座位集合及其邻居”相交的 term。

交换两个座位后重新打分只需对 ``focus = {s1, s2}`` 求两次评估并作差，
代价与座位总数、学生总数基本无关，因此 3 秒内可以完成几万次交换评估。

硬约束 term 的值恒为 1（计一次违反）；软约束 term 的值是该 term 的
满意度（0~1 的奖励分）。规则满意度 = raw 之和 / max 之和，
其中 max 只取决于“哪些学生已入座”，交换学生不影响它，
所以求解过程中的增量打分与全量打分的差值完全一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ..config import HARD_PENALTY
from ..models.layout import Layout
from ..models.rule import HARD, SOFT, Rule, RuleKind, RuleScore, Violation
from ..models.selection import Selection
from ..models.student import Student
from ..utils.seat_key import make_key, try_parse_key
from ..utils.seat_key import Seat as Coord

Key = Tuple[Coord, ...]

MALE = {"男", "male", "m", "男生", "1"}
FEMALE = {"女", "female", "f", "女生", "0", "2"}

# term 只依赖“自己所在座位”的规则：增量评估时只需扫描变动座位本身
OWN_SEAT_KINDS = frozenset({
    RuleKind.ATTR_ORDER, RuleKind.ATTR_TIER, RuleKind.FRONT_PREFER, RuleKind.AVOID_REPEAT,
    RuleKind.FIXED_SEAT, RuleKind.REGION_REQUIRED, RuleKind.REGION_FORBIDDEN,
    RuleKind.FRONT_REQUIRED,
})


def normalize_gender(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in MALE:
        return "男"
    if text in FEMALE:
        return "女"
    return ""


def _key_of(seats: Iterable[Coord]) -> Key:
    """term 的座位集合键；单座位走快路径（热路径上省掉 set + sort）。"""
    if isinstance(seats, tuple) and len(seats) == 1:
        s = seats[0]
        return ((int(s[0]), int(s[1]), int(s[2])),)
    values = [(int(s[0]), int(s[1]), int(s[2])) for s in seats]
    if len(values) == 1:
        return (values[0],)
    return tuple(sorted(set(values)))


@dataclass
class HardTerm:
    """一条硬约束违反（增量评估单位）。"""

    rule_id: str
    kind: str
    rule_label: str
    key: Key
    seats: List[Coord] = field(default_factory=list)
    students: List[str] = field(default_factory=list)
    message: str = ""

    def to_violation(self) -> Violation:
        return Violation(
            rule_id=self.rule_id,
            kind=self.kind,
            rule_label=self.rule_label,
            message=self.message,
            seats=[make_key(s) for s in sorted(self.seats)],
            students=list(self.students),
            severity=HARD,
        )


@dataclass
class SoftTerm:
    """一条软约束贡献（增量评估单位）。"""

    rule_id: str
    kind: str
    label: str
    weight: float
    key: Key
    value: float = 0.0          # 0~1，越大越好


@dataclass
class Evaluation:
    """一次评估的结果。"""

    hard_count: int = 0
    soft_raw: Dict[str, float] = field(default_factory=dict)
    soft_max: Dict[str, float] = field(default_factory=dict)
    objective: float = 0.0
    score: float = 0.0
    rule_scores: List[RuleScore] = field(default_factory=list)


class RuleEngine:
    """针对一份固定 ``layout`` + ``rules`` 的评估器。"""

    def __init__(
        self,
        layout: Layout,
        rules: Sequence[Rule],
        students: Optional[Iterable[Student]] = None,
        selections: Optional[Iterable[Selection]] = None,
        previous_assignment: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.layout = layout
        self.rules: List[Rule] = [r for r in (rules or []) if r.enabled]
        self.hard_rules: List[Rule] = [r for r in self.rules if r.is_hard]
        self.soft_rules: List[Rule] = [r for r in self.rules if r.is_soft]
        self.students: Dict[str, Student] = {s.sid: s for s in (students or [])}
        self.selections: Dict[str, Selection] = {s.id: s for s in (selections or [])}
        self.previous: Dict[str, str] = dict(previous_assignment or {})
        self._all_seats: List[Coord] = layout.all_seats()
        self._neighbor_cache: Dict[Coord, List[Coord]] = {}
        self._rank_cache: Dict[str, List[str]] = {}
        self._tier_cache: Dict[Tuple[str, int], Dict[str, int]] = {}
        self._target_cache: Dict[str, List[str]] = {}
        self._students_with_tag_cache: Dict[str, List[str]] = {}
        self._target_set_cache: Dict[str, Set[str]] = {}
        self._key_cache: Dict[Coord, str] = {}
        self._label_cache: Dict[str, str] = {}
        self._previous_by_sid: Dict[str, str] = {}
        for key, sid in self.previous.items():
            if sid:
                self._previous_by_sid[sid] = key

    # 构造
    @classmethod
    def from_project(cls, project) -> "RuleEngine":
        return cls(
            project.layout,
            project.rules,
            project.students,
            project.selections,
            project.previous_assignment,
        )

    # 缓存工具
    def key_of(self, seat: Coord) -> str:
        """``(g, r, c) -> "g-r-c"``，带缓存（热路径）。"""
        cached = self._key_cache.get(seat)
        if cached is None:
            cached = make_key(seat)
            self._key_cache[seat] = cached
        return cached

    def label_of(self, rule: Rule) -> str:
        cached = self._label_cache.get(rule.id)
        if cached is None:
            cached = rule.label
            self._label_cache[rule.id] = cached
        return cached

    def target_set(self, rule: Rule) -> Set[str]:
        cached = self._target_set_cache.get(rule.id)
        if cached is None:
            cached = set(self.target_sids(rule))
            self._target_set_cache[rule.id] = cached
        return cached
    def neighbors_of(self, seat: Coord) -> List[Coord]:
        cached = self._neighbor_cache.get(seat)
        if cached is None:
            cached = self.layout.neighbors(seat)
            self._neighbor_cache[seat] = cached
        return cached

    def students_with_tag(self, tag: str) -> List[str]:
        tag = str(tag or "").strip()
        if not tag:
            return []
        cached = self._students_with_tag_cache.get(tag)
        if cached is None:
            cached = [s.sid for s in self.students.values() if tag in s.tags]
            self._students_with_tag_cache[tag] = cached
        return cached

    def target_sids(self, rule: Rule) -> List[str]:
        """规则作用的学生集合：指定学生优先，其次标签。"""
        cached = self._target_cache.get(rule.id)
        if cached is not None:
            return cached
        sid = rule.target_sid()
        if sid:
            result = [sid] if sid in self.students else []
        else:
            result = self.students_with_tag(rule.target_tag())
        self._target_cache[rule.id] = result
        return result

    def ranked_sids(self, attr: str) -> List[str]:
        """按属性升序排列、且该属性存在的学生 sid 列表（与座位无关，可缓存）。"""
        cached = self._rank_cache.get(attr)
        if cached is None:
            pairs = [(s.sid, float(s.attrs[attr])) for s in self.students.values() if attr in s.attrs]
            pairs.sort(key=lambda item: (item[1], item[0]))
            cached = [sid for sid, _ in pairs]
            self._rank_cache[attr] = cached
        return cached

    def tier_index(self, attr: str, tiers: int) -> Dict[str, int]:
        """``sid -> 同档内序号``（属性排序后按档切分，档内再编号）。"""
        cache_key = (attr, int(tiers))
        cached = self._tier_cache.get(cache_key)
        if cached is not None:
            return cached
        ranked = self.ranked_sids(attr)
        n = len(ranked)
        result: Dict[str, int] = {}
        counters: Dict[int, int] = {}
        for i, sid in enumerate(ranked):
            tier = min(tiers - 1, i * tiers // n) if n else 0
            j = counters.get(tier, 0)
            counters[tier] = j + 1
            result[sid] = j
        self._tier_cache[cache_key] = result
        return result

    def _focus(self, focus: Optional[Iterable[Coord]]) -> Set[Coord]:
        if focus is None:
            return set(self._all_seats)
        return {(int(s[0]), int(s[1]), int(s[2])) for s in focus}

    def _wide_scope(self, focus: Optional[Iterable[Coord]]) -> Set[Coord]:
        """变动座位 + 其四邻域。

        因为“同桌 / 相邻”类 term 的 ``key`` 里包含自己的邻居座位，只有把邻居
        也纳入评估范围，“邻居位置变化导致的收益变化”才不会被漏掉；
        before / after 用同一个范围，差值即为真实增量。
        """
        return self._scopes(focus)[1]

    def _scopes(self, focus: Optional[Iterable[Coord]]) -> Tuple[Set[Coord], Set[Coord]]:
        """返回 ``(narrow, wide)``：只依赖自身的规则用 narrow，依赖邻居的用 wide。"""
        if focus is None:
            all_seats = set(self._all_seats)
            return all_seats, all_seats
        narrow = self._focus(focus)
        if len(narrow) >= len(self._all_seats):
            return narrow, narrow
        wide = set(narrow)
        for seat in narrow:
            wide.update(self.neighbors_of(seat))
        return narrow, wide

    def affected_seats(self, seats: Iterable[Coord]) -> Set[Coord]:
        """变动座位及其四邻域（UI 增量校验用）。"""
        return self._wide_scope(seats)

    def _seat_of(self, assignment: Mapping[str, str], sid: str) -> Optional[Coord]:
        for key, value in assignment.items():
            if value == sid:
                return try_parse_key(key)
        return None

    def _occupant(self, assignment: Mapping[str, str], seat: Coord) -> str:
        return assignment.get(self.key_of(seat), "")

    # ============================================================ 硬约束
    def hard_terms(
        self,
        assignment: Mapping[str, str],
        focus: Optional[Iterable[Coord]] = None,
        scope: Optional[Set[Coord]] = None,
    ) -> List[HardTerm]:
        if scope is not None:
            narrow = wide = scope
        else:
            narrow, wide = self._scopes(focus)
        if not wide:
            return []
        terms: Dict[Tuple[str, Key], HardTerm] = {}
        for rule in self.hard_rules:
            rule_scope = narrow if rule.kind in OWN_SEAT_KINDS else wide
            if not rule_scope:
                continue
            for term in self._hard_rule_terms(rule, assignment, rule_scope):
                terms.setdefault((term.rule_id, term.key), term)
        return list(terms.values())

    def _hard_rule_terms(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[HardTerm]:
        kind = rule.kind
        if kind == RuleKind.FIXED_SEAT:
            return self._hard_fixed_seat(rule, assignment, scope)
        if kind == RuleKind.FORBID_ADJACENT:
            return self._hard_forbid_adjacent(rule, assignment, scope)
        if kind == RuleKind.REGION_REQUIRED:
            return self._hard_region(rule, assignment, scope, required=True)
        if kind == RuleKind.REGION_FORBIDDEN:
            return self._hard_region(rule, assignment, scope, required=False)
        if kind == RuleKind.FRONT_REQUIRED:
            return self._hard_front_required(rule, assignment, scope)
        return []

    def _hard_fixed_seat(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[HardTerm]:
        seat = try_parse_key(rule.params.get("seat"))
        sid = rule.target_sid()
        if seat is None or not sid:
            return []
        seat_key = self.key_of(seat)
        if assignment.get(seat_key, "") == sid:
            return []
        # 只有在“该座位或其学生的实际座位”落在评估范围内时才算一条违反
        other = self._seat_of(assignment, sid)
        involved = [seat] if other is None or other == seat else [seat, other]
        if not (set(involved) & scope):
            return []
        return [HardTerm(
            rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
            key=_key_of(involved), seats=involved, students=[sid],
            message="「%s」应固定在 %s，实际在%s" % (
                self._name(sid), self._seat_text(seat),
                "未入座" if other is None else self._seat_text(other),
            ),
        )]

    def _hard_forbid_adjacent(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[HardTerm]:
        a, b = rule.target_sid_a(), rule.target_sid_b()
        if not a or not b:
            return []
        targets = (a, b)
        terms: List[HardTerm] = []
        seen: Set[Key] = set()
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if sid != a and sid != b:
                continue
            for neighbor in self.neighbors_of(seat):
                other = assignment.get(self.key_of(neighbor), "")
                if not other or other == sid or (other != a and other != b):
                    continue
                key = _key_of([seat, neighbor])
                if key in seen:
                    continue
                seen.add(key)
                terms.append(HardTerm(
                    rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
                    key=key, seats=[seat, neighbor], students=[sid, other],
                    message="「%s」与「%s」相邻（%s / %s），违反「禁止相邻」" % (
                        self._name(sid), self._name(other),
                        self._seat_text(seat), self._seat_text(neighbor),
                    ),
                ))
        return terms

    def _hard_region(
        self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord], required: bool
    ) -> List[HardTerm]:
        selection = self.selections.get(rule.selection_id())
        if selection is None or not selection.seats:
            return []
        targets = self.target_set(rule)
        if not targets:
            return []
        seats_in = selection.seats
        terms: List[HardTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in targets:
                continue
            inside = seat in seats_in
            if required and not inside:
                terms.append(HardTerm(
                    rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
                    key=_key_of([seat]), seats=[seat], students=[sid],
                    message="「%s」应在选区「%s」内，实际在 %s" % (
                        self._name(sid), selection.name, self._seat_text(seat)),
                ))
            elif (not required) and inside:
                terms.append(HardTerm(
                    rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
                    key=_key_of([seat]), seats=[seat], students=[sid],
                    message="「%s」不应进入选区「%s」，实际在 %s" % (
                        self._name(sid), selection.name, self._seat_text(seat)),
                ))
        return terms

    def _hard_front_required(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[HardTerm]:
        rows = self._int_param(rule, "rows", 2, 1)
        targets = self.target_set(rule)
        if not targets:
            return []
        terms: List[HardTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in targets:
                continue
            if self.layout.front_row_index(seat) >= rows:
                terms.append(HardTerm(
                    rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
                    key=_key_of([seat]), seats=[seat], students=[sid],
                    message="「%s」必须坐在前 %d 排，实际在 %s" % (
                        self._name(sid), rows, self._seat_text(seat)),
                ))
        return terms

    # ============================================================ 软约束
    def soft_terms(
        self,
        assignment: Mapping[str, str],
        focus: Optional[Iterable[Coord]] = None,
        scope: Optional[Set[Coord]] = None,
    ) -> List[SoftTerm]:
        if scope is not None:
            narrow = wide = scope
        else:
            narrow, wide = self._scopes(focus)
        if not wide:
            return []
        terms: List[SoftTerm] = []
        for rule in self.soft_rules:
            rule_scope = narrow if rule.kind in OWN_SEAT_KINDS else wide
            if not rule_scope:
                continue
            terms.extend(self._soft_rule_terms(rule, assignment, rule_scope))
        return terms

    def _soft_rule_terms(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        kind = rule.kind
        if kind == RuleKind.ATTR_ORDER:
            return self._soft_attr_order(rule, assignment, scope)
        if kind == RuleKind.ATTR_TIER:
            return self._soft_attr_tier(rule, assignment, scope)
        if kind == RuleKind.TAG_DISPERSE:
            return self._soft_tag_disperse(rule, assignment, scope)
        if kind == RuleKind.DESK_PAIR:
            return self._soft_desk_pair(rule, assignment, scope)
        if kind == RuleKind.AVOID_REPEAT:
            return self._soft_avoid_repeat(rule, assignment, scope)
        if kind == RuleKind.GENDER_ALTERNATE:
            return self._soft_gender_alternate(rule, assignment, scope)
        if kind == RuleKind.FRONT_PREFER:
            return self._soft_front_prefer(rule, assignment, scope)
        return []

    def _term(self, rule: Rule, key: Key, value: float) -> SoftTerm:
        return SoftTerm(
            rule.id, rule.kind, self.label_of(rule), rule.weight, key,
            max(0.0, min(1.0, value)),
        )

    def _soft_attr_order(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        """按属性排序入座：每个学生的“理想排（或组）”由他在属性序列中的名次决定。"""
        attr = str(rule.params.get("attr") or "").strip()
        if not attr:
            return []
        ranked = self.ranked_sids(attr)
        n = len(ranked)
        if n == 0:
            return []
        rank_of = {sid: i for i, sid in enumerate(ranked)}
        axis = str(rule.params.get("axis") or "row")
        if str(rule.params.get("direction") or "asc") == "desc":
            rank_of = {sid: n - 1 - i for sid, i in rank_of.items()}

        if axis == "group":
            buckets = max(1, self.layout.group_count)
            span = max(1, buckets - 1)

            def actual(seat: Coord) -> int:
                return seat[0]

            def ideal(rank: int) -> int:
                return min(buckets - 1, rank * buckets // n)
        else:
            rows = max(1, self.layout.max_rows)
            span = max(1, rows - 1)

            def actual(seat: Coord) -> int:
                return self.layout.front_row_index(seat)

            def ideal(rank: int) -> int:
                return min(rows - 1, rank * rows // n)

        terms: List[SoftTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in rank_of:
                continue
            diff = abs(actual(seat) - ideal(rank_of[sid]))
            terms.append(self._term(rule, _key_of([seat]), 1.0 - diff / float(span)))
        return terms

    def _soft_attr_tier(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        """属性分档均匀分布：同档内第 j 名学生希望落在第 ``j % 桶数`` 个桶。"""
        attr = str(rule.params.get("attr") or "").strip()
        if not attr:
            return []
        tiers = self._int_param(rule, "tiers", 4, 2)
        mode = str(rule.params.get("mode") or "group")
        index_of = self.tier_index(attr, tiers)
        if not index_of:
            return []

        if mode == "row":
            buckets = max(1, self.layout.max_rows)
            span = max(1, buckets - 1)

            def actual(seat: Coord) -> int:
                return self.layout.front_row_index(seat)
        else:
            buckets = max(1, self.layout.group_count)
            span = max(1, buckets - 1)

            def actual(seat: Coord) -> int:
                return seat[0]

        terms: List[SoftTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in index_of:
                continue
            diff = abs(actual(seat) - (index_of[sid] % buckets))
            terms.append(self._term(rule, _key_of([seat]), 1.0 - diff / float(span)))
        return terms

    def _soft_tag_disperse(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        """每个带该标签的学生一个 term：同标签邻居越少越好。"""
        tag = rule.target_tag()
        if not tag:
            return []
        terms: List[SoftTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid:
                continue
            student = self.students.get(sid)
            if student is None or tag not in student.tags:
                continue
            neighbor_seats = self.neighbors_of(seat)
            occupied = [n for n in neighbor_seats if assignment.get(self.key_of(n), "")]
            if not occupied:
                value = 1.0
            else:
                same = 0
                for n in occupied:
                    other = self.students.get(assignment.get(self.key_of(n), ""))
                    if other is not None and tag in other.tags:
                        same += 1
                value = 1.0 - same / float(len(occupied))
            terms.append(self._term(rule, _key_of([seat] + neighbor_seats), value))
        return terms

    def _soft_desk_pair(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        tag_a = str(rule.params.get("tag_a") or "").strip()
        tag_b = str(rule.params.get("tag_b") or "").strip()
        if not tag_a or not tag_b:
            return []
        mode = str(rule.params.get("mode") or "same")
        terms: List[SoftTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid:
                continue
            student = self.students.get(sid)
            if student is None or tag_a not in student.tags:
                continue
            group = self.layout.groups[seat[0]] if 0 <= seat[0] < self.layout.group_count else None
            if group is None:
                continue
            partner_seats: List[Coord] = [
                (seat[0], seat[1], col) for col in (seat[2] - 1, seat[2] + 1) if 0 <= col < group.cols
            ]
            occupied = [n for n in partner_seats if assignment.get(self.key_of(n), "")]
            hits = 0
            for n in occupied:
                other = self.students.get(assignment.get(self.key_of(n), ""))
                if other is not None and tag_b in other.tags:
                    hits += 1
            if mode == "apart":
                value = 1.0 if not occupied else 1.0 - hits / float(len(occupied))
            else:
                value = 0.0 if not occupied else hits / float(len(occupied))
            terms.append(self._term(rule, _key_of([seat] + partner_seats), value))
        return terms

    def _soft_avoid_repeat(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        previous_by_sid = self._previous_by_sid
        if not previous_by_sid:
            return []
        terms: List[SoftTerm] = []
        for seat in scope:
            key = self.key_of(seat)
            sid = assignment.get(key, "")
            if not sid or sid not in previous_by_sid:
                continue
            terms.append(self._term(rule, _key_of([seat]), 0.0 if previous_by_sid[sid] == key else 1.0))
        return terms

    def _soft_gender_alternate(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        """每个性别已知的学生一个 term：同桌中异性占比越高越好。"""
        terms: List[SoftTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid:
                continue
            student = self.students.get(sid)
            if student is None:
                continue
            gender = normalize_gender(student.gender)
            if not gender:
                continue
            group = self.layout.groups[seat[0]] if 0 <= seat[0] < self.layout.group_count else None
            if group is None:
                continue
            partner_seats: List[Coord] = [
                (seat[0], seat[1], col) for col in (seat[2] - 1, seat[2] + 1) if 0 <= col < group.cols
            ]
            known = 0
            opposite = 0
            for n in partner_seats:
                other = self.students.get(assignment.get(self.key_of(n), ""))
                if other is None:
                    continue
                other_gender = normalize_gender(other.gender)
                if not other_gender:
                    continue
                known += 1
                if other_gender != gender:
                    opposite += 1
            value = 1.0 if known == 0 else opposite / float(known)
            terms.append(self._term(rule, _key_of([seat] + partner_seats), value))
        return terms

    def _soft_front_prefer(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        sids = self.target_set(rule)
        if not sids:
            return []
        rows = max(1, self.layout.max_rows)
        terms: List[SoftTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in sids:
                continue
            index = self.layout.front_row_index(seat)
            value = 1.0 if rows <= 1 else max(0.0, 1.0 - index / float(rows - 1))
            terms.append(self._term(rule, _key_of([seat]), value))
        return terms

    # ============================================================ 评估
    def objective(
        self,
        assignment: Mapping[str, str],
        focus: Optional[Iterable[Coord]] = None,
        max_raw: Optional[Mapping[str, float]] = None,
        scope: Optional[Set[Coord]] = None,
    ) -> float:
        """只计算综合目标值（求解器热路径：不构造规则明细对象）。

        与 ``evaluate(...).objective`` 结果完全一致，但少了 RuleScore 列表、
        raw/max 字典复制等开销，单次交换评估更快。
        """
        ht = self.hard_terms(assignment, focus, scope)
        st = self.soft_terms(assignment, focus, scope)
        if max_raw is None:
            maxima = self.max_raw(assignment)
        else:
            maxima = max_raw
        raw: Dict[str, float] = {}
        for term in st:
            raw[term.rule_id] = raw.get(term.rule_id, 0.0) + term.value
        objective = -HARD_PENALTY * len(ht)
        for rule in self.soft_rules:
            maximum = maxima.get(rule.id, 0.0)
            if maximum <= 0:
                continue
            satisfaction = raw.get(rule.id, 0.0) / maximum
            if satisfaction > 1.0:
                satisfaction = 1.0
            objective += float(rule.weight) * satisfaction
        return objective

    def max_raw(
        self, assignment: Mapping[str, str], terms: Optional[List[SoftTerm]] = None
    ) -> Dict[str, float]:
        """每条软规则的理论满分（term 个数）。

        只取决于“哪些学生已入座”，交换学生不会改变它，
        因此可在求解开始时算一次并全程复用。
        """
        terms = self.soft_terms(assignment) if terms is None else terms
        result: Dict[str, float] = {rule.id: 0.0 for rule in self.soft_rules}
        for term in terms:
            result[term.rule_id] = result.get(term.rule_id, 0.0) + 1.0
        return result

    def evaluate(
        self,
        assignment: Mapping[str, str],
        focus: Optional[Iterable[Coord]] = None,
        hard_terms: Optional[List[HardTerm]] = None,
        soft_terms: Optional[List[SoftTerm]] = None,
        max_raw: Optional[Mapping[str, float]] = None,
    ) -> Evaluation:
        ht = self.hard_terms(assignment, focus) if hard_terms is None else hard_terms
        st = self.soft_terms(assignment, focus) if soft_terms is None else soft_terms

        raw: Dict[str, float] = {rule.id: 0.0 for rule in self.soft_rules}
        for term in st:
            raw[term.rule_id] = raw.get(term.rule_id, 0.0) + term.value

        if max_raw is None:
            maxima = self.max_raw(assignment)
        else:
            maxima = dict(max_raw)

        objective = -HARD_PENALTY * len(ht)
        weight_sum = 0.0
        weighted = 0.0
        rule_scores: List[RuleScore] = []
        for rule in self.soft_rules:
            maximum = maxima.get(rule.id, 0.0)
            satisfaction = 1.0 if maximum <= 0 else max(0.0, min(1.0, raw.get(rule.id, 0.0) / maximum))
            weight = float(rule.weight)
            objective += weight * satisfaction
            weighted += weight * satisfaction
            weight_sum += weight
            rule_scores.append(RuleScore(rule.id, rule.label, weight, raw.get(rule.id, 0.0), satisfaction))

        score = 100.0 if weight_sum <= 0 else 100.0 * weighted / weight_sum
        return Evaluation(
            hard_count=len(ht),
            soft_raw=raw,
            soft_max={k: float(v) for k, v in maxima.items()},
            objective=objective,
            score=score,
            rule_scores=rule_scores,
        )

    # PRD 接口
    def check_hard(
        self, assignment: Mapping[str, str], seats: Optional[Iterable[Coord]] = None
    ) -> List[Violation]:
        """硬约束校验；``seats`` 为 None 时全量校验，否则只校验受影响的座位。"""
        return [term.to_violation() for term in self.hard_terms(assignment, seats)]

    # 预检
    def precheck(self) -> List[str]:
        """搜索前的可行性预检，返回错误信息列表。"""
        problems: List[str] = []
        for rule in self.rules:
            for error in rule.validate():
                problems.append("规则「%s」：%s" % (rule.label, error))

        required: Dict[str, Set[str]] = {}
        forbidden: Dict[str, Set[str]] = {}
        for rule in self.hard_rules:
            if not rule.selection_id():
                continue
            sids = set(self.target_sids(rule))
            if not sids:
                continue
            if rule.kind == RuleKind.REGION_REQUIRED:
                required.setdefault(rule.selection_id(), set()).update(sids)
            elif rule.kind == RuleKind.REGION_FORBIDDEN:
                forbidden.setdefault(rule.selection_id(), set()).update(sids)
        for selection_id, sids in required.items():
            for sid in sorted(sids & forbidden.get(selection_id, set())):
                problems.append(
                    "「%s」同时被要求必须进入和不得进入选区「%s」"
                    % (self._name(sid), self._selection_name(selection_id))
                )

        fixed: Dict[str, str] = {}
        for rule in self.hard_rules:
            if rule.kind != RuleKind.FIXED_SEAT:
                continue
            sid, seat = rule.target_sid(), str(rule.params.get("seat") or "")
            if not sid or not seat:
                continue
            if sid in fixed and fixed[sid] != seat:
                problems.append("「%s」被固定到了多个座位" % self._name(sid))
            fixed[sid] = seat
        seat_owner: Dict[str, str] = {}
        for sid, seat in sorted(fixed.items()):
            if seat in seat_owner and seat_owner[seat] != sid:
                problems.append(
                    "座位 %s 被固定给了多名学生（%s / %s）" % (
                        self._seat_text(try_parse_key(seat)),
                        self._name(seat_owner[seat]), self._name(sid))
                )
            seat_owner[seat] = sid

        for sid, seat_key in fixed.items():
            seat = try_parse_key(seat_key)
            if seat is not None and self.layout.is_disabled(seat):
                problems.append("「%s」被固定在了空置座位上（%s）" % (self._name(sid), self._seat_text(seat)))

        for rule in self.hard_rules:
            if rule.kind == RuleKind.FRONT_REQUIRED:
                rows = self._int_param(rule, "rows", 2, 1)
                if rows > self.layout.max_rows:
                    problems.append(
                        "规则「%s」要求前 %d 排，但教室只有 %d 排" % (rule.label, rows, self.layout.max_rows)
                    )

        # 需要强制入座的学生数是否超过可用座位
        must_seat = set(fixed)
        if len(must_seat) > self.layout.available_count():
            problems.append("固定座位的学生人数超过可用座位数")
        return problems

    # 文案
    def _int_param(self, rule: Rule, key: str, default: int, minimum: int = 0) -> int:
        try:
            return max(minimum, int(rule.params.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _name(self, sid: str) -> str:
        student = self.students.get(sid)
        return student.name if student else (sid or "（未知学生）")

    def _selection_name(self, selection_id: str) -> str:
        selection = self.selections.get(selection_id)
        return selection.name if selection else (selection_id or "（未知选区）")

    def _seat_text(self, seat: Optional[Coord]) -> str:
        if seat is None:
            return "（未入座）"
        g, r, c = seat
        return "%s 第%d排 第%d列" % (self.layout.group_name(g), r + 1, c + 1)


def describe_violations(violations: Sequence[Violation], limit: int = 3) -> str:
    """把违反列表压成一行状态栏提示。"""
    if not violations:
        return ""
    head = "；".join(v.message for v in violations[:limit] if v.message)
    if len(violations) > limit:
        head += "；…还有 %d 条" % (len(violations) - limit)
    return head
