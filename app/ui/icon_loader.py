"""工具栏 / 菜单图标的着色：把 resources/icons 里的线性 SVG 按当前主题重画。

这些 SVG 的描边色是写死在文件里的（``#C9CED6``，当初只考虑了深色底），
浅色主题下它们贴在近白的工具栏上几乎看不见——按钮就成了「文字在、图标糊」。
与其存两份 SVG（切主题时还得逐个换 QIcon），不如读进 SVG 文本、把描边色替换成
当前主题的 ``ICON_MUTED``，用 ``QSvgRenderer`` 直接渲染成 QPixmap 给 QIcon 用。

缓存按 (图标名, 颜色, 尺寸) 建；因为颜色进缓存键，切换主题后自然拿到新颜色。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from .. import config

STROKE_PATTERN = re.compile(r'stroke="#[0-9A-Fa-f]{3,6}"')

_CACHE: Dict[Tuple[str, str, int], QIcon] = {}


def _recolor(svg_text: str, color: str) -> bytes:
    """把 SVG 里所有写死的描边色换成 ``color``（只动描边，不动 fill="none"）。"""
    return STROKE_PATTERN.sub('stroke="%s"' % color, svg_text).encode("utf-8")


def themed_icon(path: Path, color: str, size: int = 16) -> QIcon:
    """按主题色渲染一张 SVG 图标；文件缺失或解析失败时返回空 QIcon。

    返回空图标而不是抛异常：图标只是装饰，缺一张不该拦住启动。
    """
    key = (str(path), str(color), int(size))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    icon = QIcon()
    try:
        data = _recolor(path.read_text(encoding="utf-8"), color)
        renderer = QSvgRenderer(data)
        if renderer.isValid():
            pixmap = QPixmap(QSize(size, size))
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            icon = QIcon(pixmap)
    except (OSError, ValueError):
        icon = QIcon()
    _CACHE[key] = icon
    return icon


def action_icon(name: str, size: int = 16) -> QIcon:
    """动作（菜单 / 工具栏）图标：优先用自绘图标集，其次用 resources/icons 的 SVG。

    自绘集（``widgets/icons.py``）和活动栏、面板头共用同一套形状，
    所以菜单里的「侧边栏 / AI 助手 / 底部面板」和左边那列图标长得一样；
    「打开 / 保存 / 导入」这类只有 SVG 的仍走文件（按主题重新着色）。
    两种来源都按当前主题色渲染，切换主题后重新取即可。
    """
    from .widgets import icons

    color = icon_color()
    if name in icons.GLYPHS:
        key = ("glyph", name, color, int(size))
        cached = _CACHE.get(key)
        if cached is None:
            cached = QIcon(icons.glyph_color(name, color, int(size)))
            _CACHE[key] = cached
        return cached
    return themed_icon(config.ICONS_DIR / ("%s.svg" % name), color, size)


def icon_color(dark: Optional[bool] = None) -> str:
    """当前（或指定）主题下工具栏图标的颜色。"""
    from .style import theme

    if dark is None:
        dark = theme.is_dark()
    return theme.DARK_PALETTE["ICON_MUTED"] if dark else theme.LIGHT_PALETTE["ICON_MUTED"]
