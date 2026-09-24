"""学生名单服务：增删改查 / 排序 / 过滤 / 批量打标签。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ..models.project import Project, Tag
from ..models.student import Student
from ..utils.natural_sort import natural_key
from ..utils.pinyin import pinyin_key

TAG_MODE_ANY = "any"
TAG_MODE_ALL = "all"

ASSIGN_ALL = "all"
ASSIGN_ASSIGNED = "assigned"
ASSIGN_UNASSIGNED = "unassigned"

# 列头 -> 排序键
SORT_KEYS = ("sid", "name", "gender", "tags", "assigned", "attrs")


@dataclass
class StudentFilter:
    """名单过滤条件。"""

    keyword: str = ""
    tags: Set[str] = field(default_factory=set)
    tag_mode: str = TAG_MODE_ANY
    gender: str = ""
    assign_state: str = ASSIGN_ALL
    attrs: Dict[str, Tuple[Optional[float], Optional[float]]] = field(default_factory=dict)


class StudentService:
    """围绕 :class:`Project` 的学生操作。"""

    def __init__(self, project: Project) -> None:
        self.project = project

    # ------------------------------------------------------------ 增删改
    def add(self, sid: str, name: str, gender: str = "", tags: Optional[Iterable[str]] = None,
            attrs: Optional[Mapping[str, float]] = None, note: str = "") -> Tuple[bool, str]:
        sid, name = str(sid or "").strip(), str(name or "").strip()
        if not sid:
            return False, "学号不能为空"
        if not name:
            return False, "姓名不能为空"
        if self.project.get_student(sid) is not None:
            return False, "学号 %s 已存在" % sid
        student = Student(sid=sid, name=name, gender=gender, tags=list(tags or []),
                          attrs=dict(attrs or {}), note=note)
        self.project.add_student(student)
        for tag in student.tags:
            self.project.ensure_tag(tag)
        self.project.notify("students")
        return True, ""

    def update(self, target_sid: str, **changes: Any) -> Tuple[bool, str]:
        """更新学生信息；``changes`` 里可以带 ``sid`` 表示修改学号。"""
        student = self.project.get_student(target_sid)
        if student is None:
            return False, "找不到该学生"
        new_sid = str(changes.get("sid", target_sid) or "").strip()
        if not new_sid:
            return False, "学号不能为空"
        if not str(changes.get("name", student.name) or "").strip():
            return False, "姓名不能为空"
        ok = self.project.update_student(target_sid, **changes)
        if not ok:
            return False, "学号 %s 已被占用" % new_sid
        updated = self.project.get_student(new_sid)
        if updated is not None:
            for tag in updated.tags:
                self.project.ensure_tag(tag)
        self.project.notify("students")
        return True, ""

    def remove(self, sids: Iterable[str]) -> int:
        count = self.project.remove_students(sids)
        if count:
            self.project.notify("students")
        return count

    # ------------------------------------------------------------ 查询
    def filter(self, condition: StudentFilter) -> List[Student]:
        result: List[Student] = []
        assigned = set(self.project.assignment.values())
        for student in self.project.students:
            if condition.keyword and not student.matches(condition.keyword):
                continue
            if condition.tags:
                if condition.tag_mode == TAG_MODE_ALL:
                    if not condition.tags.issubset(set(student.tags)):
                        continue
                elif not (condition.tags & set(student.tags)):
                    continue
            if condition.gender and student.gender != condition.gender:
                continue
            if condition.assign_state == ASSIGN_ASSIGNED and student.sid not in assigned:
                continue
            if condition.assign_state == ASSIGN_UNASSIGNED and student.sid in assigned:
                continue
            skip = False
            for attr, (low, high) in condition.attrs.items():
                value = student.attrs.get(attr)
                if value is None:
                    skip = True
                    break
                if low is not None and value < low:
                    skip = True
                    break
                if high is not None and value > high:
                    skip = True
                    break
            if skip:
                continue
            result.append(student)
        return result

    # ------------------------------------------------------------ 排序
    def sort_key(self, key: str):
        if key == "name":
            return lambda s: pinyin_key(s.name)
        if key == "gender":
            return lambda s: (s.gender or "~", natural_key(s.sid))
        if key == "tags":
            return lambda s: (len(s.tags), tuple(sorted(s.tags)), natural_key(s.sid))
        if key == "assigned":
            seat = self.project.assignment
            assigned = set(seat.values())

            def _assigned_key(student: Student):
                return (0 if student.sid in assigned else 1, natural_key(student.sid))

            return _assigned_key
        return lambda s: natural_key(s.sid)

    def sorted_students(self, students: Sequence[Student], key: str = "sid", reverse: bool = False) -> List[Student]:
        return sorted(students, key=self.sort_key(key), reverse=reverse)

    # ------------------------------------------------------------ 标签
    def add_tag(self, sids: Iterable[str], tag: str) -> int:
        tag = str(tag or "").strip()
        if not tag:
            return 0
        self.project.ensure_tag(tag)
        count = 0
        for sid in sids:
            student = self.project.get_student(sid)
            if student is None or tag in student.tags:
                continue
            student.tags.append(tag)
            count += 1
        if count:
            self.project.notify("tags")
        return count

    def remove_tag_from(self, sids: Iterable[str], tag: str) -> int:
        count = 0
        for sid in sids:
            student = self.project.get_student(sid)
            if student is None or tag not in student.tags:
                continue
            student.tags = [t for t in student.tags if t != tag]
            count += 1
        if count:
            self.project.notify("tags")
        return count

    def tag_usage(self) -> Dict[str, int]:
        counts: Dict[str, int] = {tag.name: 0 for tag in self.project.tags}
        for student in self.project.students:
            for tag in student.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return counts

    # ------------------------------------------------------------ 文本导入
    @staticmethod
    def parse_text(text: str, default_gender: str = "") -> Tuple[List[Student], List[str]]:
        """解析粘贴的名单：支持 ``学号 姓名`` / ``学号,姓名,性别`` 等。"""
        students: List[Student] = []
        problems: List[str] = []
        seen: Set[str] = set()
        for line_no, raw_line in enumerate(str(text or "").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            parts = [p.strip() for p in re.split(r"[\t,，;；|]+|\s{2,}|\s+", line) if p.strip()]
            if len(parts) == 1:
                students.append(Student(sid=parts[0], name=parts[0], gender=default_gender))
                continue
            sid, name = parts[0], parts[1]
            gender = parts[2] if len(parts) > 2 else default_gender
            if sid in seen:
                problems.append("第 %d 行：学号 %s 重复，已跳过" % (line_no, sid))
                continue
            seen.add(sid)
            students.append(Student(sid=sid, name=name, gender=gender))
        return students, problems
