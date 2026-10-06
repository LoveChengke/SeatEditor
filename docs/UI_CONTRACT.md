# 界面层接口契约（内部文档）

> 所有 UI 代码位于 `app/ui/`。模型层（`app/models/`）与服务层（`app/services/`）
> 已完成并通过自检，UI 只允许**调用**它们，不得在其中新增业务逻辑。

## 0. 通用约定

* PyQt6（`from PyQt6.QtWidgets import ...`）。Python 3.8 兼容：文件头必须写
  `from __future__ import annotations`；不要使用 `match`、`X | Y` 运行期语法（注解里可以）。
* 颜色 / 尺寸一律取自 `app/ui/style/theme.py` 的 `Color` / `CARD_SIZE_LABELS` /
  `seat_size()` / `aisle_width()` / `PANEL_STUDENT_WIDTH` 等常量，不要硬编码十六进制色。
* 控件需要白底卡片时设置 `objectName`：`Panel` / `SidePanel` / `PanelTitle` / `Hint` /
  `Primary`（主按钮）/ `Danger` / `Ghost` / `HLine`，全局 QSS 已定义。
* 低频 / 高级选项用 `common.CollapsibleSection`（`app/ui/common.py`）包起来，
  **默认收起**；区块标题的 `objectName` 是 `SectionToggle`。界面上只留主流程控件。
* 文案规则：短句 + 步骤化（`1 … → 2 … → 3 …`），不写长段落；按钮文字用动词开头。
* 尺寸规则：主窗口用 `MainWindow._fit_window_to_screen()`（按 `availableGeometry()`
  收口）并在 `main.py` 里 `showMaximized()` 启动；对话框构造完调一次
  `common.fit_to_screen(self)`。**任何菜单的 `sizeHint().height()` 都要小于屏幕
  可用高度**——一屏放不下的菜单在高 DPI 下会直接顶出屏幕（规则菜单因此拆成
  「必须满足类 / 尽量满足类」两个子菜单）。
* 主题是**深色**（近黑底 + 亮蓝强调色）：启动时由 `theme.apply_dark_theme(app)`
  统一装调色板、QSS 与字体，不要在各处再调 `setStyleSheet` / `setPalette`。
  QSS 里的图片路径写占位符 `@ASSET_DIR@`（`app/ui/__init__.py:load_stylesheet`
  会替换成 `app/ui/style/assets/` 的绝对路径）；动作图标放 `resources/icons/*.svg`
  （`config.ICONS_DIR`），通过 `QAction.setIcon` 使用。
* 座位坐标类型是三元组 `(group, row, col)`（下文写作 `Coord`）；
  `app/utils/seat_key.py` 提供 `make_key` / `parse_key`。
* 项目状态在 `app.models.project.Project` 上；通过 `project.subscribe(cb)` 监听变更，
  `cb(event: str, payload)`，事件名见 `app/models/project.py` 的 `EV_*` 常量。
* 所有会修改项目的操作**必须**通过 `MainWindow`（对话框与面板只发出信号或返回数据，
  不要自己直接改 `project`，唯一例外是文末标注「可直接改」的项）。

## 1. 已冻结：座位表控件（由主智能体实现）

### `app/ui/widgets/seat_widget.py`
```python
class SeatWidget(QFrame):
    clicked = pyqtSignal(object, int)              # (seat: Coord, modifiers: int)
    double_clicked = pyqtSignal(object)            # (seat,)
    context_requested = pyqtSignal(object, object) # (seat, global QPoint)
    seat_dropped = pyqtSignal(object, object)      # (src_seat, dst_seat)
    student_dropped = pyqtSignal(str, object)      # (sid, dst_seat)
    drag_started = pyqtSignal(object)              # (seat,)

    def __init__(self, seat: Coord, parent=None) -> None: ...
    @property
    def seat(self) -> Coord: ...
    def set_group_name(self, name: str) -> None: ...
    def set_card_size(self, size_name: str) -> None: ...     # "small"/"medium"/"large"
    def set_show_sid(self, flag: bool) -> None: ...
    def bind(self, student, tag_color: str) -> None: ...     # student: Student | None
    def set_disabled(self, flag: bool) -> None: ...
    def set_conflict(self, flag: bool, tip: str = "") -> None: ...
    def set_selected(self, flag: bool) -> None: ...
    def set_highlight(self, flag: bool) -> None: ...         # 拖拽放置目标
```

