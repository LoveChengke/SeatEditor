"""选区模型。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

from ..utils.seat_key import make_key, seat_sort_key, try_parse_key
from ..utils.seat_key import Seat as Coord

DEFAULT_SELECTION_COLOR = "#2F6BFF"


def _clean_seats(seats: Any) -> Set[Coord]:
    result: Set[Coord] = set()
    for item in seats or []:
        coord = try_parse_key(item)
        if coord is not None:
            result.add(coord)
    return result


@dataclass
class Selection:
    """一组座位坐标的集合，可命名并复用（参与规则 / 轮换）。"""

    id: str
    name: str
    seats: Set[Coord] = field(default_factory=set)
    color: str = DEFAULT_SELECTION_COLOR

    def __post_init__(self) -> None:
        self.id = str(self.id or uuid.uuid4().hex[:8])
        self.name = str(self.name or "未命名选区")
        self.seats = _clean_seats(self.seats)
        self.color = str(self.color or DEFAULT_SELECTION_COLOR)

    # ------------------------------------------------------------ 查询
    def __len__(self) -> int:
        return len(self.seats)

    def __contains__(self, seat: object) -> bool:
        coord = try_parse_key(seat) if not isinstance(seat, tuple) else seat
        return coord in self.seats

    def contains(self, seat: Sequence[int]) -> bool:
        coord = try_parse_key(seat) if not isinstance(seat, (tuple, list)) else tuple(int(v) for v in seat)
        return coord in self.seats

    def sorted_seats(self) -> List[Coord]:
        return sorted(self.seats, key=seat_sort_key)

    @property
    def size(self) -> int:
        return len(self.seats)

    # ------------------------------------------------------------ 编辑
    def add(self, seats: Iterable[Sequence[int]]) -> None:
        for seat in seats:
            coord = try_parse_key(seat) if not isinstance(seat, (tuple, list)) else tuple(int(v) for v in seat)
            if coord is not None:
                self.seats.add(coord)  # type: ignore[arg-type]

    def remove(self, seats: Iterable[Sequence[int]]) -> None:
        for seat in seats:
            coord = try_parse_key(seat) if not isinstance(seat, (tuple, list)) else tuple(int(v) for v in seat)
            self.seats.discard(coord)  # type: ignore[arg-type]

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "seats": [make_key(s) for s in self.sorted_seats()],
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Selection":
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:8]),
            name=str(data.get("name") or "未命名选区"),
            seats=_clean_seats(data.get("seats") or []),
            color=str(data.get("color") or DEFAULT_SELECTION_COLOR),
        )


def make_selection_id() -> str:
    return uuid.uuid4().hex[:8]
