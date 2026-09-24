"""项目聚合根：持有一间教室的全部状态。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from ..config import TAG_PALETTE
from ..utils.seat_key import dict_to_assignment, make_key
from ..utils.seat_key import Seat as Coord
from .assignment import Assignment, sanitize, seat_of
from .layout import Layout
from .rule import HARD, Rule, Violation
from .selection import Selection, make_selection_id
from .student import Student, attr_names

# ------------------------------------------------------------------ 事件名
EV_LAYOUT = "layout"
EV_STUDENTS = "students"
EV_TAGS = "tags"
EV_SELECTIONS = "selections"
EV_RULES = "rules"
EV_ASSIGNMENT = "assignment"
EV_HISTORY = "history"
EV_ANY = "any"


@dataclass
class Tag:
    """标签定义。"""

    name: str
    color: str = TAG_PALETTE[0]

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "color": self.color}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Tag":
        return cls(str(data.get("name") or "").strip(), str(data.get("color") or TAG_PALETTE[0]))


@dataclass
class RotationRecord:
    """一次轮换（或一次快照）的历史记录。"""

    week: int
    assignment: Assignment = field(default_factory=dict)
    label: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "week": self.week,
            "assignment": dict(self.assignment),
            "label": self.label,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RotationRecord":
        return cls(
            week=int(data.get("week", 1)),
            assignment=dict_to_assignment(data.get("assignment") or {}),
            label=str(data.get("label") or ""),
            timestamp=float(data.get("timestamp", time.time())),
        )


class Project:
    """聚合根。发出轻量级观察者通知（不依赖 Qt，便于单元测试）。"""

    def __init__(self) -> None:
        self.layout: Layout = Layout.default()
        self.students: List[Student] = []
        self.tags: List[Tag] = []
        self.selections: List[Selection] = []
        self.rules: List[Rule] = []
        self.assignment: Assignment = {}
        self.previous_assignment: Assignment = {}
        self.history: List[RotationRecord] = []

        self.path: str = ""
        self.dirty: bool = False

        self._student_index: Dict[str, Student] = {}
        self._selection_index: Dict[str, Selection] = {}
        self._listeners: List[Callable[[str, Any], None]] = []
        self._suspend = 0

    # ------------------------------------------------------------ 观察者
    def subscribe(self, listener: Callable[[str, Any], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[str, Any], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def notify(self, event: str = EV_ANY, payload: Any = None) -> None:
        self.dirty = True
        if self._suspend:
            return
        for listener in list(self._listeners):
            try:
                listener(event, payload)
            except Exception:  # noqa: BLE001 - 监听器异常不应打断业务
                pass

    def mark_clean(self) -> None:
        self.dirty = False

    class _Suspend:
        def __init__(self, project: "Project") -> None:
            self.project = project

        def __enter__(self) -> "Project":
            self.project._suspend += 1
            return self.project

        def __exit__(self, *exc: Any) -> bool:
            self.project._suspend = max(0, self.project._suspend - 1)
            if self.project._suspend == 0:
                self.project.notify(EV_ANY)
            return False

    def suspend(self) -> "Project._Suspend":
        """批量修改期间挂起通知：``with project.suspend(): ...``"""
        return Project._Suspend(self)

    # ------------------------------------------------------------ 学生
    def rebuild_index(self) -> None:
        self._student_index = {s.sid: s for s in self.students}

    def get_student(self, sid: str) -> Optional[Student]:
        return self._student_index.get(sid)

    def student_name(self, sid: str) -> str:
        stu = self._student_index.get(sid)
        return stu.name if stu else (sid or "")

    def add_student(self, student: Student, notify: bool = True) -> bool:
        """sid 重复时返回 False。"""
        if not student.sid or student.sid in self._student_index:
            return False
        self.students.append(student)
        self._student_index[student.sid] = student
        if notify:
            self.notify(EV_STUDENTS)
        return True

    def add_students(self, students: Iterable[Student]) -> int:
        """批量添加，返回成功条数；重复学号自动跳过。"""
        added = 0
        with self.suspend():
            for student in students:
                if self.add_student(student, notify=False):
                    added += 1
        return added

    def update_student(self, target_sid: str, **changes: Any) -> bool:
        """更新学生；``changes`` 里可以带 ``sid`` 表示改学号。"""
        student = self._student_index.get(target_sid)
        if student is None:
            return False
        new_sid = str(changes.pop("sid", student.sid) or "").strip()
        if not new_sid:
            return False
        for key, value in changes.items():
            if hasattr(student, key):
                setattr(student, key, value)
        student.__post_init__()
        if new_sid != target_sid:
            if new_sid in self._student_index:
                return False
            del self._student_index[target_sid]
            student.sid = new_sid
            self._student_index[new_sid] = student
            self.assignment = {
                key: (new_sid if value == target_sid else value)
                for key, value in self.assignment.items()
            }
        self.notify(EV_STUDENTS)
        return True

    def remove_student(self, sid: str, notify: bool = True) -> bool:
        student = self._student_index.pop(sid, None)
        if student is None:
            return False
        try:
            self.students.remove(student)
        except ValueError:
            pass
        self.assignment = {k: v for k, v in self.assignment.items() if v != sid}
        if notify:
            self.notify(EV_STUDENTS)
        return True

    def remove_students(self, sids: Iterable[str]) -> int:
        removed = 0
        with self.suspend():
            for sid in list(sids):
                if self.remove_student(sid, notify=False):
                    removed += 1
        return removed

    def all_sids(self) -> List[str]:
        return [s.sid for s in self.students]

    def attr_names(self) -> List[str]:
        return attr_names(self.students)

    # ------------------------------------------------------------ 标签
    def tag_names(self) -> List[str]:
        return [t.name for t in self.tags]

    def get_tag(self, name: str) -> Optional[Tag]:
        for tag in self.tags:
            if tag.name == name:
                return tag
        return None

    def tag_color(self, name: str) -> str:
        tag = self.get_tag(name)
        return tag.color if tag else TAG_PALETTE[0]

    def next_tag_color(self) -> str:
        used = {t.color for t in self.tags}
        for color in TAG_PALETTE:
            if color not in used:
                return color
        return TAG_PALETTE[len(self.tags) % len(TAG_PALETTE)]

    def ensure_tag(self, name: str, color: str = "") -> Optional[Tag]:
        """标签不存在时创建。"""
        name = (name or "").strip()
        if not name:
            return None
        existing = self.get_tag(name)
        if existing is not None:
            return existing
        tag = Tag(name, color or self.next_tag_color())
        self.tags.append(tag)
        return tag

    def add_tag(self, name: str, color: str = "") -> bool:
        name = (name or "").strip()
        if not name or self.get_tag(name) is not None:
            return False
        self.tags.append(Tag(name, color or self.next_tag_color()))
        self.notify(EV_TAGS)
        return True

    def rename_tag(self, old: str, new: str) -> bool:
        new = (new or "").strip()
        if not new or old == new or self.get_tag(new) is not None:
            return False
        tag = self.get_tag(old)
        if tag is None:
            return False
        tag.name = new
        for student in self.students:
            student.tags = [new if t == old else t for t in student.tags]
        for rule in self.rules:
            for key in ("tag", "tag_a", "tag_b"):
                if rule.params.get(key) == old:
                    rule.params[key] = new
        self.notify(EV_TAGS)
        return True

    def set_tag_color(self, name: str, color: str) -> bool:
        tag = self.get_tag(name)
        if tag is None:
            return False
        tag.color = color
        self.notify(EV_TAGS)
        return True

    def remove_tag(self, name: str) -> bool:
        """删除标签，并从所有学生身上移除。"""
        tag = self.get_tag(name)
        if tag is None:
            return False
        self.tags.remove(tag)
        for student in self.students:
            if name in student.tags:
                student.tags = [t for t in student.tags if t != name]
        for rule in self.rules:
            for key in ("tag", "tag_a", "tag_b"):
                if rule.params.get(key) == name:
                    rule.params[key] = ""
        self.notify(EV_TAGS)
        return True

    # ------------------------------------------------------------ 选区
    def get_selection(self, selection_id: str) -> Optional[Selection]:
        return self._selection_index.get(selection_id)

    def selection_name(self, selection_id: str) -> str:
        sel = self._selection_index.get(selection_id)
        return sel.name if sel else (selection_id or "")

    def add_selection(self, name: str, seats: Iterable[Sequence[int]], color: str = "",
                      selection_id: str = "") -> Selection:
        sid = selection_id or make_selection_id()
        sel = Selection(sid, name, set(tuple(int(v) for v in s) for s in seats), color or "#2F6BFF")
        self.selections.append(sel)
        self._selection_index[sel.id] = sel
        self.notify(EV_SELECTIONS)
        return sel

    def remove_selection(self, selection_id: str) -> bool:
        sel = self._selection_index.pop(selection_id, None)
        if sel is None:
            return False
        try:
            self.selections.remove(sel)
        except ValueError:
            pass
        for rule in self.rules:
            if rule.params.get("selection") == selection_id:
                rule.enabled = False
        self.notify(EV_SELECTIONS)
        return True

    def rename_selection(self, selection_id: str, name: str) -> bool:
        sel = self._selection_index.get(selection_id)
        if sel is None:
            return False
        sel.name = (name or "").strip() or sel.name
        self.notify(EV_SELECTIONS)
        return True

    def update_selection_seats(self, selection_id: str, seats: Iterable[Sequence[int]]) -> bool:
        sel = self._selection_index.get(selection_id)
        if sel is None:
            return False
        sel.seats = set(tuple(int(v) for v in s) for s in seats)
        self.notify(EV_SELECTIONS)
        return True

    def rebuild_selection_index(self) -> None:
        self._selection_index = {s.id: s for s in self.selections}

    # ------------------------------------------------------------ 规则
    def add_rule(self, rule: Rule) -> bool:
        if any(r.id == rule.id for r in self.rules):
            return False
        self.rules.append(rule)
        self.notify(EV_RULES)
        return True

    def remove_rule(self, rule_id: str) -> bool:
        for rule in list(self.rules):
            if rule.id == rule_id:
                self.rules.remove(rule)
                self.notify(EV_RULES)
                return True
        return False

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None

    def hard_rules(self) -> List[Rule]:
        return [r for r in self.rules if r.is_hard and r.enabled]

    def soft_rules(self) -> List[Rule]:
        return [r for r in self.rules if r.is_soft and r.enabled]

    # ------------------------------------------------------------ 分配
    def sanitize_assignment(self) -> List[str]:
        """清洗分配结果，返回发现的问题列表。"""
        from .assignment import is_valid

        problems = is_valid(self.assignment, self.layout)
        self.assignment = sanitize(self.assignment, self.layout, self.all_sids())
        return problems

    def seat_of(self, sid: str) -> Optional[Coord]:
        return seat_of(self.assignment, sid)

    # ------------------------------------------------------------ 轮换历史
    def push_history(self, label: str = "", week: Optional[int] = None) -> RotationRecord:
        if week is None:
            week = (max([r.week for r in self.history]) + 1) if self.history else 1
        record = RotationRecord(int(week), dict(self.assignment), label)
        self.history.append(record)
        self.notify(EV_HISTORY)
        return record

    def get_history(self, week: int) -> Optional[RotationRecord]:
        for record in self.history:
            if record.week == week:
                return record
        return None

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": "1.0",
            "layout": self.layout.to_dict(),
            "students": [s.to_dict() for s in self.students],
            "tags": [t.to_dict() for t in self.tags],
            "selections": [s.to_dict() for s in self.selections],
            "rules": [r.to_dict() for r in self.rules],
            "assignment": dict(self.assignment),
            "previous_assignment": dict(self.previous_assignment),
            "history": [h.to_dict() for h in self.history],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Project":
        project = cls()
        project.layout = Layout.from_dict(data.get("layout"))
        project.students = [Student.from_dict(s) for s in (data.get("students") or [])]
        project.tags = [Tag.from_dict(t) for t in (data.get("tags") or []) if str(t.get("name") or "").strip()]
        project.selections = [Selection.from_dict(s) for s in (data.get("selections") or [])]
        project.rules = [Rule.from_dict(r) for r in (data.get("rules") or [])]
        project.assignment = dict_to_assignment(data.get("assignment") or {})
        project.previous_assignment = dict_to_assignment(data.get("previous_assignment") or {})
        project.history = [RotationRecord.from_dict(h) for h in (data.get("history") or [])]

        # 去重：学号 / 标签名
        seen_sids: Set[str] = set()
        unique_students: List[Student] = []
        for student in project.students:
            if student.sid and student.sid not in seen_sids:
                seen_sids.add(student.sid)
                unique_students.append(student)
        project.students = unique_students

        seen_tags: Set[str] = set()
        unique_tags: List[Tag] = []
        for tag in project.tags:
            if tag.name not in seen_tags:
                seen_tags.add(tag.name)
                unique_tags.append(tag)
        project.tags = unique_tags

        # 补齐学生身上出现过但标签库缺失的标签
        for student in project.students:
            for name in student.tags:
                if name not in seen_tags:
                    seen_tags.add(name)
                    project.tags.append(Tag(name, TAG_PALETTE[len(project.tags) % len(TAG_PALETTE)]))

        project.rebuild_index()
        project.rebuild_selection_index()
        project.sanitize_assignment()
        project.mark_clean()
        return project

    # ------------------------------------------------------------ 摘要
    def summary(self) -> Dict[str, Any]:
        return {
            "groups": self.layout.group_count,
            "seats": self.layout.seat_count(),
            "available": self.layout.available_count(),
            "students": len(self.students),
            "tags": len(self.tags),
            "selections": len(self.selections),
            "rules": len(self.rules),
            "assigned": len([v for v in self.assignment.values() if v]),
        }


def new_project() -> Project:
    """新建带默认布局的空项目。"""
    return Project()