### `app/ui/widgets/podium_widget.py`
```python
class PodiumWidget(QWidget):
    def __init__(self, text: str = "讲　台", parent=None) -> None: ...
```

### `app/ui/widgets/seat_grid_view.py`
```python
class SeatGridView(QWidget):
    seat_clicked = pyqtSignal(object, int)             # (seat, modifiers)
    seat_double_clicked = pyqtSignal(object)
    seat_context_requested = pyqtSignal(object, object)
    seat_swap_requested = pyqtSignal(object, object)   # (src, dst)
    student_drop_requested = pyqtSignal(str, object)   # (sid, seat)
    selection_changed = pyqtSignal(set)                # set[Coord]

    def __init__(self, parent=None) -> None: ...
    def set_project(self, project) -> None: ...
    def rebuild(self) -> None: ...                     # 依据 layout 重建
    def refresh(self, seats=None) -> None: ...         # 局部刷新（None = 全部）
    def set_show_sid(self, flag: bool) -> None: ...
    def set_show_group_title(self, flag: bool) -> None: ...
    def set_conflicts(self, mapping: dict) -> None: ...# {seat_key: 冲突文案}
    def set_selected(self, seats) -> None: ...
    def selected_seats(self) -> set: ...
    def clear_selection(self) -> None: ...
    def widget_at(self, seat) -> "SeatWidget | None": ...
    def seat_at_pos(self, pos) -> "Coord | None": ...
    def set_selection_visible(self, flag: bool) -> None: ...
```

### `app/ui/widgets/student_table.py`
```python
class StudentTableModel(QAbstractTableModel):
    def __init__(self, project, service, parent=None) -> None: ...
    def set_students(self, students: list) -> None: ...
    def student_at(self, row: int): ...                # -> Student | None
    def refresh(self) -> None: ...
    def sort(self, column: int, order) -> None: ...    # 支持点击列头排序
    def flags(self, index): ...                        # 必须含 ItemIsDragEnabled
COLUMNS = ["学号", "姓名", "性别", "标签", "数值属性", "已分配座位"]

class StudentTableView(QTableView):
    """支持多选、拖拽（mime: application/x-student，内容为 sid）、右键菜单。"""
    students_dropped = pyqtSignal(list)   # 拖出时不需要，仅用于内部
    seat_drop_requested = pyqtSignal(str) # 把座位上的学生拖回名单：座位 key（取消入座）
```

**拖拽的两个坑**（都踩过，改的时候别退回去）：

* `flags()` 不返回 `Qt.ItemFlag.ItemIsDragEnabled` 时，`QAbstractItemView` 根本不会
  调用 `startDrag()`——表现是「按住名字拖半天没反应」，而且没有任何报错。
* `startDrag()` 里只能抓**被拖的那几行**（`StudentTableView._drag_pixmap()`）；
  抓 `viewport().rect()` 会让拖拽残影变成一整块半透明表格，看着像花屏。

QSS 上 `QTableView::item:selected` 必须写在 `QTableView::item:hover` **后面**
（同权重后写的赢），否则鼠标停在已选中的格子上时那一格会掉回悬停底色，
整行高亮像被挖了个洞；`QListWidget::item:*` 等同理。

带下拉箭头的按钮要注意右侧留白：`QToolButton[popupMode="1"]`（MenuButtonPopup）
与 `[popupMode="2"]`（InstantPopup，标签筛选 / 添加规则用的就是它）都要给
`padding-right`，否则箭头会压在文字上。

### `app/ui/widgets/tag_chip.py`
```python
class TagChip(QFrame):
    removed = pyqtSignal(str)      # tag name（仅 closable=True 时发出）
    def __init__(self, name: str, color: str, closable: bool = False, parent=None) -> None: ...

class TagFlow(QWidget):
    """自动换行的标签胶囊容器。"""
    removed = pyqtSignal(str)
    def set_tags(self, tags: list) -> None: ...   # [(name, color), ...]
```

## 2. 对话框（交给子智能体 A 实现）

每个对话框只负责**收集用户输入**，返回数据；除标注外不直接改 `project`。

