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
from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QToolButton,
    QVBoxLayout, QWidget,
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


def polish_dialog(dialog) -> None:
    """对话框收尾三件套：几何收口 + 首次显示的内容揭示动效。

    所有对话框在 ``__init__`` 末尾调用它代替裸的 ``fit_to_screen``；
    动效规范见 ``app/ui/motion.py``（220ms EASE_OUT，位移 8px）。
    """
    fit_to_screen(dialog)
    from . import motion

    motion.reveal_window(dialog)


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


class IconButton(QPushButton):
    """方形图标键：活动栏、面板头、编辑器头共用。

    图标用 ``widgets.icons`` 的矢量线条自绘（不经过 QIcon，双主题即时变色；
    也不用 ✕ 这类字形——微软雅黑缺码位，会渲染成方框）。
    ``paintEvent`` 整体接管，所以底色 / 悬停 / 选中都在这里画，
    不去和全局 ``QPushButton`` 样式打架。
    """

    def __init__(self, icon: str, tooltip: str = "",
                 size: tuple = (26, 26), danger: bool = False,
                 checkable: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("IconButton")
        self._icon = str(icon)
        self._danger = bool(danger)
        self._fixed = (int(size[0]), int(size[1]))
        self._icon_size = max(14, min(size) - 8)   # 26×26 键 → 18px 图标
        self.setCheckable(bool(checkable))
        self.setFixedSize(*self._fixed)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if tooltip:
            self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)

    # 尺寸：必须自己报，不能只靠 setFixedSize
    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        return QSize(*self._fixed)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        """图标键的最小尺寸就是它自己的尺寸。

        全局样式表里的 ``QPushButton { min-height: 20px }`` 会**覆盖**控件自己
        ``setFixedSize`` 设的值（QSS 的尺寸属性优先于控件的 min/max 属性）。
        于是切换主题重新套用样式表之后，44px 高的活动栏格子被布局压回 20px
        ——「一点切换黑夜模式控件就缩在一起」就是这么来的。把最小尺寸报成
        真实尺寸，布局就不会再压它。
        """
        return QSize(*self._fixed)

    def set_icon_box(self, size: tuple) -> None:
        """改图标键的尺寸（活动栏矮窗档用）。"""
        self._fixed = (int(size[0]), int(size[1]))
        self._icon_size = max(14, min(self._fixed) - 8)
        self.setFixedSize(*self._fixed)
        self.updateGeometry()
        self.update()

    def set_glyph(self, icon: str) -> None:
        if icon != self._icon:
            self._icon = str(icon)
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        from PyQt6.QtCore import QPointF, QRectF
        from PyQt6.QtGui import QColor, QPainter

        from .style.theme import Color
        from .widgets.icons import paint_glyph

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        hot = self.underMouse()
        down = self.isDown()
        checked = self.isChecked()

        if self._danger and (hot or down or checked):
            fill = Color.DANGER_BORDER if down else Color.DANGER_BG
        elif checked:
            fill = Color.PRIMARY_LIGHT
        elif down:
            fill = Color.BG_HOVER
        elif hot:
            fill = Color.BG_SUBTLE
        else:
            fill = None
        if fill:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(rect, 4, 4)

        if self._danger and (hot or down):
            color = Color.DANGER
        elif checked:
            color = Color.PRIMARY
        elif hot or down:
            color = Color.TEXT_PRIMARY
        else:
            color = Color.ICON_MUTED

        side = float(self._icon_size)
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


