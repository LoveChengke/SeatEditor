# 开发注意事项（develop.md）

这份文档承接**代码注释被清空之前**记在源码里的所有坑。发布版（`main` 分支）
的源码刻意不带注释；带注释的完整版本在 `with-comments` 分支，需要查"当初为什么
这么写"时去那个分支翻。

改代码前请先把这里读一遍——下面每一条都是踩过之后写下来的，症状、原因、做法
分开写，方便对号入座。

---

## 1. 分支与发布约定

| 分支 | 内容 | 在哪 |
|---|---|---|
| `master` | **发布版**：带完整注释与文档字符串，署名只写 `Love_Chengke`，不含任何个人信息 | GitHub（主分支） |
| `local-private` | **本机私有版**：带署名（真名 + 学校）、源码无注释 | 只在本机，不推送 |

两个分支是**快照关系**，不是自动同步：代码演进以 `master` 为准（注释版更好维护），
`local-private` 只是"带署名的无注释版"这一份留档。要刷新它：
`git switch local-private` 后按需把 `master` 的改动取过来，再补回 `config.py` 里
被删掉的那两个常量（`DEVELOPER_REAL_NAME` / `DEVELOPER_ORG`）与 `about_text` 的署名行。
**任何会把真名写进代码的改动都不要提交到 `master`。**

- `tests/`、`pytest.ini`、以及 `scripts/` 里的若干自检脚本**被 .gitignore 排除**，
  只在本机保留（这是项目原本的约定，不是遗漏）。所以 GitHub 上没有测试。
- `local-private` 是用 `scripts/strip_comments.py` 把 `master` 的注释剥掉、
  再补回署名得到的。剥离脚本会用 `ast` 校验"除了注释和文档字符串之外什么都没动"，
  任何一个文件校验失败就整份跳过并报告（幂等，可重复跑）。
- 发布前自查：`git grep -n "真名\|学校名" master` 必须为空。

---

## 2. 环境与运行

- Python + PyQt6 + openpyxl，依赖见 `requirements.txt`；本机环境在 `.venv/`。
- 无头运行（测试、渲染）用 `QT_QPA_PLATFORM=offscreen`。
- **offscreen 的虚拟屏幕是 800×800**，比真实显示器小得多。任何"按屏幕尺寸
  收敛"的逻辑（窗口最小尺寸、自适应断点、对话框收口）在无头环境下会走**另一条
  分支**。判断这类行为时别只看无头结果，或者显式把窗口 resize 到目标尺寸再断言。
- `main.py` 启动即最大化，并按 `QSettings` 里记的主题（`view/theme`）决定明暗。

---

## 3. 界面骨架（编辑器式布局）

```
菜单栏 → 工具栏 → [活动栏 48px][侧边栏页面栈] | 中央(视图头+座位表) | [AI 助手] | [底部面板] → 状态栏
```

- 三个可停靠面板：`side_dock`（侧边栏，4 页：名单/规则/区域/换座）、`ai_dock`、
  `bottom_dock`（冲突/排位结果）；活动栏 `rail_dock` 固定 48px、无标题栏、
  不可浮动。
- **`QDockWidget` 必须传 `windowTitle`**。视图菜单里的面板开关项文字取自
  `dock.toggleViewAction().text()`，而这个 text 就是 `windowTitle`；改成自绘标题栏
  （`setTitleBarWidget`）时很容易把标题弄丢，菜单里就只剩几个"有勾没字"的空项，
  浮动窗口的系统标题栏也会是空的。`tests/test_shell.py::test_no_action_is_left_without_text`
  守着这条。
- 活动栏点"当前已选中的那一页"= 收起侧边栏（VS Code 习惯）。收起时必须给一句
  toast 说明怎么找回，否则老师只看到左边一条图标栏，会以为界面坏了。
- 自适应收起面板的标记：`_side_user_open` / `_ai_user_open` / `_bottom_user_open`
  （用户意愿，由 `visibilityChanged` 记录）与 `_xxx_auto_hidden`（是我们收的）。
  只回滚"自己收掉的"；用户手动开的，自适应不动。启动时窗口首次显示会把本来就
  可见的子面板一并"显示"，那一批 `visibilityChanged` **不是**用户操作——
  `_finish_startup()`（showEvent 后一个事件循环）负责把它们排除。
- `_on_dock_visibility_changed` 里的 `except RuntimeError` 是必需的：窗口析构途中
  子面板仍会报告可见性变化，此时碰 MainWindow 的任何成员都会抛。

---

## 4. 样式表（QSS）与尺寸