| 文件 | 类 | 构造 | 结果属性 |
|---|---|---|---|
| `dialogs/layout_editor_dialog.py` | `LayoutEditorDialog` | `(project, parent=None)` | `.result_layout`（accept 后为新的 `Layout`） |
| `dialogs/import_mapping_dialog.py` | `ImportMappingDialog` | `(preview, parent=None)` | `.mapping: dict[str,str]`、`.skip_invalid: bool` |
| `dialogs/export_dialog.py` | `ExportDialog` | `(project, parent=None)` | `.mode: str`（`"excel"`/`"png"`）、`.options: ExportOptions`、`.png_scale: int` |
| `dialogs/solver_progress_dialog.py` | `SolverProgressDialog` | `(project, parent=None, locked_seats=None)` | `.solution: Solution | None` |
| `dialogs/conflict_report_dialog.py` | `ConflictReportDialog` | `(solution, project, parent=None)` | 无（只展示；内容块来自 `widgets/result_report.py`，与底部面板同源） |
| `dialogs/rule_edit_dialog.py` | `RuleEditDialog` | `(project, rule=None, parent=None)` | `.result_rule: Rule` |
| `dialogs/student_edit_dialog.py` | `StudentEditDialog` | `(project, student=None, parent=None)` | `.result_student: Student`（接受时已 `ensure_tag`） |
| `dialogs/tag_manager_dialog.py` | `TagManagerDialog` | `(project, parent=None)` | 直接改 `project.tags`（允许） |
| `dialogs/text_import_dialog.py` | `TextImportDialog` | `(project, parent=None)` | `.students: list[Student]` |
| `dialogs/onboarding_dialog.py` | `OnboardingDialog` | `(parent=None, steps=None)` | `.dont_show_again()`、`.taken_action()`（步骤回调由主窗口注入） |
| `dialogs/ai_settings_dialog.py` | `AISettingsDialog` | `(endpoint, api_key, model, parent=None)` | `.result_config: (endpoint, api_key, model)` |


要点：

* `ImportMappingDialog`：表头一行一个 `QComboBox`，选项为
  `excel_io.FIELD_LABELS` 的全部字段 + 每个表头对应的 `attr:<名字>` 选项；
  默认值取 `preview.mapping`；底部复选框「跳过错误行继续导入」。
* `SolverProgressDialog`：用 `QTimer` + `Solver.iterate(SOLVER_CHUNK)` 分片驱动
  （见 `app/config.py` 的 `SOLVER_CHUNK`），显示进度条、已重启次数、当前方案满意度，
  提供「停止」按钮；关闭窗口等同于停止。求解完成后 `self.solution` 为 `Solution`。
  若 `Solver.prepare()` 抛 `SolverError`，用 `QMessageBox.warning` 提示并 `reject()`。
* `ConflictReportDialog`：上半部分「必须满足」清单（✅/⚠️ + 明细），
  下半部分「尽量满足」情况（总分 + 每条规则的进度条与重要程度）。
* `RuleEditDialog`：表单**由 `rule.RULE_SPECS[kind].fields` 动态生成**，
  控件类型见 `app/models/rule.py` 的 `F_*` 常量；
  学生下拉显示「姓名（学号）」、数据为 sid；标签下拉取 `project.tag_names()`；
  区域下拉取 `project.selections`；数值属性下拉取 `project.attr_names()`；
  座位下拉用「第 N 组 第 M 排 第 K 列」，数据为 `"g-r-c"`；
  「新增」时先用 `make_rule(kind)` 造默认规则；校验用 `rule.validate()`。
* `AISettingsDialog`：服务商预设下拉（`config.AI_PRESETS`，切换自动填地址/模型）
  + 接口地址 + 模型名 + API Key（密码框）+「测试连接」（真实发一个最小请求）。
  确认后由调用方把 `result_config` 写入 QSettings 的 `SK_AI_ENDPOINT/SK_AI_API_KEY/SK_AI_MODEL`。
* `LayoutEditorDialog`：左侧参数面板（组数、每组的行/列/组名/组间距、上下移动/删除、
  「添加分组」，以及「＋/− 一排 / 一列」的步进按钮）+ 右侧实时预览
  （用 `SeatGridView` 或简化的 `QGridLayout` 均可）；
  顶部快速模板下拉取自 `layout.LAYOUT_TEMPLATES`（含单排 / 单列）；
  参数区上方用一句话说明当前形状（`单排：1 排 × 8 列，共 8 个座位`）；
  讲台方向常驻，座位卡片尺寸与显示组标题放进「高级选项」折叠区；
  用 `QSpinBox` 的 range 限制在 `layout.MIN_ROWS..MAX_ROWS` 之类常量内。

