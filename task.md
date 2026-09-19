# 教室自动排座位程序 PRD

---

## 一、项目概述

### 1.1 产品定位
一款**单机桌面端**教室座位编排工具，面向中小学班主任 / 任课教师。教师可自定义教室布局、导入学生名单、通过规则引擎自动生成座位方案，并在可视化网格上拖拽微调，最终一键导出 Excel / PNG 座位表。

### 1.2 设计原则
| 原则 | 说明 |
|---|---|
| **零学习成本** | 核心操作（拖拽换座、一键排位、一键导出）三步内完成 |
| **本地优先** | 全部数据本地存储，无网络依赖、无账号体系 |
| **可解释性** | 排位结果必须能看出"为什么这么排"，冲突必须能定位到具体座位 |
| **技术克制** | 不使用异步框架、数据库 ORM、复杂算法库，用标准库 + PyQt 原生能力完成 |

### 1.3 技术难度控制红线
- ❌ 不引入 SQLAlchemy / Django / FastAPI / Celery
- ❌ 不使用 QGraphicsScene 做座位表（过重）
- ❌ 不实现多线程排位（用 `QTimer` 分片或直接同步 + 进度对话框）
- ❌ 不做插件系统、脚本引擎
- ✅ 排位算法使用**随机重启 + 爬山法（局部交换）**，不做遗传算法 / 模拟退火

---

## 二、功能需求

### 2.1 功能总览

```
┌────────────────────────────────────────────────────────────┐
│  F1 教室布局编辑   F2 学生名单管理   F3 标签与选区          │
│  F4 智能排位        F5 自动轮换       F6 座位表交互编辑      │
│  F7 导出            F8 项目存取       F9 撤销重做            │
└────────────────────────────────────────────────────────────┘
```

---

### F1 可视化座位表布局编辑

**需求描述**：教师能配置教室物理座位布局，支持多分组。

**功能点**：

1. **布局参数**
   - 分组（Group）：一个教室可含 1~6 个分组（如"第 1 组 / 第 2 组 / 第 3 组"）
   - 每个分组独立配置：
     - 行数 `rows`（1~12）
     - 列数 `cols`（1~8）
     - 组名（默认"第 N 组"）
     - 该组右侧的**组间距** `gap_after`（以像素/列宽为单位，0~3）
   - 布局级配置：
     - **讲台方向** `podium_side`：`top / bottom`（默认 top）
     - 座位卡片尺寸（小 / 中 / 大 三档）
     - 是否显示组标题

2. **布局编辑器**
   - 左侧参数面板（QSpinBox 列表）+ 右侧实时预览
   - "添加分组 / 删除分组 / 上下移动分组"
   - 支持**快速模板**：`3 组 × 6 行 × 2 列`、`4 组 × 5 行 × 2 列`、`2 组 × 6 行 × 3 列` 等

3. **座位状态**
   - 正常座位（可坐人）
   - **空置座位**（`disabled = True`，不参与排位，渲染为虚线框）

**数据结构**：

```python
@dataclass
class SeatGroup:
    id: int
    name: str
    rows: int
    cols: int
    gap_after: int = 1          # 组间距（列数单位）

@dataclass
class Layout:
    groups: list[SeatGroup]
    podium_side: str = "top"    # top | bottom
    card_size: str = "medium"   # small | medium | large
    show_group_title: bool = True
```

---

### F2 学生名单与属性管理

**功能点**：

1. **学生字段**

   | 字段 | 类型 | 必填 | 说明 |
   |---|---|---|---|
   | `sid` | str | ✅ | 学号，唯一主键 |
   | `name` | str | ✅ | 姓名 |
   | `gender` | str | ❌ | 男 / 女 / 空 |
   | `tags` | list[str] | ❌ | 标签集合 |
   | `attrs` | dict[str, float] | ❌ | 数值属性，如 `{"身高": 165, "视力": 4.8}` |
   | `note` | str | ❌ | 备注 |

