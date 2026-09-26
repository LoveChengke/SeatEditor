"""设计规范常量：色彩 / 字体 / 尺寸（对应 PRD 第三章）。"""

from __future__ import annotations

import sys
from typing import Dict, Tuple

from ...config import TAG_PALETTE   # 单一真源，避免 models/ui 循环依赖


class Color:
    """色彩系统（深色 + 亮蓝强调色）。

    取值与 ``app/ui/style/app.qss`` 一一对应：改色时两处都要改。
    分层约定：``BG_APP`` 最底 → ``BG_PANEL`` 侧栏 → ``BG_CARD`` 卡片 →
    ``BG_SUBTLE`` 输入框 / ``BG_HOVER`` 悬停，越靠上层越亮。
    """

    # 品牌色
    PRIMARY = "#3D9BF5"
    PRIMARY_HOVER = "#5CB0FF"
    PRIMARY_PRESSED = "#2A7FD0"
    PRIMARY_LIGHT = "#1D3550"        # 品牌色淡底（选中项 / 勾选态）
    PRIMARY_SOFT = "#213347"         # 品牌色更淡一层（悬浮）
    TEXT_ON_ACCENT = "#0B1622"       # 亮底上的深字，对比度高于白字

    # 中性色
    BG_APP = "#131316"
    BG_PANEL = "#1A1A1E"
    BG_CARD = "#232329"
    BG_SUBTLE = "#2A2A31"
    BG_HOVER = "#32323A"
    BORDER = "#33333B"
    BORDER_LIGHT = "#26262C"
    BORDER_STRONG = "#45454F"

    # 文字
    TEXT_PRIMARY = "#ECEDEF"
    TEXT_SECONDARY = "#9BA1AB"
    TEXT_DISABLED = "#6A7079"

    # 语义色
    DANGER = "#FF6B6B"
    DANGER_BG = "#3A2327"
    SUCCESS = "#3DD68C"
    WARNING = "#F5A524"
    PODIUM = "#2C3C55"

    # 座位状态
    SEAT_DEFAULT = "#27272D"
    SEAT_HOVER = "#2F3B49"
    SEAT_SELECTED = "#1E3B5C"
    SEAT_CONFLICT = "#3C2529"
    SEAT_DISABLED = "#1B1B20"
    SEAT_EMPTY_TXT = "#666C76"

    # 其他
    DASHED = "#3E3E48"
    TAG_UNKNOWN = "#6A7079"
    OVERLAY = "#1F1F24"


class CardSize:
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class PrintColor:
    """导出 PNG / 打印用的浅色配色（只覆盖座位表用到的项）。

    屏幕上是深色主题，但座位表图片常常要打印，深底会糊成一片还费墨。
    导出时用 :func:`set_print_mode` 临时把这些色值换掉，导出完立刻还原。
    """

    SEAT_DEFAULT = "#FFFFFF"
    SEAT_HOVER = "#EEF4FF"
    SEAT_SELECTED = "#DCE8FF"
    SEAT_CONFLICT = "#FFECEC"
    SEAT_DISABLED = "#F2F4F7"

    TEXT_PRIMARY = "#1F2430"
    TEXT_SECONDARY = "#6B7280"
    TEXT_DISABLED = "#A8B0BD"

    BORDER = "#D9DEE7"
    DASHED = "#C7CDD6"
    PRIMARY = "#2F6BFF"
    DANGER = "#E5484D"
    TAG_UNKNOWN = "#A8B0BD"


# 打印模式下会被临时替换的色值（其余色值屏幕内外一致）
_PRINT_SWAP_KEYS = (
    "SEAT_DEFAULT", "SEAT_HOVER", "SEAT_SELECTED", "SEAT_CONFLICT", "SEAT_DISABLED",
    "TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_DISABLED",
    "BORDER", "DASHED", "PRIMARY", "DANGER", "TAG_UNKNOWN",
)

_SCREEN_COLOR_SNAPSHOT: Dict[str, str] = {}