## 2.4 主题系统（黑夜 / 白天）

- 色板单一真源在 `app/ui/style/theme.py` 的 `PALETTES`（`DARK_PALETTE` /
  `LIGHT_PALETTE`，键即 QSS 令牌）；`app.qss` 里的颜色全部是 `@TOKEN@` 占位符，
  由 `app/ui/__init__.py` 的 `load_stylesheet(palette)` 填充。
- `Color` 是元类代理：全代码 `Color.X` 读取当前色板，切换主题即时生效；
  `set_print_mode` 的临时覆盖用 setattr / delattr 与之配合。
- 切换入口：视图菜单「深色模式」勾选框（`act_dark_mode`）→
  `MainWindow._on_theme_toggled` → `theme.apply_theme(app, dark)` +
  `apply_dark_titlebar(self, dark)`（原生标题栏明暗联动）+ 写
  `config.SK_THEME`；启动时 main.py 按该键选择主题。
- 渲染走查脚本必须 `motion.set_reduced_motion(True)`，否则静态截图会抓到
  淡入动画的半透明中间帧。
- 骨架专用令牌：`BG_RAIL`（活动栏）、`BG_TABBAR`（工具栏 / 面板头 / 状态栏，
  比面板暗一档）、`TAB_ACTIVE_BG`（选中的标签条与内容同色，两档之间只靠
  1px 分隔线划界）。改版新增的这三档统一了「窗口骨架」这一层。

## 2.5 程序内窗口的贴靠与关闭按钮

- 浮动的停靠面板（侧边栏 / AI 助手 / 底部面板）拖近**主窗口**边缘 / 角落
  时磁性贴齐：`MainWindow.eventFilter` 捕获 QDockWidget 的 Move →
  `motion.compute_dock_snap_target`（四向全开，相邻两向命中自动组合成角，
  如左下 `left+bottom`、右下 `right+bottom`）→ 200ms EASE_IN_OUT 滑入。
- 自绘标题栏：除活动栏外，所有 `QDockWidget` 经 `setTitleBarWidget` 挂
  `common.HeaderBar`（标题 / 标签条 + 右侧 26×26 图标键 + 放大的关闭键，
  关闭键悬停变红；点击 = `dock.close()`，可从视图菜单再打开）。
  原生的 14px 关闭键在触屏 / 高 DPI 下点不中，且 `grab()` 呈现不可控。
- **停靠窗口必须给 `windowTitle`**（`QDockWidget("侧边栏", self)`）：视图菜单里的
  面板开关项文字取自它，浮动时的系统标题栏也用它。改自绘标题栏时把标题弄丢过
  一次——菜单里就只剩三个「有勾没字」的空项，且浮动窗口标题为空。
  `tests/test_shell.py::test_no_action_is_left_without_text` 守着这条。
- 活动栏（`rail_dock`）是唯一不带标题栏的停靠面板：`NoDockWidgetFeatures`
  + `common.blank_title_bar()`（零高度标题栏；空 QWidget 的 sizeHint 不可靠，
  有的平台会留出一行空白）+ `setFixedWidth(48)`。

## 2.5b 界面骨架：活动栏 / 侧边栏 / 视图头 / 底部面板

2026 改版把「左右两块面板并排」收成编辑器式布局，四个新控件都在
`app/ui/widgets/`（图标）与 `app/ui/common.py`（骨架）：

- `widgets/activity_bar.py` — `ActivityBar`：48px 图标列。上半 `add_page()`
  是侧边栏页面（学生名单 / 排座规则 / 常用区域 / 定期换座），下半
  `add_action()` 是常驻动作（AI 助手 / 明暗切换 / 帮助）。发出
  `clicked(key)` 由主窗口 `_on_rail_clicked` 分派；选中项左侧 2.5px 主色竖条。
  **再点一次当前页 = 收起侧边栏**（同 VS Code），侧边栏隐藏时全列不亮
  （`_sync_rail_active` 跟着 `side_dock.visibilityChanged` 走）。
