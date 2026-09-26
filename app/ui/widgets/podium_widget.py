"""讲台控件：蓝灰底 + 亮字「讲 台」。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..style.theme import Color, FONT_PODIUM, PODIUM_HEIGHT


class PodiumWidget(QWidget):
    """横向讲台条。宽度随容器拉伸。"""

    def __init__(self, text: str = "讲　台", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Podium")
        self.setFixedHeight(PODIUM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        label = QLabel(text, self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            "color: %s; background: %s; border: 1px solid %s; border-radius: 10px;"
            " font-size: %dpx; font-weight: 600; letter-spacing: 8px;"
            % (Color.TEXT_PRIMARY, Color.PODIUM, Color.BORDER_STRONG, FONT_PODIUM)
        )
        from PyQt6.QtWidgets import QHBoxLayout

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
