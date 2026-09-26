"""UI 层。"""

from __future__ import annotations

ASSET_PLACEHOLDER = "@ASSET_DIR@"


def load_stylesheet() -> str:
    """读取全局 QSS（找不到时返回空串，不阻塞启动）。

    QSS 是以字符串方式交给 Qt 的，里面的 ``url(...)`` 相对路径会按**进程工作
    目录**解析——从别处启动程序时图标就会丢。所以样式表里写占位符
    ``@ASSET_DIR@``，这里替换成 assets 目录的绝对路径（正斜杠，Windows 也认）。
    """
    from pathlib import Path

    style_dir = Path(__file__).resolve().parent / "style"
    try:
        text = (style_dir / "app.qss").read_text(encoding="utf-8")
    except OSError:
        return ""
    assets = (style_dir / "assets").as_posix()
    return text.replace(ASSET_PLACEHOLDER, assets)