2. **列表视图**
   - `QTableView` + `QAbstractTableModel`（不用 `QTableWidget`，便于排序过滤）
   - 列：学号 / 姓名 / 性别 / 标签 / 数值属性 / 已分配座位
   - **点击列头排序**：学号（自然序，`1-2-10` 而非 `1-10-2`）、姓名（拼音）
   - 搜索框：按学号 / 姓名 / 标签实时过滤
   - 标签筛选：多选下拉，取并集/交集

3. **Excel 导入**
   - 使用 `openpyxl` 读取 `.xlsx`
   - 弹窗映射字段：`Excel 列名 → 系统字段`
   - 自动识别表头（学号/姓名/性别/身高/视力等常见别名）
   - 数值属性列自动创建（`attrs` 动态扩展）
   - 导入校验：学号重复 / 姓名为空 → 高亮错误行，允许"跳过错误行继续导入"

4. **Excel 导出**
   - 导出当前名单（含标签、数值属性）

5. **持久化**
   - 学生数据存在项目文件中（JSON）

---

### F3 标签与选区

#### F3.1 标签系统
- 标签库（项目级）：`优等生 / 需关注 / 视力差 / 近视 / 班干部 / 内向 …`
- 每个标签可配置**颜色**（预设 12 色调色板，自动分配未使用色）
- 批量打标签：在名单中多选学生 → 右键 → 添加/移除标签
- 标签删除时同步从所有学生上移除

#### F3.2 座位选区（Selection）

**选区定义**：一组座位坐标的集合，可命名并复用。

- **创建方式**
  - 鼠标框选（拖拽矩形）
  - Ctrl + 点击 追加 / 移除
  - "按分组选择"（选中整组）
  - "按行范围选择"（如第 1–3 排）
  - "按列范围选择"
- **选区操作**
  - 命名保存（"前排区"、"左护法区"、"第 1 组"）
  - 批量操作：清空座位 / 设为空置 / 批量分配 / 打标签
  - 参与规则（见 F4）
  - 参与轮换（见 F5）

**数据结构**：

```python
@dataclass
class Selection:
    id: str
    name: str
    seats: set[tuple[int, int, int]]   # (group_idx, row, col)
    color: str = "#2F6BFF"
```

---

### F4 智能排位（规则引擎）

#### F4.1 规则类型

**硬约束（Hard）** — 必须满足，违反即标红

| 规则 | 参数 | 说明 |
|---|---|---|
| 固定座位 | 学生 → 座位 | 某学生锁定在某座位 |
| 禁止相邻 | 学生 A、学生 B | 四邻域不相邻 |
| 区域限制 | 标签/学生 + 选区 | 该标签学生必须在该选区内 |
| 排除区域 | 标签/学生 + 选区 | 该标签学生不得在该选区内 |
| 前排必需 | 标签 + 前 N 排 | 视力差学生必须在前 N 排 |

**软约束（Soft）** — 加权评分，尽量满足

| 规则 | 参数 | 说明 |
|---|---|---|
| 属性排序 | 数值属性 + 方向 | 如身高从矮到高、从前到后 |
| 属性分档 | 数值属性 + 档数 + 区域 | 如成绩分 4 档，各档均匀分布到 4 个分组 |
| 同标签分散 | 标签 + 权重 | 同标签学生尽量不相邻 |
| 同桌搭配 | 标签 A + 标签 B | 优等生与需关注学生同桌 |
| 避免重复 | 与上次方案 | 尽量不坐原座位 |
| 性别交替 | — | 男女交替排列 |
| 靠前偏好 | 标签 / 学生 | 优先前排 |

#### F4.2 搜索算法（低难度方案）

```
输入：学生集合 S、座位集合 P、规则集 R
输出：分配方案 assignment: P -> S ∪ {None}

1. 可行性预检
   - len(S) > len(可用座位) → 报错
   - 硬约束集合本身矛盾（如"必须在 A 区" + "不得在 A 区"）→ 报错

2. 随机重启循环（时间上限 3 秒，或用户点击"停止"）
   a. 随机初始化分配（固定座位先落位）
   b. 爬山法局部优化：
      - 反复随机选取两个座位，尝试交换
      - 计算 Δscore = 硬约束惩罚变化 + 软约束得分变化
      - 若 Δscore >= 0 则接受，否则回滚
      - 连续 K 次无改进则跳出
   c. 记录本次最优解
3. 返回全局最优解 + 每个约束的满足情况报告
```

