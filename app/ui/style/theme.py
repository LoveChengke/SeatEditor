"""主题系统：黑夜 / 白天双色板 + 动效尺寸常量。

结构：
- ``PALETTES``：dark / light 两套完整色板（含 QSS 专用令牌），单一真源。
  ``app/ui/style/app.qss`` 里的颜色全部写成 ``@TOKEN@`` 占位符，
  由 :func:`app.ui.load_stylesheet` 按当前色板填充——改色只改这里。
- ``Color``：兼容旧用法的动态代理。全代码 ``Color.PRIMARY`` 这样的读取
  走元类转发到当前色板，切换主题即时生效，不需要改任何调用点。
- :func:`apply_theme`：装调色板 + QSS + 字体；:func:`apply_dark_titlebar`
  联动 Windows 原生标题栏明暗。
"""

from __future__ import annotations

import sys
from typing import Dict, Tuple

from ...config import TAG_PALETTE   # 单一真源，避免 models/ui 循环依赖

DARK = "dark"
LIGHT = "light"

# ---------------------------------------------------------------- 色板
# 键即 QSS 令牌名（@PRIMARY@ 这种）；被自绘控件经 Color 读取 + QSS 填充共用。
DARK_PALETTE: Dict[str, str] = {
    "PRIMARY": "#4C97FF",
    "PRIMARY_HOVER": "#6DB0FF",
    "PRIMARY_PRESSED": "#2F7FE8",
    "PRIMARY_LIGHT": "#17304C",
    "PRIMARY_SOFT": "#1C2836",
    "PRIMARY_BORDER": "#2F5C86",
    "PRIMARY_DISABLED_BG": "#24405F",
    "PRIMARY_DISABLED_TEXT": "#8FA8C2",
    "TEXT_ON_ACCENT": "#06182B",
    "BG_APP": "#0F141A",
    "BG_PANEL": "#161B22",
    # 活动栏 / 标签条是「窗口骨架」那一层：比面板再暗一档，
    # 面板内容才显得是浮在上面的纸（白天模式同理，见 LIGHT_PALETTE）
    "BG_RAIL": "#0D1319",
    # 活动栏选中项的底色：深色下靠「底色更深」拉不开差距（面板本来就接近黑），
    # 所以选中项改成比活动栏亮一档的方块，配合左缘主色竖条一起表达选中
    "RAIL_ACTIVE_BG": "#232B36",
    "BG_TABBAR": "#131A21",
    "TAB_ACTIVE_BG": "#161B22",
    "BG_CARD": "#1C222B",
    "BG_SUBTLE": "#242B35",
    "BG_HOVER": "#2D3542",
    "BG_DISABLED": "#1B2027",
    "BG_TABLE_ALT": "#1E242D",
    "BORDER": "#2E3742",
    # 控件的描边单独一档：比容器描边重，按钮 / 输入框才看得出边界
    # （BORDER 在按钮底色上只有 1.2:1，那种「糊在面板里」的观感就是这个原因）
    "BORDER_CONTROL": "#414D5C",
    "BORDER_LIGHT": "#2A3340",
    "BORDER_STRONG": "#46525F",
    "TEXT_PRIMARY": "#EDF2F8",
    "TEXT_SECONDARY": "#A7B2BF",
    # 图标专用灰：线条图标比文字细，用次要文字色在浅色底上会「发虚」，
    # 所以单独一档（浅色下比 TEXT_SECONDARY 深，深色下与它一致）
    "ICON_MUTED": "#A7B2BF",
    "TEXT_DISABLED": "#6B7683",
    "TEXT_TOOLBAR_DISABLED": "#4E5762",
    "PLACEHOLDER": "#9BA7B5",
    "DANGER": "#FF7A70",
    "DANGER_BG": "#3B2328",
    "DANGER_BG_DARK": "#24191C",
    "DANGER_BORDER": "#4A2C31",
    "DANGER_BORDER_HOVER": "#6A3A40",
    "SUCCESS": "#48D597",
    "WARNING": "#F6B94F",
    "PODIUM": "#2B3B4F",
    "SEAT_DEFAULT": "#252B34",
    "SEAT_HOVER": "#2F3A47",
    "SEAT_SELECTED": "#1E3A58",
    "SEAT_CONFLICT": "#3E262B",
    "SEAT_DISABLED": "#1A1F26",
    "SEAT_EMPTY_TXT": "#7A8492",
    "DASHED": "#3C4551",
    "SCROLLBAR_HOVER": "#4C5765",
    "TAG_UNKNOWN": "#7A8492",
    "OVERLAY": "#1B2027",
}

