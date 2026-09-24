"""侧边面板的公共骨架：项目换绑与事件合并刷新。

四个面板里逐字相同的那段机制收在这里，重点是 ``_deferred_refresh`` 用的
``QTimer.singleShot(0, ...)``：``project.notify`` 可能在 Qt 正派发信号的过程中
被调用（规则面板就是在 ``itemChanged`` 里 notify 的），此刻同步 ``refresh()``
会销毁正在处理中的那个列表项。这段保护原本有四个副本，任何一个被改成同步
调用都会让 Qt 崩，而且崩了看不出跟改动有关。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget

from ...models.project import Project


class ProjectPanel(QWidget):
    """面板公共骨架。

    只上提四个面板里逐字相同的机制；``_on_project_event`` 留在各面板——
    那里的事件元组是每个面板唯一真正不同的信息，收上来反而要多学一条约定。
    """

    def __init__(self, project: Optional[Project] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._project: Optional[Project] = project
        self._refresh_pending = False

    def _schedule_refresh(self) -> None:
        """合并连续的项目事件，只安排一次延迟刷新。"""
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._deferred_refresh)

    def _deferred_refresh(self) -> None:
        # 顺序要紧：先复位标志、再判空、最后才刷新。
        # 子类的 refresh() 不一定自带 None 守卫，靠这里的顺序兜住。
        # 也不要改成 lambda: self.refresh()——那样会丢掉
        # _refresh_pending 的置位/复位配对，重入保护就失效了。
        self._refresh_pending = False
        if self._project is None:
            return
        self.refresh()

    def set_project(self, project: Optional[Project], service=None) -> None:
        """切换到另一个 Project（新建 / 打开项目时由主窗口调用）。

        骨架固定，各面板的差异全在 ``_on_project_change`` 里。
        注意调用顺序：钩子在 ``self._project`` 被改写**之前**跑，
        这样钩子里读 ``self._project`` 拿到的还是旧项目（StudentPanel 要靠它退订旧模型）。
        """
        if project is None:
            return
        self._unbind_self()
        self._on_project_change(project, service)
        self._project = project
        self._refresh_pending = False
        project.subscribe(self._on_project_event)
        self.refresh()

    def _unbind_self(self) -> None:
        """从旧项目退订自身（幂等）。"""
        if self._project is None:
            return
        try:
            self._project.unsubscribe(self._on_project_event)
        except Exception:
            pass

    def _on_project_change(self, project: Project, service=None) -> None:
        """面板特有的一次性准备：清缓存、换服务、重建模型。默认什么都不做。"""

    def _on_project_event(self, event: str, payload=None) -> None:
        raise NotImplementedError

    def refresh(self) -> None:
        raise NotImplementedError