def set_print_mode(flag: bool) -> None:
    """切换「导出 / 打印」配色；可重复调用，幂等。"""
    global _SCREEN_COLOR_SNAPSHOT
    if flag and not _SCREEN_COLOR_SNAPSHOT:
        _SCREEN_COLOR_SNAPSHOT = {key: getattr(Color, key) for key in _PRINT_SWAP_KEYS}
        for key in _PRINT_SWAP_KEYS:
            setattr(Color, key, getattr(PrintColor, key))
    elif not flag and _SCREEN_COLOR_SNAPSHOT:
        for key, value in _SCREEN_COLOR_SNAPSHOT.items():
            setattr(Color, key, value)
        _SCREEN_COLOR_SNAPSHOT = {}


# 导出时给座位表控件临时套上的浅色样式（覆盖全局 QSS 里的深色底）
PRINT_CANVAS_QSS = (
    "QScrollArea, QWidget#Canvas { background: #FFFFFF; }"
    "QLabel#GroupTitle { color: #6B7280; }"
    "QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #C7CDD6; }"
    "QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }"
)


# 座位卡片：宽 × 高 × 圆角
SEAT_CARD_SIZES: Dict[str, Tuple[int, int, int]] = {
    CardSize.SMALL: (64, 44, 8),
    CardSize.MEDIUM: (84, 56, 10),
    CardSize.LARGE: (104, 68, 10),
}

CARD_SIZE_LABELS = {
    CardSize.SMALL: "小",
    CardSize.MEDIUM: "中",
    CardSize.LARGE: "大",
}

# 间距
GRID_SPACING = 6                      # 组内行/列间距
GRID_MARGIN = 24                      # 座位表外边距
AISLE_UNITS = {0: 24, 1: 32, 2: 40, 3: 48}   # gap_after -> 组间距像素
PODIUM_HEIGHT = 48
PODIUM_GAP = 32

# 面板尺寸
PANEL_STUDENT_WIDTH = 320
PANEL_RULE_WIDTH = 300
TOOLBAR_HEIGHT = 48
STATUSBAR_HEIGHT = 28

# 圆角
RADIUS_BUTTON = 8
RADIUS_INPUT = 8
RADIUS_CARD = 12
RADIUS_DIALOG = 14