LIGHT_PALETTE: Dict[str, str] = {
    "PRIMARY": "#2F6BFF",
    "PRIMARY_HOVER": "#1F5CEB",
    "PRIMARY_PRESSED": "#1A4FD1",
    "PRIMARY_LIGHT": "#DCE8FF",
    "PRIMARY_SOFT": "#E8EFFD",
    "PRIMARY_BORDER": "#9DBEFF",
    "PRIMARY_DISABLED_BG": "#D8E2F0",
    "PRIMARY_DISABLED_TEXT": "#51637A",
    "TEXT_ON_ACCENT": "#FFFFFF",
    "BG_APP": "#F3F5F9",
    "BG_PANEL": "#FFFFFF",
    "BG_RAIL": "#DCE2EA",
    "RAIL_ACTIVE_BG": "#FFFFFF",
    "BG_TABBAR": "#E9EDF3",
    "TAB_ACTIVE_BG": "#FFFFFF",
    "BG_CARD": "#FFFFFF",
    "BG_SUBTLE": "#EEF1F6",
    "BG_HOVER": "#E2E8F1",
    "BG_DISABLED": "#ECEFF4",
    "BG_TABLE_ALT": "#F4F7FA",
    "BORDER": "#D5DCE6",
    "BORDER_CONTROL": "#AFBCCC",
    "BORDER_LIGHT": "#E3E9F0",
    "BORDER_STRONG": "#B4BFCD",
    "TEXT_PRIMARY": "#17222E",
    "TEXT_SECONDARY": "#5B6B7D",
    "ICON_MUTED": "#46566B",
    "TEXT_DISABLED": "#97A3B2",
    "TEXT_TOOLBAR_DISABLED": "#A9B3C0",
    "PLACEHOLDER": "#6E7C8C",
    "DANGER": "#DC3D43",
    "DANGER_BG": "#FDECEC",
    "DANGER_BG_DARK": "#FFF4F4",
    "DANGER_BORDER": "#F0B9BB",
    "DANGER_BORDER_HOVER": "#E5484D",
    "SUCCESS": "#0E7A48",
    "WARNING": "#8F6A00",
    "PODIUM": "#D9E5F8",
    "SEAT_DEFAULT": "#FFFFFF",
    "SEAT_HOVER": "#EAF2FF",
    "SEAT_SELECTED": "#D6E5FF",
    "SEAT_CONFLICT": "#FFE9E9",
    "SEAT_DISABLED": "#F1F3F7",
    "SEAT_EMPTY_TXT": "#9AA4B1",
    "DASHED": "#C3CCD9",
    "SCROLLBAR_HOVER": "#AAB6C5",
    "TAG_UNKNOWN": "#A8B0BD",
    "OVERLAY": "#ECEFF4",
}

PALETTES = {DARK: DARK_PALETTE, LIGHT: LIGHT_PALETTE}

# 当前激活的色板（进程级；apply_theme 切换）
_ACTIVE: Dict[str, str] = DARK_PALETTE
_ACTIVE_NAME: str = DARK


def is_dark() -> bool:
    return _ACTIVE_NAME == DARK


def palette() -> Dict[str, str]:
    return _ACTIVE