**评分函数**：

```python
score = soft_score - HARD_PENALTY * hard_violation_count
# HARD_PENALTY 取一个远大于所有软约束权重之和的常数，如 10000
```

**性能估算**：60 座位规模下，单次爬山约 2000 次交换评估，3 秒内可完成 200+ 次重启，对教师场景足够。

#### F4.3 结果呈现

- 排位完成 → 弹窗显示：
  - 硬约束满足情况（✅ 全部满足 / ⚠️ N 条未满足，列出明细）
  - 软约束得分（进度条 + 各规则贡献度）
- 未满足的硬约束座位**红色高亮**，鼠标悬停显示冲突原因
- 支持"换一批"（重新搜索）/ "锁定当前满意的座位再排位"

---

### F5 自动轮换

#### F5.1 区域轮换
- 定义 2~6 个**区域**（复用选区）
- 学生按区域整体循环：`区域1 → 区域2 → ... → 区域N → 区域1`
- 区域内座位按固定规则重排（保持原相对位置 / 重新排位）

#### F5.2 平移轮换
- **按组平移**：学生在组内循环平移（如第 1 组第 1 排 → 第 1 组第 2 排）
- **按列平移**：整列学生向右移动 N 列（处理边缘回绕）
- **自定义平移向量**：`(Δrow, Δcol)`

#### F5.3 轮换管理
- 记录轮换历史（第 1 周 / 第 2 周 …）
- 支持"回退到第 N 周"
- 轮换前自动检查硬约束冲突，冲突则提示

---

### F6 座位表交互编辑（主界面核心）

#### F6.1 可视化网格
- 中央区域渲染座位表，每个座位为一个 **`SeatWidget`（QFrame 子类）**
- 布局实现：`QHBoxLayout` 包裹每个分组的 `QGridLayout`，组间距由 `layout.setSpacing()` 控制 —— **天然实现"过道留空"**
- 座位显示内容：
  - 主文本：姓名（超长省略，`elidedText`）
  - 副文本：学号后 4 位（小号灰字，可开关）
  - 标签色条：座位卡片左侧 3px 竖条，颜色取学生第一个标签色
- 讲台：在顶部/底部渲染一个横向条块，深灰底 + 白字"讲 台"

#### F6.2 悬停信息
- `QToolTip` 或自定义悬浮卡片（`QFrame` + `Qt.ToolTip` 窗口标志）
- 内容：姓名 / 学号 / 性别 / 全部标签 / 全部数值属性 / 备注
- 延迟 400ms 显示

#### F6.3 交互操作

| 操作 | 触发方式 | 行为 |
|---|---|---|
| **点击分配** | 先在左侧名单选中学生 → 点击空座位 | 学生入座 |
| **拖拽分配** | 从名单列表拖学生 → 拖到座位 | 学生入座 |
| **拖拽交换** | 从座位拖学生 → 拖到另一座位 | 两人交换 |
| **拖拽移动** | 从座位拖到空座位 | 直接移动 |
| **清空座位** | 右键 → 清空 / Delete 键 | 学生回到未分配池 |
| **空置座位** | 右键 → 设为空置 | 该座位不参与排位，虚线框 |
| **多选** | Ctrl+点击 / 框选 | 选区，支持批量操作 |
| **撤销/重做** | Ctrl+Z / Ctrl+Y | 见 F9 |

**拖拽实现**（Qt 原生，低难度）：

```python
# 拖动源
def mouseMoveEvent(self, e):
    if (e.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
        return
    drag = QDrag(self)
    mime = QMimeData()
    mime.setData("application/x-seat", QByteArray(json.dumps(payload).encode()))
    drag.setMimeData(mime)
    drag.exec(Qt.DropAction.MoveAction)

# 放置目标
def dragEnterEvent(self, e):
    if e.mimeData().hasFormat("application/x-seat"):
        e.acceptProposedAction()
```

#### F6.4 冲突实时检测与高亮

