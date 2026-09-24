"""学生数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping


def _clean_tags(tags: Any) -> List[str]:
    """标签去重且保持顺序。"""
    result: List[str] = []
    seen = set()
    if not tags:
        return result
    if isinstance(tags, str):
        raw = [p for p in tags.replace("，", ",").replace("；", ";").replace(";", ",").split(",")]
    else:
        raw = list(tags)
    for tag in raw:
        name = str(tag).strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _clean_attrs(attrs: Any) -> Dict[str, float]:
    """数值属性清洗：无法转 float 的值被丢弃。"""
    result: Dict[str, float] = {}
    if not attrs:
        return result
    if isinstance(attrs, Mapping):
        items = attrs.items()
    else:  # 容错：允许 [["身高", 168], ...]
        try:
            items = [(str(k), v) for k, v in attrs]
        except (TypeError, ValueError):
            return result
    for key, value in items:
        name = str(key).strip()
        if not name or value is None or value == "":
            continue
        try:
            result[name] = float(value)
        except (TypeError, ValueError):
            continue
    return result


@dataclass
class Student:
    """一名学生。``sid`` 为唯一主键。"""

    sid: str
    name: str
    gender: str = ""
    tags: List[str] = field(default_factory=list)
    attrs: Dict[str, float] = field(default_factory=dict)
    note: str = ""

    def __post_init__(self) -> None:
        self.sid = str(self.sid).strip()
        self.name = str(self.name).strip()
        self.gender = str(self.gender or "").strip()
        self.note = str(self.note or "").strip()
        self.tags = _clean_tags(self.tags)
        self.attrs = _clean_attrs(self.attrs)

    # 属性
    def sid_tail(self, n: int = 4) -> str:
        """学号后 n 位，用于座位卡片副文本。"""
        sid = self.sid
        if len(sid) <= n:
            return sid
        return sid[-n:]

    def matches(self, keyword: str) -> bool:
        """搜索匹配：学号 / 姓名 / 标签 / 备注。"""
        kw = (keyword or "").strip().lower()
        if not kw:
            return True
        haystack = [self.sid.lower(), self.name.lower(), self.note.lower()]
        haystack.extend(t.lower() for t in self.tags)
        return any(kw in h for h in haystack)

    # 序列化
    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"sid": self.sid, "name": self.name}
        if self.gender:
            data["gender"] = self.gender
        if self.tags:
            data["tags"] = list(self.tags)
        if self.attrs:
            data["attrs"] = {k: v for k, v in self.attrs.items()}
        if self.note:
            data["note"] = self.note
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Student":
        if not isinstance(data, Mapping):
            raise ValueError("学生记录必须是对象")
        sid = data.get("sid", data.get("id", ""))
        name = data.get("name", "")
        return cls(
            sid=str(sid or "").strip(),
            name=str(name or "").strip(),
            gender=data.get("gender", "") or "",
            tags=data.get("tags", []) or [],
            attrs=data.get("attrs", {}) or {},
            note=data.get("note", "") or "",
        )

    # 排序键
    def __repr__(self) -> str:  # 调试用
        return "Student(%r, %r)" % (self.sid, self.name)


def attr_names(students: List[Student]) -> List[str]:
    """收集全部学生出现过的数值属性名（保持首次出现顺序）。"""
    names: List[str] = []
    seen = set()
    for stu in students:
        for name in stu.attrs:
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names
