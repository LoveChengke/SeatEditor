"""座位操作：分配 / 交换 / 移动 / 清空 / 空置（原子操作）。

所有函数都是纯函数风格：接收 assignment 字典，返回新的字典，
便于与 :class:`HistoryService` 的快照式撤销配合。
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Set

from ..models.assignment import Assignment, seat_key_of, student_at
from ..utils.seat_key import make_key, try_parse_key
from ..utils.seat_key import Seat as Coord


def _key(seat) -> Optional[str]:
    """接受 ``"g-r-c"`` 或坐标。"""
    if isinstance(seat, str):
        coord = try_parse_key(seat)
        return make_key(coord) if coord is not None else None
    coord = try_parse_key(seat)
    return make_key(coord) if coord is not None else None


class SeatService:
    """座位分配服务。"""

    def __init__(self, assignment: Optional[Mapping[str, str]] = None) -> None:
        self.assignment: Assignment = dict(assignment or {})

    # ------------------------------------------------------------ 查询
    def student_at(self, seat) -> str:
        key = _key(seat)
        return self.assignment.get(key, "") if key else ""

    def seat_of(self, sid: str) -> Optional[str]:
        return seat_key_of(self.assignment, sid)

    def is_empty(self, seat) -> bool:
        return not self.student_at(seat)

    # ------------------------------------------------------------ 写操作
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

    def move(self, seat_from, seat_to) -> bool:
        return self.swap(seat_from, seat_to)

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

    def unassign_student(self, sid: str) -> Optional[str]:
        """把学生移出座位（回到未分配池）。"""
        key = seat_key_of(self.assignment, sid)
        if key is None:
            return None
        self.assignment.pop(key, None)
        return key

    # ------------------------------------------------------------ 批量
    def assign_many(self, pairs: Sequence) -> int:
        """批量分配 ``[(seat, sid), ...]``，返回成功条数。"""
        count = 0
        for seat, sid in pairs:
            key = _key(seat)
            if key is None or not sid:
                continue
            self.assign(seat, sid)
            if self.assignment.get(key) == sid:
                count += 1
        return count

    def place_students(self, seats: Sequence, sids: Sequence[str]) -> int:
        """把一批学生顺序放进一批座位，返回入座人数。"""
        count = 0
        for seat, sid in zip(seats, sids):
            if not sid:
                continue
            self.assign(seat, sid, push_out=False)
            count += 1
        return count

    def occupied_seats(self) -> Set[Coord]:
        result: Set[Coord] = set()
        for key, sid in self.assignment.items():
            if not sid:
                continue
            coord = try_parse_key(key)
            if coord is not None:
                result.add(coord)
        return result

    def unassigned(self, all_sids: Sequence[str]) -> List[str]:
        seated = set(self.assignment.values())
        return [sid for sid in all_sids if sid not in seated]

    # ------------------------------------------------------------ 空置座位
    @staticmethod
    def set_disabled(layout, seat, disabled: bool = True) -> Optional[str]:
        """设置空置座位；若该座位有人，返回需要移出的 sid。"""
        coord = try_parse_key(seat)
        if coord is None:
            return None
        layout.set_disabled(coord, disabled)
        return None

    @staticmethod
    def apply_disabled(assignment: Assignment, layout, seat) -> Assignment:
        """置为空置并把人移出。"""
        result = dict(assignment)
        coord = try_parse_key(seat)
        if coord is None:
            return result
        layout.set_disabled(coord, True)
        result.pop(make_key(coord), None)
        return result


def swap_students(assignment: Mapping[str, str], seat_a, seat_b) -> Assignment:
    """便捷函数：返回交换后的新字典。"""
    service = SeatService(assignment)
    service.swap(seat_a, seat_b)
    return service.assignment


def assign_student(assignment: Mapping[str, str], seat, sid: str) -> Assignment:
    service = SeatService(assignment)
    service.assign(seat, sid)
    return service.assignment


def clear_seat(assignment: Mapping[str, str], seat) -> Assignment:
    service = SeatService(assignment)
    service.clear(seat)
    return service.assignment