- 每次拖拽释放 / 交换 / 分配后，调用 `RuleEngine.check_hard(assignment)` 仅校验**受影响的座位**（增量校验，O(1)~O(邻居数)）
- 冲突座位渲染：**2px 红色边框 + 浅红背景 + 右上角 ⚠ 图标**
- 状态栏提示：`⚠️ 张三 与 李四 相邻，违反"禁止相邻"规则`
- 允许保留冲突（教师可自行判断），但导出时给出提醒

---

### F7 导出

#### F7.1 Excel 座位表导出
- 使用 `openpyxl`
- 布局映射：
  - 每个座位占 1 个单元格（行高 40，列宽 12）
  - **组间距** → 空列（过道）
  - **讲台** → 首行/末行合并单元格，居中"讲 台"
  - 座位内容：`姓名\n学号`
  - 单元格样式：细边框、居中、字号 11、标签色作为左侧边框色
  - 空置座位：灰色填充
- 附加 Sheet：
  - `名单`：完整学生名单
  - `规则说明`：本次排位使用的规则列表
- 支持"是否含学号"、"是否含组标题"选项

#### F7.2 PNG 图片导出
- 直接 `seat_grid_widget.grab()` → `QPixmap` → `save(path, "PNG")`
- 导出前临时隐藏选区高亮、冲突高亮（可选）
- 提供 1x / 2x 缩放（`QImage` 重绘或设置 `devicePixelRatio`）

---

### F8 项目存取

- 项目文件扩展名：`.seatproj`（内容为 JSON，UTF-8）
- 保存内容：布局 / 学生 / 标签 / 选区 / 规则 / 当前分配 / 轮换历史 / 撤销栈（可选）
- 自动保存：每 2 分钟或每次重大操作后写临时文件
- 最近打开列表（`QSettings`）

**JSON 结构示例**：

```json
{
  "version": "1.0",
  "layout": { "groups": [...], "podium_side": "top" },
  "students": [ { "sid": "1001", "name": "张三", "tags": ["班干部"], "attrs": {"身高": 168} } ],
  "tags": [ { "name": "班干部", "color": "#2F6BFF" } ],
  "selections": [ { "id": "s1", "name": "前排区", "seats": [[0,0,0],[0,0,1]] } ],
  "rules": [ { "id": "r1", "type": "hard", "kind": "fixed_seat", "params": {...} } ],
  "assignment": { "0-0-0": "1001", "0-0-1": "1002" },
  "history": [ { "week": 1, "assignment": {...} } ]
}
```

---

### F9 撤销 / 重做

**实现方式（最简）**：快照式

```python
class HistoryStack:
    def __init__(self, max_size=50):
        self._undo: deque[Snapshot] = deque(maxlen=max_size)
        self._redo: list[Snapshot] = []

    def push(self, assignment: dict, label: str):
        self._undo.append(Snapshot(copy.deepcopy(assignment), label))
        self._redo.clear()
```

- 快照粒度 = 整个 `assignment` 字典（60 座位约几 KB，50 步完全无压力）
- 记录点：点击分配 / 拖拽交换 / 清空 / 空置 / 批量操作 / 智能排位 / 轮换
- UI：工具栏按钮 + 快捷键，按钮 tooltip 显示操作名称（"撤销：交换 张三 ↔ 李四"）

---

## 三、视觉设计规范

### 3.1 设计风格
**清亮 · 克制 · 信息优先**。参考 Linear / Notion 的浅色系，避免重投影和强渐变。

### 3.2 色彩系统

```python
class Color:
    # 品牌色
    PRIMARY        = "#2F6BFF"
    PRIMARY_HOVER  = "#1E56E0"
    PRIMARY_LIGHT  = "#E8F0FF"

    # 中性色
    BG_APP         = "#F5F7FA"   # 应用背景
    BG_PANEL       = "#FFFFFF"   # 面板背景
    BG_SUBTLE      = "#F2F4F7"   # 次级背景
    BORDER         = "#D9DEE7"
    BORDER_LIGHT   = "#EAEEF4"

    # 文字
    TEXT_PRIMARY   = "#1F2430"
    TEXT_SECONDARY = "#6B7280"
    TEXT_DISABLED  = "#A8B0BD"

    # 语义色
    DANGER         = "#E5484D"
    DANGER_BG      = "#FFECEC"
    SUCCESS        = "#12B76A"
    WARNING        = "#F79009"
    PODIUM         = "#3A4252"

    # 座位状态
    SEAT_DEFAULT   = "#FFFFFF"
    SEAT_HOVER     = "#EEF4FF"
    SEAT_SELECTED  = "#DCE8FF"
    SEAT_CONFLICT  = "#FFECEC"
    SEAT_DISABLED  = "#F2F4F7"
    SEAT_EMPTY_TXT = "#A8B0BD"
```

