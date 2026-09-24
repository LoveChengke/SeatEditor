"""规则定义（硬约束 / 软约束）与参数元数据。

``RULE_SPECS`` 用数据描述每种规则的参数，规则面板据此动态生成表单，
无需在 UI 里为每条规则写一遍界面。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

HARD = "hard"
SOFT = "soft"


class RuleKind:
    """全部规则种类。"""

    # ---- 硬约束
    FIXED_SEAT = "fixed_seat"                 # 固定座位
    FORBID_ADJACENT = "forbid_adjacent"       # 禁止相邻
    REGION_REQUIRED = "region_required"       # 区域限制
    REGION_FORBIDDEN = "region_forbidden"     # 排除区域
    FRONT_REQUIRED = "front_required"         # 前排必需
    # ---- 软约束
    ATTR_ORDER = "attr_order"                 # 属性排序
    ATTR_TIER = "attr_tier"                   # 属性分档
    TAG_DISPERSE = "tag_disperse"             # 同标签分散
    DESK_PAIR = "desk_pair"                   # 同桌搭配
    AVOID_REPEAT = "avoid_repeat"             # 避免重复
    GENDER_ALTERNATE = "gender_alternate"     # 性别交替
    FRONT_PREFER = "front_prefer"             # 靠前偏好


# 参数控件类型
F_STUDENT = "student"
F_TAG = "tag"
F_SELECTION = "selection"
F_ATTR = "attr"
F_INT = "int"
F_BOOL = "bool"
F_CHOICE = "choice"
F_SEAT = "seat"
F_TEXT = "text"


@dataclass
class ParamField:
    """一个规则参数的界面元数据。"""

    key: str
    label: str
    kind: str
    default: Any = None
    choices: Tuple[Tuple[str, str], ...] = ()   # (value, label)
    minimum: int = 0
    maximum: int = 999
    optional: bool = True
    hint: str = ""


@dataclass
class RuleSpec:
    """一种规则的完整描述。"""

    kind: str
    type: str
    label: str
    description: str
    fields: Tuple[ParamField, ...] = ()
    default_weight: float = 1.0
    has_weight: bool = False

    @property
    def is_hard(self) -> bool:
        return self.type == HARD


_OPT = [("", "（不使用）"), ("tag", "按标签"), ("student", "按学生")]

RULE_SPECS: Dict[str, RuleSpec] = {}


def _register(spec: RuleSpec) -> RuleSpec:
    RULE_SPECS[spec.kind] = spec
    return spec


# ------------------------------------------------------------------ 硬约束
_register(RuleSpec(
    kind=RuleKind.FIXED_SEAT, type=HARD,
    label="固定座位",
    description="指定的学生必须坐在指定座位上，不参与交换。",
    fields=(
        ParamField("sid", "学生", F_STUDENT, optional=False),
        ParamField("seat", "座位", F_SEAT, optional=False),
    ),
))

_register(RuleSpec(
    kind=RuleKind.FORBID_ADJACENT, type=HARD,
    label="禁止相邻",
    description="两名学生在四邻域（上下左右）内不得相邻。",
    fields=(
        ParamField("sid_a", "学生 A", F_STUDENT, optional=False),
        ParamField("sid_b", "学生 B", F_STUDENT, optional=False),
    ),
))

_register(RuleSpec(
    kind=RuleKind.REGION_REQUIRED, type=HARD,
    label="区域限制",
    description="指定的学生或标签学生必须落在选区内。",
    fields=(
        ParamField("tag", "标签", F_TAG),
        ParamField("sid", "学生", F_STUDENT),
        ParamField("selection", "选区", F_SELECTION, optional=False),
    ),
))

_register(RuleSpec(
    kind=RuleKind.REGION_FORBIDDEN, type=HARD,
    label="排除区域",
    description="指定的学生或标签学生不得落在选区内。",
    fields=(
        ParamField("tag", "标签", F_TAG),
        ParamField("sid", "学生", F_STUDENT),
        ParamField("selection", "选区", F_SELECTION, optional=False),
    ),
))

_register(RuleSpec(
    kind=RuleKind.FRONT_REQUIRED, type=HARD,
    label="前排必需",
    description="指定学生或标签学生必须坐在讲台侧的前 N 排内。",
    fields=(
        ParamField("tag", "标签", F_TAG),
        ParamField("sid", "学生", F_STUDENT),
        ParamField("rows", "前 N 排", F_INT, default=2, minimum=1, maximum=12, optional=False),
    ),
))

# ------------------------------------------------------------------ 软约束
_register(RuleSpec(
    kind=RuleKind.ATTR_ORDER, type=SOFT,
    label="属性排序",
    description="按数值属性排序入座，如“身高从矮到高、从前到后”。",
    fields=(
        ParamField("attr", "数值属性", F_ATTR, optional=False),
        ParamField("direction", "方向", F_CHOICE, default="asc",
                   choices=(("asc", "从小到大"), ("desc", "从大到小")), optional=False),
        ParamField("axis", "排序方向", F_CHOICE, default="row",
                   choices=(("row", "从前到后（按排）"), ("group", "从左到右（按组）")), optional=False),
    ),
    default_weight=1.0, has_weight=True,
))

_register(RuleSpec(
    kind=RuleKind.ATTR_TIER, type=SOFT,
    label="属性分档",
    description="把属性分成 N 档，各档学生尽量均匀分布到不同分组。",
    fields=(
        ParamField("attr", "数值属性", F_ATTR, optional=False),
        ParamField("tiers", "档数", F_INT, default=4, minimum=2, maximum=8, optional=False),
        ParamField("mode", "分布方式", F_CHOICE, default="group",
                   choices=(("group", "均匀分布到各组"), ("row", "均匀分布到各排")), optional=False),
    ),
    default_weight=1.0, has_weight=True,
))

_register(RuleSpec(
    kind=RuleKind.TAG_DISPERSE, type=SOFT,
    label="同标签分散",
    description="相同标签的学生尽量不要相邻。",
    fields=(ParamField("tag", "标签", F_TAG, optional=False),),
    default_weight=1.0, has_weight=True,
))

_register(RuleSpec(
    kind=RuleKind.DESK_PAIR, type=SOFT,
    label="同桌搭配",
    description="让两类标签的学生成为同桌（同一排左右相邻）。",
    fields=(
        ParamField("tag_a", "标签 A", F_TAG, optional=False),
        ParamField("tag_b", "标签 B", F_TAG, optional=False),
        ParamField("mode", "搭配方式", F_CHOICE, default="same",
                   choices=(("same", "尽量同桌"), ("apart", "尽量不同桌")), optional=False),
    ),
    default_weight=1.0, has_weight=True,
))

_register(RuleSpec(
    kind=RuleKind.AVOID_REPEAT, type=SOFT,
    label="避免重复",
    description="尽量不让学生坐在与上次方案相同的位置。",
    fields=(),
    default_weight=1.0, has_weight=True,
))

_register(RuleSpec(
    kind=RuleKind.GENDER_ALTERNATE, type=SOFT,
    label="性别交替",
    description="男女尽量交替排列（左右相邻不同性别）。",
    fields=(),
    default_weight=0.8, has_weight=True,
))

_register(RuleSpec(
    kind=RuleKind.FRONT_PREFER, type=SOFT,
    label="靠前偏好",
    description="指定的学生或标签学生优先安排到前排。",
    fields=(
        ParamField("tag", "标签", F_TAG),
        ParamField("sid", "学生", F_STUDENT),
    ),
    default_weight=0.8, has_weight=True,
))

# 按面板展示顺序排列
HARD_KINDS: Tuple[str, ...] = (
    RuleKind.FIXED_SEAT, RuleKind.FORBID_ADJACENT, RuleKind.REGION_REQUIRED,
    RuleKind.REGION_FORBIDDEN, RuleKind.FRONT_REQUIRED,
)
SOFT_KINDS: Tuple[str, ...] = (
    RuleKind.ATTR_ORDER, RuleKind.ATTR_TIER, RuleKind.TAG_DISPERSE,
    RuleKind.DESK_PAIR, RuleKind.AVOID_REPEAT, RuleKind.GENDER_ALTERNATE,
    RuleKind.FRONT_PREFER,
)


def make_rule_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Rule:
    """一条规则实例。"""

    id: str
    type: str
    kind: str
    params: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    weight: float = 1.0
    name: str = ""

    def __post_init__(self) -> None:
        self.id = str(self.id or make_rule_id())
        self.kind = str(self.kind)
        spec = RULE_SPECS.get(self.kind)
        if spec is not None:
            self.type = spec.type
            if not self.name:
                self.name = spec.label
            if self.weight in (None, 0):
                self.weight = spec.default_weight
        self.params = dict(self.params or {})
        if spec is not None:
            for fld in spec.fields:
                if fld.key not in self.params:
                    self.params[fld.key] = fld.default
                elif fld.kind == F_INT and self.params[fld.key] is not None:
                    try:
                        self.params[fld.key] = int(self.params[fld.key])
                    except (TypeError, ValueError):
                        self.params[fld.key] = fld.default
        try:
            self.weight = float(self.weight)
        except (TypeError, ValueError):
            self.weight = 1.0

    # ------------------------------------------------------------ 便捷属性
    @property
    def is_hard(self) -> bool:
        return self.type == HARD

    @property
    def is_soft(self) -> bool:
        return self.type == SOFT

    @property
    def spec(self) -> Optional[RuleSpec]:
        return RULE_SPECS.get(self.kind)

    @property
    def label(self) -> str:
        spec = self.spec
        return self.name or (spec.label if spec else self.kind)

    def target_sid(self) -> str:
        return str(self.params.get("sid") or "").strip()

    def target_tag(self) -> str:
        return str(self.params.get("tag") or "").strip()

    def selection_id(self) -> str:
        return str(self.params.get("selection") or "").strip()

    # ------------------------------------------------------------ 校验
    def validate(self) -> List[str]:
        """返回错误信息列表，空列表表示合法。"""
        errors: List[str] = []
        spec = self.spec
        if spec is None:
            return ["未知的规则类型：%s" % self.kind]
        for fld in spec.fields:
            value = self.params.get(fld.key)
            blank = value is None or (isinstance(value, str) and not value.strip())
            if fld.kind == F_INT and not blank:
                try:
                    int(value)
                except (TypeError, ValueError):
                    errors.append("%s 必须是整数" % fld.label)
            if not fld.optional and blank:
                errors.append("请填写「%s」" % fld.label)
        kind = self.kind
        if kind in (RuleKind.REGION_REQUIRED, RuleKind.REGION_FORBIDDEN, RuleKind.FRONT_PREFER):
            if not self.target_tag() and not self.target_sid():
                errors.append("需要指定一个标签或一名学生")
        if kind == RuleKind.FORBID_ADJACENT:
            a, b = self.target_sid_a(), self.target_sid_b()
            if a and b and a == b:
                errors.append("学生 A 与学生 B 不能是同一个人")
        if kind == RuleKind.DESK_PAIR:
            a = str(self.params.get("tag_a") or "").strip()
            b = str(self.params.get("tag_b") or "").strip()
            if a and b and a == b and self.params.get("mode") == "same":
                errors.append("同桌搭配的两个标签不能相同")
        return errors

    def target_sid_a(self) -> str:
        return str(self.params.get("sid_a") or "").strip()

    def target_sid_b(self) -> str:
        return str(self.params.get("sid_b") or "").strip()

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "kind": self.kind,
            "params": dict(self.params),
            "enabled": bool(self.enabled),
        }
        if self.is_soft:
            data["weight"] = float(self.weight)
        if self.name and self.name != (self.spec.label if self.spec else ""):
            data["name"] = self.name
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Rule":
        kind = str(data.get("kind") or "")
        spec = RULE_SPECS.get(kind)
        return cls(
            id=str(data.get("id") or make_rule_id()),
            type=str(data.get("type") or (spec.type if spec else HARD)),
            kind=kind,
            params=dict(data.get("params") or {}),
            enabled=bool(data.get("enabled", True)),
            weight=float(data.get("weight", spec.default_weight if spec else 1.0) or 1.0),
            name=str(data.get("name") or ""),
        )

def make_rule(kind: str) -> Optional[Rule]:
    """按规则种类创建一条带默认参数的规则。"""
    spec = RULE_SPECS.get(kind)
    if spec is None:
        return None
    params: Dict[str, Any] = {}
    for fld in spec.fields:
        params[fld.key] = fld.default
    return Rule(make_rule_id(), spec.type, kind, params, True, spec.default_weight)


# ------------------------------------------------------------------ 描述
def describe_rule(
    rule: Rule,
    student_name: Optional[Callable[[str], str]] = None,
    selection_name: Optional[Callable[[str], str]] = None,
    tag_set: Optional[Sequence[str]] = None,
) -> str:
    """生成规则的人话描述，用于规则列表与导出说明。"""
    sname = student_name or (lambda sid: sid or "（未指定）")
    selname = selection_name or (lambda sid: sid or "（未指定选区）")
    sel = selname(rule.selection_id()) if rule.selection_id() else "（未指定选区）"
    p = rule.params
    kind = rule.kind

    def who() -> str:
        sid = rule.target_sid()
        if sid:
            return sname(sid)
        tag = rule.target_tag()
        if tag:
            return "「%s」标签学生" % tag
        return "（未指定对象）"

    if kind == RuleKind.FIXED_SEAT:
        return "%s 固定在 %s" % (sname(rule.target_sid()), _seat_text(p.get("seat")))
    if kind == RuleKind.FORBID_ADJACENT:
        return "%s 与 %s 不得相邻" % (sname(rule.target_sid_a()), sname(rule.target_sid_b()))
    if kind == RuleKind.REGION_REQUIRED:
        return "%s 必须在 %s 内" % (who(), sel)
    if kind == RuleKind.REGION_FORBIDDEN:
        return "%s 不得进入 %s" % (who(), sel)
    if kind == RuleKind.FRONT_REQUIRED:
        return "%s 必须坐在前 %s 排" % (who(), p.get("rows", 2))
    if kind == RuleKind.ATTR_ORDER:
        direction = "从小到大" if p.get("direction") == "asc" else "从大到小"
        axis = "从前到后" if p.get("axis", "row") == "row" else "从左到右"
        return "%s %s 排列（%s）" % (p.get("attr") or "属性", direction, axis)
    if kind == RuleKind.ATTR_TIER:
        where = "各组" if p.get("mode", "group") == "group" else "各排"
        return "%s 分 %s 档，均匀分布到%s" % (p.get("attr") or "属性", p.get("tiers", 4), where)
    if kind == RuleKind.TAG_DISPERSE:
        return "「%s」标签学生尽量不相邻" % (rule.target_tag() or "（未选）")
    if kind == RuleKind.DESK_PAIR:
        mode = "尽量同桌" if p.get("mode", "same") == "same" else "尽量不同桌"
        return "「%s」与「%s」%s" % (p.get("tag_a") or "?", p.get("tag_b") or "?", mode)
    if kind == RuleKind.AVOID_REPEAT:
        return "尽量不与上次方案重复"
    if kind == RuleKind.GENDER_ALTERNATE:
        return "男女尽量交替排列"
    if kind == RuleKind.FRONT_PREFER:
        return "%s 优先前排" % who()
    return rule.label


def _seat_text(seat: Any) -> str:
    if not seat:
        return "（未指定座位）"
    try:
        g, r, c = str(seat).split("-")
        return "第 %d 组 第 %d 排 第 %d 列" % (int(g) + 1, int(r) + 1, int(c) + 1)
    except Exception:  # noqa: BLE001
        return str(seat)


# ------------------------------------------------------------------ 冲突
@dataclass
class Violation:
    """一条硬约束违反记录。"""

    rule_id: str = ""
    kind: str = ""
    message: str = ""
    seats: List[str] = field(default_factory=list)
    students: List[str] = field(default_factory=list)
    rule_label: str = ""
    severity: str = HARD

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "kind": self.kind,
            "message": self.message,
            "seats": list(self.seats),
            "students": list(self.students),
            "rule_label": self.rule_label,
            "severity": self.severity,
        }

    def __str__(self) -> str:  # pragma: no cover - 调试用
        return self.message or self.rule_label


@dataclass
class RuleScore:
    """单条软约束的得分明细。"""

    rule_id: str
    label: str
    weight: float = 1.0
    raw: float = 0.0
    satisfaction: float = 0.0     # 0~1
