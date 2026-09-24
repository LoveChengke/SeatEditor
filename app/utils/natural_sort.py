"""学号自然排序：``1-2-10`` 而不是 ``1-10-2``。"""

from __future__ import annotations

import re
from typing import Any, Tuple

_NUM_RE = re.compile(r"(\d+)")


def natural_key(text: Any) -> Tuple:
    """把字符串切成 文本/数字 交替的元组，使数字段按数值比较。

    ``re.split`` 带捕获组的结果固定为 ``[str, int, str, int, ..., str]``，
    因此相同下标处的元素类型始终一致，可以安全比较。
    """
    s = "" if text is None else str(text)
    parts = _NUM_RE.split(s.strip())
    return tuple(int(p) if i % 2 else p.lower() for i, p in enumerate(parts))