**标签色板（12 色）**：
`#2F6BFF #12B76A #F79009 #E5484D #7A5AF8 #0BA5EC #EE46BC #84CC16 #F04438 #14B8A6 #F59E0B #8B5CF6`

### 3.3 字体

| 用途 | 字体 | 字号 | 字重 |
|---|---|---|---|
| 应用默认 | 微软雅黑 / PingFang SC / 系统默认 | 12px | Regular |
| 面板标题 | 同上 | 13px | Medium (500) |
| 座位姓名 | 同上 | 13px | Medium |
| 座位学号 | 同上 | 10px | Regular |
| 讲台 | 同上 | 16px | Bold |
| 按钮 | 同上 | 12px | Regular |

### 3.4 尺寸与间距

```
基准单位：4px

座位卡片：
  小： 64 × 44 px   圆角 6px
  中： 84 × 56 px   圆角 8px   ← 默认
  大： 104 × 68 px  圆角 8px

组内行间距 / 列间距：6 px
组间距（过道）：24 / 32 / 40 px（对应 gap 0/1/2）
座位表外边距：24 px
讲台条：高度 48px，宽度 100%，距座位表 32px

面板：
  左侧学生面板宽 320px
  右侧规则面板宽 300px
  顶部工具栏高 48px
  底部状态栏高 28px

圆角规范：
  按钮 6px / 输入框 6px / 卡片 8px / 弹窗 12px
```

### 3.5 状态样式

| 状态 | 背景 | 边框 | 其他 |
|---|---|---|---|
| 默认座位（有人） | `#FFFFFF` | `1px #D9DEE7` | 左侧 3px 标签色条 |
| 悬停 | `#EEF4FF` | `1px #2F6BFF` | 鼠标 Pointer |
| 选中 | `#DCE8FF` | `2px #2F6BFF` | — |
| 冲突 | `#FFECEC` | `2px #E5484D` | 右上角 ⚠ |
| 空置 | `#F2F4F7` | `1px dashed #C7CDD6` | 文字灰 |
| 拖拽中 | 半透明 0.5 | `2px #2F6BFF` 虚线 | — |
| 放置目标高亮 | `#DCE8FF` | `2px #2F6BFF` 虚线 | — |

### 3.6 动效
- 全部使用 `QPropertyAnimation`，时长 120~180ms，`OutCubic` 缓动
- 座位交换：位置交叉淡入淡出（可选，若实现成本高可省略）
- 面板展开/收起：宽度动画 180ms
- **不做过场动画、不做粒子效果**

---

## 四、技术栈选型

| 层次 | 选型 | 理由 |
|---|---|---|
| 语言 | **Python 3.10+** | 匹配现代类型注解语法 |
| GUI | **PyQt6** | 需求指定；成熟稳定，Qt Designer 可辅助 |
| 表格模型 | `QAbstractTableModel` + `QTableView` | 性能优于 QTableWidget，支持排序过滤 |
| Excel | **openpyxl** | 纯 Python，无 Excel 依赖，读写样式方便 |
| 图片导出 | `QPixmap.grab()` + `QPainter` | Qt 原生，零额外依赖 |
| 数据持久化 | **JSON**（标准库 `json`） | 结构简单，可读可 diff，无需数据库 |
| 数据校验 | `dataclasses` + 手写校验函数 | 不引入 pydantic |
| 排位算法 | 手写随机重启 + 爬山法 | 无依赖，代码量 < 200 行 |
| 配置存储 | `QSettings` | 记住窗口位置、最近文件、偏好 |
| 测试 | `pytest` + `pytest-qt` | 仅覆盖核心算法与数据层 |
| 打包 | **PyInstaller** | 生成单文件 exe，方便教师使用 |
| 代码规范 | `ruff` + `black`（可选） | — |

