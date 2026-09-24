"""姓名拼音排序。

优先使用可选的 ``pypinyin``；未安装时回退到 GB2312 编码序——
GB2312 一级汉字区（0xB0A1~0xD7F9）本身就是按拼音排序的，因此
``char.encode('gbk')`` 的字节序可以近似拼音序，无需任何第三方依赖。
"""

from __future__ import annotations

from typing import List, Tuple

_LAZY = None
try:  # pragma: no cover - 取决于环境是否安装 pypinyin
    from pypinyin import lazy_pinyin as _LAZY  # type: ignore
except Exception:  # noqa: BLE001 - 任何导入失败都回退
    _LAZY = None


def _char_keys(text: str) -> List[Tuple[int, int, int]]:
    keys: List[Tuple[int, int, int]] = []
    for ch in text:
        try:
            raw = ch.encode("gbk")
        except Exception:  # noqa: BLE001 - 非常用字
            keys.append((2, ord(ch), 0))
            continue
        if len(raw) == 2:
            if 0xB0 <= raw[0] <= 0xD7:
                keys.append((1, raw[0], raw[1]))   # 一级汉字：近似拼音序
            else:
                keys.append((2, raw[0], raw[1]))   # 二级汉字 / 符号
        else:
            # ASCII：按小写字符排序，排在汉字之前
            keys.append((0, ord(ch.lower()), 0))
    return keys


def pinyin_key(text: str) -> Tuple:
    """返回可比较的排序键。"""
    s = (text or "").strip()
    if not s:
        return (1, ())
    if _LAZY is not None:
        try:
            return (0, tuple(_LAZY(s)), s)
        except Exception:  # noqa: BLE001
            pass
    return (1, tuple(_char_keys(s)), s)
