"""AI 设置对话框：配置 OpenAI 兼容的大模型接口（地址 / 模型 / API Key）。

按 dialogs 契约只收集输入不改设置：确认后把结果挂在 ``result_config``
（ ``(endpoint, api_key, model)`` 三元组），由调用方写入 QSettings。
「测试连接」发一个极小的真实请求，帮助老师确认配置能用。
"""

from __future__ import annotations

from typing import Optional, Tuple

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

from ...config import AI_PRESETS
from ..common import button, polish_dialog, hline
from ..style.theme import Color


class AISettingsDialog(QDialog):
    """AI 服务连接设置。``result_config`` 仅在确认后有效。"""

    def __init__(self, endpoint: str = "", api_key: str = "", model: str = "",
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI 设置")
        self.result_config: Optional[Tuple[str, str, str]] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(8)

        title = QLabel("AI 设置")
        title.setObjectName("PanelTitle")
        root.addWidget(title)
        root.addWidget(hline())

        hint = QLabel("填一份「OpenAI 兼容」的接口信息即可接入对应的大模型服务。"
                      "API Key 只保存在这台电脑的系统设置里，不会随项目文件分享。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(6)

        self._preset_combo = QComboBox()
        for name, _endpoint, _model in AI_PRESETS:
            self._preset_combo.addItem(name)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow("服务商", self._preset_combo)

        self._endpoint_edit = QLineEdit(endpoint)
        self._endpoint_edit.setPlaceholderText("https://api.example.com/v1")
        form.addRow("接口地址", self._endpoint_edit)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.lineEdit().setPlaceholderText("填模型名，或点「获取模型列表」自动拉取")
        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        model_row.addWidget(self._model_combo, 1)
        self._fetch_button = button("获取模型列表", self._on_fetch_models)
        model_row.addWidget(self._fetch_button)
        form.addRow("模型名称", model_row)

        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        self._key_edit = QLineEdit(api_key)
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("服务商官网申请，形如 sk-…")
        key_row.addWidget(self._key_edit, 1)
        self._show_key = QCheckBox("显示")
        self._show_key.toggled.connect(self._on_show_key)
        key_row.addWidget(self._show_key)
        form.addRow("API Key", key_row)

        root.addLayout(form)

        self._status_label = QLabel("")
        self._status_label.setObjectName("Hint")
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        actions = QHBoxLayout()
        self._test_button = button("测试连接", self._on_test)
        actions.addWidget(self._test_button)
        actions.addStretch(1)
        ok = QPushButton("保存")
        ok.setObjectName("Primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        actions.addWidget(ok)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        root.addLayout(actions)

        # 打开时按当前值反推预设（都对不上就落在「自定义…」）
        self._select_preset_for(endpoint, model)
        self._client = None
        self._models_client = None
        polish_dialog(self)
        self.setMinimumWidth(460)

    # 界面联动
    def _on_preset_changed(self, index: int) -> None:
        if index < 0 or index >= len(AI_PRESETS):
            return
        _name, endpoint, model = AI_PRESETS[index]
        if endpoint:
            self._endpoint_edit.setText(endpoint)
        if model:
            self._model_combo.setCurrentText(model)

    def _select_preset_for(self, endpoint: str, model: str) -> None:
        for index, (_name, p_endpoint, _p_model) in enumerate(AI_PRESETS):
            if endpoint and endpoint.rstrip("/") == p_endpoint.rstrip("/"):
                self._preset_combo.setCurrentIndex(index)
                return
        self._preset_combo.setCurrentIndex(len(AI_PRESETS) - 1)   # 自定义…

    def _on_show_key(self, checked: bool) -> None:
        self._key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    # 获取模型列表
    def _on_fetch_models(self) -> None:
        from ...services.ai_client import AIModelsClient

        endpoint = self._endpoint_edit.text().strip()
        if not endpoint:
            self._set_status("请先填接口地址。", error=True)
            return
        self._fetch_button.setEnabled(False)
        self._set_status("正在从 %s 获取模型列表…" % endpoint, error=False)
        if self._models_client is not None:
            self._models_client.deleteLater()
        self._models_client = AIModelsClient(endpoint, self._key_edit.text().strip(), self)
        self._models_client.finished.connect(self._on_models_fetched)
        self._models_client.failed.connect(self._on_models_failed)
        self._models_client.send()

    def _on_models_fetched(self, models: list) -> None:
        self._fetch_button.setEnabled(True)
        if not models:
            self._set_status("服务商没有返回模型列表，请手动填写模型名称。", error=True)
            return
        current = self._model_combo.currentText().strip()
        self._model_combo.clear()
        self._model_combo.addItems(models)
        if current:
            self._model_combo.setCurrentText(current)
        self._set_status("获取到 %d 个模型，下拉选择即可（也可手动输入）。" % len(models), error=False)

    def _on_models_failed(self, message: str) -> None:
        self._fetch_button.setEnabled(True)
        self._set_status(message, error=True)

    def _current_config(self) -> Tuple[str, str, str]:
        return (
            self._endpoint_edit.text().strip(),
            self._key_edit.text().strip(),
            self._model_combo.currentText().strip(),
        )

    # 测试连接
    def _on_test(self) -> None:
        from ...services.ai_client import AIChatClient

        endpoint, api_key, model = self._current_config()
        if not endpoint or not model:
            self._set_status("请先填接口地址和模型名称。", error=True)
            return
        self._test_button.setEnabled(False)
        self._set_status("正在连接 %s …" % endpoint, error=False)
        if self._client is not None:
            self._client.deleteLater()
        self._client = AIChatClient(endpoint, api_key, model, self)
        self._client.finished.connect(
            lambda _text: self._on_test_done(True, "连接成功，服务返回正常。"))
        self._client.failed.connect(lambda message: self._on_test_done(False, message))
        self._client.send("你是一个连通性测试端点。收到任何消息都只回复：OK", "ping")

    def _on_test_done(self, ok: bool, message: str) -> None:
        self._test_button.setEnabled(True)
        self._set_status(message, error=not ok)

    def _set_status(self, text: str, error: bool) -> None:
        self._status_label.setText(text)
        self._status_label.setStyleSheet(
            "color: %s;" % (Color.DANGER if error else Color.SUCCESS)
        )

    # 结果
    def accept(self) -> None:  # noqa: D102 - Qt 命名
        endpoint, api_key, model = self._current_config()
        if not endpoint:
            self._set_status("接口地址不能为空。", error=True)
            return
        if not model:
            self._set_status("模型名称不能为空。", error=True)
            return
        self.result_config = (endpoint, api_key, model)
        super().accept()