- `app/ui/style/app.qss` 里的颜色全部写成占位符（`@` + 令牌名 + `@`），由
  `app/ui/__init__.py:load_stylesheet()` 按当前色板填充；`@ASSET_DIR@` 换成
  assets 目录的**绝对路径**（QSS 字符串里的相对路径按进程工作目录解析，会丢图标）。
- **注释里不能出现完整的占位符字样**（大写字母被两个 `@` 包起来的形态），
  测试会把注释当成"漏填的令牌"报错。
- QSS 只支持 `/* */` 注释，写 Python 式 `#` 注释会让 Qt 整份样式表解析失败。
- **`QPushButton { min-height: 20px }` 这类 QSS 尺寸会覆盖控件的 `setFixedSize`。**
  症状：切换主题（重新套用样式表）后，44px 高的活动栏格子被布局压回 20px，
  看着像"控件缩在一起"。做法：自绘控件必须自己报 `sizeHint()` / `minimumSizeHint()`
  （见 `common.IconButton`）。
- **长中文标签会把布局的最小宽度顶死**：`QLabel` 开了 `setWordWrap(True)` 也没用，
  中文没有空格，Qt 按整行算最小宽度（实测一条提示顶出 313px，把整个主窗口的
  最小宽度也带大了）。做法：要么换行 + 该标签单独 `setWordWrap`，要么在窄窗里
  收起它（视图头的教室摘要就是收起 + 转悬停提示），必要时给
  `QSizePolicy(Ignored, Preferred)`。
- 窗口最小尺寸**按骨架算**（活动栏 + 侧边栏 + 座位表下限），不要写死一个数：
  写死的值如果比布局自身的最小值还小，窗口就能被压到只剩一根活动栏。

---

## 5. 字体与字形

- **微软雅黑缺少 ✕(U+2715)、▶、▼、⚠、✅ 这些码位**，用它们当图标会渲染成方框。
  界面里的 × 用矢量画（`common.IconButton` 的 close），或者用 `×`(U+00D7)。
- 已注册字体列表在 `theme.ensure_font_db()`；缺字体时按候选列表降级。
- 给控件写死字号时注意高 DPI：用 `setPixelSize` 而不是 `setPointSize`。

---

## 6. 图标体系

- 界面图标有**两套来源**，由 `app/ui/icon_loader.py:action_icon()` 统一入口分发：
  1. 自绘矢量图标集 `app/ui/widgets/icons.py`（活动栏、面板头、视图头、菜单里的
     面板开关项）——跟着主题即时变色，没有字体依赖；
  2. `resources/icons/*.svg`（打开/保存/导入/导出等）——文件里的描边色是写死的，
     **必须**经 `themed_icon()` 按主题替换描边色再转 QIcon。直接
     `QIcon(路径)` 在浅色主题下几乎看不见（原本就是这个 bug）。
- **墨迹归一化**：每颗图标在 16 单位设计空间里"真正画出来"的占比不同
  （箭头 58%、实心圆 92%），`GLYPH_ZOOM` 把每颗校正到约 85%，否则同一个盒子里
  图标一大一小（"图标太小"多半就是这么来的）。新增/改图标后跑
  `scripts/calibrate_icons.py`，把输出贴进 `GLYPH_ZOOM`；
  `tests/test_shell.py::test_every_glyph_fills_its_box_consistently` 会守住 74%~102%。
- **`paint_glyph` 的缩放必须按缩放后尺寸居中**：先按 `size` 居中再乘 zoom 的话，
  放大后的图形会从盒子左上角往右下长、右下角被切掉（自校准脚本曾量出"箭头只占
  10%"这种荒唐值，根因就在这里）。
- 圆点/问号这类形状用线条画，别用 `drawText`：字号写在 16 单位空间里，缩放后
  会比圆圈还大、溢出圆边。

### 应用图标

- 源文件两张 SVG：`resources/app_icon.svg`（完整构图：讲台 + 3×2 座位网格）、
  `resources/app_icon_small.svg`（≤32px 用：讲台 + 一个座位 + 人）。
  **完整版缩到 16px 只有 2.9px 座位、0.9px 间隙，必然糊**，所以小尺寸换构图。
- 生成物 `resources/app_icon.ico`（16/24/32/48/64/128/256）与 `app_icon.png`，
  由 `scripts/make_app_icon.py` 生成。ICO 容器是脚本手工拼的（Qt 的 ico 插件
  写不出多尺寸文件）。