- `widgets/icons.py` — 单色矢量图标集（`paint_glyph` / `ink_box`）。
  不用 SVG 文件是为了跟着主题即时变色，也避开微软雅黑缺码位导致的方框字。
  坐标按 16×16 设计，按目标矩形缩放，线宽同步缩放。三条硬规矩：
  1. **墨迹归一化**：每个图标真正画出来的部分在 16 单位空间里占比不同
     （箭头 58%、实心圆 92%），`GLYPH_ZOOM` 把每颗都校正到 ~85%，
     否则同一个盒子里图标一大一小（「图标太小」多半是这么来的）。
     改图标签后跑 `scripts/calibrate_icons.py` 重新出这张表。
     缩放必须按**缩放后**尺寸居中，否则放大的图形会从盒子左上角往右下拉、
     右下角被切掉（这个 bug 是自校准脚本量出来的）。
  2. **不依赖字体**：问号这类形状用线条画（原来 `drawText` 的字号写在 16 单位
     空间里，缩放后比圆圈还大、溢出圆边，浅色下就是个怪符号）。
  3. 尺寸：活动栏 28px、面板头图标键 18px；矮窗档 22px。
- `app/ui/icon_loader.py` — 工具栏 / 菜单那批 SVG 图标的**按主题重新着色**：
  SVG 描边色写死在文件里（`#C9CED6`），浅色主题下贴在近白工具栏上等于看不见。
  运行时读 SVG 文本替换描边色 → `QSvgRenderer` 渲染成 QIcon（按颜色进缓存），
  切换主题时 `MainWindow._recolor_action_icons()` 全量换一遍。
- 图标专用色令牌 `ICON_MUTED`（浅色 #46566B / 深色 #A7B2BF）：线条图标比文字细，
  用次要文字色在浅色底上会发虚。活动栏选中项底色用 `RAIL_ACTIVE_BG`
  ——深色主题下光靠「把活动栏压暗」拉不开差距（面板本来就接近黑）。
- `common.IconButton` — 方形图标键（活动栏、面板头、视图头共用）。
  底色 / 悬停 / 选中全在 `paintEvent` 里画，不去和全局 QPushButton 样式叠加。
  `danger=True` 时悬停变红（关闭键）。
  **尺寸必须自己报 `sizeHint` / `minimumSizeHint`**：全局样式表里的
  `QPushButton { min-height: 20px }` 会**覆盖**控件的 `setFixedSize`，而切换主题
  会重新套用样式表 → 布局改用 QSS 算出来的高度 → 44px 高的活动栏格子被压回
  20px。这就是「一点切换黑夜模式控件就缩在一起」的成因。
  `tests/test_shell.py::test_theme_toggle_keeps_chrome_sizes` 守着这条。
- `common.HeaderBar` — 面板 / 内容区顶部的 32px 细横条。三种用法靠
  `object_name` 分档：`HeaderBar`（程序内窗口标题栏，带关闭键）、
  `HeaderBar` + `add_leading(tab_bar)`（底部面板）、`EditorHeader`（中央视图头，
  无关闭键）。`add_button()` / `add_menu_button()` 加右侧图标动作，
  `add_leading()` 把内容（标签条）插到最左。
- 中央 `EditorHeader` 右侧的图标键全部**镜像**同名 `QAction`
  （`_build_editor_buttons` 里 `clicked → act.trigger`、`act.toggled → setChecked`），
  菜单里改和视图头里改是同一份状态。
- 底部面板（`bottom_dock`）：`QTabBar#PanelTabs`（冲突 / 排位结果）放在头部
  横条里，内容是与标签同步的 `QStackedWidget`。**排位完成不再弹模态报告**
  → `show_report()` 填「排位结果」页并打开面板；冲突数在状态栏是可点的
  （`_StatusLink`），点一下开「冲突」页，双击清单条目定位到座位
  （`SeatGridView.focus_seats`）。


## 2.5c 自适应（窄窗 / 矮窗 / 小屏）

`MainWindow._apply_responsive_layout()` 在每次 resize 与面板开关时重算，
判据是**预算与下限**，不是写死的断点：

| 优先级 | 面板 | 让位条件 |
|---|---|---|
| 1（最高） | 座位表 | 永远优先 \(≥ `GRID_MIN_WIDTH` 380 × `GRID_MIN_HEIGHT` 260\) |
| 2 | 侧边栏 | 宽度不够时收；够用时还原 |
| 3 | AI 面板 | 先于侧边栏让位（它是辅助面板） |
| 4 | 底部面板 | 座位表纵向拿不到下限时收 |

几处必须按这个顺序理解的细节：

- **最小尺寸按骨架算，不写死**：`_content_min_size()` = 活动栏 + 侧边栏（紧凑档）
  + 座位表下限。写死一个比布局自身最小值更小的数，窗口就能被压到侧边栏与
  座位表双双消失、只剩一根 48px 活动栏——那就是「界面缩成一根条」的成因。
