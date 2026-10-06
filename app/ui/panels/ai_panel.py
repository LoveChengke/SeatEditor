"""AI 助手面板：常驻主窗口的白话排位入口。

与 ``AISettingsDialog`` / 主窗口的关系：
- 配置（QSettings 的 ``ai/*``）由本面板直接读写——它是连接信息，不属于项目数据。
- 面板遵守 panels 契约不修改 project：确认后的规则经 ``rules_ready(list, bool)``
  信号交给主窗口落库，第二个参数表示「添加完马上排位」。
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QSettings, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from ...config import APP_ID, ORG_NAME, SK_AI_API_KEY, SK_AI_ENDPOINT, SK_AI_MODEL
from ...models.rule import describe_rule
from ..common import button
from ..style.theme import Color
from .base import ProjectPanel


class AIRulePanel(ProjectPanel):
    """大白话 → 排座规则。结果经 ``rules_ready`` 交给主窗口。"""

    rules_ready = pyqtSignal(list, bool)   # (勾选的规则, 添加完马上排位)

    def __init__(self, project=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(project, parent)
        self._drafts: List = []
        self._rows: List[dict] = []
        self._client = None              # 在途请求；面板销毁时 abort

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        privacy = QLabel("生成时会把你班里的学生名单摘要（姓名、标签、区域）发送给你配置的 AI 服务。")
        privacy.setObjectName("Hint")
        privacy.setWordWrap(True)
        root.addWidget(privacy)

        self._config_label = QLabel("")
        self._config_label.setObjectName("Hint")
        # 必须换行：一句话不换行时 QLabel 会把整行宽度当成最小宽度（实测 313px），
        # 于是「AI 助手」面板再也压不窄，还把这个最小宽度传染给了主窗口
        self._config_label.setWordWrap(True)
        root.addWidget(self._config_label)
        self._refresh_config_label()

        self._input = QPlainTextEdit()
        self._input.setPlaceholderText(
            "用大白话写要求，一条一行更清楚，例如：\n"
            "视力差的坐前排\n"
            "班长分散开，别坐在一起"
        )
        self._input.setFixedHeight(76)
        root.addWidget(self._input)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._generate_button = button("生成规则", self._on_generate, "Primary",
                                       "把上面的大白话交给 AI 转成排座规则")
        actions.addWidget(self._generate_button)
        actions.addWidget(button("AI 设置…", self._open_settings,
                                 tooltip="配置接口地址、模型与 API Key"))
        actions.addStretch(1)
        root.addLayout(actions)

        self._problems_label = QLabel("")
        self._problems_label.setObjectName("Hint")
        self._problems_label.setWordWrap(True)
        self._problems_label.hide()
        root.addWidget(self._problems_label)

        self._results_host = QWidget()
        self._results_layout = QVBoxLayout(self._results_host)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._results_host)
        scroll.setMinimumHeight(120)
        root.addWidget(scroll, 1)

        self._empty_hint = QLabel("还没有生成规则。写好要求后点「生成规则」。")
        self._empty_hint.setObjectName("Hint")
        self._empty_hint.setWordWrap(True)
        self._results_layout.addWidget(self._empty_hint)

        self._solve_check = QCheckBox("添加完马上排位")
        self._solve_check.setToolTip("添加规则后直接自动排座")
        root.addWidget(self._solve_check)
        self._add_button = button("添加勾选的规则", self._on_add, "Primary",
                                  "把勾选的规则交给主窗口加入规则列表")
        self._add_button.setEnabled(False)
        root.addWidget(self._add_button)

        self._refresh_config_label()

    # ---------------------------------------------------------- ProjectPanel
    def _on_project_event(self, event: str, payload=None) -> None:
        """项目变化不清理草稿——草稿是临时产物，生成时会用最新项目数据。"""

    def refresh(self) -> None:
        """面板没有常驻列表可刷新；草稿在每次生成时重建。"""

    # ---------------------------------------------------------- 配置
    @staticmethod
    def _read_setting(key: str) -> str:
        return str(QSettings(ORG_NAME, APP_ID).value(key, "", type=str) or "")

    def _has_config(self) -> bool:
        return bool(self._endpoint and self._model)

    def _refresh_config_label(self) -> None:
        self._endpoint = self._read_setting(SK_AI_ENDPOINT)
        self._api_key = self._read_setting(SK_AI_API_KEY)
        self._model = self._read_setting(SK_AI_MODEL)
        if self._has_config():
            self._config_label.setText("当前 AI 服务：%s（%s）" % (self._endpoint, self._model))
        else:
            self._config_label.setText("尚未配置 AI 服务——点「AI 设置…」填接口地址和 Key。")

    def open_settings(self) -> None:
        """打开 AI 设置（面板头的图标键也走这里，不再是面板内部私有动作）。"""
        self._open_settings()

    def _open_settings(self) -> None:
        from ..dialogs.ai_settings_dialog import AISettingsDialog

        dialog = AISettingsDialog(self._endpoint, self._api_key, self._model,
                                  self.window())
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.result_config is None:
            return
        self._endpoint, self._api_key, self._model = dialog.result_config
        settings = QSettings(ORG_NAME, APP_ID)
        settings.setValue(SK_AI_ENDPOINT, self._endpoint)
        settings.setValue(SK_AI_API_KEY, self._api_key)
        settings.setValue(SK_AI_MODEL, self._model)
        self._refresh_config_label()

    # ---------------------------------------------------------- 生成
    def _on_generate(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "先在上面写一两句要求。")
            return
        if not self._has_config():
            answer = QMessageBox.question(
                self, "先配置 AI 服务",
                "还没配置 AI 服务的接口地址和 Key，现在去配置吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._open_settings()
            if not self._has_config():
                return
        if self._project is not None and not self._project.students:
            QMessageBox.information(
                self, "提示", "名单还是空的——先导入学生名单，AI 才能引用具体学生。")
            return

        from ...services.ai_client import AIChatClient, build_system_prompt

        self._generate_button.setEnabled(False)
        self._generate_button.setText("AI 思考中…")
        self._set_problems("")
        if self._client is not None:
            self._client.deleteLater()
        self._client = AIChatClient(self._endpoint, self._api_key, self._model, self)
        self._client.finished.connect(self._on_ai_finished)
        self._client.failed.connect(self._on_ai_failed)
        self._client.send(build_system_prompt(self._project), text)

    def _restore_generate_button(self) -> None:
        self._generate_button.setEnabled(True)
        self._generate_button.setText("生成规则")

    def _on_ai_failed(self, message: str) -> None:
        self._restore_generate_button()
        self._set_problems(message, error=True)

    def _on_ai_finished(self, text: str) -> None:
        from ...services.ai_client import parse_rules_payload

        self._restore_generate_button()
        rules, problems = parse_rules_payload(text, self._project)
        self._set_problems("\n".join(problems), error=bool(problems and not rules))
        self._rebuild_results(rules)

    def _set_problems(self, text: str, error: bool = False) -> None:
        self._problems_label.setText(text)
        self._problems_label.setVisible(bool(text))
        self._problems_label.setStyleSheet(
            "color: %s;" % (Color.DANGER if error else Color.WARNING)
        )

    # ---------------------------------------------------------- 结果区
    def _rebuild_results(self, rules: List) -> None:
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._empty_hint:
                widget.setParent(None)
                widget.deleteLater()
        self._drafts = list(rules)
        self._rows = []
        for index in range(len(self._drafts)):
            row, refs = self._build_rule_row(index)
            self._results_layout.addWidget(row)
            self._rows.append(refs)
        self._empty_hint.setVisible(not self._drafts)
        if not self._drafts:
            self._results_layout.addWidget(self._empty_hint)
        # 尾部弹簧： leftover 高度全部收到底部，规则卡片之间不会被拉开大缝
        self._results_layout.addStretch(1)
        self._add_button.setEnabled(bool(self._drafts))
        if self._rows:
            from .. import motion

            motion.stagger_reveal([refs["widget"] for refs in self._rows])

    def _build_rule_row(self, index: int) -> "tuple[QWidget, dict]":
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(6)

        checkbox = QCheckBox(row)
        checkbox.setChecked(True)
        checkbox.setToolTip("勾选的规则才会被添加")
        layout.addWidget(checkbox)

        desc = QLabel(self._describe(index), row)
        desc.setWordWrap(True)
        layout.addWidget(desc, 1)

        edit = button("编辑", lambda _=False, i=index: self._edit_rule(i),
                      tooltip="微调这条规则的参数")
        layout.addWidget(edit)
        return row, {"checkbox": checkbox, "desc": desc, "widget": row}

    def _describe(self, index: int) -> str:
        return describe_rule(
            self._drafts[index], self._project.student_name, self._project.selection_name
        )

    def _edit_rule(self, index: int) -> None:
        from ..dialogs.rule_edit_dialog import RuleEditDialog

        dialog = RuleEditDialog(self._project, self._drafts[index], self.window())
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.result_rule is None:
            return
        self._drafts[index] = dialog.result_rule
        self._rows[index]["desc"].setText(self._describe(index))

    # ---------------------------------------------------------- 添加
    def _on_add(self) -> None:
        checked = [
            rule for rule, refs in zip(self._drafts, self._rows)
            if refs["checkbox"].isChecked()
        ]
        if not checked:
            QMessageBox.information(self, "提示", "先勾选要添加的规则。")
            return
        self.rules_ready.emit(checked, self._solve_check.isChecked())
        # 交出去之后清空草稿区，避免同一批规则被再次添加
        self._input.clear()
        self._rebuild_results([])

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._abort_request()
        super().hideEvent(event)

    def _abort_request(self) -> None:
        if self._client is not None:
            self._client.abort()
