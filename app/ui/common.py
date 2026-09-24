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

from PyQt6.QtWidgets import QFrame, QMessageBox, QPushButton, QWidget


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