- **开着的面板会抬高最小尺寸**：`_apply_responsive_layout` 末尾把
  `setMinimumSize` 算成当前布局的真实需要，于是「窄窗里再开一个面板」的结果是
  窗口被顶大到装得下，而不是把座位表挤没。
- **`_xxx_user_open` / `_xxx_auto_hidden` 两个标记**：面板的 `visibilityChanged`
  记录用户意愿（点活动栏 / `×` / 视图菜单都算），自适应只回滚**自己**收掉的
  面板；启动时那批可见性变化由 `_finish_startup()`（showEvent 后一个事件循环）
  排除，免得被当成用户操作。
- **预算按面板最小宽度算**（`_panel_cost`）：按实际宽度算会出现「拖宽侧边栏 →
  判定放不下 → 收掉 → 空间又够了 → 打开」的抖动。
- **`room = max(窗口宽, 屏幕宽 - 20)`**：窗口比屏幕窄是用户自己拉的，
  只有连屏幕都放不下才真需要收面板。
- **视图头的教室摘要在窄窗里收起**：一行长文字会把中央区最小宽度顶到 450px
  （Qt 对不换行的中文标签就是按整行算最小宽度），摘要改用悬停提示承载。
  同类坑在 `panels/ai_panel.py` 的配置提示上，那里加了 `setWordWrap(True)`
  （原本一个标签顶出 313px，把 AI 面板的最小宽度也传染给了主窗口）。
- **矮窗**：活动栏图标行从 24px/44px 收到 20px/36px（`ActivityBar.set_compact`），
  底部面板高度上限取窗口的 40%。
- `_on_dock_visibility_changed` 里的 `except RuntimeError` 是必要的：窗口析构
  途中子面板仍会报告可见性变化，此时再碰 MainWindow 的任何成员都会抛。

## 2.5d 应用图标

- 源文件是**两张 SVG**（矢量、可编辑，单一真源）：
  `resources/app_icon.svg`（完整构图：讲台 + 3×2 座位网格，其中一个座位点亮）
  与 `resources/app_icon_small.svg`（小尺寸构图：讲台 + 一个座位 + 人）。
  为什么分两张：完整版的座位缩到 16px 只有 2.9px、间隙 0.9px，连不成形；
  小尺寸换构图是图标集的标准做法。
- 生成物 `resources/app_icon.ico`（16/24/32/48/64/128/256 七个尺寸，≤32 用
  小尺寸构图）与 `resources/app_icon.png`（256，给 README / 非 Windows 用），
  由 `scripts/make_app_icon.py` 生成；改图标只改 SVG 再重跑脚本。
  ICO 是脚本手工拼的（Qt 的 ico 插件写不出多尺寸文件）。
- 启动时 `app/ui.install_app_icon(app)`（main.py 里调用）装窗口图标，
  并在 Windows 上设 `AppUserModelID` —— 不设的话任务栏会把程序归到
  `python.exe` 名下、显示 Python 图标，跟别的 Python 程序挤成一组。
- 校验在 `tests/test_app_icon.py`：源文件、ICO 尺寸齐全、每张图是 PNG、
  装到 QApplication 上不为空。

## 2.6 动效系统（`app/ui/motion.py`）

按 beUI 动效指南（beui.dev/docs/motion-patterns）实现的令牌与助手，
**所有动效改动必须以此处为唯一来源**：

| 令牌 | 值 | 用途 |
|---|---|---|
| `EASE_OUT` | cubic-bezier(0.16, 1, 0.3, 1) | 入场 / 退场 |
| `EASE_IN_OUT` | cubic-bezier(0.77, 0, 0.175, 1) | 屏上移动（窗口吸边） |
| `DUR_REVEAL` | 220ms | 内容揭示（opacity + 位移 8px） |
| `DUR_SWAP_IN/OUT` | 180/120ms | 内容交换（离场快于进场） |
| `DUR_SNAP` | 200ms | 窗口吸边滑入 |
| `STAGGER_STEP` | 60ms | 相邻元素错峰（>5 个元素退化为整组揭示） |

接入点：对话框 `polish_dialog()`（fit_to_screen + 揭示）、右侧页签
`currentChanged → motion.swap_in`、引导卡片 / AI 结果行 `stagger_reveal`、
主窗口启动 `motion.reveal_window`（main.py）。

