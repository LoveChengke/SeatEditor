"""JSON 项目存取（``.seatproj``）。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .. import config
from ..models.project import Project


class ProjectStoreError(Exception):
    """项目文件读写失败。"""


CURRENT_VERSION = "1.0"
SUPPORTED_VERSIONS = ("1.0",)


def dumps(project: Project, indent: int = 2) -> str:
    return json.dumps(project.to_dict(), ensure_ascii=False, indent=indent)


def loads(text: str) -> Project:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectStoreError("项目文件不是合法的 JSON：%s" % exc) from exc
    if not isinstance(data, Mapping):
        raise ProjectStoreError("项目文件格式错误：根节点应为对象")
    return _from_data(data)


def _from_data(data: Mapping[str, Any]) -> Project:
    data = _migrate(data)
    try:
        return Project.from_dict(data)
    except Exception as exc:  # 统一转成可读错误
        raise ProjectStoreError("项目内容解析失败：%s" % exc) from exc


def _migrate(data: Mapping[str, Any]) -> Dict[str, Any]:
    """版本兼容处理；未知的更高版本给出明确错误。"""
    version = str(data.get("version") or CURRENT_VERSION)
    major = version.split(".")[0]
    if major not in {v.split(".")[0] for v in SUPPORTED_VERSIONS}:
        raise ProjectStoreError(
            "项目文件版本（%s）高于当前程序支持的版本（%s），请升级程序" % (version, CURRENT_VERSION)
        )
    result = dict(data)
    result["version"] = CURRENT_VERSION
    # 兼容：早期版本把空置座位放在 layout.seats 里
    layout = result.get("layout")
    if isinstance(layout, Mapping) and "disabled_seats" not in layout:
        layout = dict(layout)
        layout["disabled_seats"] = []
        result["layout"] = layout
    return result


class JsonProjectStore:
    """项目文件读写。所有写入都是“先写临时文件再替换”，避免写坏原文件。"""

    @staticmethod
    def save(project: Project, path: str | Path) -> Path:
        target = Path(path)
        if target.suffix.lower() != config.PROJECT_EXT:
            target = target.with_suffix(config.PROJECT_EXT)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = dumps(project)
        JsonProjectStore._atomic_write(target, payload)
        project.path = str(target)
        project.mark_clean()
        return target

    @staticmethod
    def load(path: str | Path) -> Project:
        source = Path(path)
        if not source.exists():
            raise ProjectStoreError("文件不存在：%s" % source)
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProjectStoreError("无法读取文件：%s" % exc) from exc
        project = loads(text)
        project.path = str(source)
        project.mark_clean()
        return project

    @staticmethod
    def _atomic_write(target: Path, payload: str) -> None:
        """先写同目录的临时文件再 ``os.replace``，避免写到一半留下半个项目文件。"""
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
            )
        except OSError as exc:
            raise ProjectStoreError("写入文件失败：%s" % exc) from exc

        try:
            # mkstemp 交出的 fd 要自己负责关闭：fdopen 成功后由 with 关掉，
            # fdopen 自己失败时在这里关——不能只写 `with os.fdopen(fd, ...)`，
            # 因为 with 是先求值再进入，fdopen 抛异常时 with 根本不会执行。
            try:
                handle = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            JsonProjectStore._remove_quietly(tmp_path)
            raise ProjectStoreError("写入文件失败：%s" % exc) from exc

        try:
            os.replace(tmp_path, target)
        except OSError as exc:
            JsonProjectStore._remove_quietly(tmp_path)
            raise ProjectStoreError("保存文件失败：%s" % exc) from exc

    @staticmethod
    def _remove_quietly(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    # 自动保存
    @staticmethod
    def autosave(project: Project) -> Optional[Path]:
        """崩溃恢复用的临时保存；失败时静默返回 None。"""
        try:
            config.AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
            payload = dumps(project)
            JsonProjectStore._atomic_write(config.AUTOSAVE_FILE, payload)
            return config.AUTOSAVE_FILE
        except Exception:  # 自动保存不应打断用户操作
            return None

    @staticmethod
    def has_autosave() -> bool:
        try:
            return config.AUTOSAVE_FILE.exists() and config.AUTOSAVE_FILE.stat().st_size > 0
        except OSError:
            return False

    @staticmethod
    def autosave_info() -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "exists": False, "time": "", "mtime": 0.0, "path": str(config.AUTOSAVE_FILE)
        }
        try:
            if config.AUTOSAVE_FILE.exists():
                mtime = config.AUTOSAVE_FILE.stat().st_mtime
                info["exists"] = True
                info["mtime"] = mtime
                info["time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        except OSError:
            pass
        return info

    @staticmethod
    def load_autosave() -> Optional[Project]:
        if not JsonProjectStore.has_autosave():
            return None
        try:
            project = loads(config.AUTOSAVE_FILE.read_text(encoding="utf-8"))
        except (OSError, ProjectStoreError):
            return None
        project.path = ""
        return project

    @staticmethod
    def clear_autosave() -> None:
        try:
            if config.AUTOSAVE_FILE.exists():
                config.AUTOSAVE_FILE.unlink()
        except OSError:
            pass