class HeaderBar(QFrame):
    """面板 / 内容区顶部的细横条：左边标题（或标签条），右边一排图标键。

    一个类服务三种位置，靠 ``object_name`` 分档（QSS 里各自配色）：
    - ``HeaderBar``：程序内窗口（QDockWidget）的标题栏，带放大的关闭键；
    - ``HeaderBar`` + ``tab_bar``：底部面板——标签条占左边，动作在右边；
    - ``EditorHeader``：中央座位表上方，只放视图类动作，没有关闭键。

    关闭键 26×26（原生 QDockWidget 的关闭键只有 14px，高 DPI 下点不中）。
    """

    def __init__(self, title: str = "", parent: Optional[QWidget] = None,
                 object_name: str = "HeaderBar", closable=None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFixedHeight(32)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(8, 0, 6, 0)
        self._row.setSpacing(2)

        self._title = QLabel(str(title), self)
        self._title.setObjectName("HeaderTitle")
        self._title.setContentsMargins(4, 0, 0, 0)
        self._row.addWidget(self._title)
        if not title:
            self._title.hide()
        self._row.addStretch(1)

        self._closable = closable
        self._close: Optional[IconButton] = None
        if closable is not None:
            self._attach_close(closable)

    # 组成
    def _add(self, widget: QWidget) -> None:
        """加到右侧动作区，**关闭键永远排在最后**。

        关闭键在 ``__init__`` 里就建好了（要先知道自己关的是哪个 dock），
        而标题、标签条、动作键都是之后才加的；直接 ``addWidget`` 会让关闭键
        挤到它们左边。所以动作一律插到关闭键之前。
        """
        if self._close is not None:
            self._row.insertWidget(self._row.indexOf(self._close), widget)
        else:
            self._row.addWidget(widget)

    def _attach_close(self, closable) -> None:
        target = closable if hasattr(closable, "close") else None
        self._close = IconButton("close", "关闭这个窗口（可从「视图」菜单重新打开）",
                                 size=(28, 26), danger=True, parent=self)
        if target is not None:
            self._close.clicked.connect(target.close)
        self._row.addWidget(self._close)

    def add_widget(self, widget: QWidget) -> None:
        self._add(widget)

    def add_leading(self, widget: QWidget) -> None:
        """插到最左边：标签条这类「内容」，而不是右侧的动作键。"""
        self._row.insertWidget(0, widget)

    def add_after_title(self, widget: QWidget) -> None:
        """插到标题右边、弹性空白之前（副标题 / 摘要这类说明文字）。"""
        self._row.insertWidget(1, widget)

    def set_title(self, text: str) -> None:
        self._title.setText(str(text))
        self._title.setVisible(bool(text))

    def title_label(self) -> QLabel:
        return self._title

    def add_button(self, icon: str, tooltip: str, slot=None, checkable: bool = False,
                   checked: bool = False, danger: bool = False) -> IconButton:
        btn = IconButton(icon, tooltip, checkable=checkable, danger=danger, parent=self)
        if checked:
            btn.setChecked(True)
        if slot is not None:
            btn.clicked.connect(slot)
        self._add(btn)
        return btn

    def add_menu_button(self, icon: str, tooltip: str, menu) -> IconButton:
        """点一下弹菜单的图标键（菜单自带在按钮右下方弹出）。"""
        btn = IconButton(icon, tooltip, parent=self)
        btn.setMenu(menu)
        self._add(btn)
        return btn

    def add_close_button(self, tooltip: str, slot) -> IconButton:
        btn = IconButton("close", tooltip, size=(28, 26), danger=True, parent=self)
        btn.clicked.connect(slot)
        self._row.addWidget(btn)
        return btn

    def add_stretch(self, stretch: int = 1) -> None:
        self._row.addStretch(stretch)


def blank_title_bar(dock) -> QWidget:
    """给不需要标题栏的停靠面板一个零高度的标题栏控件（活动栏用）。

    QDockWidget 没有「不要标题栏」这个开关，官方推荐的做法是
    ``setTitleBarWidget(QWidget())``；但空 QWidget 的 sizeHint 是无效值，
    有的平台会因此给标题栏留出一行高度，活动栏顶上就多一条空白。
    钉死 0 高度更稳。
    """
    holder = QWidget(dock)
    holder.setFixedHeight(0)
    return holder


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
        # 用中文而不是 ▶ / ▼：微软雅黑里没有这两个几何符号，会渲染成方框。
        # 分隔用「·」而不是再套一层括号——标题自带「（可选）」这类后缀时，
        # 「附加表格（可选）（展开）」连着两个括号很累赘。
        return "%s · %s" % (self._title, "收起" if self._toggle.isChecked() else "展开")

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
