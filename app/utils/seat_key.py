"""座位坐标 <-> 字符串互转，以及座位邻域工具。

座位坐标统一为三元组 ``(group_idx, row, col)``；字符串形式为 ``"g-r-c"``，
用于 JSON 序列化与 assignment 字典的键。
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

Seat = Tuple[int, int, int]


def make_key(seat: Sequence[int]) -> str:
    """``(0, 1, 2) -> "0-1-2"``"""
    g, r, c = seat
    return "%d-%d-%d" % (int(g), int(r), int(c))


def parse_key(key: str) -> Seat:
    """``"0-1-2" -> (0, 1, 2)``；非法输入抛出 ``ValueError``。"""
    if isinstance(key, (tuple, list)):
        # 容错：允许直接传坐标
        g, r, c = key
        return (int(g), int(r), int(c))
    parts = str(key).strip().split("-")
    if len(parts) != 3:
        raise ValueError("非法的座位键：%r" % (key,))
    try:
        g, r, c = (int(p) for p in parts)
    except ValueError:
        raise ValueError("非法的座位键：%r" % (key,))
    return (g, r, c)


def try_parse_key(key) -> Seat | None:
    try:
        return parse_key(key)
    except (ValueError, TypeError):
        return None


def seat_sort_key(seat: Sequence[int]) -> Tuple[int, int, int]:
    """稳定的座位排序键（用于报告、导出的确定性输出）。"""
    g, r, c = seat
    return (int(g), int(r), int(c))


def neighbors(seat: Seat, rows: int, cols: int) -> List[Seat]:
    """同组内四邻域（上/下/左/右），不含对角。"""
    g, r, c = seat
    result: List[Seat] = []
    if r > 0:
        result.append((g, r - 1, c))
    if r < rows - 1:
        result.append((g, r + 1, c))
    if c > 0:
        result.append((g, r, c - 1))
    if c < cols - 1:
        result.append((g, r, c + 1))
    return result


def dict_to_assignment(raw: Dict[str, str] | None) -> Dict[str, str]:
    """清洗从 JSON 读入的 assignment。"""
    out: Dict[str, str] = {}
    if not raw:
        return out
    for k, v in raw.items():
        seat = try_parse_key(k)
        if seat is None or not v:
            continue
        out[make_key(seat)] = str(v)
    return out
