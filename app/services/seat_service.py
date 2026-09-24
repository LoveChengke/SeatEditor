"""座位操作：分配 / 交换 / 清空。

``SeatService`` 包着一份 assignment 字典做增删改；调用方改完取回
``service.assignment`` 写回项目，配合 HistoryService 的快照式撤销。
"""

from __future__ import annotations

from typing import List, Mapping, Optional, Sequence

from ..models.assignment import Assignment, seat_key_of
from ..utils.seat_key import make_key, try_parse_key


def _key(seat) -> Optional[str]:
    """接受 ``"g-r-c"`` 或坐标。"""
    coord = try_parse_key(seat)
    return make_key(coord) if coord is not None else None


class SeatService:
    """座位分配服务。"""

    def __init__(self, assignment: Optional[Mapping[str, str]] = None) -> None:
        self.assignment: Assignment = dict(assignment or {})

    def assign(self, seat, sid: str, push_out: bool = True) -> Optional[str]:
        """把学生放到座位。

        学生已在别处时先移出；目标座位有人时（``push_out``）该学生被移到
        原座位（互为交换）。返回被“挤出”的学生 sid（没有则为 None）。
        """
        key = _key(seat)
        if key is None or not sid:
            return None
        previous_key = seat_key_of(self.assignment, sid)
        occupant = self.assignment.get(key, "")
        pushed: Optional[str] = None
        if previous_key == key:
            return None
        if previous_key:
            self.assignment.pop(previous_key, None)
        if occupant and occupant != sid:
            pushed = occupant
            if push_out and previous_key:
                self.assignment[previous_key] = occupant
        self.assignment[key] = sid
        return pushed

    def swap(self, seat_a, seat_b) -> bool:
        """交换两个座位上的学生（任一侧可为空）。"""
        ka, kb = _key(seat_a), _key(seat_b)
        if ka is None or kb is None or ka == kb:
            return False
        va = self.assignment.get(ka, "")
        vb = self.assignment.get(kb, "")
        if not va and not vb:
            return False
        if vb:
            self.assignment[ka] = vb
        else:
            self.assignment.pop(ka, None)
        if va:
            self.assignment[kb] = va
        else:
            self.assignment.pop(kb, None)
        return True

    def clear(self, seat) -> Optional[str]:
        """清空座位，返回被清掉的学生 sid。"""
        key = _key(seat)
        if key is None:
            return None
        return self.assignment.pop(key, None)

    def clear_many(self, seats: Sequence) -> List[str]:
        removed: List[str] = []
        for seat in seats:
            sid = self.clear(seat)
            if sid:
                removed.append(sid)
        return removed