class _ColorMeta(type):
    """让 ``Color.X`` 始终读当前色板——切换主题后所有自绘控件即时生效。"""

    def __getattr__(cls, name: str) -> str:
        try:
            return _ACTIVE[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(cls, name: str, value) -> None:
        # 打印模式等旧逻辑用 setattr 临时覆盖；只允许覆盖色板里已有的键
        if name in _ACTIVE:
            type.__setattr__(cls, name, value)
        else:
            raise AttributeError(name)

    def __delattr__(cls, name: str) -> None:
        type.__delattr__(cls, name)


class Color(metaclass=_ColorMeta):
    """动态色板代理：``Color.PRIMARY`` 永远返回当前主题的值。"""


def set_theme(name: str) -> None:
    """切换激活色板（"dark" / "light"）；未知名字保持不变。"""
    global _ACTIVE, _ACTIVE_NAME
    if name in PALETTES:
        _ACTIVE = PALETTES[name]
        _ACTIVE_NAME = name


def theme_name() -> str:
    return _ACTIVE_NAME


# ---------------------------------------------------------------- 打印配色
class PrintColor:
    """导出 PNG / 打印用的浅色配色（只覆盖座位表用到的项）。

    屏幕上无论深浅主题，座位表图片常常要打印，深底会糊成一片还费墨。
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
        for key in _PRINT_SWAP_KEYS:
            try:
                delattr(Color, key)   # 摘掉覆盖，回落到当前色板
            except AttributeError:
                pass
        _SCREEN_COLOR_SNAPSHOT = {}


# 导出时给座位表控件临时套上的浅色样式（覆盖全局 QSS 的底色）
PRINT_CANVAS_QSS = (
    "QScrollArea, QWidget#Canvas { background: #FFFFFF; }"
    "QLabel#GroupTitle { color: #6B7280; }"
    "QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #C7CDD6; }"
    "QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }"
)


# ---------------------------------------------------------------- 布局常量
class CardSize:
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


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

# 间距（4px 网格：控件内 8、控件间 12、区块间 16、页面留白 24）
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

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

# 圆角（小件 8 / 卡片 12 / 对话框 16 / 胶囊=高度一半）
RADIUS_BUTTON = 8
RADIUS_INPUT = 8
RADIUS_CARD = 12
RADIUS_DIALOG = 16
RADIUS_PILL = 999

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
    "disabled": "留空",
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


def qt_palette():
    """按当前色板构建 QPalette。

    QSS 能覆盖大部分绘制，但 Fusion 风格仍有一部分走调色板（输入框的清除按钮、
    标准图标、视口底色、禁用态文本等），只换 QSS 会让它们保持旧配色。
    """
    from PyQt6.QtGui import QColor, QPalette

    def rgb(key: str):
        return QColor(_ACTIVE.get(key, key))

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, rgb("BG_APP"))
    palette.setColor(QPalette.ColorRole.WindowText, rgb("TEXT_PRIMARY"))
    palette.setColor(QPalette.ColorRole.Base, rgb("BG_SUBTLE"))
    palette.setColor(QPalette.ColorRole.AlternateBase, rgb("BG_PANEL"))
    palette.setColor(QPalette.ColorRole.Text, rgb("TEXT_PRIMARY"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, rgb("PLACEHOLDER"))
    palette.setColor(QPalette.ColorRole.Button, rgb("BG_SUBTLE"))
    palette.setColor(QPalette.ColorRole.ButtonText, rgb("TEXT_PRIMARY"))
    palette.setColor(QPalette.ColorRole.BrightText, rgb("DANGER"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, rgb("BG_SUBTLE"))
    palette.setColor(QPalette.ColorRole.ToolTipText, rgb("TEXT_PRIMARY"))
    palette.setColor(QPalette.ColorRole.Highlight, rgb("PRIMARY"))
    palette.setColor(QPalette.ColorRole.HighlightedText, rgb("TEXT_ON_ACCENT"))
    palette.setColor(QPalette.ColorRole.Link, rgb("PRIMARY"))
    palette.setColor(QPalette.ColorRole.Mid, rgb("BORDER"))
    palette.setColor(QPalette.ColorRole.Dark, rgb("BG_APP"))
    palette.setColor(QPalette.ColorRole.Shadow, rgb("#000000"))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, rgb("TEXT_DISABLED"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, rgb("OVERLAY"))
    return palette


def apply_theme(app, dark: bool = True) -> None:
    """切换并应用主题（调色板 + QSS + 字体）；可在运行中反复调用。"""
    from PyQt6.QtGui import QFont

    from .. import load_stylesheet

    set_theme(DARK if dark else LIGHT)
    ensure_font_db()
    app.setPalette(qt_palette())
    app.setStyleSheet(load_stylesheet(_ACTIVE))
    font = QFont()
    font.setFamilies(list(FONT_FAMILIES))
    font.setPixelSize(FONT_APP)
    app.setFont(font)


def apply_dark_theme(app) -> None:
    """兼容旧调用的别名：应用深色主题。"""
    apply_theme(app, dark=True)


def apply_dark_titlebar(window, dark: bool = True) -> bool:
    """Windows 下把系统标题栏改成深 / 浅色；其他平台或失败时返回 False。

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
        value = ctypes.c_int(1 if dark else 0)
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
    """新窗口获得焦点时按当前主题补标题栏配色（对话框走这条路径）。"""
    if window is not None:
        apply_dark_titlebar(window, is_dark())


def install_dark_titlebars(app) -> bool:
    """新窗口获得焦点时自动套当前主题的原生标题栏（对话框走这条路径）。

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