- **`QBuffer(QByteArray())` 会段错误**：临时 QByteArray 当场析构，Qt 接着往已释放
  内存里写，进程崩得连一句输出都没有。QBuffer 必须挂在一个活着的 QByteArray 上。
- Windows 上要显式 `SetCurrentProcessExplicitAppUserModelID`（`app/ui.install_app_icon`），
  否则任务栏把程序归到 `python.exe` 名下、显示 Python 图标，并跟其它 Python 程序挤成一组。

---

## 7. 主题系统

- 色板单一真源 `app/ui/style/theme.py` 的 `PALETTES`；`DARK_PALETTE` 与
  `LIGHT_PALETTE` **键必须完全一致**（有测试断言），新增色值两边都要加。
- 全代码用 `Color.X` 读颜色（元类代理），切换主题即时生效——不要在 import 时
  把色值取成常量。
- 骨架与内容分两层底色：`BG_RAIL`（活动栏）、`BG_TABBAR`（工具栏/面板头/状态栏）、
  `BG_PANEL`（面板内容）、`RAIL_ACTIVE_BG`（活动栏选中项）。图标专用色
  `ICON_MUTED` 比次要文字色更深，因为线条图标比文字细。
- 对比度是量出来的，别凭感觉：正文 ≥4.5:1，次要文字 ≥3:1，图标 ≥4.5:1，
  骨架分隔线 ≥1.2:1。`tests/test_shell.py::test_chrome_icon_colors_have_enough_contrast`
  守着活动栏/面板头那几组。
- 深色主题下"把活动栏压暗"拉不开选中项与底色的差距（面板本来就接近黑），
  所以选中项用比活动栏**亮一档**的底色 + 左缘 2.5px 主色竖条。
- 打印模式（导出）会临时覆盖色值，见 `theme.set_print_mode()`：它用 setattr 改
  `Color`，退出时 delattr 还原。

---

## 8. 动效（`app/ui/motion.py`）

按 beUI 动效指南实现，令牌是唯一真源：

| 令牌 | 值 | 用途 |
|---|---|---|
| `EASE_OUT` | cubic-bezier(0.16, 1, 0.3, 1) | 入场 |
| `EASE_IN_OUT` | cubic-bezier(0.77, 0, 0.175, 1) | 屏上移动（窗口吸边） |
| `DUR_REVEAL` | 220ms | 内容揭示（透明度 + 位移 8px） |
| `DUR_SWAP_OUT` / `DUR_SWAP_IN` | 120ms / 180ms | 页面交换（离场比进场快） |
| `DUR_SNAP` | 200ms | 窗口吸边 |
| `STAGGER_STEP` | 60ms | 列表逐项揭示 |

- **顶层窗口的揭示动画必须动 `windowOpacity`，不能用 `QGraphicsOpacityEffect`**：
  后者在真实 Windows 上不生效（窗口仍然完全透明 → 对话框看不见），
  offscreen 平台更是直接提示不支持设置窗口不透明度。
- 布局管理的子控件只能做淡入（`QGraphicsOpacityEffect`），动画结束必须
  `_drop_effect` 卸掉，否则每个控件长期挂着一个 effect。
- `stagger_reveal` 的定时器回调要防 `RuntimeError`（对象可能在动画期间被销毁）。
- **降级**：`reduced_motion()` 读系统"关闭动画效果"设置（SPI_GETCLIENTAREAANIMATION），
  开了降级就只保留起止状态、不做动画。
- 渲染走查脚本必须 `motion.set_reduced_motion(True)`，否则静态截图会抓到淡入
  动画的半透明中间帧。

---

## 9. 窗口吸边

- `compute_snap_target(frame, available, threshold, edges)` 是纯函数（好测）；
  主窗口只吸左 / 右 / 上三边（Windows 不吸下缘，那里是任务栏），
  浮动面板用 `compute_dock_snap_target`，四向全开、相邻两向命中自动组合成角。
- 拖动途中若用户往回拖超过 `SNAP_HYSTERESIS`，立刻停掉吸附动画还回控制权。
- 降级模式下直接 `move()`，不做滑动。

---

## 10. 数据 / 服务层

- `Rule` 的构造是位置参数：`Rule(make_rule_id(), spec.type, kind, params, True,
  spec.default_weight)`；改用关键字会踩 `TypeError`。新建规则请走 `make_rule(kind)`。
- 规则种类清单以 `RULE_SPECS` 为准（27 种，分 `HARD_KINDS` / `SOFT_KINDS`）；
  规则参数清洗（选项归一、整数强转）在 `Rule.__post_init__`，合法性在
  `validate()`——外部（含 AI 解析）进来的规则**必须**过一遍 `validate()`，
  并把错误当成"跳过这一条 + 提示"，不要让整批失败。
