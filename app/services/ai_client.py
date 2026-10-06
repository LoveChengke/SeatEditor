"""AI 大白话排位：提示词构建、响应解析与 OpenAI 兼容 HTTP 客户端。

分两半：
- 纯函数（build_system_prompt / parse_rules_payload）不依赖 Qt，可脱离界面单测
  ——LLM 的回复是不可信输入，解析与清洗必须能独立验证。
- AIChatClient(QObject) 用 PyQt6 自带的 QtNetwork 发请求：零新依赖、信号槽异步
  不卡界面。只负责把「消息列表」变成「回复文本」，规则解析交给纯函数。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtNetwork import (
    QNetworkAccessManager, QNetworkReply, QNetworkRequest,
)

from ..models.rule import (
    F_ATTR, F_BOOL, F_CHOICE, F_INT, F_SEAT, F_SELECTION, F_STUDENT, F_TAG,
    HARD, ParamField, RULE_SPECS, SOFT, Rule, make_rule_id,
)

# LLM 单次回复上限；规则 JSON 很短，2048 足够，避免个别服务商默认值过小被截断
_MAX_TOKENS = 2048
# 网络超时（毫秒）：本地 Ollama 首次加载模型可能较慢，放宽到 60 秒
_TIMEOUT_MS = 60_000


# ---------------------------------------------------------------- 提示词构建
def _format_field(field: ParamField) -> str:
    """把一个参数字段写成 LLM 能读懂的一行说明。"""
    parts = [field.label]
    if field.kind == F_CHOICE:
        options = " / ".join("%s=%s" % (label, value) for value, label in field.choices)
        parts.append("取值：%s" % options)
    elif field.kind == F_INT:
        parts.append("整数 %d~%d" % (field.minimum, field.maximum))
    elif field.kind == F_TAG:
        parts.append("填已有标签名")
    elif field.kind == F_STUDENT:
        parts.append("填学号")
    elif field.kind == F_SELECTION:
        parts.append("填区域 id")
    elif field.kind == F_ATTR:
        parts.append("填数值属性名")
    elif field.kind == F_SEAT:
        parts.append("填座位 key（组-排-列，如 1-1-1）")
    elif field.kind == F_BOOL:
        parts.append("true / false")
    if field.default not in (None, ""):
        parts.append("默认 %s" % field.default)
    if field.optional:
        parts.append("可不填")
    return "%s: %s" % (field.key, "，".join(parts))


def _rule_catalog() -> str:
    """从 RULE_SPECS 自动生成规则清单——新增规则种类会自动进入提示词。"""
    lines: List[str] = []
    for spec in RULE_SPECS.values():
        kind_type = "必须满足" if spec.type == HARD else "尽量满足"
        line = "- %s｜%s（%s）：%s" % (spec.kind, spec.label, kind_type, spec.description)
        if spec.fields:
            line += " 参数：" + "；".join(_format_field(f) for f in spec.fields)
        else:
            line += " 无参数"
        if spec.has_weight:
            line += "（weight：0~99 的重要程度，默认 %g）" % spec.default_weight
        lines.append(line)
    return "\n".join(lines)


def build_project_brief(project) -> str:
    """把班级信息写成提示词里的一段，供 AI 取参数值。"""
    lines: List[str] = []
    if project.students:
        students = "、".join("%s(%s)" % (s.name, s.sid) for s in project.students)
        lines.append("学生（姓名(学号)）：%s" % students)
    tags = project.tag_names()
    if tags:
        lines.append("已有标签：%s" % "、".join(tags))
    if project.selections:
        sels = "、".join("%s(id=%s)" % (s.name, s.id) for s in project.selections)
        lines.append("已有区域：%s" % sels)
    layout = project.layout
    group_names = "、".join(
        layout.group_name(i) or "第 %d 组" % (i + 1) for i in range(len(layout.groups))
    )
    lines.append(
        "教室：%d 组 × %d 排 × %d 列（组名：%s）"
        % (len(layout.groups), layout.groups[0].rows if layout.groups else 0,
           layout.groups[0].cols if layout.groups else 0, group_names)
    )
    return "\n".join(lines)


def build_system_prompt(project) -> str:
    return (
        "你是「教室座位编排」程序的排座规则助手。老师会用大白话说要求，"
        "你的任务是把每条要求转换成程序可执行的排座规则，输出 JSON。\n\n"
        "可用规则种类（kind｜名称｜类型：说明）：\n%s\n\n"
        "班级信息：\n%s\n\n"
        "输出格式（严格遵守，除 JSON 外一个字都不要输出）：\n"
        '{"rules": [{"kind": "规则种类", "params": {"参数名": "值"}, "weight": 数字}]}\n'
        "weight 只给尽量满足类规则，可省略。\n\n"
        "要求：\n"
        "1. 老师的每条独立要求对应一条规则；没提到的不编造。\n"
        "2. 参数值必须取自班级信息：tag 用已有标签名、sid 用学号、selection 用区域 id。"
        "班级里没有的标签/学生/区域不要输出。\n"
        "3. 描述模糊时选最接近的规则种类，拿不准就用尽量满足类。\n"
        "4. 只输出 JSON，不要 markdown 代码块标记，不要解释。"
    ) % (_rule_catalog(), build_project_brief(project))


# ---------------------------------------------------------------- 响应解析
def _extract_json(text: str) -> Optional[Any]:
    """从 LLM 回复里抠出 JSON：先整段解析，失败再剥围栏、按最先出现的括号抠。"""
    if not text:
        return None
    cleaned = text.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 剥 ```json ... ``` 围栏
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    # 裸数组里也含 "{"，必须按「最先出现的括号」决定抠哪一种，否则
    # [{"kind":...}] 会被抠成第一个元素的对象
    pairs = [("{", "}"), ("[", "]")]
    pairs.sort(key=lambda pair: (cleaned.find(pair[0]) == -1, cleaned.find(pair[0])))
    for opener, closer in pairs:
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _normalize_items(payload: Any) -> List[Dict[str, Any]]:
    """兼容 {"rules": [...]} 和裸 [...] 两种返回。"""
    if isinstance(payload, dict):
        items = payload.get("rules")
        if isinstance(items, list):
            return [it for it in items if isinstance(it, dict)]
        return []
    if isinstance(payload, list):
        return [it for it in payload if isinstance(it, dict)]
    return []


def _match_student(value: str, project) -> Optional[str]:
    """学号直取；AI 有时会给姓名，唯一匹配时换算成学号。"""
    students = project.students
    for s in students:
        if s.sid == value:
            return value
    hits = [s.sid for s in students if s.name == value]
    return hits[0] if len(hits) == 1 else None


def _match_selection(value: str, project) -> Optional[str]:
    """区域 id 直取；按名称唯一匹配时换算成 id。"""
    for sel in project.selections:
        if sel.id == value:
            return value
    hits = [sel.id for sel in project.selections if sel.name == value]
    return hits[0] if len(hits) == 1 else None


def parse_rules_payload(
    text: str, project
) -> Tuple[List[Rule], List[str]]:
    """把 LLM 回复解析成规则列表。

    返回 ``(rules, problems)``：rules 是已通过 ``Rule`` 构造清洗的草稿规则
    （不写进 project，由调用方在用户确认后落库）；problems 是逐条的中文
    说明（解析失败 / 未识别的 kind / 校验未过 / 重复 / 引用了不存在的东西）。
    """
    problems: List[str] = []
    payload = _extract_json(text)
    if payload is None:
        return [], ["AI 没有返回可识别的 JSON，换个说法再试一次，或到「AI 设置」里换模型。"]
    items = _normalize_items(payload)
    if not items:
        return [], ["AI 返回了空的规则列表。如果它没理解要求，换个说法再试一次。"]

    existing = {
        (r.kind, tuple(sorted((k, str(v)) for k, v in r.params.items())))
        for r in project.rules
    }
    tag_names = set(project.tag_names())
    rules: List[Rule] = []
    seen = set()

    for index, item in enumerate(items, start=1):
        kind = str(item.get("kind") or "").strip()
        spec = RULE_SPECS.get(kind)
        if spec is None:
            problems.append("第 %d 条：无法识别的规则类型「%s」，已跳过" % (index, kind or "(空)"))
            continue
        raw_params = item.get("params")
        raw_params = dict(raw_params) if isinstance(raw_params, dict) else {}
        params: Dict[str, Any] = {}
        fields = {f.key: f for f in spec.fields}
        for key, value in raw_params.items():
            if key not in fields:
                continue   # 多余/拼错的参数直接丢弃，Rule 构造器也会忽略
            if value in (None, ""):
                continue
            field = fields[key]
            if field.kind == F_STUDENT:
                sid = _match_student(str(value), project)
                if sid is None:
                    problems.append(
                        "第 %d 条：学生「%s」不在名单里，该参数已忽略" % (index, value)
                    )
                    continue
                value = sid
            elif field.kind == F_SELECTION:
                sel_id = _match_selection(str(value), project)
                if sel_id is None:
                    problems.append(
                        "第 %d 条：区域「%s」不存在，该参数已忽略" % (index, value)
                    )
                    continue
                value = sel_id
            elif field.kind == F_TAG and str(value) not in tag_names:
                problems.append(
                    "第 %d 条：班里还没有「%s」这个标签——规则会先生成，"
                    "但要去「标签管理」里建一个同名标签它才会起作用" % (index, value)
                )
            params[key] = value
        try:
            # 与 make_rule 同构：id/type 显式给，params 走 __post_init__ 的清洗管道
            rule = Rule(make_rule_id(), spec.type, kind, params, True, spec.default_weight)
        except Exception as exc:   # 构造器兜底失败，绝不因一条坏数据中断整批
            problems.append("第 %d 条：规则构造失败（%s）" % (index, exc))
            continue
        for message in rule.validate():
            problems.append("第 %d 条（%s）：%s" % (index, spec.label, message))
        if spec.fields and not any(
            v is not None and str(v) != "" for v in rule.params.values()
        ):
            # 有参数字段的规则一个值都没填上：加进去也不生效，不如明说
            problems.append(
                "第 %d 条：%s 缺少参数（比如没写清是谁/哪个标签），已跳过" % (index, spec.label)
            )
            continue
        if rule.validate():
            continue   # 校验未过的规则不进预览，原因已写进 problems
        signature = (rule.kind, tuple(sorted((k, str(v)) for k, v in rule.params.items())))
        if signature in existing or signature in seen:
            problems.append("第 %d 条：%s 与已有规则重复，已跳过" % (index, spec.label))
            continue
        seen.add(signature)
        if spec.has_weight:
            weight = item.get("weight")
            if isinstance(weight, (int, float)) and weight > 0:
                rule.weight = float(weight)
        rules.append(rule)
    return rules, problems


# ---------------------------------------------------------------- HTTP 客户端
def parse_models_payload(text: str) -> List[str]:
    """解析 GET /models 的响应，返回模型 id 列表（OpenAI 兼容：{"data":[{"id":..}]}）。"""
    payload = _extract_json(text)
    if isinstance(payload, dict):
        payload = payload.get("data")
    if not isinstance(payload, list):
        return []
    ids: List[str] = []
    for item in payload:
        if isinstance(item, dict):
            model_id = item.get("id") or item.get("model") or item.get("name")
        elif isinstance(item, str):
            model_id = item
        else:
            model_id = None
        if model_id and str(model_id) not in ids:
            ids.append(str(model_id))
    return ids


class AIModelsClient(QObject):
    """拉取服务商可用模型列表（GET {endpoint}/models），信号返回 id 列表。"""

    finished = pyqtSignal(list)   # 模型 id 列表（可能为空）
    failed = pyqtSignal(str)

    def __init__(self, endpoint: str, api_key: str,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._url = endpoint.rstrip("/") + "/models"
        self._api_key = str(api_key or "").strip()
        self._manager = QNetworkAccessManager(self)
        self._manager.setTransferTimeout(_TIMEOUT_MS)
        self._reply: Optional[QNetworkReply] = None

    def send(self) -> None:
        self.abort()
        request = QNetworkRequest(QUrl(self._url))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        if self._api_key:
            request.setRawHeader(b"Authorization", ("Bearer " + self._api_key).encode("utf-8"))
        self._reply = self._manager.get(request)
        self._reply.finished.connect(self._on_finished)

    def abort(self) -> None:
        if self._reply is not None:
            self._reply.finished.disconnect(self._on_finished)
            self._reply.abort()
            self._reply = None

    def _on_finished(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self._reply = None
        error = reply.error()
        try:
            raw = bytes(reply.readAll())
        finally:
            reply.deleteLater()
        if error == QNetworkReply.NetworkError.OperationCanceledError:
            return
        if error != QNetworkReply.NetworkError.NoError:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if error == QNetworkReply.NetworkError.TimeoutError:
                message = "获取模型列表超时（%d 秒）。" % (_TIMEOUT_MS // 1000)
            elif status in (401, 403):
                message = "服务端返回 %s：API Key 可能不对或没有权限。" % status
            elif status == 404:
                message = "该服务商不支持 /models 接口，请手动填写模型名称。"
            else:
                message = "获取模型列表失败：%s" % reply.errorString()
            self.failed.emit(message)
            return
        models = parse_models_payload(raw.decode("utf-8", "replace"))
        self.finished.emit(models)


class AIChatClient(QObject):
    """OpenAI 兼容 chat/completions 的最小客户端（QtNetwork 异步）。

    用法：构造后 ``send(system_prompt, user_text)``，结果经 ``finished`` /
    ``failed`` 信号返回；``abort()`` 取消在途请求。这个类不弹任何界面。
    """

    finished = pyqtSignal(str)   # 回复正文
    failed = pyqtSignal(str)     # 中文错误说明

    def __init__(self, endpoint: str, api_key: str, model: str,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._url = endpoint.rstrip("/") + "/chat/completions"
        self._api_key = str(api_key or "").strip()
        self._model = str(model or "").strip()
        self._manager = QNetworkAccessManager(self)
        self._manager.setTransferTimeout(_TIMEOUT_MS)
        self._reply: Optional[QNetworkReply] = None

    def send(self, system_prompt: str, user_text: str) -> None:
        self.abort()
        body = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.2,
            "stream": False,
            "max_tokens": _MAX_TOKENS,
        }).encode("utf-8")
        request = QNetworkRequest(QUrl(self._url))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        if self._api_key:
            request.setRawHeader(b"Authorization", ("Bearer " + self._api_key).encode("utf-8"))
        self._reply = self._manager.post(request, body)
        self._reply.finished.connect(self._on_finished)

    def abort(self) -> None:
        if self._reply is not None:
            self._reply.finished.disconnect(self._on_finished)
            self._reply.abort()
            self._reply = None

    def _on_finished(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self._reply = None
        error = reply.error()
        try:
            raw = bytes(reply.readAll())
        finally:
            reply.deleteLater()
        if error == QNetworkReply.NetworkError.OperationCanceledError:
            return   # 主动取消：不发失败信号，由调用方自己处理界面状态
        if error != QNetworkReply.NetworkError.NoError:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            detail = raw.decode("utf-8", "replace")[:200]
            if error == QNetworkReply.NetworkError.TimeoutError:
                message = "请求超时（%d 秒）。网络不稳或服务端太慢，可重试或换模型。" % (_TIMEOUT_MS // 1000)
            elif status == 401 or status == 403:
                message = "服务端返回 %s：API Key 可能不对或没有权限。" % status
            elif status == 404:
                message = "服务端返回 404：接口地址可能写错了（应填到 /v1 或 /v4 这一级）。"
            elif status is not None and status >= 400:
                message = "服务端返回 %s：%s" % (status, detail or "无详情")
            else:
                message = "网络连接失败：%s。请检查网络与接口地址。" % reply.errorString()
            self.failed.emit(message)
            return
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
            content = data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            self.failed.emit("服务端返回了无法解析的响应格式。请确认接口是 OpenAI 兼容的 chat/completions。")
            return
        self.finished.emit(str(content))