**明确不引入**：numpy / pandas / scipy / sqlalchemy / networkx / ortools / 任何云服务 SDK

---

## 五、项目架构

### 5.1 分层架构

```
┌─────────────────────────────────────────────────────────┐
│  UI 层 (ui/)                                             │
│  MainWindow · SeatGridView · SeatWidget · StudentPanel   │
│  RulePanel · LayoutEditorDialog · ExportDialog           │
└────────────────────┬────────────────────────────────────┘
                     │ 信号/槽 + 服务调用
┌────────────────────▼────────────────────────────────────┐
│  服务层 (services/)                                       │
│  SeatService · StudentService · RuleEngine · Solver      │
│  RotationService · ExportService · HistoryService        │
└────────────────────┬────────────────────────────────────┘
                     │ 纯数据操作
┌────────────────────▼────────────────────────────────────┐
│  模型层 (models/)                                         │
│  Student · SeatGroup · Layout · Seat · Selection         │
│  Rule · Project · Assignment                             │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  持久化层 (storage/)                                      │
│  JsonProjectStore · ExcelImporter · ExcelExporter        │
└─────────────────────────────────────────────────────────┘
```

### 5.2 目录结构

```
classroom_seating/
├── main.py                      # 入口
├── app/
│   ├── __init__.py
│   ├── config.py                # 常量、路径、QSettings key
│   ├── models/
│   │   ├── student.py
│   │   ├── layout.py            # Layout, SeatGroup, Seat
│   │   ├── selection.py
│   │   ├── rule.py              # Rule 定义 + 枚举
│   │   ├── assignment.py        # 分配结果 + 座位 Key 工具
│   │   └── project.py           # 聚合根
│   ├── services/
│   │   ├── seat_service.py      # 分配/交换/清空/空置
│   │   ├── student_service.py   # 增删改查/排序/过滤
│   │   ├── rule_engine.py       # 硬约束校验 + 软约束评分
│   │   ├── solver.py            # 随机重启爬山法
│   │   ├── rotation_service.py  # 区域轮换 / 平移轮换
│   │   ├── history_service.py   # 撤销重做栈
│   │   └── export_service.py    # Excel / PNG 导出
│   ├── storage/
│   │   ├── project_store.py     # JSON 读写
│   │   └── excel_io.py          # 导入/导出
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── widgets/
│   │   │   ├── seat_grid_view.py    # 座位表容器
│   │   │   ├── seat_widget.py       # 单个座位
│   │   │   ├── podium_widget.py     # 讲台
│   │   │   ├── student_table.py     # 学生列表
│   │   │   └── tag_chip.py          # 标签胶囊
│   │   ├── panels/
│   │   │   ├── student_panel.py
│   │   │   ├── rule_panel.py
│   │   │   ├── selection_panel.py
│   │   │   └── rotation_panel.py
│   │   ├── dialogs/
│   │   │   ├── layout_editor_dialog.py
│   │   │   ├── import_mapping_dialog.py
│   │   │   ├── export_dialog.py
│   │   │   ├── solver_progress_dialog.py
│   │   │   └── conflict_report_dialog.py
│   │   └── style/
│   │       ├── theme.py            # Color / Font / Size 常量
│   │       └── app.qss             # 全局样式表
│   └── utils/
│       ├── seat_key.py             # (g,r,c) <-> "g-r-c"
│       ├── natural_sort.py         # 学号自然排序
│       └── pinyin.py               # 姓名拼音排序（可选，用 pypinyin 或简易映射）
├── tests/
│   ├── test_solver.py
│   ├── test_rule_engine.py
│   └── test_rotation.py
├── resources/
│   ├── icons/
│   └── templates/            # 布局模板 JSON
├── requirements.txt
└── README.md
```

### 5.3 核心模块职责

