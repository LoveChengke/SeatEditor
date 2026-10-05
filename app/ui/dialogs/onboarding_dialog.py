"""开始引导对话框：首次启动（及菜单重看）时的四步上手引导。

只做「讲清楚 + 跳过去」两件事：四张步骤卡片各带一个动作按钮，点按钮关闭
引导并直接跳到对应操作；不做多页向导——教师只需要知道先做什么、点哪里。
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..style.theme import Color

# 步骤 = (标题, 一句话说明, 动作按钮文字或 None, 点击后的回调或 None)
Step = Tuple[str, str, Optional[str], Optional[Callable]]

# 未注入步骤时的兜底（只有文案，不带动作按钮）；主窗口会传入带真实动作的版本
DEFAULT_STEPS: Sequence[Step] = (
    ("设置教室布局", "教室分几组、几排、几列。点顶部「教室布局」，选个模板就行。", None, None),
    ("导入学生名单", "点「导入学生名单」选 Excel 文件；没有 Excel 也可以手动添加。", None, None),
    ("挑几条排座规则", "比如「视力差的坐前排」。不挑也行，直接排。", None, None),
    ("一键排位并导出", "按 F5 自动排好，拖一拖微调，满意就导出 Excel 或图片。", None, None),
)


class OnboardingDialog(QDialog):
    """四步引导卡。步骤动作由主窗口注入，点击后关闭引导并执行。"""

    def __init__(self, parent: Optional[QWidget] = None,
                 steps: Optional[Sequence[Step]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("开始引导")
        self.setMinimumWidth(560)   # 步骤说明要一口气读完，太窄会碎成四五行
        self._on_action: Optional[Callable] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        title = QLabel("欢迎使用教室座位编排")
        title.setObjectName("PanelTitle")
        root.addWidget(title)

        subtitle = QLabel("四步排好一次座位，跟着做就行。做完一步再做下一步。")
        subtitle.setObjectName("Hint")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        for index, (step_title, desc, action_text, callback) in enumerate(
            steps if steps is not None else DEFAULT_STEPS, start=1
        ):
            root.addWidget(self._step_card(index, step_title, desc, action_text, callback))

        root.addSpacing(4)
        footer = QHBoxLayout()
        self._dont_show = QCheckBox("下次启动不再显示这个引导")
        self._dont_show.setChecked(True)
        footer.addWidget(self._dont_show)
        footer.addStretch(1)
        start = QPushButton("开始使用")
        start.setObjectName("Primary")
        start.setDefault(True)
        start.clicked.connect(self.accept)
        footer.addWidget(start)
        root.addLayout(footer)

    # 界面
    def _step_card(self, index: int, title: str, desc: str,
                   action_text: Optional[str], callback: Optional[Callable]) -> QWidget:
        card = QWidget()
        card.setObjectName("Panel")
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)

        badge = QLabel(str(index), card)
        badge.setFixedSize(32, 32)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "background: %s; color: %s; border-radius: 16px;"
            " font-size: 16px; font-weight: 600;"
            % (Color.PRIMARY, Color.TEXT_ON_ACCENT)
        )
        row.addWidget(badge)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title_label = QLabel(title, card)
        title_label.setStyleSheet("font-size: 14px; font-weight: 600; background: transparent;")
        text_col.addWidget(title_label)
        desc_label = QLabel(desc, card)
        desc_label.setObjectName("Hint")
        desc_label.setWordWrap(True)
        text_col.addWidget(desc_label)
        row.addLayout(text_col, 1)

        if action_text and callback is not None:
            button = QPushButton(action_text, card)
            button.clicked.connect(lambda: self._run_action(callback))
            row.addWidget(button)
        return card

    # 动作
    def _run_action(self, callback: Callable) -> None:
        """先记住回调，关掉引导再执行——模态对话框开着时再开新窗口会互相卡住。"""
        self._on_action = callback
        self.accept()

    def dont_show_again(self) -> bool:
        return self._dont_show.isChecked()

    def taken_action(self) -> Optional[Callable]:
        return self._on_action