**窗口吸边**（仿 Windows 贴靠）：`MainWindow.moveEvent` → `compute_snap_target`
（纯函数，上 / 左 / 右三向，阈值 24px）→ 200ms EASE_IN_OUT 滑入；
系统开启「减少动态效果」时全局降级为直接到位（吸附行为保留、动画去除）。

## 3. 面板（交给子智能体 B 实现）

面板是 `QWidget`，只发信号 + 读 `project`，不直接修改项目。

### `panels/student_panel.py`
```python
class StudentPanel(QWidget):
    selection_changed = pyqtSignal(list)      # 选中的 sid 列表
    import_requested = pyqtSignal()           # 交给 MainWindow 走文件对话框
    add_requested = pyqtSignal()
    edit_requested = pyqtSignal(str)          # sid
    delete_requested = pyqtSignal(list)       # sids
    tag_requested = pyqtSignal(list)          # sids（打开“批量打标签”）
    export_requested = pyqtSignal()
    template_requested = pyqtSignal()         # 下载 Excel 名单导入模板
    def __init__(self, project, parent=None) -> None: ...
    def refresh(self) -> None: ...
    def selected_sids(self) -> list: ...
    def current_sid(self) -> str: ...
    def clear_selection(self) -> None: ...
```
内含：搜索框（实时过滤）、标签筛选下拉（多选，交集/并集切换）、性别与「已分配/未分配」
筛选、`StudentTableView`、人数统计标签，以及底部按钮
**导入 Excel 名单（主）/ 添加 / 编辑 / 删除 / 批量标签 / 更多名单操作**——
粘贴文本导入、导出名单、下载模板都属于低频入口，收进「更多名单操作」菜单，
不再各占一个按钮（同一功能在「文件」菜单里也有一份）。
表格必须支持把学生拖到座位表（mime `application/x-student`）。
表格与面板本身都要接住 `application/x-seat` 的拖放（从座位拖回名单 = 取消入座），
经 `clear_seat_requested(seat_key)` 交给主窗口处理——面板照旧不直接改项目。
「更多名单操作」是 **`QPushButton#MenuButton`**（不再是 QToolButton）：
这样才能和上面的按钮共用同一套 QSS，高度一致；箭头位置由
`QPushButton#MenuButton::menu-indicator` 单独给。

### `panels/rule_panel.py`
```python
class RulePanel(QWidget):
    rules_changed = pyqtSignal()
    ai_requested = pyqtSignal()   # 大白话生成规则（AI）；主窗口负责打开对话框
    def __init__(self, project, parent=None) -> None: ...
    def refresh(self) -> None: ...
```
内含：必须满足 / 尽量满足两个分组列表（`QListWidget`，每项带勾选框与「人话描述」），
工具栏「添加规则」（`QMenu`：第一项是 `自定义规则（向导）…`，其余 27 种规则按
`HARD_KINDS` / `SOFT_KINDS` 拆成 `按类型添加：必须满足类…` / `按类型添加：尽量满足类…`
两个子菜单——单列 27 条会顶出屏幕）、「编辑」、「删除」、
「上移/下移」（可选），尽量满足项显示重要程度。编辑走 `RuleEditDialog`，确认后
调用 `project.add_rule` / `project.remove_rule` / 直接改 `rule.params` 后 `project.notify("rules")`。

### `panels/ai_panel.py`
```python
class AIRulePanel(ProjectPanel):
    rules_ready = pyqtSignal(list, bool)   # (勾选的规则草稿, 添加完马上排位)
    def __init__(self, project=None, parent=None) -> None: ...
```
主窗口右侧新增的「AI 助手」停靠窗口（`QDockWidget`，objectName `AIDock`，
默认隐藏，工具栏「AI 助手」/ 排位菜单「AI 助手」/ 视图菜单开关三处入口打开）。
输入大白话 → `services/ai_client.py` 调 OpenAI 兼容接口 → `parse_rules_payload`
解析成草稿 → 勾选 + `describe_rule` 预览 + 「编辑」走 `RuleEditDialog` →
`rules_ready` 交给主窗口落库。AI 连接配置（`ai/*` 设置键）由面板直接读写
QSettings。生成中关闭面板会 abort 在途请求。

