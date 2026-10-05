"""AI 大白话排位对话框：老师输入大白话 → AI 生成排座规则 → 勾选确认。

按 dialogs 契约不修改 project：确认后的规则挂在 ``result_rules``，是否接着
自动排位挂在 ``solve_after``，由主窗口落库并触发求解。例外是 AI 连接配置
（QSettings 的 ``ai/*``）：它不属于项目数据，且要让「AI 设置…」立即生效，
所以本对话框直接读写设置。
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...config import ORG_NAME, APP_ID, SK_AI_API_KEY, SK_AI_ENDPOINT, SK_AI_MODEL
from ..common import button, fit_to_screen, hline
from ..style.theme import Color
from .rule_edit_dialog import RuleEditDialog


class AIRuleDialog(QDialog):
    """大白话 → 排座规则。``result_rules`` / ``solve_after`` 仅在接受后有效。"""

    def __init__(self, project, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("AI 大白话排位")
        self.result_rules: List = []
        self.solve_after: bool = False

        self._drafts: List = []          # 与 self._rows 一一对应
        self._rows: List[dict] = []
        self._client = None              # 在途请求（关窗时 abort）

        self._endpoint = self._read_setting(SK_AI_ENDPOINT)
        self._api_key = self._read_setting(SK_AI_API_KEY)
        self._model = self._read_setting(SK_AI_MODEL)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(8)

        title = QLabel("AI 大白话排位")
        title.setObjectName("PanelTitle")
        root.addWidget(title)
        root.addWidget(hline())

        privacy = QLabel("生成时会把你班里的学生名单摘要（姓名、标签、区域）发送到你配置的 AI 服务。")
        privacy.setObjectName("Hint")
        privacy.setWordWrap(True)
        root.addWidget(privacy)

        self._config_label = QLabel("")
        self._config_label.setObjectName("Hint")
        root.addWidget(self._config_label)
        self._refresh_config_label()

        self._input = QPlainTextEdit()
        self._input.setPlaceholderText(
            "用大白话写要求，一条一行更清楚，例如：\n"
            "视力差的坐前排\n"
            "班长分散开，别坐在一起\n"
            "近视的不要坐最后一排"
        )
        self._input.setFixedHeight(88)
        root.addWidget(self._input)

        actions = QHBoxLayout()
        self._generate_button = button("生成排座规则", self._on_generate, "Primary",
                                       "把上面的大白话交给 AI 转成排座规则")
        actions.addWidget(self._generate_button)
        actions.addWidget(button("AI 设置…", self._open_settings,
                                 "配置接口地址、模型与 API Key"))
        actions.addStretch(1)
        root.addLayout(actions)

        self._problems_label = QLabel("")
        self._problems_label.setObjectName("Hint")
        self._problems_label.setWordWrap(True)
        self._problems_label.hide()
        root.addWidget(self._problems_label)

        # 结果区：可滚动，行数随 AI 产出变化
        self._results_host = QWidget()
        self._results_layout = QVBoxLayout(self._results_host)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._results_host)
        scroll.setMinimumHeight(140)
        root.addWidget(scroll, 1)

        self._empty_hint = QLabel("还没有生成规则。写好要求后点「生成排座规则」。")
        self._empty_hint.setObjectName("Hint")
        self._results_layout.addWidget(self._empty_hint)

        footer = QHBoxLayout()
        self._add_button = button("添加勾选的规则", self.accept, "Primary",
                                  "把勾选的规则加入规则列表")
        self._add_button.setEnabled(False)
        footer.addWidget(self._add_button)
        self._solve_check = QCheckBox("添加完马上排位")
        self._solve_check.setToolTip("添加规则后直接按 F5 自动排座")
        footer.addWidget(self._solve_check)
        footer.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        root.addLayout(footer)

        fit_to_screen(self)
        self.setMinimumWidth(560)

    # ---------------------------------------------------------------- 配置
    @staticmethod
    def _read_setting(key: str) -> str:
        return str(QSettings(ORG_NAME, APP_ID).value(key, "", type=str) or "")

    def _has_config(self) -> bool:
        return bool(self._endpoint and self._model)

    def _refresh_config_label(self) -> None:
        if self._has_config():
            self._config_label.setText("当前 AI 服务：%s（%s）" % (self._endpoint, self._model))
        else:
            self._config_label.setText("尚未配置 AI 服务——点「AI 设置…」填接口地址和 Key。")

    def _open_settings(self) -> None:
        from .ai_settings_dialog import AISettingsDialog

        dialog = AISettingsDialog(self._endpoint, self._api_key, self._model, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_config is None:
            return
        self._endpoint, self._api_key, self._model = dialog.result_config
        settings = QSettings(ORG_NAME, APP_ID)
        settings.setValue(SK_AI_ENDPOINT, self._endpoint)
        settings.setValue(SK_AI_API_KEY, self._api_key)
        settings.setValue(SK_AI_MODEL, self._model)
        self._refresh_config_label()

    # ---------------------------------------------------------------- 生成
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
        if not self.project.students:
            QMessageBox.information(
                self, "提示", "名单还是空的——先在左侧「导入学生名单」，AI 才能引用具体学生。")
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
        self._client.send(build_system_prompt(self.project), text)

    def _restore_generate_button(self) -> None:
        self._generate_button.setEnabled(True)
        self._generate_button.setText("生成排座规则")

    def _on_ai_failed(self, message: str) -> None:
        self._restore_generate_button()
        self._set_problems(message, error=True)

    def _on_ai_finished(self, text: str) -> None:
        from ...services.ai_client import parse_rules_payload

        self._restore_generate_button()
        rules, problems = parse_rules_payload(text, self.project)
        self._set_problems("\n".join(problems), error=bool(problems and not rules))
        self._rebuild_results(rules)

    def _set_problems(self, text: str, error: bool = False) -> None:
        self._problems_label.setText(text)
        self._problems_label.setVisible(bool(text))
        self._problems_label.setStyleSheet(
            "color: %s;" % (Color.DANGER if error else Color.WARNING)
        )

    # ---------------------------------------------------------------- 结果区
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
        self._add_button.setEnabled(bool(self._drafts))

    def _build_rule_row(self, index: int) -> "tuple[QWidget, dict]":
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        checkbox = QCheckBox(row)
        checkbox.setChecked(True)
        checkbox.setToolTip("勾选的规则才会被添加")
        layout.addWidget(checkbox)

        desc = QLabel(self._describe(index), row)
        desc.setWordWrap(True)
        layout.addWidget(desc, 1)

        edit = button("编辑", lambda _=False, i=index: self._edit_rule(i), "Ghost",
                      "微调这条规则的参数")
        layout.addWidget(edit)
        return row, {"checkbox": checkbox, "desc": desc}

    def _describe(self, index: int) -> str:
        from ...models.rule import describe_rule

        return describe_rule(
            self._drafts[index], self.project.student_name, self.project.selection_name
        )

    def _edit_rule(self, index: int) -> None:
        dialog = RuleEditDialog(self.project, self._drafts[index], self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_rule is None:
            return
        self._drafts[index] = dialog.result_rule
        self._rows[index]["desc"].setText(self._describe(index))

    # ---------------------------------------------------------------- 结果
    def accept(self) -> None:  # noqa: D102 - Qt 命名
        checked = [
            rule for rule, row in zip(self._drafts, self._rows)
            if row["checkbox"].isChecked()
        ]
        if not checked:
            QMessageBox.information(self, "提示", "先勾选要添加的规则。")
            return
        self.result_rules = checked
        self.solve_after = self._solve_check.isChecked()
        super().accept()

    def reject(self) -> None:  # noqa: D102 - Qt 命名
        self._abort_request()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._abort_request()
        super().closeEvent(event)

    def _abort_request(self) -> None:
        if self._client is not None:
            self._client.abort()