- 座位键统一 `"组-排-列"`（0 起），用 `utils/seat_key.py` 的 `make_key` /
  `try_parse_key`，别自己拼字符串。
- `Project.notify` 可能在 Qt 正在派发信号时被调用（规则面板就是在 `itemChanged` 里
  notify 的），此时同步 `refresh()` 会销毁正在处理中的列表项 → 崩溃。所以
  `panels/base.py` 用 `QTimer.singleShot(0, ...)` 合并刷新，且顺序必须是
  "先复位标志、再判空、最后刷新"。任何面板都不要改成同步刷新。
- `QSettings` 键都在 `config.SK_*`。窗口停靠状态用 `window/state_v2`：
  窗口集合变过（旧版没有活动栏/底部面板），老状态会让 `restoreState` 把面板摆错
  甚至藏掉，所以换键名而不是做迁移。

---

## 11. 测试

- 无头运行；`conftest.py` 里有个 session 级 autouse 夹具把
  `SK_WELCOME_SHOWN` 置为已看，否则首启引导（400ms 定时器的模态窗）会把测试挂死。
- 构造 `MainWindow` 的测试必须把模态弹窗替换掉。**注意 `QDialog.DialogCode.Ok`
  不存在**（PyQt6 只有 `Accepted`/`Rejected`），写错了会在"某个测试真的打开弹窗"
  时抛 `AttributeError`；要返回确定值就用 `QMessageBox.StandardButton.Ok`。
- 测试进程共享本机 `QSettings`：主窗口关闭时会保存停靠布局，**所以不要断言
  "一上来某个面板是收起的"**——断言状态转换，或先显式设置成已知状态。
- **已知历史包袱（不是你的回归）**：
  - `tests/test_models.py`、`tests/test_solver.py` 收集期就报 ImportError
    （`natural_sort` / `solve_once` 早已删除），所以跑全量要带
    `--continue-on-collection-errors`；
  - `tests/test_ui.py` 有 5 项、`tests/test_history.py` 5 项、`tests/test_rotation.py`
    6 项等共 21 项早已失效（引用重构掉的属性，如 `view._header_configured`、
    `HistoryService.push` 的旧签名）；
  - `scripts/check_widgets.py`（`PodiumWidget` 已不在 `app.ui.widgets` 导出）、
    `scripts/gui_smoke.py`（`RotationService.shift_rows` 已不存在）同样是旧的。
  对比回归时请以"基线那 21+2 项"为准，别把这些当成新问题。
- 新增测试优先放在 `tests/test_shell.py`（界面骨架）这类按主题分文件的模组里；
  能写**不变式**（"座位表永不被挤到下限以下"）就别钉具体像素。

---

## 12. 渲染 / 走查脚本

| 脚本 | 用途 |
|---|---|
| `scripts/render_preview.py` | 主窗口、座位表、冲突态、底部面板、明暗两套、自适应三档、图标对照条 |
| `scripts/render_dialogs.py` | 各对话框（含"关于"）单独出图 |
| `scripts/make_app_icon.py` | 生成多尺寸 .ico / .png / 预览图 |
| `scripts/calibrate_icons.py` | 重新标定图标的墨迹缩放系数 |
| `scripts/strip_comments.py` | 生成无注释发布版（`main` 分支用） |

- 这些脚本都会把模态弹窗替换成桩，否则会被卡住。
- 输出统一进 `docs/preview/`（README 的「界面预览」就是这些图）。
- 主观视觉走查（是否对齐、清晰、好看）需要用**支持视觉的模型**跑，脚本里没有这步。
- 走查截图前记得 `motion.set_reduced_motion(True)`；`grab()` 抓不到浮动的顶层窗口，
  需要浮窗时用 `QPainter` 在真实坐标上合成。

---

## 13. 提交前自查清单

```
.venv\Scripts\python.exe -m compileall -q app main.py scripts
.venv\Scripts\python.exe -m pytest -q --continue-on-collection-errors     # 与基线 21+2 项对比
.venv\Scripts\python.exe scripts\render_preview.py docs\preview           # 界面改动后
.venv\Scripts\python.exe main.py                                          # 确认能起来
```

改过界面（尺寸 / 颜色 / 图标 / 布局）时，至少把 `render_preview.py` 跑一遍并看一眼
`docs/preview/` 里的图；只改业务逻辑时前两条就够。
