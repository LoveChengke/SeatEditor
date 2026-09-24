"""拖拽用的 MIME 类型与载荷编解码。

* 座位 → 座位：``application/x-seat``
* 名单 → 座位：``application/x-student``
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QByteArray, QMimeData

from ..utils.seat_key import make_key, try_parse_key

MIME_SEAT = "application/x-seat"
MIME_STUDENT = "application/x-student"


# 座位
def seat_payload(seat, sid: str = "", source: str = "seat") -> Dict[str, Any]:
    return {"seat": make_key(seat), "sid": sid or "", "source": source}


def seat_mime(seat, sid: str = "", source: str = "seat") -> QMimeData:
    mime = QMimeData()
    mime.setData(MIME_SEAT, QByteArray(json.dumps(seat_payload(seat, sid, source)).encode("utf-8")))
    label = sid or make_key(seat)
    mime.setText(str(label))
    return mime


def decode_seat(mime: Optional[QMimeData]) -> Dict[str, Any]:
    if mime is None or not mime.hasFormat(MIME_SEAT):
        return {}
    try:
        raw = bytes(mime.data(MIME_SEAT)).decode("utf-8")
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    coord = try_parse_key(data.get("seat"))
    if coord is None:
        return {}
    return {"seat": coord, "sid": str(data.get("sid") or ""), "source": str(data.get("source") or "seat")}


# 学生
def student_mime(sids: List[str]) -> QMimeData:
    mime = QMimeData()
    payload = {"sids": [str(s) for s in sids if s]}
    mime.setData(MIME_STUDENT, QByteArray(json.dumps(payload).encode("utf-8")))
    mime.setText("、".join(payload["sids"][:3]))
    return mime


def decode_students(mime: Optional[QMimeData]) -> List[str]:
    if mime is None or not mime.hasFormat(MIME_STUDENT):
        return []
    try:
        data = json.loads(bytes(mime.data(MIME_STUDENT)).decode("utf-8"))
    except Exception:
        return []
    sids = data.get("sids") if isinstance(data, dict) else None
    if not sids:
        return []
    return [str(s) for s in sids if s]
