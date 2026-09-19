"""全局常量、路径与 QSettings key。

本模块只依赖标准库，UI/服务/存储层均可安全导入。
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------- 应用信息
APP_NAME = "教室座位编排"
APP_ID = "ClassroomSeating"
ORG_NAME = "ClassroomSeating"
VERSION = "1.0"

# ---------------------------------------------------------------- 文件
PROJECT_EXT = ".seatproj"
PROJECT_FILTER = "座位编排项目 (*.seatproj);;所有文件 (*)"
EXCEL_FILTER = "Excel 工作簿 (*.xlsx);;所有文件 (*)"
PNG_FILTER = "PNG 图片 (*.png)"
JSON_FILTER = "JSON 文件 (*.json);;所有文件 (*)"

BASE_DIR = Path(__file__).resolve().parent.parent
RESOURCES_DIR = BASE_DIR / "resources"
TEMPLATES_DIR = RESOURCES_DIR / "templates"
ICONS_DIR = RESOURCES_DIR / "icons"

# ---------------------------------------------------------------- 算法参数
HARD_PENALTY = 10000.0     # 单条硬约束违反的惩罚（远大于软约束权重之和）
DEFAULT_TIME_LIMIT = 3.0   # 排位时间上限（秒）
DEFAULT_IDLE_LIMIT = 300   # 爬山法连续无改进多少次后重启
SOLVER_CHUNK = 40          # 每次 QTimer 分片评估的交换次数

# ---------------------------------------------------------------- 撤销
MAX_UNDO = 50
AUTOSAVE_INTERVAL_MS = 2 * 60 * 1000   # 每 2 分钟自动保存

AUTOSAVE_DIR = Path.home() / ".classroom_seating"
AUTOSAVE_FILE = AUTOSAVE_DIR / "autosave.seatproj"

# ---------------------------------------------------------------- QSettings key
SK_GEOMETRY = "window/geometry"
SK_STATE = "window/state"
SK_RECENT_FILES = "files/recent"
SK_LAST_DIR = "files/last_dir"
SK_LAST_PROJECT = "files/last_project"
SK_SHOW_SID = "view/show_sid"
SK_SHOW_GROUP_TITLE = "view/show_group_title"
SK_CARD_SIZE = "view/card_size"
SK_SHOW_SELECTION = "view/show_selection"
SK_WELCOME_SHOWN = "welcome/shown"

# ---------------------------------------------------------------- Excel 表头别名
# 自动识别表头：值越小优先级越高
SID_ALIASES = ["学号", "学籍号", "考号", "学生编号", "编号", "序号", "sid", "id", "no", "number"]
NAME_ALIASES = ["姓名", "学生姓名", "名字", "学生", "name", "student"]
GENDER_ALIASES = ["性别", "gender", "sex"]
TAG_ALIASES = ["标签", "分类", "类型", "tag", "tags", "group"]
NOTE_ALIASES = ["备注", "说明", "note", "remark", "comment", "说明备注"]

# 已知的数值属性列（其余未识别列若整体为数值也会自动成为数值属性）
KNOWN_ATTR_ALIASES = {
    "身高": "身高", "身高(cm)": "身高", "height": "身高",
    "体重": "体重", "体重(kg)": "体重", "weight": "体重",
    "视力": "视力", "左眼视力": "视力", "右眼视力": "视力",
    "成绩": "成绩", "总分": "成绩", "分数": "成绩", "score": "成绩",
    "年龄": "年龄", "age": "年龄",
}

# 导入时识别为“保留字段”的表头（不作为数值属性）
RESERVED_FIELDS = ("学号", "姓名", "性别", "标签", "备注")

# ---------------------------------------------------------------- 标签色板（12 色）
# 放在 config 而非 theme，避免 models 层反向依赖 ui 层
TAG_PALETTE = [
    "#2F6BFF", "#12B76A", "#F79009", "#E5484D",
    "#7A5AF8", "#0BA5EC", "#EE46BC", "#84CC16",
    "#F04438", "#14B8A6", "#F59E0B", "#8B5CF6",
]

# ---------------------------------------------------------------- 空状态引导
WELCOME_STEPS = (
    "1. 新建项目 → 在“布局”中配置教室分组",
    "2. 导入学生名单（Excel 模板可在「文件」菜单下载，也可手动添加）",
    "3. 设置规则 → 点击“一键排位”生成方案",
    "4. 拖拽微调 → 导出 Excel / PNG 座位表",
)
