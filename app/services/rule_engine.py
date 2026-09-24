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
from ..models.rule import HARD, PAIR_KINDS, RULE_SPECS, Rule, RuleKind, RuleScore, Violation
from ..models.selection import Selection
from ..models.student import Student
from ..utils.natural_sort import natural_key
from ..utils.seat_key import make_key, try_parse_key
from ..utils.seat_key import Seat as Coord

Key = Tuple[Coord, ...]

MALE = {"男", "male", "m", "男生", "1"}
FEMALE = {"女", "female", "f", "女生", "0", "2"}

# 增量评估要扫多大范围由每条规则自己的“影响半径”决定（0 只扫变动座位本身、
# 1 再加四邻域、2 再加整组），登记在 models/rule.py 的 RuleSpec.scope 上，
# 引擎启动时会校验没有漏登记（见 RuleEngine._check_scopes）。


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
        self._prev_desk_mates: Dict[str, Set[str]] = {}
        for key, sid in self.previous.items():
            seat = try_parse_key(key)
            if seat is None or not sid:
                continue
            for mate_seat in self._desk_mates(seat):
                mate = self.previous.get(self.key_of(mate_seat), "")
                if mate and mate != sid:
                    self._prev_desk_mates.setdefault(sid, set()).add(mate)
        self._pair_cache: Dict[str, Tuple[Set[str], Set[str]]] = {}
        self._seat_index_cache: Optional[Dict[str, Coord]] = None
        self._group_seats_cache: Dict[int, List[Coord]] = {}
        self._active_groups_cache: Optional[List[int]] = None
        self._order_cache: Dict[str, List[str]] = {}
        self._max_distance_cache: Optional[int] = None
        # 全班男生比例：整组类规则的目标值。刻意用「全体学生」而不是「已入座学生」
        # 算，让它是与排位完全无关的常量——否则它会在交换下变化，而没被扫到的组
        # 的 term 不会重算，增量差就不再等于全量差。
        known = 0
        males = 0
        for student in self.students.values():
            gender = normalize_gender(student.gender)
            if not gender:
                continue
            known += 1
            if gender == "男":
                males += 1
        self._male_ratio = (males / float(known)) if known else 0.5
        self._stage_cache: Dict[str, int] = {}
        self._check_scopes()
        # 没有整组类规则时，整组范围既没人用也不该进 affected_seats
        self._has_group_scope = any(self._stage_of(r) == 2 for r in self.rules)

    def _check_scopes(self) -> None:
        """每条规则种类都必须登记合法的扫描半径。

        漏登记会让增量评估静默算错（求解器照跑，只是结果不再等于报表里的分数），
        所以宁可在这里响亮地失败。见 RuleSpec.scope 的注释。
        """
        bad = sorted(kind for kind, spec in RULE_SPECS.items() if spec.scope not in (0, 1, 2))
        if bad:
            raise ValueError("这些规则种类没有登记合法的 scope：%s" % ", ".join(bad))

    def _stage_of(self, rule: Rule) -> int:
        """该规则该用哪一档扫描范围（0 / 1 / 2）。"""
        cached = self._stage_cache.get(rule.kind)
        if cached is None:
            spec = RULE_SPECS.get(rule.kind)
            cached = int(spec.scope) if spec is not None and spec.scope in (0, 1, 2) else 1
            self._stage_cache[rule.kind] = cached
        return cached

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

    def _desk_mates(self, seat: Coord) -> List[Coord]:
        """同桌座位：同一排左右相邻的两列（不跨排、不跨组）。"""
        group_index = int(seat[0])
        if not (0 <= group_index < self.layout.group_count):
            return []
        cols = self.layout.groups[group_index].cols
        col = int(seat[2])
        return [(group_index, int(seat[1]), c) for c in (col - 1, col + 1) if 0 <= c < cols]

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

    def pair_sets(self, rule: Rule) -> Tuple[Set[str], Set[str]]:
        """``(对象 A 的学生集合, 对象 B 的学生集合)``，每个端点都是学生优先于标签。"""
        cached = self._pair_cache.get(rule.id)
        if cached is None:
            cached = (self._side_sids(rule, "a"), self._side_sids(rule, "b"))
            self._pair_cache[rule.id] = cached
        return cached

    def _side_sids(self, rule: Rule, suffix: str) -> Set[str]:
        sid = str(rule.params.get("sid_" + suffix) or "").strip()
        if sid:
            return {sid} if sid in self.students else set()
        tag = str(rule.params.get("tag_" + suffix) or "").strip()
        return set(self.students_with_tag(tag))

    def _side_text(self, rule: Rule, suffix: str) -> str:
        """「对象 A / 对象 B」端点的中文描述（用于冲突文案）。"""
        sid = str(rule.params.get("sid_" + suffix) or "").strip()
        if sid:
            return "「%s」" % self._name(sid)
        tag = str(rule.params.get("tag_" + suffix) or "").strip()
        if tag:
            return "「%s」标签学生" % tag
        return "（未指定对象）"

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

    def _group_seats(self, seat: Coord) -> List[Coord]:
        """座位所在组的全部座位；组下标越界时返回空。"""
        group_index = int(seat[0])
        if not (0 <= group_index < self.layout.group_count):
            return []
        cached = self._group_seats_cache.get(group_index)
        if cached is None:
            cached = self.layout.seats_in_group(group_index)
            self._group_seats_cache[group_index] = cached
        return cached

    def _active_group_indexes(self) -> List[int]:
        """有可用座位的组下标。只由布局决定，与谁坐在哪里无关。"""
        if self._active_groups_cache is None:
            result: List[int] = []
            for index in range(self.layout.group_count):
                if any(not self.layout.is_disabled(seat) for seat in self.layout.seats_in_group(index)):
                    result.append(index)
            self._active_groups_cache = result
        return self._active_groups_cache

    def _group_seated_count(self, group_index: int, assignment: Mapping[str, str]) -> int:
        count = 0
        for seat in self.layout.seats_in_group(group_index):
            if assignment.get(self.key_of(seat), ""):
                count += 1
        return count

    def _group_gender_counts(self, group_index: int, assignment: Mapping[str, str]) -> Tuple[int, int]:
        """``(性别已知人数, 其中男生数)``。"""
        known = 0
        males = 0
        for seat in self.layout.seats_in_group(group_index):
            sid = assignment.get(self.key_of(seat), "")
            if not sid:
                continue
            student = self.students.get(sid)
            if student is None:
                continue
            gender = normalize_gender(student.gender)
            if not gender:
                continue
            known += 1
            if gender == "男":
                males += 1
        return known, males

    def _order_sequence(self, rule: Rule) -> List[str]:
        """「按顺序排座」的顺序：给了数值属性就按属性升序，否则按学号的自然序。"""
        attr = str(rule.params.get("attr") or "").strip()
        cached = self._order_cache.get(attr)
        if cached is None:
            if attr:
                cached = list(self.ranked_sids(attr))
            else:
                cached = sorted(self.students, key=natural_key)
            self._order_cache[attr] = cached
        return cached

    def _order_position(self, seat: Coord, axis: str) -> int:
        if axis == "group":
            return int(seat[0])
        return self.layout.front_row_index(seat)

    def _max_distance(self) -> int:
        """教室里两个座位之间最大的曼哈顿距离（只由布局决定）。"""
        if self._max_distance_cache is None:
            seats = self._all_seats
            if not seats:
                self._max_distance_cache = 1
            else:
                span = (max(s[0] for s in seats) + max(s[1] for s in seats)
                        + max(s[2] for s in seats))
                self._max_distance_cache = max(1, span)
        return self._max_distance_cache

    def _scope_sets(self, focus: Optional[Iterable[Coord]]) -> Tuple[Set[Coord], Set[Coord], Set[Coord]]:
        """返回 ``(radius0, radius1, radius2)`` 三档扫描范围，按规则的影响半径取用。

        半径的含义见 ``RuleSpec.scope``：0 只扫变动座位本身，1 还要加四邻域
        （"同桌 / 相邻"类 term 的 ``key`` 含邻居座位，只有把邻居纳入范围，
        "邻居位置变化导致的收益变化"才不会被漏掉），2 还要加整组（每组人数、
        组内男女比例这类全组计数）。

        **三档都只由坐标导出，绝不读占用者**：before / after 两次评估必须拿到
        同一组集合，差值才是真实增量。
        """
        if focus is None:
            all_seats = set(self._all_seats)
            return all_seats, all_seats, all_seats
        narrow = self._focus(focus)
        if len(narrow) >= len(self._all_seats):
            return narrow, narrow, narrow
        wide = set(narrow)
        group = set(narrow)
        for seat in narrow:
            wide.update(self.neighbors_of(seat))
            group.update(self._group_seats(seat))
        return narrow, wide, group

    def affected_seats(self, seats: Iterable[Coord]) -> Set[Coord]:
        """变动座位及其可能波及的座位（UI 增量校验用）。

        取三档范围的并集：宁可多标几处，也不能漏掉旧标记，
        否则界面上会残留已经不存在的高亮。
        """
        narrow, wide, group = self._scope_sets(seats)
        if self._has_group_scope:
            return narrow | wide | group
        return narrow | wide

    def _seat_index(self, assignment: Mapping[str, str]) -> Dict[str, Coord]:
        """本次评估的 ``sid -> 座位`` 索引（供「对象对」类规则反查）。

        求解器是**原地交换**那个 assignment 字典，所以缓存不能跨调用复用：
        ``hard_terms`` / ``soft_terms`` 每次进来都会把它置为 None。
        没有规则用到时不会构建（惰性）。
        """
        if self._seat_index_cache is None:
            index: Dict[str, Coord] = {}
            for key, sid in assignment.items():
                if not sid:
                    continue
                seat = try_parse_key(key)
                if seat is not None:
                    index[sid] = seat
            self._seat_index_cache = index
        return self._seat_index_cache

    def _seat_of(self, assignment: Mapping[str, str], sid: str) -> Optional[Coord]:
        return self._seat_index(assignment).get(sid)

    def _occupant(self, assignment: Mapping[str, str], seat: Coord) -> str:
        return assignment.get(self.key_of(seat), "")

    # 硬约束
    def hard_terms(
        self,
        assignment: Mapping[str, str],
        focus: Optional[Iterable[Coord]] = None,
        scope: Optional[Set[Coord]] = None,
    ) -> List[HardTerm]:
        self._seat_index_cache = None
        if scope is not None:
            narrow = wide = group = scope
        else:
            narrow, wide, group = self._scope_sets(focus)
        if not wide:
            return []
        terms: Dict[Tuple[str, Key], HardTerm] = {}
        for rule in self.hard_rules:
            rule_scope = (narrow, wide, group)[self._stage_of(rule)]
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
        if kind == RuleKind.MUST_DESK:
            return self._hard_must_desk(rule, assignment, scope)
        if kind == RuleKind.FORBID_DESK:
            return self._hard_forbid_desk(rule, assignment, scope)
        if kind == RuleKind.MUST_ADJACENT:
            return self._hard_must_adjacent(rule, assignment, scope)
        if kind == RuleKind.FORBID_ADJACENT_PAIR:
            return self._hard_forbid_adjacent_pair(rule, assignment, scope)
        if kind == RuleKind.NEIGHBOR_CLEAR:
            return self._hard_neighbor_clear(rule, assignment, scope)
        if kind == RuleKind.SAME_AREA:
            return self._hard_same_area(rule, assignment, scope)
        if kind == RuleKind.GROUP_SIZE_LIMIT:
            return self._hard_group_size_limit(rule, assignment, scope)
        if kind == RuleKind.EXAM_ORDER:
            return self._hard_exam_order(rule, assignment, scope)
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

    def _hard_must_desk(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[HardTerm]:
        """对象 A 的每个已入座成员，至少有一个对象 B 的同桌。

        「至少一个」而不是「全部同桌都得是 B」：一个 A 同学夹在两个 B 同学中间
        是完全正常的排法。``seats`` 只放自己——同桌是被换走的那个座位时，
        把同桌也写进去会让冲突标记落到两跳之外，界面上清不掉。
        """
        sids_a, sids_b = self.pair_sets(rule)
        if not sids_a or not sids_b:
            return []
        terms: List[HardTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in sids_a:
                continue
            if any(assignment.get(self.key_of(n), "") in sids_b for n in self._desk_mates(seat)):
                continue
            terms.append(HardTerm(
                rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
                key=_key_of([seat]), seats=[seat], students=[sid],
                message="「%s」在 %s 没有和%s同桌" % (
                    self._name(sid), self._seat_text(seat), self._side_text(rule, "b")),
            ))
        return terms

    def _hard_forbid_desk(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[HardTerm]:
        """对象 A 的学生不得与对象 B 的学生同桌，每个同桌对算一条。"""
        sids_a, sids_b = self.pair_sets(rule)
        if not sids_a or not sids_b:
            return []
        terms: List[HardTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in sids_a:
                continue
            for mate in self._desk_mates(seat):
                other = assignment.get(self.key_of(mate), "")
                if not other or other not in sids_b:
                    continue
                terms.append(HardTerm(
                    rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
                    key=_key_of([seat, mate]), seats=[seat, mate], students=[sid, other],
                    message="「%s」与「%s」同桌（%s / %s），违反「禁止同桌」" % (
                        self._name(sid), self._name(other),
                        self._seat_text(seat), self._seat_text(mate)),
                ))
        return terms

    def _hard_must_adjacent(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[HardTerm]:
        """对象 A 的每个已入座成员，四邻域里至少有一个对象 B 的成员。"""
        sids_a, sids_b = self.pair_sets(rule)
        if not sids_a or not sids_b:
            return []
        terms: List[HardTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in sids_a:
                continue
            if any(assignment.get(self.key_of(n), "") in sids_b for n in self.neighbors_of(seat)):
                continue
            terms.append(HardTerm(
                rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
                key=_key_of([seat]), seats=[seat], students=[sid],
                message="「%s」在 %s 附近没有%s" % (
                    self._name(sid), self._seat_text(seat), self._side_text(rule, "b")),
            ))
        return terms

    def _hard_forbid_adjacent_pair(
        self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]
    ) -> List[HardTerm]:
        """对象 A 的学生不得与对象 B 的学生相邻（四邻域），每个相邻对算一条。"""
        sids_a, sids_b = self.pair_sets(rule)
        if not sids_a or not sids_b:
            return []
        terms: List[HardTerm] = []
        seen: Set[Key] = set()
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in sids_a:
                continue
            for neighbor in self.neighbors_of(seat):
                other = assignment.get(self.key_of(neighbor), "")
                if not other or other not in sids_b:
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
                        self._seat_text(seat), self._seat_text(neighbor)),
                ))
        return terms

    def _hard_neighbor_clear(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[HardTerm]:
        """目标学生的四邻域里不得有其他学生（可选地放过某个标签的学生）。"""
        sids = self.target_set(rule)
        if not sids:
            return []
        allow_tag = str(rule.params.get("allow") or "").strip()
        allowed = set(self.students_with_tag(allow_tag)) if allow_tag else set()
        terms: List[HardTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in sids:
                continue
            intruders = []
            for neighbor in self.neighbors_of(seat):
                other = assignment.get(self.key_of(neighbor), "")
                if other and other != sid and other not in allowed:
                    intruders.append(other)
            if not intruders:
                continue
            names = "、".join("「%s」" % self._name(s) for s in intruders)
            terms.append(HardTerm(
                rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
                key=_key_of([seat]), seats=[seat], students=[sid] + intruders,
                message="「%s」四周还有 %s" % (self._name(sid), names),
            ))
        return terms

    def _hard_same_area(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[HardTerm]:
        """对象 A 与对象 B 的学生必须在同一个组（或同一排），两端都已入座才判定。

        **两个端点都当锚点**（其它规则只需锚在"对象 A 的座位"上）：同组 / 同排不是
        局部关系，两端可能隔着好几个组。只从 A 侧生成的话，"B 侧的学生被换走了"
        这件事在增量评估里根本看不见——focus 里没有 A 的座位，那条 term 就不会
        被重算，差值也就与全量对不上了。key 是对称的，两端各生成一次会被去重。

        ``seats`` 只放锚点：另一端可能在好几个组之外，写进去会让冲突标记落在
        ``affected_seats`` 之外，界面上就清不掉了。
        """
        sids_a, sids_b = self.pair_sets(rule)
        if not sids_a or not sids_b:
            return []
        mode = str(rule.params.get("mode") or "group")
        where = "同一个组" if mode == "group" else "同一排"
        index = self._seat_index(assignment)
        terms: List[HardTerm] = []
        seen: Set[Key] = set()
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid:
                continue
            in_a = sid in sids_a
            in_b = sid in sids_b
            if not in_a and not in_b:
                continue
            others: Set[str] = set()
            if in_a:
                others |= sids_b
            if in_b:
                others |= sids_a
            others.discard(sid)
            for other in sorted(others):
                mate = index.get(other)
                if mate is None:
                    continue
                same = (mate[0] == seat[0]) if mode == "group" else (mate[1] == seat[1])
                if same:
                    continue
                key = _key_of([seat, mate])
                if key in seen:
                    continue
                seen.add(key)
                terms.append(HardTerm(
                    rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
                    key=key, seats=[seat], students=[sid, other],
                    message="「%s」（%s）与「%s」（%s）不在%s" % (
                        self._name(sid), self._seat_text(seat),
                        self._name(other), self._seat_text(mate), where),
                ))
        return terms

    def _hard_group_size_limit(
        self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]
    ) -> List[HardTerm]:
        """每个组的已入座人数不得超过上限，一组最多一条。

        ``seats`` 只放超限的那几个座位（按坐标排序取最后几个，是占用集合的函数）：
        整组写进去的话，状态栏按座位计数会把"1 条违反"显示成十几处冲突。
        """
        limit = self._int_param(rule, "limit", 8, 1)
        terms: List[HardTerm] = []
        seen: Set[int] = set()
        for seat in scope:
            group_index = int(seat[0])
            if group_index in seen or not (0 <= group_index < self.layout.group_count):
                continue
            seen.add(group_index)
            seats = self._group_seats(seat)
            occupied = [s for s in seats if assignment.get(self.key_of(s), "")]
            if len(occupied) <= limit:
                continue
            occupied.sort()
            extra = occupied[limit:]
            terms.append(HardTerm(
                rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
                key=_key_of(seats), seats=extra,
                students=[assignment.get(self.key_of(s), "") for s in extra],
                message="%s 坐了 %d 人，超过上限 %d 人" % (
                    self.layout.group_name(group_index), len(occupied), limit),
            ))
        return terms

    def _hard_exam_order(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[HardTerm]:
        """按顺序就座：排序序列里相邻名次的两个人，位置必须是非降的。

        写成「相邻名次对」的局部约束，而不是「某人的理想排 = 名次 × 排数 ÷ 人数」：
        学生数通常远多于排数，后者必然不可满足，会变成一笔永远还不清的罚分。
        两端都已入座才判定；``seats`` 只放锚点。
        """
        sequence = self._order_sequence(rule)
        if len(sequence) < 2:
            return []
        rank_of = {sid: i for i, sid in enumerate(sequence)}
        axis = str(rule.params.get("axis") or "row")
        index = self._seat_index(assignment)
        terms: List[HardTerm] = []
        seen: Set[Key] = set()
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            rank = rank_of.get(sid)
            if rank is None:
                continue
            for other_rank in (rank - 1, rank + 1):
                if not (0 <= other_rank < len(sequence)):
                    continue
                other = sequence[other_rank]
                if other == sid:
                    continue
                mate = index.get(other)
                if mate is None:
                    continue
                mine = self._order_position(seat, axis)
                theirs = self._order_position(mate, axis)
                if rank < other_rank:
                    if mine <= theirs:
                        continue
                    first, second = sid, other
                else:
                    if mine >= theirs:
                        continue
                    first, second = other, sid
                key = _key_of([seat, mate])
                if key in seen:
                    continue
                seen.add(key)
                terms.append(HardTerm(
                    rule_id=rule.id, kind=rule.kind, rule_label=self.label_of(rule),
                    key=key, seats=[seat], students=[sid, other],
                    message="「%s」应排在「%s」前面（%s / %s）" % (
                        self._name(first), self._name(second),
                        self._seat_text(index.get(first)), self._seat_text(index.get(second))),
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

    # 软约束
    def soft_terms(
        self,
        assignment: Mapping[str, str],
        focus: Optional[Iterable[Coord]] = None,
        scope: Optional[Set[Coord]] = None,
    ) -> List[SoftTerm]:
        self._seat_index_cache = None
        if scope is not None:
            narrow = wide = group = scope
        else:
            narrow, wide, group = self._scope_sets(focus)
        if not wide:
            return []
        terms: List[SoftTerm] = []
        for rule in self.soft_rules:
            rule_scope = (narrow, wide, group)[self._stage_of(rule)]
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
        if kind == RuleKind.TAG_CLUSTER:
            return self._soft_tag_cluster(rule, assignment, scope)
        if kind == RuleKind.BACK_PREFER:
            return self._soft_back_prefer(rule, assignment, scope)
        if kind == RuleKind.AISLE_PREFER:
            return self._soft_aisle_prefer(rule, assignment, scope)
        if kind == RuleKind.AVOID_PREV_NEIGHBOR:
            return self._soft_avoid_prev_neighbor(rule, assignment, scope)
        if kind == RuleKind.NEAR_PREFER:
            return self._soft_near_prefer(rule, assignment, scope)
        if kind == RuleKind.GROUP_BALANCE:
            return self._soft_group_balance(rule, assignment, scope)
        if kind == RuleKind.GENDER_BALANCE:
            return self._soft_gender_balance(rule, assignment, scope)
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
            if not (0 <= seat[0] < self.layout.group_count):
                continue
            partner_seats: List[Coord] = self._desk_mates(seat)
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
            if not (0 <= seat[0] < self.layout.group_count):
                continue
            partner_seats: List[Coord] = self._desk_mates(seat)
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

    def _soft_tag_cluster(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        """每个带该标签的学生一个 term：同标签邻居越多越好（``_soft_tag_disperse`` 的对偶）。

        身边一个已入座的人都没有时给 0.0：聚集的语义下"孤零零一个人"并没有达成聚集，
        不能照抄分散规则的 1.0（那是"没有邻居就没有违反"）。
        """
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
                value = 0.0
            else:
                same = 0
                for n in occupied:
                    other = self.students.get(assignment.get(self.key_of(n), ""))
                    if other is not None and tag in other.tags:
                        same += 1
                value = same / float(len(occupied))
            terms.append(self._term(rule, _key_of([seat] + neighbor_seats), value))
        return terms

    def _soft_back_prefer(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        """目标学生越靠后越好（``_soft_front_prefer`` 的镜像）。"""
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
            value = 1.0 if rows <= 1 else max(0.0, index / float(rows - 1))
            terms.append(self._term(rule, _key_of([seat]), value))
        return terms

    def _soft_aisle_prefer(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        """目标学生优先靠近过道，或尽量居中。"""
        sids = self.target_set(rule)
        if not sids:
            return []
        mode = str(rule.params.get("mode") or "both")
        terms: List[SoftTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in sids:
                continue
            terms.append(self._term(rule, _key_of([seat]), self._aisle_value(seat, mode)))
        return terms

    def _aisle_value(self, seat: Coord, mode: str) -> float:
        """座位对"靠过道 / 居中"的满足度。

        "过道"是组与组 **之间** 的通道（渲染与导出都按 ``group.gap_after`` 留出来），
        所以最左组没有左侧过道、最右组没有右侧过道。目标位置不存在时给 1.0：
        为一件事先就无解的事扣分，只会平白拉低满意度。
        """
        group_index = int(seat[0])
        if not (0 <= group_index < self.layout.group_count):
            return 1.0
        cols = self.layout.groups[group_index].cols
        col = int(seat[2])
        last = cols - 1
        if last <= 0:
            return 1.0
        if mode == "center":
            middle = last / 2.0
            return max(0.0, 1.0 - abs(col - middle) / middle)
        has_left = group_index > 0
        has_right = group_index < self.layout.group_count - 1
        if mode == "left":
            aisles = [0] if has_left else []
        elif mode == "right":
            aisles = [last] if has_right else []
        else:
            aisles = ([0] if has_left else []) + ([last] if has_right else [])
        if not aisles:
            return 1.0
        distance = min(abs(col - c) for c in aisles)
        return max(0.0, 1.0 - distance / float(last))

    def _soft_avoid_prev_neighbor(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        """每个有上次同桌记录的学生一个 term：与上次同桌的同学重逢得越少越好。

        没有已占用同桌时给 1.0（没有同桌就无从"避免"），但**仍然发 term** ——
        term 条数必须只由"谁已入座"决定，否则 ``max_raw`` 会随排列变化。
        """
        if not self._prev_desk_mates:
            return []
        terms: List[SoftTerm] = []
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid or sid not in self._prev_desk_mates:
                continue
            mates = self._prev_desk_mates[sid]
            desk_seats = self._desk_mates(seat)
            occupied = [n for n in desk_seats if assignment.get(self.key_of(n), "")]
            if not occupied:
                value = 1.0
            else:
                hits = 0
                for n in occupied:
                    if assignment.get(self.key_of(n), "") in mates:
                        hits += 1
                value = 1.0 - hits / float(len(occupied))
            terms.append(self._term(rule, _key_of([seat] + desk_seats), value))
        return terms

    def _soft_near_prefer(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        """对象 A 与对象 B 的学生两两成对，离得越近越好。

        刻意写成「每一对一条 term」而不是「每人到最近者的距离」：后者依赖的距离
        没有上界——B 组的人可以从五个组之外搬过来，任何有限的扫描范围都盖不住，
        增量评估就会与全量悄悄分叉。

        **两端锚定**：同组 / 靠近都不是局部关系，只从 A 侧生成的话，"B 侧的人被
        换走了"在增量里根本看不见。远的对给 0 分而不是不发 term——term 条数必须
        只由"谁已入座"决定，否则 ``max_raw`` 会随排列变化。
        """
        sids_a, sids_b = self.pair_sets(rule)
        if not sids_a or not sids_b:
            return []
        span = float(self._max_distance())
        index = self._seat_index(assignment)
        terms: List[SoftTerm] = []
        seen: Set[Key] = set()
        for seat in scope:
            sid = assignment.get(self.key_of(seat), "")
            if not sid:
                continue
            in_a = sid in sids_a
            in_b = sid in sids_b
            if not in_a and not in_b:
                continue
            others: Set[str] = set()
            if in_a:
                others |= sids_b
            if in_b:
                others |= sids_a
            others.discard(sid)
            for other in sorted(others):
                mate = index.get(other)
                if mate is None:
                    continue
                key = _key_of([seat, mate])
                if key in seen:
                    continue
                seen.add(key)
                distance = abs(seat[0] - mate[0]) + abs(seat[1] - mate[1]) + abs(seat[2] - mate[2])
                terms.append(self._term(rule, key, 1.0 - distance / span))
        return terms

    def _soft_group_balance(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        """每组一个 term：该组人数越接近平均人数越好。

        每组**无条件**发一条，条数只由布局决定，``max_raw`` 于是与排列彻底无关。
        注意 ``soft_terms`` 不像 ``hard_terms`` 那样按 key 去重，整组 key 的规则
        必须自己按组去重：否则一组十几个座位会发出十几条同 key 的 term，
        把"每组一个"静默变成"每座位一个"，权重也就跟着按组大小加权了。
        """
        groups = self._active_group_indexes()
        if not groups:
            return []
        counts = {index: self._group_seated_count(index, assignment) for index in groups}
        ideal = sum(counts.values()) / float(len(groups))
        span = max(1.0, ideal)
        terms: List[SoftTerm] = []
        seen: Set[int] = set()
        for seat in scope:
            group_index = int(seat[0])
            if group_index in seen or group_index not in counts:
                continue
            seen.add(group_index)
            value = max(0.0, 1.0 - abs(counts[group_index] - ideal) / span)
            terms.append(self._term(
                rule, _key_of(self.layout.seats_in_group(group_index)), value))
        return terms

    def _soft_gender_balance(self, rule: Rule, assignment: Mapping[str, str], scope: Set[Coord]) -> List[SoftTerm]:
        """每组一个 term：组内男生数与「组内人数 × 全班男生比例」的偏差越小越好。

        目标比例是引擎初始化时按全体学生算好的常量（``self._male_ratio``），
        不依赖当前排位——否则它会随交换而变，没被扫到的组却不会重算，
        增量差就不再等于全量差。
        """
        groups = self._active_group_indexes()
        if not groups:
            return []
        counts = {index: self._group_gender_counts(index, assignment) for index in groups}
        terms: List[SoftTerm] = []
        seen: Set[int] = set()
        for seat in scope:
            group_index = int(seat[0])
            if group_index in seen or group_index not in counts:
                continue
            seen.add(group_index)
            known, males = counts[group_index]
            if known <= 0:
                value = 1.0
            else:
                expected = known * self._male_ratio
                value = max(0.0, 1.0 - abs(males - expected) / (known / 2.0))
            terms.append(self._term(
                rule, _key_of(self.layout.seats_in_group(group_index)), value))
        return terms

    # 评估
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

        # 「对象对」类规则：某一端匹配不到学生时规则会静默失效，直接报出来
        for rule in self.rules:
            if rule.kind not in PAIR_KINDS:
                continue
            sids_a, sids_b = self.pair_sets(rule)
            if not sids_a:
                problems.append("规则「%s」的对象 A（%s）没有匹配到任何学生"
                                % (rule.label, self._side_text(rule, "a")))
            if not sids_b:
                problems.append("规则「%s」的对象 B（%s）没有匹配到任何学生"
                                % (rule.label, self._side_text(rule, "b")))

        must_pairs = []
        forbid_pairs = []
        for rule in self.hard_rules:
            if rule.kind == RuleKind.MUST_DESK:
                must_pairs.append(self.pair_sets(rule))
            elif rule.kind == RuleKind.FORBID_DESK:
                forbid_pairs.append(self.pair_sets(rule))
        for sids_a, sids_b in must_pairs:
            if not sids_a or not sids_b:
                continue
            if any(sids_a == other_a and sids_b == other_b for other_a, other_b in forbid_pairs):
                problems.append("同一组对象既被要求「必须同桌」又被要求「禁止同桌」，无法同时满足")

        # 「同类两两同桌」在每组只有 2 列时会退化成行内完美匹配，奇数人数必然配对失败
        paired_desks = all(group.cols == 2 for group in self.layout.groups) if self.layout.groups else False
        for rule in self.hard_rules:
            if rule.kind != RuleKind.MUST_DESK or not paired_desks:
                continue
            tag_a = str(rule.params.get("tag_a") or "").strip()
            tag_b = str(rule.params.get("tag_b") or "").strip()
            if not tag_a or tag_a != tag_b:
                continue
            sids_a = self.pair_sets(rule)[0]
            if len(sids_a) % 2 == 1:
                problems.append(
                    "规则「%s」要求「%s」标签学生两两同桌，但人数是 %d（奇数）、每组又只有 2 列，"
                    "必然有一位同学配不上对" % (rule.label, tag_a, len(sids_a))
                )

        # 「每组人数上限」把总容量卡到装不下全班
        for rule in self.hard_rules:
            if rule.kind != RuleKind.GROUP_SIZE_LIMIT:
                continue
            limit = self._int_param(rule, "limit", 8, 1)
            capacity = 0
            for index in self._active_group_indexes():
                free = sum(1 for seat in self.layout.seats_in_group(index)
                           if not self.layout.is_disabled(seat))
                capacity += min(limit, free)
            if capacity < len(self.students):
                problems.append("规则「%s」把总容量限制到 %d 人，但班里有 %d 名学生"
                                % (rule.label, capacity, len(self.students)))

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
