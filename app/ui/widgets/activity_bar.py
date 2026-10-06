"""左侧活动栏：一列图标，点一下切换侧边栏显示哪一页。

参照 VS Code / ZCode 的活动栏：48px 宽的窄条，选中项左侧一条彩色竖条，
悬停给一块方底，图标全部自绘（见 ``widgets.icons``），名字放在提示里。

为什么不用一排文字按钮：侧边栏要占宽度，图标栏只花 48px 就能把
「名单 / 规则 / 区域 / 换座 / AI」五个入口一次性摆出来，且不随侧边栏隐藏而消失
（侧边栏收起后，活动栏还在，点一下就能把它叫回来）。

两处自适应（见 ``set_compact`` 与主窗口的 ``_apply_responsive_layout``）：
图标 24px、每格 44px 高是正常档；窗口矮于 620px 时收到 20px / 36px，
否则七个入口在矮窗里会顶到底部动作组上，挤成一坨。
"""

from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QWidget

from ..common import IconButton
from ..style.theme import Color
from .icons import paint_glyph

RAIL_WIDTH = 48
RAIL_ICON = 28          # 正常档图标边长（含墨迹归一化后实际约 24px）
RAIL_ITEM_H = 44        # 正常档每格高度
RAIL_ICON_COMPACT = 22
RAIL_ITEM_H_COMPACT = 36


class RailButton(IconButton):
    """活动栏里的一格：选中时整块底色 + 左缘彩色竖条。"""

    def __init__(self, key: str, icon: str, tooltip: str, checkable: bool = True,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(icon, tooltip, size=(RAIL_WIDTH, RAIL_ITEM_H),
                         checkable=checkable, parent=parent)
        self.key = str(key)
        self._icon_px = RAIL_ICON

    def set_compact(self, compact: bool) -> None:
        """矮窗档：图标与行高一起收，七个入口才排得下。"""
        self._icon_px = RAIL_ICON_COMPACT if compact else RAIL_ICON
        height = RAIL_ITEM_H_COMPACT if compact else RAIL_ITEM_H
        if self._fixed[1] != height:
            self.set_icon_box((RAIL_WIDTH, height))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        hot = self.underMouse()
        checked = self.isChecked()

        if checked:
            # 选中项底色比活动栏亮一档（深色主题下只靠加深活动栏是拉不开差距的），
            # 再叠左缘 2.5px 主色竖条
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(Color.RAIL_ACTIVE_BG))
            painter.drawRect(rect)
            painter.setBrush(QColor(Color.PRIMARY))
            painter.drawRect(QRectF(rect.left(), rect.top(), 2.5, rect.height()))
        elif hot:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(Color.BG_SUBTLE))
            painter.drawRect(rect)

        color = (Color.PRIMARY if checked
                 else (Color.TEXT_PRIMARY if hot else Color.ICON_MUTED))
        side = float(self._icon_px)
        box = QRectF(QPointF(rect.center().x() - side / 2.0,
                             rect.center().y() - side / 2.0), QPointF(side, side))
        paint_glyph(painter, self._icon, box, color, 1.35)
        painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self.update()
        super().leaveEvent(event)


class ActivityBar(QWidget):
    """活动栏：上半部分是侧边栏页面，下半部分是常驻动作。"""

    clicked = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ActivityBar")
        self.setFixedWidth(RAIL_WIDTH)
        self._buttons: Dict[str, RailButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 6)
        root.setSpacing(0)

        self._top = QWidget(self)
        self._top_layout = QVBoxLayout(self._top)
        self._top_layout.setContentsMargins(0, 0, 0, 0)
        self._top_layout.setSpacing(0)
        root.addWidget(self._top)

        root.addStretch(1)

        # 两组之间一条发丝线：窗口拉高时中间是一大片空白，没有这条线，
        # 底部三个动作看着像「掉到最下面去了」而不是另一组
        self._separator = QFrame(self)
        self._separator.setObjectName("RailSeparator")
        self._separator.setFixedHeight(1)
        root.addWidget(self._separator)
        root.addSpacing(4)

        self._bottom = QWidget(self)
        self._bottom_layout = QVBoxLayout(self._bottom)
        self._bottom_layout.setContentsMargins(0, 0, 0, 0)
        self._bottom_layout.setSpacing(0)
        root.addWidget(self._bottom)

    # 组成
    def add_page(self, key: str, icon: str, tooltip: str) -> RailButton:
        """加一个页面入口（上半部分）。"""
        button = RailButton(key, icon, tooltip, self._top)
        button.clicked.connect(lambda _checked=False, k=key: self.clicked.emit(k))
        self._buttons[key] = button
        self._top_layout.addWidget(button)
        return button

    def set_theme_icon(self, dark: bool) -> None:
        """明暗切换键画成目标状态：黑夜模式显示太阳（点了变亮），反之显示月亮。"""
        button = self._buttons.get("theme")
        if button is not None:
            button.set_glyph("sun" if dark else "moon")

    def add_action(self, key: str, icon: str, tooltip: str) -> RailButton:
        """加一个常驻动作（下半部分，贴底）。

        动作键**不可勾选**：它不是「当前页面」，点亮会让人以为这一页被选中了
        （而且没人会把它取消，就一直是选中态）。
        """
        button = RailButton(key, icon, tooltip, checkable=False, parent=self._bottom)
        button.clicked.connect(lambda _checked=False, k=key: self.clicked.emit(k))
        self._buttons[key] = button
        self._bottom_layout.addWidget(button)
        return button

    # 状态
    def set_compact(self, compact: bool) -> None:
        """矮窗档：所有格子一起收（见模块开头的说明）。"""
        for button in self._buttons.values():
            button.set_compact(compact)

    def set_active(self, key: Optional[str]) -> None:
        """高亮某一页；``None`` 表示侧边栏已收起，全部不亮。

        只动可勾选的（页面）键：动作键本来就不该有选中态。
        """
        for name, button in self._buttons.items():
            if button.isCheckable():
                button.setChecked(name == key)

    def button(self, key: str) -> Optional[RailButton]:
        return self._buttons.get(key)