### `panels/selection_panel.py`
```python
class SelectionPanel(QWidget):
    apply_requested = pyqtSignal(str)         # selection id：高亮该选区
    batch_clear_requested = pyqtSignal(set)   # set[Coord]
    batch_disable_requested = pyqtSignal(set)
    batch_assign_requested = pyqtSignal(set)
    selection_created = pyqtSignal(str, set)  # name, seats —— 由 MainWindow 落库
    selection_deleted = pyqtSignal(str)
    selection_renamed = pyqtSignal(str, str)  # id, new name
    def __init__(self, project, parent=None) -> None: ...
    def refresh(self) -> None: ...
    def set_current_seats(self, seats: set) -> None: ...   # 来自座位表的当前选区
```
内含：区域列表（名称 + 座位数 + 颜色块）、按钮「把选中的座位存为区域」
（弹 `QInputDialog` 取名字，发 `selection_created`）、「应用/高亮」、「重命名」、「删除」；
批量操作（清空 / 留空 / 批量分配）与快捷区域（按分组 / 按排 / 按列 →
发 `selection_created`）分别放进两个 `CollapsibleSection`，**默认收起**。

### `panels/rotation_panel.py`
```python
class RotationPanel(QWidget):
    preview_ready = pyqtSignal(object)        # RotationPlan
    apply_requested = pyqtSignal(object)      # RotationPlan
    rollback_requested = pyqtSignal(int)      # week
    def __init__(self, project, parent=None) -> None: ...
    def refresh(self) -> None: ...
```
内含：模式选择（定期换座 / 按排平移 / 按列平移 / 自定义向量）、参数控件
（区域多选、Δ排、Δ列）、「预览」按钮（用 `RotationService` 生成 `RotationPlan`）、
「应用换座」按钮、历史周列表（第 N 周 + 回退按钮）、以及 `plan.warnings` 的提示区。
`RotationService` 用法见 `app/services/rotation_service.py`。
面板顶部要写一句「进阶功能」的说明，让只想排一次座的老师知道这页可以不管。

## 4. 主窗口（由主智能体实现）

`app/ui/main_window.py` 的 `MainWindow(QMainWindow)`，版式自 2026 改版起为：

```
菜单栏
工具栏（主线）
├ 活动栏 rail_dock（48px 固定，无标题栏）           ← widgets/activity_bar.py
├ 侧边栏 side_dock（页面栈：名单 / 规则 / 区域 / 换座）← HeaderBar 标题 + ⋯ + ×
├ 中央 central_area：EditorHeader（视图头）+ SeatGridView
├ AI 助手 ai_dock（右侧，默认可关）                 ← HeaderBar + AI 设置图标键
├ 底部面板 bottom_dock（PanelTabs：冲突 / 排位结果）  ← HeaderBar 装 QTabBar
状态栏（摘要 + 自动保存告警 + 可点的冲突数）
```

- 页面切换：`show_sidebar_page(key)`（活动栏与新手引导都走它）；再点当前页收起，
  `_sync_rail_active` 跟着 `visibilityChanged` 更新活动栏高亮。
- 构建顺序有依赖：`_build_central → _build_panels → _build_bottom → _build_actions`
  （视图头的图标键要镜像 QAction，所以放在 `_build_actions` 末尾的
  `_build_editor_buttons`）；侧边栏头部「⋯」因此**不复用 QAction**，直接建菜单项。
- 停靠状态用 `config.SK_STATE`（键名 `window/state_v2`）：新版窗口集合变了，
  老状态会让 `restoreState` 把新面板摆错位置，所以换键名而不是做迁移。
- 排位结果不再走模态窗：`show_report()` → 底部面板「排位结果」页；
  冲突清单由 `_refresh_conflict_panel`（在 `_update_conflicts` 里）维护。

菜单与快捷键：文件（新建、打开、保存、另存为、最近文件、导入、导出、自动保存与
崩溃恢复）、编辑（撤销 `Ctrl+Z` / 重做 `Ctrl+Y`，另给 `Ctrl+Shift+Z` 兜底）、
视图（显示学号、组标题、区域高亮、卡片尺寸、深色模式、侧边栏 / AI 助手 /
底部面板开关）、排位（一键排位、换一批、AI 助手、查看排位结果、清空全部座位）、
帮助（新手引导、快捷键说明、关于）。

工具栏**只放一条主线**：打开 → 保存 → 教室布局 → 导入名单 → AI 助手 / 一键排位 →
导出座位表 → 撤销 / 重做；新建、粘贴导入、名单模板等低频入口留在菜单里。
