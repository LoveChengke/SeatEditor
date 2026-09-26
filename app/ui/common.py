"""界面公共小工具：分隔线、便捷按钮、确认 / 提示弹窗。

放在一处是为了让 ``HLine`` / ``Primary`` 这类 objectName 只有**一个**施加点。
QSS 是按 objectName 匹配的（见 ``app/ui/style/app.qss``），
同一个名字散在十几份副本里时，改了一处漏掉另一处不会报任何错，
只会悄悄丢掉样式。

本模块只依赖 PyQt6，不 import ``theme`` / ``panels`` / ``dialogs``，
这样两边都能安全地 import 它。
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget,
)


def hline() -> QFrame:
    """1px 浅色分隔线（QSS：``QFrame#HLine``）。

    高度要在控件上压住：QSS 只给了 ``max-height: 1px``，
    而裸 QFrame 默认会撑高。也不要改成 ``setFrameShape(HLine)``——
    QSS 里的背景色是针对裸 QFrame 写的，走原生描边会丢背景色。
    """
    line = QFrame()
    line.setObjectName("HLine")
    line.setFixedHeight(1)
    return line


def button(text: str, slot: Optional[Callable] = None, name: str = "",
           tooltip: str = "") -> QPushButton:
    """便捷按钮；``name`` 用于 QSS 的 Primary / Danger / Ghost。

    三个判断不能省：无条件调用会写入空 objectName，
    QSS 选择器匹配行为就变了。
    """
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    if tooltip:
        widget.setToolTip(tooltip)
    if slot is not None:
        widget.clicked.connect(slot)
    return widget


def confirm(parent: QWidget, text: str, title: str) -> bool:
    """是 / 否询问，默认停在「否」。"""
    answer = QMessageBox.question(
        parent, title, text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def warn(parent: QWidget, text: str, title: str = "提示") -> None:
    QMessageBox.warning(parent, title, text)


def fit_to_screen(widget: QWidget, margin: int = 48) -> None:
    """把窗口限制在当前屏幕的可用区域内。

    高 DPI 缩放（150% / 200%）或小屏笔记本上，「逻辑像素」的可用高度可能只有
    800 上下：写死的尺寸会让对话框的按钮或菜单落到屏幕外。这里统一按
    ``availableGeometry()`` 收口——最大值收窄、最小值放宽，必要时把当前尺寸缩回去。
    """
    from PyQt6.QtWidgets import QApplication

    screen = widget.screen() or QApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    max_width = max(360, int(available.width()) - int(margin))
    max_height = max(280, int(available.height()) - int(margin))
    if widget.minimumWidth() > max_width or widget.minimumHeight() > max_height:
        widget.setMinimumSize(
            min(widget.minimumWidth(), max_width),
            min(widget.minimumHeight(), max_height),
        )
    widget.setMaximumSize(max_width, max_height)
    size = widget.size()
    if size.width() > max_width or size.height() > max_height:
        widget.resize(min(size.width(), max_width), min(size.height(), max_height))


class CollapsibleSection(QWidget):
    """可折叠区块：标题一行（带 ▶ / ▼），内容默认收起。

    低频选项（座位尺寸、导出明细这类）折叠起来，界面上只留主流程需要的控件。
    内容仍然是普通的 ``QWidget``，外部照常往 ``body_layout`` 里加控件。
    """

    def __init__(self, title: str, parent: Optional[QWidget] = None,
                 expanded: bool = False, tooltip: str = "") -> None:
        super().__init__(parent)
        self._title = str(title)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self._toggle = QToolButton(self)
        self._toggle.setObjectName("SectionToggle")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(bool(expanded))
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._toggle.setText(self._header_text())
        self._toggle.setToolTip(tooltip or "展开 / 收起")
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.clicked.connect(self._on_toggled)
        root.addWidget(self._toggle)

        self._body = QWidget(self)
        self.body_layout = QVBoxLayout(self._body)
        self.body_layout.setContentsMargins(8, 0, 0, 0)
        self.body_layout.setSpacing(6)
        self._body.setVisible(bool(expanded))
        root.addWidget(self._body)

    def _header_text(self) -> str:
        # 用中文而不是 ▶ / ▼：微软雅黑里没有这两个几何符号，会渲染成方框
        return "%s（%s）" % (self._title, "收起" if self._toggle.isChecked() else "展开")

    def _on_toggled(self, checked: bool) -> None:
        self._body.setVisible(bool(checked))
        self._toggle.setText(self._header_text())

    # 对外接口
    @property
    def body(self) -> QWidget:
        return self._body

    def is_expanded(self) -> bool:
        return self._toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self._toggle.setChecked(bool(expanded))
        self._on_toggled(bool(expanded))
