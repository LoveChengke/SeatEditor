"""教室布局模型：SeatGroup / Layout。

坐标三元组统一用 ``Coord`` 表示，即 ``(group_idx, row, col)``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..utils.seat_key import make_key, neighbors, try_parse_key
from ..utils.seat_key import Seat as Coord

PODIUM_SIDES = ("top", "bottom")
CARD_SIZES = ("small", "medium", "large")

MIN_GROUPS = 1
MAX_GROUPS = 6
MIN_ROWS, MAX_ROWS = 1, 12
MIN_COLS, MAX_COLS = 1, 8
MIN_GAP, MAX_GAP = 0, 3


@dataclass
class SeatGroup:
    """一个分组（如“第 1 组”）。"""

    id: int
    name: str
    rows: int
    cols: int
    gap_after: int = 1

    def __post_init__(self) -> None:
        self.id = int(self.id)
        self.name = str(self.name or ("第 %d 组" % (self.id + 1)))
        self.rows = max(MIN_ROWS, min(MAX_ROWS, int(self.rows)))
        self.cols = max(MIN_COLS, min(MAX_COLS, int(self.cols)))
        self.gap_after = max(MIN_GAP, min(MAX_GAP, int(self.gap_after)))

    @property
    def size(self) -> int:
        return self.rows * self.cols

    def seats(self, group_index: Optional[int] = None) -> List[Coord]:
        gi = self.id if group_index is None else int(group_index)
        return [(gi, r, c) for r in range(self.rows) for c in range(self.cols)]

    def contains(self, row: int, col: int) -> bool:
        return 0 <= row < self.rows and 0 <= col < self.cols

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "rows": self.rows,
            "cols": self.cols,
            "gap_after": self.gap_after,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], fallback_id: int = 0) -> "SeatGroup":
        return cls(
            id=int(data.get("id", fallback_id)),
            name=str(data.get("name", "") or ""),
            rows=int(data.get("rows", 6)),
            cols=int(data.get("cols", 2)),
            gap_after=int(data.get("gap_after", 1)),
        )

    def clone(self) -> "SeatGroup":
        return SeatGroup(self.id, self.name, self.rows, self.cols, self.gap_after)


@dataclass
class Layout:
    """整间教室的座位布局。"""

    groups: List[SeatGroup] = field(default_factory=list)
    podium_side: str = "top"          # top | bottom
    card_size: str = "medium"         # small | medium | large
    show_group_title: bool = True
    disabled_seats: Set[Coord] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.groups = list(self.groups or [])
        if self.podium_side not in PODIUM_SIDES:
            self.podium_side = "top"
        if self.card_size not in CARD_SIZES:
            self.card_size = "medium"
        cleaned: Set[Coord] = set()
        for item in self.disabled_seats or set():
            coord = _as_coord(item)
            if coord is not None:
                cleaned.add(coord)
        self.disabled_seats = cleaned
        self._reindex()

    # 基础
    def _reindex(self) -> None:
        """保证分组 id 与列表下标一致。"""
        for gi, group in enumerate(self.groups):
            group.id = gi

    @property
    def group_count(self) -> int:
        return len(self.groups)

    def group_name(self, index: int) -> str:
        if 0 <= index < len(self.groups):
            return self.groups[index].name
        return "第 %d 组" % (index + 1)

    def all_seats(self) -> List[Coord]:
        seats: List[Coord] = []
        for gi, group in enumerate(self.groups):
            seats.extend(group.seats(gi))
        return seats

    def available_seats(self) -> List[Coord]:
        return [s for s in self.all_seats() if s not in self.disabled_seats]

    def seat_count(self) -> int:
        return sum(g.size for g in self.groups)

    def available_count(self) -> int:
        return len(self.available_seats())

    def contains(self, seat: Sequence[int]) -> bool:
        coord = _as_coord(seat)
        if coord is None:
            return False
        g, r, c = coord
        if not (0 <= g < len(self.groups)):
            return False
        return self.groups[g].contains(r, c)

    def is_disabled(self, seat: Sequence[int]) -> bool:
        coord = _as_coord(seat)
        return coord is not None and coord in self.disabled_seats

    def set_disabled(self, seat: Sequence[int], disabled: bool = True) -> None:
        coord = _as_coord(seat)
        if coord is None:
            return
        if disabled:
            self.disabled_seats.add(coord)
        else:
            self.disabled_seats.discard(coord)

    def prune_disabled(self) -> None:
        """删除越界或被缩短的分组留下的空置标记。"""
        self.disabled_seats = {s for s in self.disabled_seats if self.contains(s)}

    def neighbors(self, seat: Sequence[int]) -> List[Coord]:
        coord = _as_coord(seat)
        if coord is None:
            return []
        g, r, c = coord
        if not (0 <= g < len(self.groups)):
            return []
        group = self.groups[g]
        return neighbors((g, r, c), group.rows, group.cols)

    # 排 / 列
    @property
    def max_rows(self) -> int:
        return max([g.rows for g in self.groups], default=0)

    def front_row_index(self, seat: Sequence[int]) -> int:
        """距讲台排序：0 = 最前排（越大越靠后）。"""
        coord = _as_coord(seat) or (0, 0, 0)
        _, row, _ = coord
        if self.podium_side == "top":
            return int(row)
        return self.max_rows - 1 - int(row)

    def seats_in_group(self, index: int) -> List[Coord]:
        if not (0 <= index < len(self.groups)):
            return []
        return self.groups[index].seats(index)

    def row_range(self, start: int, end: int) -> List[Coord]:
        lo, hi = sorted((int(start), int(end)))
        return [s for s in self.all_seats() if lo <= s[1] <= hi]

    def col_range(self, start: int, end: int) -> List[Coord]:
        lo, hi = sorted((int(start), int(end)))
        return [s for s in self.all_seats() if lo <= s[2] <= hi]

    def index_of(self, seat: Sequence[int]) -> int:
        """座位在 ``all_seats()`` 中的线性下标，-1 表示不存在。"""
        coord = _as_coord(seat)
        if coord is None or not self.contains(coord):
            return -1
        g, r, c = coord
        base = 0
        for i in range(g):
            base += self.groups[i].size
        return base + r * self.groups[g].cols + c

    # 分组编辑
    def add_group(self, name: str = "", rows: int = 6, cols: int = 2, gap_after: int = 1) -> Optional[SeatGroup]:
        if len(self.groups) >= MAX_GROUPS:
            return None
        gi = len(self.groups)
        group = SeatGroup(gi, name or ("第 %d 组" % (gi + 1)), rows, cols, gap_after)
        self.groups.append(group)
        self._reindex()
        return group

    def remove_group(self, index: int) -> bool:
        if not (0 <= index < len(self.groups)) or len(self.groups) <= MIN_GROUPS:
            return False
        self.groups.pop(index)
        self._reindex()
        self.prune_disabled()
        return True

    def move_group(self, index: int, delta: int) -> bool:
        target = index + int(delta)
        if not (0 <= index < len(self.groups)) or not (0 <= target < len(self.groups)):
            return False
        group = self.groups.pop(index)
        self.groups.insert(target, group)
        self._reindex()
        return True

    # 序列化
    def to_dict(self) -> Dict[str, Any]:
        return {
            "groups": [g.to_dict() for g in self.groups],
            "podium_side": self.podium_side,
            "card_size": self.card_size,
            "show_group_title": bool(self.show_group_title),
            "disabled_seats": sorted(make_key(s) for s in self.disabled_seats),
        }

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "Layout":
        if not data:
            return cls.default()
        raw_groups = data.get("groups") or []
        groups = [SeatGroup.from_dict(g, i) for i, g in enumerate(raw_groups)]
        if not groups:
            groups = cls.default().groups
        disabled: Set[Coord] = set()
        for item in data.get("disabled_seats") or []:
            coord = _as_coord(item)
            if coord is not None:
                disabled.add(coord)
        layout = cls(
            groups=groups,
            podium_side=data.get("podium_side", "top"),
            card_size=data.get("card_size", "medium"),
            show_group_title=bool(data.get("show_group_title", True)),
            disabled_seats=disabled,
        )
        layout.prune_disabled()
        return layout

    @classmethod
    def default(cls) -> "Layout":
        """默认布局：3 组 × 6 行 × 2 列。"""
        return cls.from_template(3, 6, 2)

    @classmethod
    def from_template(cls, groups: int, rows: int, cols: int, podium_side: str = "top") -> "Layout":
        seat_groups = [
            SeatGroup(i, "第 %d 组" % (i + 1), rows, cols, 1) for i in range(int(groups))
        ]
        return cls(groups=seat_groups, podium_side=podium_side)

    def clone(self) -> "Layout":
        return Layout(
            groups=[g.clone() for g in self.groups],
            podium_side=self.podium_side,
            card_size=self.card_size,
            show_group_title=self.show_group_title,
            disabled_seats=set(self.disabled_seats),
        )

def _as_coord(value) -> Optional[Coord]:
    """把 ``"g-r-c"`` / ``(g, r, c)`` / ``[g, r, c]`` 统一成坐标元组。"""
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and len(value) == 3:
        try:
            return (int(value[0]), int(value[1]), int(value[2]))
        except (TypeError, ValueError):
            return None
    return try_parse_key(value)


# 常用快速模板：(名称, 组数, 行数, 列数)
BUILTIN_TEMPLATES: List[Tuple[str, int, int, int]] = [
    ("3 组 × 6 行 × 2 列", 3, 6, 2),
    ("4 组 × 5 行 × 2 列", 4, 5, 2),
    ("2 组 × 6 行 × 3 列", 2, 6, 3),
    ("6 组 × 5 行 × 2 列", 6, 5, 2),
    ("3 组 × 5 行 × 2 列", 3, 5, 2),
    ("1 组 × 6 行 × 6 列", 1, 6, 6),
    ("4 组 × 6 行 × 2 列", 4, 6, 2),
    ("2 组 × 8 行 × 3 列", 2, 8, 3),
    # 单排 / 单列：一排横座（考试单排）或一列纵座（靠墙单列）
    ("单排：1 组 × 1 行 × 8 列", 1, 1, 8),
    ("单列：1 组 × 8 行 × 1 列", 1, 8, 1),
    ("三组单列：3 组 × 6 行 × 1 列", 3, 6, 1),
]


def suggest_card_size(groups: int, rows: int, cols: int) -> str:
    """按形状挑一个合适的座位卡片尺寸（只在套用快速模板时使用）。

    一行里的座位越多，卡片越该小一号——8 列的单排若还用中号卡片，
    座位表就得横向滚动才能看全。
    """
    return "small" if int(cols) >= 5 else "medium"


def load_layout_templates() -> List[Tuple[str, int, int, int]]:
    """读取 ``resources/templates/*.json``；目录缺失或文件损坏时回退内置模板。

    模板 JSON 形如::

        {"name": "3 组 × 6 行 × 2 列", "groups": 3, "rows": 6, "cols": 2}

    教师可以直接往这个目录里丢自定义模板文件。
    """
    import json
    from pathlib import Path

    directory = Path(__file__).resolve().parent.parent.parent / "resources" / "templates"
    templates: List[Tuple[str, int, int, int]] = []
    try:
        files = sorted(directory.glob("*.json"))
    except OSError:
        return list(BUILTIN_TEMPLATES)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            groups = int(data.get("groups", 3))
            rows = int(data.get("rows", 6))
            cols = int(data.get("cols", 2))
        except (TypeError, ValueError):
            continue
        name = str(data.get("name") or path.stem)
        if not (MIN_GROUPS <= groups <= MAX_GROUPS and MIN_ROWS <= rows <= MAX_ROWS
                and MIN_COLS <= cols <= MAX_COLS):
            continue
        templates.append((name, groups, rows, cols))
    if not templates:
        return list(BUILTIN_TEMPLATES)
    # 追加内置模板中不在文件里的组合
    seen = {(g, r, c) for _, g, r, c in templates}
    for item in BUILTIN_TEMPLATES:
        if (item[1], item[2], item[3]) not in seen:
            templates.append(item)
    return templates


LAYOUT_TEMPLATES: List[Tuple[str, int, int, int]] = load_layout_templates()


def template_layout(index: int) -> Layout:
    name, groups, rows, cols = LAYOUT_TEMPLATES[index % len(LAYOUT_TEMPLATES)]
    layout = Layout.from_template(groups, rows, cols)
    layout.card_size = suggest_card_size(groups, rows, cols)
    return layout
