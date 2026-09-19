"""快照式撤销 / 重做栈（PRD F9）。

快照粒度 = 整个 ``assignment`` 字典（60 座位约几 KB，50 步毫无压力）。
"""

from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Mapping, Optional

from ..config import MAX_UNDO
from ..models.assignment import Assignment


@dataclass
class Snapshot:
    """一次操作前的状态快照。"""

    assignment: Assignment
    label: str = ""
    layout_snapshot: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None

    def clone(self) -> "Snapshot":
        return Snapshot(
            copy.deepcopy(self.assignment),
            self.label,
            copy.deepcopy(self.layout_snapshot),
            copy.deepcopy(self.extra),
        )


class HistoryService:
    """撤销栈。``push`` 在**修改之前**调用，记录修改前的状态。"""

    def __init__(self, max_size: int = MAX_UNDO) -> None:
        self.max_size = max(1, int(max_size))
        self._undo: Deque[Snapshot] = deque(maxlen=self.max_size)
        self._redo: List[Snapshot] = []
        self._current: Snapshot = Snapshot({}, "初始状态")
        self._listeners: List[Any] = []

    # ------------------------------------------------------------ 状态
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def current(self) -> Snapshot:
        return self._current

    def undo_label(self) -> str:
        if not self._undo:
            return ""
        return self._undo[-1].label or "上一步操作"

    def redo_label(self) -> str:
        if not self._redo:
            return ""
        return self._redo[-1].label or "下一步操作"

    def depth(self) -> int:
        return len(self._undo)

    # ------------------------------------------------------------ 记录
    def reset(self, assignment: Optional[Mapping[str, str]] = None, label: str = "初始状态") -> None:
        self._undo.clear()
        self._redo.clear()
        self._current = Snapshot(copy.deepcopy(dict(assignment or {})), label)

    def push(
        self,
        assignment: Mapping[str, str],
        label: str = "",
        layout_snapshot: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录“操作前”的状态。"""
        self._undo.append(
            Snapshot(copy.deepcopy(dict(assignment or {})), label, layout_snapshot, extra)
        )
        self._redo.clear()
        self._notify()

    def push_current(
        self,
        assignment: Mapping[str, str],
        label: str = "",
        layout_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录“操作后”的状态（用于把当前状态存起来以便 redo）。"""
        self._current = Snapshot(copy.deepcopy(dict(assignment or {})), label, layout_snapshot)
        self._notify()

    # ------------------------------------------------------------ 撤销
    def undo(
        self,
        current_assignment: Mapping[str, str],
        layout_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[Snapshot]:
        """回退一步，返回需要恢复的快照（None 表示无可撤销）。

        ``layout_snapshot`` 是**当前**布局状态，会被存进 redo 记录，
        这样重做「设为空置」这类会改布局的操作时才能连布局一起恢复。
        """
        if not self._undo:
            return None
        snapshot = self._undo.pop()
        self._redo.append(
            Snapshot(copy.deepcopy(dict(current_assignment or {})), snapshot.label, layout_snapshot)
        )
        self._current = snapshot
        self._notify()
        return snapshot

    def redo(
        self,
        current_assignment: Mapping[str, str],
        layout_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[Snapshot]:
        if not self._redo:
            return None
        snapshot = self._redo.pop()
        self._undo.append(
            Snapshot(copy.deepcopy(dict(current_assignment or {})), snapshot.label, layout_snapshot)
        )
        self._current = snapshot
        self._notify()
        return snapshot

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._notify()

    def drop_last(self) -> bool:
        """丢弃最近一次 push（操作被取消时用，避免产生多余的 redo 记录）。"""
        if not self._undo:
            return False
        self._undo.pop()
        self._notify()
        return True

    def full_state(self) -> Dict[str, Any]:
        """用于项目文件的可选保存。"""
        return {
            "undo": [{"assignment": s.assignment, "label": s.label} for s in self._undo],
            "redo": [{"assignment": s.assignment, "label": s.label} for s in self._redo],
        }

    def load_state(self, data: Optional[Mapping[str, Any]]) -> None:
        self._undo.clear()
        self._redo.clear()
        if not data:
            return
        for item in data.get("undo") or []:
            self._undo.append(Snapshot(dict(item.get("assignment") or {}), str(item.get("label") or "")))
        for item in data.get("redo") or []:
            self._redo.append(Snapshot(dict(item.get("assignment") or {}), str(item.get("label") or "")))

    # ------------------------------------------------------------ 监听
    def subscribe(self, listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                pass
