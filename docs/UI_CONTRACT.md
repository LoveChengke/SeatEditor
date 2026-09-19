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
COLUMNS = ["学号", "姓名", "性别", "标签", "数值属性", "已分配座位"]

class StudentTableView(QTableView):
    """支持多选、拖拽（mime: application/x-student，内容为 sid）、右键菜单。"""
    students_dropped = pyqtSignal(list)   # 拖出时不需要，仅用于内部
```

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
| `dialogs/conflict_report_dialog.py` | `ConflictReportDialog` | `(solution, project, parent=None)` | 无（只展示） |
| `dialogs/rule_edit_dialog.py` | `RuleEditDialog` | `(project, rule=None, parent=None)` | `.result_rule: Rule` |
| `dialogs/student_edit_dialog.py` | `StudentEditDialog` | `(project, student=None, parent=None)` | `.result_student: Student`（接受时已 `ensure_tag`） |
| `dialogs/tag_manager_dialog.py` | `TagManagerDialog` | `(project, parent=None)` | 直接改 `project.tags`（允许） |
| `dialogs/text_import_dialog.py` | `TextImportDialog` | `(project, parent=None)` | `.students: list[Student]` |

要点：

* `ImportMappingDialog`：表头一行一个 `QComboBox`，选项为
  `excel_io.FIELD_LABELS` 的全部字段 + 每个表头对应的 `attr:<名字>` 选项；
  默认值取 `preview.mapping`；底部复选框「跳过错误行继续导入」。
* `SolverProgressDialog`：用 `QTimer` + `Solver.iterate(SOLVER_CHUNK)` 分片驱动
  （见 `app/config.py` 的 `SOLVER_CHUNK`），显示进度条、已重启次数、当前软约束得分，
  提供「停止」按钮；关闭窗口等同于停止。求解完成后 `self.solution` 为 `Solution`。
  若 `Solver.prepare()` 抛 `SolverError`，用 `QMessageBox.warning` 提示并 `reject()`。
* `ConflictReportDialog`：上半部分硬约束清单（✅/⚠️ + 明细），
  下半部分软约束得分（总分 + 每条规则的进度条与权重）。
* `RuleEditDialog`：表单**由 `rule.RULE_SPECS[kind].fields` 动态生成**，
  控件类型见 `app/models/rule.py` 的 `F_*` 常量；
  学生下拉显示「姓名（学号）」、数据为 sid；标签下拉取 `project.tag_names()`；
  选区下拉取 `project.selections`；数值属性下拉取 `project.attr_names()`；
  座位下拉用「第 N 组 第 M 排 第 K 列」，数据为 `"g-r-c"`；
  「新增」时先用 `make_rule(kind)` 造默认规则；校验用 `rule.validate()`。
* `LayoutEditorDialog`：左侧参数面板（组数、每组的行/列/组名/组间距、上下移动/删除、
  「添加分组」）+ 右侧实时预览（用 `SeatGridView` 或简化的 `QGridLayout` 均可）；
  顶部快速模板下拉取自 `layout.LAYOUT_TEMPLATES`；
  另有讲台方向、座位卡片尺寸、是否显示组标题；
  用 `QSpinBox` 的 range 限制在 `layout.MIN_ROWS..MAX_ROWS` 之类常量内。

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
筛选、`StudentTableView`、底部按钮（导入 Excel / 添加 / 编辑 / 删除 / 批量标签 / 导出名单 /
下载导入模板）与人数统计标签。表格必须支持把学生拖到座位表（mime `application/x-student`）。

### `panels/rule_panel.py`
```python
class RulePanel(QWidget):
    rules_changed = pyqtSignal()
    def __init__(self, project, parent=None) -> None: ...
    def refresh(self) -> None: ...
```
内含：硬约束 / 软约束两个分组列表（`QListWidget`，每项带勾选框与「人话描述」），
工具栏「添加规则」（`QMenu` 按 `HARD_KINDS` / `SOFT_KINDS` 分组）、「编辑」、「删除」、
「上移/下移」（可选），软约束项显示权重。编辑走 `RuleEditDialog`，确认后
调用 `project.add_rule` / `project.remove_rule` / 直接改 `rule.params` 后 `project.notify("rules")`。

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
内含：选区列表（名称 + 座位数 + 颜色块）、按钮「用当前选中座位新建选区」
（弹 `QInputDialog` 取名字，发 `selection_created`）、「应用/高亮」、「重命名」、「删除」、
批量操作按钮（清空 / 设为空置 / 批量分配）、以及常用快捷选区生成
（按分组 / 按行范围 / 按列范围 → 发 `selection_created`）。

### `panels/rotation_panel.py`
```python
class RotationPanel(QWidget):
    preview_ready = pyqtSignal(object)        # RotationPlan
    apply_requested = pyqtSignal(object)      # RotationPlan
    rollback_requested = pyqtSignal(int)      # week
    def __init__(self, project, parent=None) -> None: ...
    def refresh(self) -> None: ...
```
内含：模式选择（区域轮换 / 按排平移 / 按列平移 / 自定义向量）、参数控件
（选区多选、Δ排、Δ列）、「预览」按钮（用 `RotationService` 生成 `RotationPlan`）、
「应用轮换」按钮、历史周列表（第 N 周 + 回退按钮）、以及 `plan.warnings` 的提示区。
`RotationService` 用法见 `app/services/rotation_service.py`。

## 4. 主窗口（由主智能体实现）

`app/ui/main_window.py` 的 `MainWindow(QMainWindow)` 负责：
菜单栏 / 工具栏 / 三个 Dock（左：学生面板；右：规则面板 + 选区 + 轮换 Tab）/
中央 `SeatGridView` / 状态栏；文件（新建、打开、保存、另存为、最近文件、导出、
自动保存与崩溃恢复）、编辑（撤销 Ctrl+Z / 重做 Ctrl+Y）、视图（显示学号、组标题、
卡片尺寸、选区高亮）、排位（一键排位、换一批、锁定选中座位再排位、冲突报告）、
轮换、帮助（快捷键说明、关于）。
