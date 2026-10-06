"""UI 层。"""

from __future__ import annotations

from typing import Dict, Optional

ASSET_PLACEHOLDER = "@ASSET_DIR@"


def load_stylesheet(palette: Optional[Dict[str, str]] = None) -> str:
    """读取全局 QSS 并按色板填充颜色令牌（找不到文件时返回空串，不阻塞启动）。

    QSS 是以字符串方式交给 Qt 的，里面的 ``url(...)`` 相对路径会按**进程工作
    目录**解析——从别处启动程序时图标就会丢。所以样式表里写占位符
    ``@ASSET_DIR@``（替换成 assets 目录绝对路径）和 ``@TOKEN@``（替换成当前
    主题色板里的色值，黑夜 / 白天共用同一份样式表）。
    ``palette`` 缺省时用当前激活的主题色板。
    """
    from pathlib import Path

    if palette is None:
        from .style import theme

        palette = theme.palette()
    style_dir = Path(__file__).resolve().parent / "style"
    try:
        text = (style_dir / "app.qss").read_text(encoding="utf-8")
    except OSError:
        return ""
    assets = (style_dir / "assets").as_posix()
    text = text.replace(ASSET_PLACEHOLDER, assets)
    for token, value in palette.items():
        text = text.replace("@%s@" % token, value)
    return text

def install_app_icon(app) -> bool:
    """给应用装图标：窗口、任务栏、对话框都跟着它。

    Windows 上还要显式设置 AppUserModelID：不设的话任务栏会把这个程序归到
    ``python.exe`` 名下，显示 Python 的图标，而且跟别的 Python 程序挤成一组
    （哪怕 exe 已经换了图标也没用）。AppUserModelID 要在窗口显示之前设。
    """
    import sys

    from .. import config

    ok = False
    if config.APP_ICON.exists():
        from PyQt6.QtGui import QIcon

        icon = QIcon(str(config.APP_ICON))
        if not icon.isNull():
            app.setWindowIcon(icon)
            ok = True
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(config.APP_ID)
        except Exception:
            pass          # 设不上只是任务栏图标不好看，不该拦住启动
    return ok