# 字体：应用默认 / 面板标题 / 座位姓名 / 座位学号 / 讲台
FONT_FAMILIES = ["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "sans-serif"]
FONT_APP = 13
FONT_PANEL_TITLE = 13
FONT_SEAT_NAME = 13
FONT_SEAT_SID = 10
FONT_PODIUM = 16

# 冲突 / 状态样式
CONFLICT_BORDER_WIDTH = 2
TAG_STRIPE_WIDTH = 3

STATUS_LABELS = {
    "default": "默认",
    "hover": "悬停",
    "selected": "选中",
    "conflict": "冲突",
    "disabled": "空置",
}


# 精简环境（离屏渲染 / 绿色版运行环境）里 Qt 的字体库可能是空的，
# 这时直接从系统字体目录补注册，避免整屏中文变成方框。
SYSTEM_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",     # 黑体
    "C:/Windows/Fonts/simsun.ttc",     # 宋体
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def ensure_font_db() -> int:
    """字体库为空时补注册系统字体，返回新增的字体族数量。

    必须在 ``QApplication`` 创建之后调用；任何失败都静默忽略。
    """
    try:
        from PyQt6.QtGui import QFontDatabase
    except Exception:
        return 0
    try:
        if QFontDatabase.families():
            return 0
        added = 0
        for path in SYSTEM_FONT_CANDIDATES:
            try:
                font_id = QFontDatabase.addApplicationFont(path)
            except Exception:
                continue
            if font_id != -1:
                added += len(QFontDatabase.applicationFontFamilies(font_id))
        return added
    except Exception:
        return 0


def dark_palette():
    """深色调色板。

    QSS 能覆盖大部分绘制，但 Fusion 风格仍有一部分走调色板（输入框的清除按钮、
    标准图标、视口底色、禁用态文本等），只换 QSS 会让它们保持浅色而看不清。
    这里返回调色板，由 :func:`apply_dark_theme` 安装。
    """
    from PyQt6.QtGui import QColor, QPalette

    def rgb(value: str) -> QColor:
        return QColor(value)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, rgb(Color.BG_APP))
    palette.setColor(QPalette.ColorRole.WindowText, rgb(Color.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, rgb(Color.BG_SUBTLE))
    palette.setColor(QPalette.ColorRole.AlternateBase, rgb(Color.BG_PANEL))
    palette.setColor(QPalette.ColorRole.Text, rgb(Color.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.PlaceholderText, rgb(Color.TEXT_DISABLED))
    palette.setColor(QPalette.ColorRole.Button, rgb(Color.BG_SUBTLE))
    palette.setColor(QPalette.ColorRole.ButtonText, rgb(Color.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.BrightText, rgb(Color.DANGER))
    palette.setColor(QPalette.ColorRole.ToolTipBase, rgb(Color.BG_SUBTLE))
    palette.setColor(QPalette.ColorRole.ToolTipText, rgb(Color.TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Highlight, rgb(Color.PRIMARY))
    palette.setColor(QPalette.ColorRole.HighlightedText, rgb(Color.TEXT_ON_ACCENT))
    palette.setColor(QPalette.ColorRole.Link, rgb(Color.PRIMARY))
    palette.setColor(QPalette.ColorRole.Mid, rgb(Color.BORDER))
    palette.setColor(QPalette.ColorRole.Dark, rgb(Color.BG_APP))
    palette.setColor(QPalette.ColorRole.Shadow, rgb("#000000"))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, rgb(Color.TEXT_DISABLED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base,
                     rgb(Color.OVERLAY))
    return palette


def apply_dark_theme(app) -> None:
    """给 ``QApplication`` 装上深色主题（调色板 + QSS + 字体）。"""
    from PyQt6.QtGui import QFont

    from .. import load_stylesheet

    app.setStyle("Fusion")
    ensure_font_db()
    app.setPalette(dark_palette())
    app.setStyleSheet(load_stylesheet())
    font = QFont()
    font.setFamilies(list(FONT_FAMILIES))
    font.setPixelSize(FONT_APP)
    app.setFont(font)
    install_dark_titlebars(app)


def apply_dark_titlebar(window) -> bool:
    """Windows 下把系统标题栏改成深色；其他平台或失败时返回 False。

    只影响原生标题栏的配色，不改变窗口行为（与 ``frameless`` 方案相比
    不会动最大化 / 贴边 / 任务栏这些系统行为）。
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = (
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        )
        value = ctypes.c_int(1)
        handle = wintypes.HWND(int(window.winId()))
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE；Win10 1809~1903 上是 19
        for attribute in (20, 19):
            if dwm.DwmSetWindowAttribute(
                handle, attribute, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                return True
    except Exception:
        return False
    return False


def _theme_focused_window(window) -> None:
    """新窗口获得焦点时补上深色标题栏（对话框走这条路径）。"""
    if window is not None:
        apply_dark_titlebar(window)


def install_dark_titlebars(app) -> bool:
    """新窗口获得焦点时自动套上深色原生标题栏（对话框走这条路径）。

    这里用 ``focusWindowChanged`` 信号而不是应用级事件过滤器：事件过滤器要在
    Python 侧长期持有 QObject 引用，解释器退出阶段会踩到已析构对象，实测直接
    以 0xC0000005 崩溃。信号连接由 Qt 侧管理，退出时干净。
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        app.focusWindowChanged.connect(_theme_focused_window)
    except Exception:
        return False
    return True


def seat_size(name: str) -> Tuple[int, int, int]:
    """返回 ``(width, height, radius)``。"""
    return SEAT_CARD_SIZES.get(name, SEAT_CARD_SIZES[CardSize.MEDIUM])


def aisle_width(gap_after: int) -> int:
    gap = max(0, min(3, int(gap_after)))
    return AISLE_UNITS.get(gap, 32)
