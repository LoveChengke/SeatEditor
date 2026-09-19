"""UI 层。"""

from __future__ import annotations


def load_stylesheet() -> str:
    """读取全局 QSS（找不到时返回空串，不阻塞启动）。"""
    from pathlib import Path

    path = Path(__file__).resolve().parent / "style" / "app.qss"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