| 模块 | 职责 | 关键接口 |
|---|---|---|
| `RuleEngine` | 硬约束校验、软约束评分 | `check_hard(assign, seats) -> list[Violation]`<br>`score(assign, students, rules) -> float` |
| `Solver` | 搜索最优分配 | `solve(students, seats, rules, time_limit) -> Solution` |
| `SeatService` | 座位操作原子化 | `assign(seat, sid)` / `swap(s1, s2)` / `clear(seat)` |
| `HistoryService` | 快照撤销栈 | `push(assign, label)` / `undo()` / `redo()` |
| `SeatGridView` | 渲染 + 交互 | 信号：`seat_clicked` / `seat_swap_requested` / `selection_changed` |
| `Project` | 聚合根，全局状态 | 持有 layout / students / rules / assignment，发出变更信号 |

### 5.4 信号流（示例：拖拽交换）

```
SeatWidget.mouseMove
  → QDrag 发起（mime: application/x-seat）
  → SeatWidget.dropEvent（目标座位）
  → SeatGridView.seat_swap_requested.emit(src, dst)
  → MainWindow 捕获
  → SeatService.swap(src, dst)
  → RuleEngine.check_hard(受影响座位)
  → HistoryService.push(before_assign, "交换 A↔B")
  → Project.assignment_changed.emit()
  → SeatGridView.refresh(受影响座位)   # 局部刷新，不全量重绘
  → StatusBar 显示冲突提示（如有）
```

---

## 六、关键实现方案（低难度落地）

### 6.1 座位表渲染：QGridLayout 方案

```python
class SeatGridView(QWidget):
    def rebuild(self, layout: Layout):
        # 清空旧布局
        self._clear()
        root = QHBoxLayout(self)
        root.setSpacing(0)          # 组间距由 spacer 控制

        for gi, group in enumerate(layout.groups):
            gbox = QVBoxLayout()
            if layout.show_group_title:
                gbox.addWidget(QLabel(group.name, alignment=Qt.AlignCenter))

            grid = QGridLayout()
            grid.setSpacing(6)
            for r in range(group.rows):
                for c in range(group.cols):
                    w = SeatWidget(gi, r, c)
                    grid.addWidget(w, r, c)
                    self._seat_widgets[(gi, r, c)] = w
            gbox.addLayout(grid)
            root.addLayout(gbox)

            # 组间距（过道）
            if gi < len(layout.groups) - 1:
                root.addSpacing(group.gap_after * AISLE_UNIT)
```

**优点**：无需手动计算坐标，Qt 自动布局；组间距即过道，天然满足导出需求。

### 6.2 增量冲突检测

```python
def check_affected(self, assignment, changed_seats):
    """只校验变动座位及其邻居，O(邻居数)"""
    violations = []
    for seat in changed_seats:
        for rule in self.hard_rules:
            if rule.involves(seat):
                v = rule.check(seat, assignment)
                if v: violations.append(v)
    return violations
```

### 6.3 排位不卡界面

```python
# 简单方案：QProgressDialog + 分片执行
class SolverDialog(QDialog):
    def run(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(0)   # 每次事件循环跑一小步

    def _step(self):
        self._solver.iterate(steps=50)
        self.progress.setValue(self._solver.progress())
        if self._solver.done() or self._cancelled:
            self._timer.stop()
            self.accept()
```

不需要 `QThread`，避免线程安全问题。

---

## 七、开发顺序（仅顺序，不含时间）

> 原则：**先骨架后血肉，先数据后 UI，先能跑后好看，先核心后边缘**

### 第 1 步：项目脚手架
- 建立目录结构、`requirements.txt`、`main.py` 空窗口
- 配置 `theme.py` 色彩/字体/尺寸常量
- 配置 `app.qss` 全局样式
- 确认 PyQt6 + openpyxl 环境可用

### 第 2 步：模型层
- `Student` / `SeatGroup` / `Layout` / `Seat` / `Selection` / `Rule` / `Project` 数据类
- `seat_key.py` 座位坐标与字符串互转
- `natural_sort.py` 学号自然排序
- 单元测试：数据类的序列化 / 反序列化

### 第 3 步：持久化层
- `JsonProjectStore`：`save(project, path)` / `load(path)`，含版本号与兼容处理
- 用命令行脚本验证存取往返一致

