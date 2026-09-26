"""标签胶囊控件。"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..style.theme import Color


class TagChip(QFrame):
    """一个小圆角色块 + 标签名；``closable=True`` 时右侧有 ✕。"""

    removed = pyqtSignal(str)

    def __init__(self, name: str, color: str, closable: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._name = str(name or "")
        self._color = QColor(color or Color.TAG_UNKNOWN)
        self._closable = bool(closable)
        self.setObjectName("TagChip")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.PointingHandCursor if closable else Qt.CursorShape.ArrowCursor)
        self.setToolTip(self._name)
        self._label = QLabel(self._name, self)
        self._label.setStyleSheet("color: %s; background: transparent;" % self._text_color())
        font = QFont()
        font.setPointSize(9)
        self._label.setFont(font)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 1, 6 if closable else 8, 1)
        layout.setSpacing(4)
        layout.addWidget(self._label)
        if closable:
            close = QLabel("✕", self)
            close.setStyleSheet("color: %s; background: transparent;" % self._text_color())
            close.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(close)
            close.mousePressEvent = self._on_close
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    # 属性
    @property
    def name(self) -> str:
        return self._name

    @property
    def color(self) -> str:
        return self._color.name()

    def _text_color(self) -> str:
        # 深色底：胶囊内部是同色系的暗色底，字用同色系亮色最耐看也最可读
        color = QColor(self._color)
        if color.lightness() < 130:
            color = color.lighter(155)
        return color.name()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()), 8.0, 8.0)
        fill = QColor(self._color)
        fill.setAlpha(48)
        painter.fillPath(path, fill)
        painter.setPen(QColor(self._color).lighter(115))
        painter.drawPath(path)
        painter.end()

    def _on_close(self, event) -> None:
        self.removed.emit(self._name)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._closable:
            self.removed.emit(self._name)
        super().mousePressEvent(event)


class TagFlow(QWidget):
    """标签胶囊容器：按行自动换行（简易流式布局）。"""

    removed = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tags: List[Tuple[str, str]] = []
        self._closable = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

    def set_closable(self, flag: bool) -> None:
        self._closable = bool(flag)
        self._rebuild()

    def set_tags(self, tags: Sequence[Tuple[str, str]]) -> None:
        self._tags = [(str(n), str(c)) for n, c in (tags or [])]
        self._rebuild()

    def tag_names(self) -> List[str]:
        return [name for name, _ in self._tags]

    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not self._tags:
            hint = QLabel("暂无标签")
            hint.setObjectName("Hint")
            self._layout.addWidget(hint)
            return
        row = QHBoxLayout()
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)
        width = 0
        limit = max(120, self.width() or 240)
        for name, color in self._tags:
            chip = TagChip(name, color, self._closable)
            if self._closable:
                chip.removed.connect(self.removed.emit)
            chip_width = len(name) * 12 + 34
            if width and width + chip_width > limit:
                row.addStretch(1)
                self._layout.addLayout(row)
                row = QHBoxLayout()
                row.setSpacing(4)
                row.setContentsMargins(0, 0, 0, 0)
                width = 0
            row.addWidget(chip)
            width += chip_width
        row.addStretch(1)
        self._layout.addLayout(row)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._rebuild()
