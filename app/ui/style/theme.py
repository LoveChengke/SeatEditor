"""设计规范常量：色彩 / 字体 / 尺寸（对应 PRD 第三章）。"""

from __future__ import annotations

from typing import Dict, Tuple

from ...config import TAG_PALETTE   # 单一真源，避免 models/ui 循环依赖


class Color:
    """色彩系统。"""

    # 品牌色
    PRIMARY = "#2F6BFF"
    PRIMARY_HOVER = "#1E56E0"
    PRIMARY_LIGHT = "#E8F0FF"

    # 中性色
    BG_APP = "#F5F7FA"
    BG_PANEL = "#FFFFFF"
    BG_SUBTLE = "#F2F4F7"
    BORDER = "#D9DEE7"
    BORDER_LIGHT = "#EAEEF4"

    # 文字
    TEXT_PRIMARY = "#1F2430"
    TEXT_SECONDARY = "#6B7280"
    TEXT_DISABLED = "#A8B0BD"

    # 语义色
    DANGER = "#E5484D"
    DANGER_BG = "#FFECEC"
    SUCCESS = "#12B76A"
    WARNING = "#F79009"
    PODIUM = "#3A4252"

    # 座位状态
    SEAT_DEFAULT = "#FFFFFF"
    SEAT_HOVER = "#EEF4FF"
    SEAT_SELECTED = "#DCE8FF"
    SEAT_CONFLICT = "#FFECEC"
    SEAT_DISABLED = "#F2F4F7"
    SEAT_EMPTY_TXT = "#A8B0BD"

    # 其他
    DASHED = "#C7CDD6"
    TAG_UNKNOWN = "#A8B0BD"


class CardSize:
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


# 座位卡片：宽 × 高 × 圆角
SEAT_CARD_SIZES: Dict[str, Tuple[int, int, int]] = {
    CardSize.SMALL: (64, 44, 6),
    CardSize.MEDIUM: (84, 56, 8),
    CardSize.LARGE: (104, 68, 8),
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
RADIUS_BUTTON = 6
RADIUS_INPUT = 6
RADIUS_CARD = 8
RADIUS_DIALOG = 12

# 字体：应用默认 / 面板标题 / 座位姓名 / 座位学号 / 讲台
FONT_FAMILIES = ["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "sans-serif"]
FONT_APP = 12
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
    except Exception:  # noqa: BLE001
        return 0
    try:
        if QFontDatabase.families():
            return 0
        added = 0
        for path in SYSTEM_FONT_CANDIDATES:
            try:
                font_id = QFontDatabase.addApplicationFont(path)
            except Exception:  # noqa: BLE001
                continue
            if font_id != -1:
                added += len(QFontDatabase.applicationFontFamilies(font_id))
        return added
    except Exception:  # noqa: BLE001
        return 0


def seat_size(name: str) -> Tuple[int, int, int]:
    """返回 ``(width, height, radius)``。"""
    return SEAT_CARD_SIZES.get(name, SEAT_CARD_SIZES[CardSize.MEDIUM])


def aisle_width(gap_after: int) -> int:
    gap = max(0, min(3, int(gap_after)))
    return AISLE_UNITS.get(gap, 32)