### 第 4 步：座位表静态渲染（第一个可见里程碑）
- `SeatWidget`：绘制姓名、学号、标签色条、空置样式
- `PodiumWidget`：讲台条
- `SeatGridView`：按 Layout 用 QGridLayout 渲染
- `LayoutEditorDialog`：配置分组参数 + 实时预览
- **此时可以：改布局 → 看到网格变化**

### 第 5 步：学生名单面板
- `StudentTableModel` + `QTableView`
- 学生增删改、搜索、按学号/姓名排序
- 标签的增删与颜色分配
- Excel 导入（含字段映射对话框）
- **此时可以：导入名单 → 看到学生列表**

### 第 6 步：座位分配交互
- 点击分配、拖拽分配、拖拽交换、清空、空置
- `SeatService` 原子操作
- `HistoryService` 撤销重做（Ctrl+Z / Ctrl+Y）
- 多选（Ctrl+点击 / 框选）
- **此时可以：手动排座位了**

### 第 7 步：悬停信息 + 视觉打磨
- `SeatWidget` 的 tooltip（姓名/学号/标签/属性/备注）
- 悬停 / 选中 / 冲突 / 空置状态样式落地
- 状态栏提示

### 第 8 步：选区系统
- 选区创建（框选 / 按组 / 按行 / 按列）
- 选区命名保存与复用
- 选区批量操作（清空 / 空置 / 分配）

### 第 9 步：规则引擎（先校验，后搜索）
- 定义 `Rule` 数据结构与种类枚举
- `RuleEngine.check_hard()` 硬约束校验
- `RuleEngine.score()` 软约束评分
- **先接入"实时冲突检测与高亮"**（此时拖拽就能看到红色冲突）
- 单元测试覆盖每条规则

### 第 10 步：智能排位
- `Solver` 随机重启 + 爬山法
- `SolverProgressDialog`（QTimer 分片 + 进度 + 取消）
- `ConflictReportDialog`（硬约束满足情况 + 软约束得分明细）
- "换一批" / "锁定座位再排位"
- **这是核心功能，务必在规则引擎稳定后做**

### 第 11 步：自动轮换
- `RotationService`：区域轮换 + 平移轮换
- `RotationPanel`：选择轮换方式、配置参数、预览结果
- 轮换历史记录与回退

### 第 12 步：导出
- Excel 座位表导出（含讲台、过道、样式、附加 Sheet）
- PNG 导出（`grab()` + 缩放选项）
- `ExportDialog` 选项面板

### 第 13 步：项目存取完善
- 新建 / 打开 / 另存为 / 最近文件
- 自动保存与崩溃恢复
- `QSettings` 记住窗口布局、偏好

### 第 14 步：收尾与打磨
- 快捷键补全（Ctrl+N/O/S/Z/Y，Delete，Esc）
- 空状态引导（首次打开显示"新建项目 → 导入名单 → 一键排位"）
- 错误提示友好化（不要抛 Python traceback）
- 布局模板库（3 组×6 行×2 列 等常用配置）
- 整体视觉走查

### 第 15 步：打包与验收
- PyInstaller 打包单文件 exe
- 在干净 Windows 环境测试（无 Python）
- 用一个真实班级名单（40~60 人）做端到端验收
- 编写面向教师的使用说明（图文）

---

## 八、验收标准（摘要）

| 项 | 标准 |
|---|---|
| 布局 | 可配置 1~6 组，每组独立行列数，组间距可见 |
| 名单 | 支持 60 人 Excel 导入 < 2s，学号排序正确 |
| 交互 | 拖拽交换响应 < 100ms，冲突高亮即时 |
| 撤销 | 至少 50 步，跨操作类型一致 |
| 排位 | 60 座位 3 秒内出结果，硬约束满足率 ≥ 95%（合理规则下 100%） |
| 轮换 | 区域轮换 / 平移轮换结果符合预期，可回退 |
| 导出 | Excel 含讲台与过道，PNG 清晰可打印 |
| 稳定性 | 连续操作 30 分钟无崩溃、无内存泄漏 |
| 易用性 | 新用户 5 分钟内完成"导入名单 → 一键排位 → 导出" |

---
