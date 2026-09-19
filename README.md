# 教室自动排座位程序（Classroom Seating Editor）

一款面向中小学班主任 / 任课教师的**单机桌面端**教室座位编排工具。

配置教室布局 → 导入学生名单 → 用规则引擎一键排位 → 在可视化网格上拖拽微调 →
一键导出 Excel / PNG 座位表。全部数据保存在本地 `.seatproj` 项目文件里，
**无网络依赖、无账号体系**。

---

## 一、快速开始

### 1. 安装依赖

```powershell
# 建议使用虚拟环境
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

依赖仅 5 个包：`PyQt6`（界面）、`openpyxl`（Excel 读写）、
`pytest` / `pytest-qt`（测试）、`pypinyin`（姓名拼音排序，可选——
未安装时自动回退到 GB2312 编码序，不再需要任何第三方库）。

### 2. 启动

```powershell
.venv\Scripts\python.exe main.py
# 也可以直接打开某个项目
.venv\Scripts\python.exe main.py 高一3班.seatproj
```

### 3. 五分钟上手

1. **新建项目**（Ctrl+N）→ 菜单「编辑 → 教室布局」配置分组。默认是 3 组 × 6 行 × 2 列。
2. **准备名单**：菜单「文件 → 下载名单导入模板…」生成一份 Excel 模板（含填写说明与示例），
   填好班级名单后 **导入**（Ctrl+I），在字段映射对话框里确认列对应关系（模板的表头会自动对应好，直接确认即可）。
3. **设规则**（右侧「规则」页）——如「视力差学生必须在前 2 排」「优等生与需关注学生同桌」。
4. **一键排位**（F5）——3 秒内出结果，弹窗给出硬约束满足情况与软约束得分明细。
5. **拖拽微调** → **导出**（Ctrl+E 导出 Excel，Ctrl+Shift+E 导出 PNG）。

### 4. 名单导入模板（给老师的表格）

不确定名单该做成什么格式时，直接用程序生成一份：

* 菜单 **文件 → 下载名单导入模板…**，或左侧学生面板底部的 **下载导入模板** 按钮；
* 随包也带了一份：`resources/templates/学生名单导入模板.xlsx`（由
  `scripts/make_templates.py` 生成，可随时重新生成）。

模板共三张工作表：

| 工作表 | 内容 |
|---|---|
| `名单` | **只有表头**，从第 2 行开始逐行填写；性别列带「男 / 女」下拉；首行冻结 |
| `填写说明` | 每一列怎么填、可以自己加哪些列、常见问题 |
| `示例` | 6 行样例数据（学号以 `X` 开头），可整行复制到「名单」页再改成自己的数据 |

要点：

* 表头就是程序用来识别字段的标准名称，**不要改表头、不要删列**；
  换成「学籍号」「身高(cm)」这类常见写法也能自动识别，识别不了的列可在导入对话框手工映射。
* 学号、姓名必填；学号重复或为空的行会被跳过并列出行号，不影响其余行导入。
* 标签用「、」或逗号分隔（如 `班干部、优等生`），导入后自动进标签库并配色。
* 任意新增的数字列（体重 / 成绩 / 年龄……）都会成为「数值属性」，可直接用于排位规则。
* **示例页的数据不会被导入**——程序只读第一张表，所以模板可以放心分发。

另外，「编辑 → 教室布局」里的**快速模板**来自 `resources/templates/*.json`
（3 组×6 行×2 列、4 组×5 行×2 列、2 组×6 行×3 列……），可以按格式自行增删。

---

## 二、功能清单

| 编号 | 功能 | 说明 |
|---|---|---|
| F1 | 教室布局编辑 | 1~6 个分组，每组独立行数（1~12）/ 列数（1~8）/ 组名 / 组间距；讲台方向、座位卡片三档尺寸、是否显示组标题（三者都属于布局，随项目保存）；左侧参数 + 右侧实时预览；快速模板 |
| F2 | 学生名单管理 | 学号 / 姓名 / 性别 / 标签 / 数值属性 / 备注；`QTableView` + `QAbstractTableModel`；自然序与拼音排序；实时搜索与标签筛选；Excel 导入（字段映射 + 错误行高亮 + 可跳过继续）；**一键生成名单导入模板**；名单导出 |
| F3 | 标签与选区 | 12 色标签库（自动分配未用色）；批量打标签；选区框选 / 按组 / 按行 / 按列创建，命名保存复用；选区批量清空 / 空置 / 分配 |
| F4 | 智能排位 | 5 条硬约束 + 7 条软约束；随机重启 + 爬山法；排位报告（硬约束明细 + 软约束得分）；「换一批」「锁定座位再排位」 |
| F5 | 自动轮换 | 区域轮换（选区循环）、按排平移、按列平移、自定义向量、边缘回绕；轮换历史与回退到第 N 周；轮换前硬约束冲突提示 |
| F6 | 座位表交互 | 点击分配 / 拖拽分配 / 拖拽交换 / 拖拽移动 / 清空 / 空置 / 多选 / 撤销重做；悬停 400ms 显示完整学生信息；冲突实时高亮（红框 + ⚠） |
| F7 | 导出 | Excel 座位表（讲台、过道、样式、名单页、规则说明页）；PNG 图片（1x / 2x） |
| F8 | 项目存取 | `.seatproj`（UTF-8 JSON）；原子写入；每 2 分钟自动保存与崩溃恢复；启动时自动打开上次的项目；最近打开列表 |
| F9 | 撤销 / 重做 | 快照式，默认 50 步，跨操作类型一致；工具栏按钮 tooltip 显示操作名称 |

### 规则一览

**硬约束**（必须满足，违反处红色高亮）

| 规则 | 参数 |
|---|---|
| 固定座位 | 学生 + 座位 |
| 禁止相邻 | 学生 A + 学生 B（四邻域） |
| 区域限制 | 标签 / 学生 + 选区 |
| 排除区域 | 标签 / 学生 + 选区 |
| 前排必需 | 标签 / 学生 + 前 N 排 |

**软约束**（加权评分，尽量满足）

| 规则 | 参数 |
|---|---|
| 属性排序 | 数值属性 + 方向 + 按排 / 按组 |
| 属性分档 | 数值属性 + 档数 + 分布方式 |
| 同标签分散 | 标签 + 权重 |
| 同桌搭配 | 标签 A + 标签 B + 同桌 / 不同桌 |
| 避免重复 | 与上次方案比较 |
| 性别交替 | 权重 |
| 靠前偏好 | 标签 / 学生 + 权重 |

---

## 三、快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl+N` / `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S` | 新建 / 打开 / 保存 / 另存为 |
| `Ctrl+I` | 导入学生名单 |
| `Ctrl+E` / `Ctrl+Shift+E` | 导出 Excel / PNG 座位表 |
| `Ctrl+Z` / `Ctrl+Y` | 撤销 / 重做 |
| `Delete` | 清空选中座位 |
| `Ctrl+D` | 设为 / 取消空置 |
| `Ctrl+A` | 全选座位 |
| `Ctrl+L` / `Ctrl+Shift+L` | 锁定选中座位 / 解除全部锁定 |
| `Ctrl+B` | 教室布局设置 |
| `Ctrl+T` | 标签管理 |
| `F5` / `Ctrl+R` | 一键排位 / 换一批 |
| `F1` | 使用说明 |

鼠标：名单里选中学生 → 点击空座位即入座；从名单拖学生到座位；
从座位拖到另一个座位即交换；在座位表空白处拖拽框选、`Ctrl+点击` 增减座位；
右键座位弹出「清空 / 空置 / 锁定」菜单；悬停 0.4 秒显示学生完整信息。

---

## 四、界面预览

`scripts/render_preview.py` 可以随时把主窗口渲染成图片用于走查：

| 文件 | 内容 |
|---|---|
| `docs/preview/main_window.png` | 42 人班级的完整界面（左：名单；中：座位表；右：规则面板） |
| `docs/preview/seat_grid.png` | 座位表特写：讲台、过道、标签色条、姓名 + 学号后 4 位 |
| `docs/preview/conflict_state.png` | 冲突高亮：红框 + 浅红底 + 右上角 ⚠ |
| `docs/preview/student_panel.png` | 左侧名单面板特写：搜索 / 标签筛选 / 表格 / 底部按钮 |

生成命令：

```powershell
.venv\Scripts\python.exe scripts\render_preview.py
.venv\Scripts\python.exe scripts\grab_student_panel.py
```

---

## 五、项目结构

```
seateditor/
├── main.py                        # 入口（含全局异常兜底）
├── app/
│   ├── config.py                  # 常量、路径、QSettings key、模板/别名表
│   ├── models/                    # 模型层（纯数据，不依赖 Qt）
│   │   ├── student.py             # Student
│   │   ├── layout.py              # SeatGroup / Layout / Seat + 布局模板加载
│   │   ├── selection.py           # Selection
│   │   ├── rule.py                # Rule / RuleSpec / Violation + 规则元数据表
│   │   ├── assignment.py          # Assignment 工具 + Solution
│   │   └── project.py             # Project 聚合根、Tag、RotationRecord
│   ├── services/                  # 服务层（纯数据操作，不依赖 Qt）
│   │   ├── rule_engine.py         # 硬约束校验 + 软约束评分（增量评估）
│   │   ├── solver.py              # 随机重启 + 爬山法
│   │   ├── seat_service.py        # 分配 / 交换 / 移动 / 清空
│   │   ├── student_service.py     # 增删改查 / 排序 / 过滤 / 批量标签
│   │   ├── rotation_service.py    # 区域轮换 / 平移轮换 / 历史回退
│   │   ├── history_service.py     # 快照式撤销栈
│   │   └── export_service.py      # Excel / PNG 导出
│   ├── storage/                   # 持久化层
│   │   ├── project_store.py       # .seatproj 原子读写 + 自动保存
│   │   ├── excel_io.py            # Excel 导入 / 导出
│   │   └── roster_template.py     # 名单导入模板生成（名单 / 填写说明 / 示例 三张表）
│   ├── ui/                        # 界面层
│   │   ├── main_window.py         # 主窗口与全部业务编排
│   │   ├── dnd.py                 # 拖拽 MIME 载荷
│   │   ├── widgets/               # SeatWidget / SeatGridView / 名单表格 / 标签胶囊
│   │   ├── panels/                # 学生 / 规则 / 选区 / 轮换面板
│   │   ├── dialogs/               # 布局、导入映射、导出、排位进度、冲突报告等
│   │   └── style/                 # theme.py 设计常量 + app.qss 全局样式
│   └── utils/                     # seat_key / natural_sort / pinyin
├── resources/templates/           # 布局模板 JSON + 学生名单导入模板.xlsx（可直接增删）
├── scripts/                       # 随包工具：生成名单模板、渲染界面截图
└── docs/UI_CONTRACT.md            # 界面层接口契约（内部文档）
```

分层依赖是单向的：`ui → services → models`，`storage` 只被 `ui` / `services` 调用。
`models` 与 `services` 完全不依赖 PyQt，因此可以脱离界面进行单元测试与命令行批处理。

---

## 六、算法说明

### 排位：随机重启 + 爬山法

```
基础分 = Σ(软规则权重 × 满足度) − 10000 × 硬约束违反数
1. 可行性预检（人数 vs 座位数、规则自相矛盾、固定座位冲突……）
2. 固定座位 / 锁定座位先落位，其余学生随机填充（空座位留在靠后的排）
3. 爬山：随机取两个座位试交换，ΔScore ≥ 0 就接受，否则回滚
   连续 K 次无改进 → 重新随机初始化（重启）
4. 时间到（默认 3 秒）或用户点「停止」→ 返回历史最优解 + 报告
```

**性能关键**：`RuleEngine` 把每条规则展开成只依赖「自己座位 + 少量邻居座位」的
*term*，交换评估时只重算受影响的 term。因此单次交换评估的代价与座位总数、
学生总数**基本无关**：60 座位 + 5 条规则的增量评估约 **0.23ms/次**
（CPU 时间实测），即每秒可评估约 2000 次交换（一次交换要评估前后两次）。
单元测试用「增量打分的差 == 全量打分的差」这一断言（120 组随机交换 +
40 组目标值快捷路径）保证优化不改变语义。

> 说明：PRD 里「3 秒内完成 200+ 次重启」是估算值。本实现把「座位占用集合」
> 在整个搜索过程中固定，用**同一批座位上的学生排列**做爬山，因此每次重启都
> 是彻底重新洗牌，收敛质量比盲目提高重启次数更重要。实测 60 座位 / 3 秒
> 可完成约 6000 次交换评估，软约束满足度 85~95%、硬约束 0 违反。

### 界面不卡

排位不用线程，而是 `QTimer` + `Solver.iterate(SOLVER_CHUNK)` 分片驱动，
在 `SolverProgressDialog` 里显示进度、重启次数与当前得分，随时可停止。

---

## 七、开发与测试

仓库只随包提供两个开发工具（都在 `QT_QPA_PLATFORM=offscreen` 下运行，无需显示器）：

```powershell
# 重新生成随包资源：resources/templates/学生名单导入模板.xlsx（并列出布局模板）
.venv\Scripts\python.exe scripts\make_templates.py

# 渲染界面截图（README「四、界面预览」的图片即由此生成）
.venv\Scripts\python.exe scripts\render_preview.py
.venv\Scripts\python.exe scripts\grab_student_panel.py
```

若运行环境里 Qt 字体库为空（精简版 / 离屏），`theme.ensure_font_db()`
会自动从系统字体目录补注册字体，避免中文显示成方框。

### 本地自测（不入库）

测试与自检脚本刻意**不纳入版本控制**（见 `.gitignore`），只在本机保留：

| 脚本 | 作用 |
|---|---|
| `pytest tests -q` | 141 个单元测试（模型 / 规则引擎 / 求解器 / 轮换 / 撤销栈 / 持久化 / Excel / 名单模板 / 界面） |
| `scripts/smoke.py` | 数据层端到端自检（不启动界面）：布局→选区→规则→求解→轮换→存取→导出 |
| `scripts/check_widgets.py` | 界面控件离屏自检（座位表、名单表格、标签胶囊） |
| `scripts/gui_smoke.py` | 完整界面冒烟：名单 / 选区 / 规则 / 排位 / 拖拽 / 撤销重做 / 轮换 / 导出 / 存取 / 新建 |
| `scripts/main_smoke.py` | 入口冒烟：真正跑一遍 `main.py`（QSS + 字体回退 + 事件循环） |
| `scripts/soak.py 2000` | 稳定性压测：连续大量随机界面操作，检查状态始终自洽（约 40 次/秒） |
| `scripts/bench.py` | 增量评估性能基准 |

`requirements.txt` 里的 `pytest` / `pytest-qt` 就是给这些本地自测用的；
开发时把它们拉下来直接跑即可，仓库内容不受影响。

### 打包（PyInstaller）

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\pyinstaller.exe --noconfirm --windowed --name 教室座位编排 ^
    --add-data "app/ui/style/app.qss;app/ui/style" ^
    --add-data "resources;resources" main.py
```

---

## 八、已知边界

* **Python 版本**：代码按 3.10+ 编写风格，但刻意避开了 3.9+ 的运行期新语法，
  因此在 Python 3.8 上也能直接运行（本项目即在 3.8.6 + PyQt6 6.7.1 上验证）。
* **撤销栈只覆盖座位方案与空置状态**，不覆盖学生名单的增删改（删除学生会二次确认）。
* **轮换历史保存的是每一周“当时的排法”**；轮换后的最新方案用 `Ctrl+Z` 回退。
* 选区框选需要在座位表的空白处（页边距或过道）起拖；座位上的操作被拖拽换座占用，
  也可用 `Ctrl+点击` 逐个增减，或用右侧「选区」页的「按分组 / 按行 / 按列」快速创建。
* 教室若有多间且布局不同，请分别建立项目文件。
* **拖拽框选**在座位表空白处（页边距 / 过道 / 组标题区）起拖最顺手；
  座位卡片上的左键拖拽被「拖人换座」占用，需要逐个增减时用 `Ctrl+点击`。
* 程序会在每次改动后（每 2 分钟一次）自动保存到
  `%USERPROFILE%\.classroom_seating\autosave.seatproj`——**只调整教室布局也算改动**，
  即使还没保存成项目文件也不会丢；崩溃或异常退出后下次启动会询问是否恢复。
  运行期未捕获异常会写入同目录的 `error.log`。
* **下次启动会自动打开上次编辑的项目**（项目文件路径记在注册表 / QSettings 里）；
  想从零开始用 `Ctrl+N`，新建项目会清掉这个记忆。
  尚未保存成文件的新项目则依赖上面的自动保存来恢复。
* **布局快速模板 JSON 目前只读取 `name` / `groups` / `rows` / `cols`**；
  `podium_side`、`card_size`、`gap_after` 沿用布局对话框里的默认值
  （详见 `resources/templates/README.md`）。
