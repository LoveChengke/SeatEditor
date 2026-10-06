"""主窗口：菜单 / 工具栏 / 三个面板 / 中央座位表 / 状态栏，以及全部业务编排。

原则：UI 事件 → 服务层原子操作 → 更新 Project → 局部刷新控件。
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from PyQt6.QtCore import (
    QAbstractAnimation, QEvent, QPropertyAnimation, QSettings, QSize, Qt, QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QActionGroup, QCloseEvent, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QTabBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .common import confirm
from .. import config
from ..models.assignment import seat_key_of, unassigned_students
from ..models.layout import Layout
from ..models.project import (
    EV_ANY,
    EV_ASSIGNMENT,
    EV_HISTORY,
    EV_LAYOUT,
    EV_RULES,
    EV_SELECTIONS,
    EV_STUDENTS,
    EV_TAGS,
    Project,
    new_project,
)
from ..services.export_service import ExportError, ExportService
from ..services.history_service import HistoryService, Snapshot
from ..services.rotation_service import RotationError, RotationPlan, RotationService
from ..services.rule_engine import RuleEngine, describe_violations
from ..services.seat_service import SeatService
from ..services.student_service import ASSIGN_UNASSIGNED, StudentService
from ..storage import excel_io
from ..storage.excel_io import ExportOptions
from ..storage.project_store import JsonProjectStore, ProjectStoreError
from ..utils.natural_sort import natural_key
from ..utils.seat_key import make_key, try_parse_key
from ..utils.seat_key import Seat as Coord
from . import motion
from .icon_loader import action_icon, icon_color
from .style import theme
from .style.theme import (
    PANEL_RULE_WIDTH,
    PANEL_STUDENT_WIDTH,
    PRINT_CANVAS_QSS,
    set_print_mode,
)
from .widgets.seat_grid_view import SeatGridView

MAX_RECENT = 8

# 主窗口尺寸：优先用首选尺寸，屏幕放不下就退到可用区域以内
PREFERRED_WINDOW_SIZE = (1440, 900)

# 自适应断点：窗口越窄，先瘦侧边栏、再自动收起侧边栏，**始终保住座位表**。
# 早先的最小尺寸写死成 1100×720，那个数比布局自身的最小值（Qt 算出来约 1158）
# 还小，于是窗口能被压到 760 宽：48px 活动栏 + 320px 侧边栏把座位表挤到 250px，
# 再窄一点就只剩一根活动栏。所以尺寸下限要**按骨架算出来**，不能写死。
WIDE_WIDTH = 1180              # 宽窗档：两侧并排还放得下座位表
SIDEBAR_MIN_WIDE = 320         # 与 PANEL_STUDENT_WIDTH 一致（名单四列需要）
SIDEBAR_MIN_COMPACT = 264      # 窄窗下的紧凑档
GRID_MIN_WIDTH = 380           # 座位表的最小可用宽度（再窄就看不到一组座位了）
GRID_MIN_HEIGHT = 260          # 座位表的最小可用高度（底部面板按它让位）
MIN_WINDOW_HEIGHT = 560        # 菜单栏 + 工具栏 + 视图头 + 座位表 + 状态栏
SHORT_HEIGHT = 700             # 比这更矮就算矮窗：活动栏图标行收紧
                               # （不能取 620：底部面板开着时窗口最小高度就有 560+120=680，
                               #  620 这个阈值永远够不到，规则等于没写）
RAIL_WIDTH = 48                # 与 widgets.activity_bar 一致


def about_text() -> str:
    """「关于」里的富文本。

    提成模块级函数是为了能被直接断言（``QMessageBox.about`` 是静态方法，
    正文藏在调用里读不出来），顺带把开发者信息集中到 ``config``。
    """
    return (
        "<b>%s</b> v%s<br><br>"
        "面向中小学教师的单机教室座位编排工具。<br>"
        "全部数据保存在本地项目文件（%s）中，无网络依赖、无账号体系。<br><br>"
        "开发者：%s<br>"
        "项目地址：%s<br>"
        "技术栈：Python + PyQt6 + openpyxl"
        % (config.APP_NAME, config.VERSION, config.PROJECT_EXT,
           config.DEVELOPER, config.PROJECT_URL)
    )


class _StatusLink(QLabel):
    """状态栏上可点的文字（点「3 处冲突」直接打开底部面板看是哪几处）。"""

    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    """教室座位编排主窗口。"""

    def __init__(self, project: Optional[Project] = None) -> None:
        super().__init__()
        self.project: Project = project or new_project()
        self.student_service = StudentService(self.project)
        self.history = HistoryService(config.MAX_UNDO)
        self.export_service = ExportService()
        self.rotation_service = RotationService(self.project)

        self._pending_sids: List[str] = []
        self._conflicts: Dict[str, str] = {}
        self._locked_seats: Set[Coord] = set()
        self._last_solution = None
        self._pending_rotation_preview: Optional[RotationPlan] = None
        self._suppress_events = False
        self._syncing_view = False
        self._snap_anim: Optional[QPropertyAnimation] = None
        # 自适应：只回滚「自己收掉的」面板，用户手动收的不动。
        # ``_xxx_user_open`` 由面板的 visibilityChanged 记录（用户点活动栏 / × /
        # 菜单开关都会走到那里），启动首次显示不算用户意愿，见 _finish_startup。
        self._side_user_open = False
        self._side_auto_hidden = False
        self._ai_user_open = False
        self._ai_auto_hidden = False
        self._bottom_user_open = False
        self._bottom_auto_hidden = False
        self._responsive_busy = False
        self._startup_done = False

        self.setWindowTitle(config.APP_NAME)
        self._fit_window_to_screen()

        self._build_central()
        self._build_panels()
        self._build_bottom()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        self.project.subscribe(self._on_project_event)
        self.history.subscribe(self._update_history_actions)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(config.AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()

        self._restore_settings()
        self._restore_last_project()
        self._refresh_all()
        self._sync_view_actions()
        self._apply_responsive_layout()
        QTimer.singleShot(200, self._maybe_recover)
        QTimer.singleShot(400, self._maybe_welcome)

    def _fit_window_to_screen(self) -> None:
        """按屏幕可用区域定尺寸，并把下限算成「骨架 + 座位表」的真实需要。

        下限不能再写死：写死一个比布局自身最小值还小的数，窗口就能被压到
        侧边栏和座位表双双消失、只剩一根活动栏。这里按
        ``活动栏 + 侧边栏紧凑档 + 座位表最小宽度`` 求和，屏幕更小再退让。
        """
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.setMinimumSize(self._content_min_size())
            self.resize(*PREFERRED_WINDOW_SIZE)
            return
        available = screen.availableGeometry()
        need_w, need_h = self._content_min_size()
        min_width = min(need_w, max(GRID_MIN_WIDTH + RAIL_WIDTH, available.width() - 40))
        min_height = min(need_h, max(420, available.height() - 80))
        self.setMinimumSize(min_width, min_height)
        self.resize(
            max(min_width, min(PREFERRED_WINDOW_SIZE[0], available.width() - 20)),
            max(min_height, min(PREFERRED_WINDOW_SIZE[1], available.height() - 40)),
        )

    @staticmethod
    def _content_min_size() -> Tuple[int, int]:
        return (RAIL_WIDTH + SIDEBAR_MIN_COMPACT + GRID_MIN_WIDTH, MIN_WINDOW_HEIGHT)

    # ---------------------------------------------------------------- 自适应
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        """窄窗 / 矮窗下的让位次序：座位表 > 侧边栏 > AI 面板 > 底部面板。

        老师排座时盯的是座位表，其余面板都是「顺手看一眼」的辅助，所以：

        - **宽度**：算清「活动栏 + 各面板最小宽度 + 座位表下限（``GRID_MIN_WIDTH``）」
          要多少地方；装不下就按 AI 面板 → 侧边栏的次序让位。用的是**预算**
          而不是写死断点，所以「开着 AI 面板 1200px 就嫌挤、只开侧边栏
          900px 也够用」都能算对。
        - 屏幕本身小到连用户自己开的面板都放不下时，连它们一起让位——
          那种情况下座位表只剩一条缝，界面看着就是坏的。
        - **最小尺寸**跟着当前布局收紧：开着的面板越多，窗口能缩到的下限越大。
          于是「在小窗里再开一个面板」的结果是窗口被顶大到装得下，
          而不是把座位表挤没。屏幕比下限还小时让位给屏幕（先保证整窗可见）。

        两个标记决定谁说话算数：``_xxx_user_open`` 是用户自己开/关过的，
        ``_xxx_auto_hidden`` 是我们为腾地方收起来的。用户自己开的优先留着；
        我们收掉的，窗口变大后由我们还原。
        """
        if self._responsive_busy or not hasattr(self, "side_dock"):
            return   # 界面还没搭完（构造过程中的 resize 事件）
        self._responsive_busy = True
        try:
            width, height = self.width(), self.height()
            screen = self.screen() or QApplication.primaryScreen()
            available = screen.availableGeometry() if screen is not None else None
            # 底部面板再高也不许超过窗口的 40%（不许把座位表压成一条缝）
            self.bottom_dock.setMaximumHeight(max(120, int(height * 0.40)))

            # 视图头的教室摘要是「一行长文字」，会把中央区的最小宽度撑到 450px，
            # 窄窗里它属于可有可无的信息：收起来（内容挪到悬停提示里），
            # 中央区才肯让位——否则窗口怎么也压不窄，座位表却还是被挤。
            self.lbl_view_meta.setVisible(width >= WIDE_WIDTH)

            # ---- 高度：底部面板要跟座位表抢纵向空间，同样用「下限」判据——
            # 座位表拿不到 GRID_MIN_HEIGHT 就让底部面板（先收起）让位。
            # 注意不能写成「窗口矮于 X 就收」：底部面板开着时最小高度本身就有
            # 560+120，窗口根本到不了那个 X，规则会永远不触发。
            chrome_height = 120          # 菜单栏 + 工具栏 + 视图头 + 状态栏
            drop_bottom = (height - chrome_height - self.bottom_dock.minimumHeight()
                           < GRID_MIN_HEIGHT)
            if drop_bottom and self._bottom_user_open and available is not None:
                # 用户自己开的：只有屏幕高到也别想放得下时才收
                drop_bottom = (available.height() - 60 - chrome_height
                               - self.bottom_dock.minimumHeight() < GRID_MIN_HEIGHT)
            self._auto_fit_dock(self.bottom_dock, "_bottom", want_visible=not drop_bottom)
            self.activity_bar.set_compact(height < SHORT_HEIGHT)

            # ---- 宽度：先瘦侧边栏一档，再决定哪些面板留得下
            compact = width < WIDE_WIDTH
            self.side_dock.setMinimumWidth(
                SIDEBAR_MIN_COMPACT if compact else SIDEBAR_MIN_WIDE)
            # 「能用的宽度」取窗口现在的宽度与屏幕能给的最大宽度里的大者：
            # 窗口比屏幕窄是用户自己拉的（最小尺寸会兜住座位表），
            # 只有连屏幕都放不下时才算真放不下，那才需要收面板。
            room = width if available is None else max(width, available.width() - 20)

            panels = ((self.ai_dock, "_ai"), (self.side_dock, "_side"))   # 让位次序
            # 候选 = 开着的 + 我们之前为腾地方收掉的（后者要在这里被还原，
            # 否则收掉一次就再也回不来了）
            keep = [dock for dock, prefix in panels
                    if dock.isVisible() or getattr(self, prefix + "_auto_hidden")]

            def need_width(docks) -> int:
                return (self.rail_dock.width() + GRID_MIN_WIDTH
                        + sum(self._panel_cost(d) for d in docks))

            # 两轮：先只动「不是用户开着的」，还不够就再动用户开着的
            for respect_user in (True, False):
                for dock, prefix in panels:
                    if dock in keep and need_width(keep) > room:
                        if respect_user and getattr(self, prefix + "_user_open"):
                            continue
                        keep.remove(dock)

            for dock, prefix in panels:
                self._auto_fit_dock(dock, prefix, want_visible=dock in keep)

            # ---- 最小尺寸 = 当前布局的真实需要（屏幕装不下时让位给屏幕）
            min_width = min(need_width(keep), max(RAIL_WIDTH + GRID_MIN_WIDTH, room))
            min_height = MIN_WINDOW_HEIGHT
            if self.bottom_dock.isVisible():
                min_height += self.bottom_dock.minimumHeight()
            if available is not None:
                min_height = min(min_height, max(420, available.height() - 60))
            self.setMinimumSize(min_width, min_height)
        finally:
            self._responsive_busy = False

    def _panel_cost(self, dock) -> int:
        """面板在预算里算多少宽度：开着的按**最小**宽度算，没开的算 0。

        不能按它当前的实际宽度算：老师把侧边栏拖宽到 500 之后，
        预算会突然判定「放不下」而把面板收掉；收掉后空间又够了，下一轮再打开——
        来回抖动。按最小宽度算则是单调的（面板总能被压到最小），判定稳定。
        """
        return dock.minimumWidth() if dock.isVisible() else 0

    def _auto_fit_dock(self, dock, prefix: str, want_visible: bool) -> None:
        """按预算开/关一个辅助面板，并记住是「谁收的」。"""
        auto_attr = prefix + "_auto_hidden"
        if getattr(self, prefix + "_user_open"):
            return                      # 用户自己开着的，自适应不动它
        if not want_visible and dock.isVisible():
            setattr(self, auto_attr, True)
            dock.close()                # close() 而非 hide()：视图菜单的勾选状态跟着走
        elif want_visible and getattr(self, auto_attr) and not dock.isVisible():
            setattr(self, auto_attr, False)
            dock.show()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        if not self._startup_done:
            # 窗口首次显示会把本来可见的子面板一并「显示」，那批 visibilityChanged
            # 不是用户操作；等事件循环转一圈再认领用户意愿（showEvent 里子面板
            # 还没显示完，直接判会漏掉后面那批）。
            QTimer.singleShot(0, self._finish_startup)

    def _finish_startup(self) -> None:
        if self._startup_done:
            return
        self._startup_done = True
        for attr in ("_side_user_open", "_ai_user_open", "_bottom_user_open"):
            setattr(self, attr, False)
        self._apply_responsive_layout()

    def _on_dock_visibility_changed(self, dock, visible: bool) -> None:
        """面板可见性变化：同步活动栏高亮，并区分「用户动的」还是「自适应动的」。"""
        try:
            self._sync_rail_active()
            if self._responsive_busy or not self._startup_done:
                return                  # 自己开/关的 / 启动那批，都不代表用户意愿
            for prefix, target in (("_side", self.side_dock), ("_ai", self.ai_dock),
                                   ("_bottom", self.bottom_dock)):
                if target is dock:
                    setattr(self, prefix + "_user_open", bool(visible))
                    setattr(self, prefix + "_auto_hidden", False)
                    break
            # 面板开/关会改变「最小尺寸」与宽度预算，立刻重算：否则关掉面板后
            # 窗口还卡在旧的最小宽度上，怎么拖都缩不小
            self._apply_responsive_layout()
        except RuntimeError:
            # 窗口正在析构：子面板这时还会报告可见性变化，而 MainWindow 的
            # C++ 对象已经销毁，再碰任何成员都会抛 RuntimeError（渲染脚本
            # 关窗口时实测踩到过）
            pass

    # ---------------------------------------------------------------- 窗口吸边
    def moveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """磁性吸边（仿 Windows 贴靠）：拖到屏幕可用边缘 24px 内自动贴齐。

        上面 / 左面 / 右面三个方向（Windows 不吸下缘，那里是任务栏）。
        拖动途中松手前窗口就被「吸」到边缘；继续往回拖超过滞回量立刻放手。
        """
        super().moveEvent(event)
        self._maybe_snap_to_edge()

    def _maybe_snap_to_edge(self) -> None:
        if self.isMaximized() or self.isFullScreen() or self._suppress_events:
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        frame = self.frameGeometry()
        # 吸附动画进行中：用户又把窗口拖离目标超过滞回量 → 停止动画还控制权
        anim = self._snap_anim
        if anim is not None and anim.state() == QAbstractAnimation.State.Running:
            end = anim.endValue()
            if (frame.topLeft() - end).manhattanLength() > motion.SNAP_HYSTERESIS:
                anim.stop()
            else:
                return
        target, _edge = motion.compute_snap_target(
            frame, screen.availableGeometry(), motion.SNAP_THRESHOLD
        )
        if target is None or target == frame.topLeft():
            return
        if motion.reduced_motion():
            self.move(target)   # 降级：保留吸附行为，去掉滑动动画
            return
        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(motion.DUR_SNAP)
        slide.setEasingCurve(motion.ease_in_out())
        slide.setStartValue(frame.topLeft())
        slide.setEndValue(target)
        slide.finished.connect(self._on_snap_finished)
        self._snap_anim = slide
        slide.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_snap_finished(self) -> None:
        self._snap_anim = None

    # 界面搭建
    def _build_central(self) -> None:
        """中央区 = 视图头（一条细横条）+ 座位表。

        视图头是「这份文档现在什么样」的控件家：左边写当前教室摘要，右边是
        显示学号 / 组标题 / 区域高亮 / 卡片尺寸 / 主题这些**看**的开关。
        它们同时也在「视图」菜单里，两处状态由各自的 QAction 统一镜像。
        """
        from .common import HeaderBar

        self.central_area = QWidget(self)
        self.central_area.setObjectName("CentralArea")
        column = QVBoxLayout(self.central_area)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self.editor_header = HeaderBar("座位表", self.central_area,
                                       object_name="EditorHeader")
        self.lbl_view_meta = QLabel("", self.central_area)
        self.lbl_view_meta.setObjectName("HeaderMeta")
        self.editor_header.add_after_title(self.lbl_view_meta)
        column.addWidget(self.editor_header)

        self.grid = SeatGridView(self.central_area)
        column.addWidget(self.grid, 1)
        self.setCentralWidget(self.central_area)

        self.grid.seat_clicked.connect(self._on_seat_clicked)
        self.grid.seat_double_clicked.connect(self._on_seat_double_clicked)
        self.grid.seat_context_requested.connect(self._on_seat_context_menu)
        self.grid.seat_swap_requested.connect(self._on_seat_swap)
        self.grid.student_drop_requested.connect(self._on_student_dropped)
        self.grid.selection_changed.connect(self._on_selection_changed)
        self.grid.set_project(self.project)

    def _build_panels(self) -> None:
        """左侧：活动栏 + 侧边栏（名单 / 规则 / 区域 / 换座 四个页面）；右侧：AI 助手。"""
        from .common import HeaderBar, blank_title_bar
        from .panels.rotation_panel import RotationPanel
        from .panels.rule_panel import RulePanel
        from .panels.selection_panel import SelectionPanel
        from .panels.student_panel import StudentPanel
        from .widgets.activity_bar import RAIL_WIDTH, ActivityBar

        self.student_panel = StudentPanel(self.project, self)
        self.student_panel.selection_changed.connect(self._on_student_selection)
        self.student_panel.import_requested.connect(self.import_excel)
        self.student_panel.add_requested.connect(self.add_student)
        self.student_panel.edit_requested.connect(self.edit_student)
        self.student_panel.delete_requested.connect(self.delete_students)
        self.student_panel.tag_requested.connect(self.batch_tag)
        self.student_panel.export_requested.connect(self.export_roster)
        self.student_panel.clear_seat_requested.connect(self.unassign_seat)
        if hasattr(self.student_panel, "template_requested"):
            self.student_panel.template_requested.connect(self.save_roster_template)
        if hasattr(self.student_panel, "students_imported"):
            self.student_panel.students_imported.connect(self._on_students_imported)
        if hasattr(self.student_panel, "clear_seats_requested"):
            self.student_panel.clear_seats_requested.connect(self._on_clear_students_seats)

        self.rule_panel = RulePanel(self.project, self)
        self.selection_panel = SelectionPanel(self.project, self)
        self.rotation_panel = RotationPanel(self.project, self)

        self.rule_panel.rules_changed.connect(self._on_rules_changed)
        self.rule_panel.ai_requested.connect(self.show_ai_panel)
        self.selection_panel.apply_requested.connect(self._on_selection_apply)
        self.selection_panel.selection_created.connect(self._on_selection_created)
        self.selection_panel.selection_deleted.connect(self._on_selection_deleted)
        self.selection_panel.selection_renamed.connect(self._on_selection_renamed)
        self.selection_panel.batch_clear_requested.connect(self.clear_seats)
        self.selection_panel.batch_disable_requested.connect(self.toggle_disabled_seats)
        self.selection_panel.batch_assign_requested.connect(self.batch_assign)
        self.rotation_panel.preview_ready.connect(self._on_rotation_preview)
        self.rotation_panel.apply_requested.connect(self._on_rotation_apply)
        self.rotation_panel.rollback_requested.connect(self._on_rotation_rollback)

        # ---- 侧边栏页面：一列一页，活动栏切换（原先左右两块面板并排，
        # 老师要同时盯两处；收成一列后一次只看一页，活动栏负责找回来）
        self._side_pages = [
            ("students", "students", "学生名单", "学生名单：导入、搜索、拖到座位上", self.student_panel),
            ("rules", "rules", "排座规则", "排座规则：谁坐哪里（先看这一页）", self.rule_panel),
            ("regions", "regions", "常用区域", "常用区域：把讲台边、靠窗这些座位存成一组", self.selection_panel),
            ("rotation", "rotation", "定期换座", "定期换座：每隔一段时间整班轮换（可选）", self.rotation_panel),
        ]
        self._side_keys = [key for key, _glyph, _title, _tip, _page in self._side_pages]
        self._side_key = self._side_keys[0]

        self.side_pages = QStackedWidget(self)
        self.side_pages.setObjectName("SidePages")
        for _key, _glyph, _title, _tip, page in self._side_pages:
            # 侧边栏里是整页内容，不再是浮在别处上的一张卡片：
            # 去掉卡片描边（QSS 里 #SidePage 与对话框用的 #Panel 分开管）
            page.setObjectName("SidePage")
            self.side_pages.addWidget(page)

        self.side_dock = QDockWidget("侧边栏", self)
        self.side_dock.setObjectName("SideDock")
        self.side_dock.setToolTip("学生名单 / 排座规则 / 常用区域 / 定期换座")
        self.side_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        # 侧边栏不能压太窄：名单的「学号 / 姓名 / 性别 / 标签」四列需要约 320px，
        # 再窄就会把标签列切成一个字，看着像界面坏了（内容其实还在，可横向滚动）。
        self.side_dock.setMinimumWidth(PANEL_STUDENT_WIDTH)
        self.side_header = HeaderBar(self._side_pages[0][2], self.side_dock,
                                     closable=self.side_dock)
        self.side_header.add_menu_button("dots", "更多：导入名单 / 布局 / 标签", self._build_side_menu())
        self.side_dock.setTitleBarWidget(self.side_header)
        self.side_dock.setWidget(self.side_pages)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.side_dock)

        # ---- 活动栏：48px 图标列，侧边栏收起后它还在
        self.activity_bar = ActivityBar(self)
        for key, glyph_name, _title, tip, _page in self._side_pages:
            self.activity_bar.add_page(key, glyph_name, "%s（再点一次收起）" % tip)
        self.activity_bar.add_action("ai", "ai", "AI 助手：用大白话让 AI 写排座规则")
        self.activity_bar.add_action("theme", "theme", "白天 / 黑夜切换")
        self.activity_bar.add_action("help", "help", "快捷键与使用说明（F1）")
        self.activity_bar.clicked.connect(self._on_rail_clicked)
        self.activity_bar.set_theme_icon(theme.is_dark())

        self.rail_dock = QDockWidget("活动栏", self)
        self.rail_dock.setObjectName("RailDock")
        self.rail_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.rail_dock.setFixedWidth(RAIL_WIDTH)
        self.rail_dock.setTitleBarWidget(blank_title_bar(self.rail_dock))
        self.rail_dock.setWidget(self.activity_bar)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.rail_dock)
        # 活动栏永远在最左：显式把侧边栏摆到它右边，不靠加入顺序
        self.splitDockWidget(self.rail_dock, self.side_dock, Qt.Orientation.Horizontal)

        # ---- AI 助手：右侧常驻停靠窗口（默认不占地方，用完可关；可拖出来吸边）
        from .panels.ai_panel import AIRulePanel

        self.ai_panel = AIRulePanel(self.project, self)
        self.ai_panel.rules_ready.connect(self._on_ai_rules_ready)
        self.ai_dock = QDockWidget("AI 助手", self)
        self.ai_dock.setObjectName("AIDock")
        self.ai_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.ai_dock.setMinimumWidth(PANEL_RULE_WIDTH - 10)
        ai_header = HeaderBar("AI 助手", self.ai_dock, closable=self.ai_dock)
        ai_header.add_button("dots", "AI 设置：接口地址、模型、API Key",
                             self.ai_panel.open_settings)
        self.ai_dock.setTitleBarWidget(ai_header)
        self.ai_dock.setWidget(self.ai_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.ai_dock)
        self.ai_dock.hide()

        self.resizeDocks([self.side_dock], [PANEL_STUDENT_WIDTH + 50],
                         Qt.Orientation.Horizontal)
        self.resizeDocks([self.ai_dock], [PANEL_RULE_WIDTH + 40],
                         Qt.Orientation.Horizontal)
        # 浮动后拖近主窗口边缘 / 角落时磁性贴靠（见 eventFilter）
        for dock in (self.side_dock, self.ai_dock, self.rail_dock):
            dock.installEventFilter(self)

    def _build_side_menu(self) -> QMenu:
        """侧边栏头部的「⋯」：跨页面的几个常用入口，避免为了导入名单先切页。

        这里直接建菜单项而不是复用 ``act_*``：侧边栏在 ``_build_actions`` 之前
        搭好，那时 QAction 还不存在（复用会拿到 AttributeError）。
        """
        menu = QMenu(self)
        menu.addAction("导入学生名单…", self.import_excel)
        menu.addAction("粘贴文本导入名单…", self.import_text)
        menu.addAction("生成名单模板（Excel）…", self.save_roster_template)
        menu.addSeparator()
        menu.addAction("教室布局…", self.edit_layout)
        menu.addAction("标签管理…", self.manage_tags)
        menu.addSeparator()
        menu.addAction("收起侧边栏", self.side_dock_hide)
        return menu

    def side_dock_hide(self) -> None:
        self.side_dock.hide()

    def _build_bottom(self) -> None:
        """底部面板：冲突清单 + 排位结果（原先「排位完成」弹的是一个模态报告窗）。

        老师排完位最想看两件事——「哪几条要求没做到」「整体排得怎么样」。
        做成常驻面板后可以一边改座位一边对照，不必反复开关弹窗；
        面板本身是停靠窗口，可以拖大、拖出来、也能吸边。
        """
        from .common import HeaderBar

        self.bottom_dock = QDockWidget("底部面板", self)
        self.bottom_dock.setObjectName("BottomDock")
        self.bottom_dock.setToolTip("冲突清单 / 排位结果")
        self.bottom_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.bottom_dock.setMinimumHeight(120)

        self.bottom_tabs = QTabBar(self.bottom_dock)
        self.bottom_tabs.setObjectName("PanelTabs")
        self.bottom_tabs.setDrawBase(False)
        self.bottom_tabs.setExpanding(False)
        self.bottom_tabs.addTab("冲突")
        self.bottom_tabs.addTab("排位结果")
        self.bottom_tabs.setTabToolTip(0, "现在哪些「必须满足」的要求没做到；双击一条可定位到座位")
        self.bottom_tabs.setTabToolTip(1, "上一次排位的明细：做到多少、哪条差一些")
        self.bottom_tabs.currentChanged.connect(self._on_bottom_tab_changed)

        self.bottom_header = HeaderBar("", self.bottom_dock, closable=self.bottom_dock)
        self.bottom_header.add_leading(self.bottom_tabs)
        self.bottom_header.add_button("report", "打开「排位结果」页", lambda: self.show_bottom(1))
        self.bottom_header.add_button("chevron-down", "收起底部面板", self.bottom_dock.close)
        self.bottom_dock.setTitleBarWidget(self.bottom_header)

        self.bottom_pages = QStackedWidget(self.bottom_dock)
        self.conflict_list = QListWidget(self.bottom_pages)
        self.conflict_list.setObjectName("ConflictList")
        self.conflict_list.setAlternatingRowColors(False)
        self.conflict_list.itemDoubleClicked.connect(self._on_conflict_activated)
        self.bottom_pages.addWidget(self.conflict_list)

        self.result_host = QWidget(self.bottom_pages)
        self.result_layout = QVBoxLayout(self.result_host)
        self.result_layout.setContentsMargins(0, 0, 0, 0)
        self.result_layout.setSpacing(0)
        self.bottom_pages.addWidget(self.result_host)

        self.bottom_dock.setWidget(self.bottom_pages)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.bottom_dock)
        self.bottom_dock.setMaximumHeight(360)
        self.resizeDocks([self.bottom_dock], [200], Qt.Orientation.Vertical)
        self.bottom_dock.hide()
        # 三个面板的显隐都接到同一处：活动栏高亮要靠它同步，
        # 自适应的「谁收的」判断也靠它区分用户操作与程序收缩（放这里是因为
        # 到这一步三个面板才都存在）
        for dock in (self.side_dock, self.ai_dock, self.bottom_dock):
            dock.installEventFilter(self)
            dock.visibilityChanged.connect(
                lambda visible, d=dock: self._on_dock_visibility_changed(d, visible))

    def show_bottom(self, index: int = 0) -> None:
        """打开底部面板并切到某一页（0 冲突 / 1 排位结果）。"""
        self.bottom_dock.show()
        self.bottom_tabs.setCurrentIndex(max(0, min(index, self.bottom_tabs.count() - 1)))

    def _on_bottom_tab_changed(self, index: int) -> None:
        self.bottom_pages.setCurrentIndex(index)
        page = self.bottom_pages.widget(index)
        if page is not None:
            motion.swap_in(page)

    def _on_conflict_activated(self, item: QListWidgetItem) -> None:
        seats = item.data(Qt.ItemDataRole.UserRole) or []
        self.grid.focus_seats(seats)

    def _refresh_conflict_panel(self) -> None:
        """把当前硬约束冲突填进底部「冲突」页（座位键存在条目里，双击可定位）。"""
        engine = self._engine()
        try:
            violations = list(engine.check_hard(self.project.assignment))
        except Exception:
            violations = []
        self.conflict_list.clear()
        for violation in violations:
            label = str(getattr(violation, "rule_label", "") or "")
            message = str(getattr(violation, "message", "") or violation)
            item = QListWidgetItem("%s%s" % (("%s：" % label) if label else "", message))
            seats = list(getattr(violation, "seats", []) or [])
            item.setData(Qt.ItemDataRole.UserRole, seats)
            if seats:
                item.setToolTip("双击定位到 %s" % self._seat_label(seats[0]))
            self.conflict_list.addItem(item)
        self.bottom_tabs.setTabText(0, "冲突 %d" % len(violations) if violations else "冲突")
        if not violations:
            placeholder = QListWidgetItem("当前方案满足全部「必须满足」的要求。")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.conflict_list.addItem(placeholder)

    def _fill_result_panel(self, solution) -> None:
        """重建「排位结果」页（结果报告由 widgets.result_report 统一渲染）。"""
        while self.result_layout.count():
            old = self.result_layout.takeAt(0).widget()
            if old is not None:
                old.setParent(None)
                old.deleteLater()
        from .widgets.result_report import build_result_report

        self.result_layout.addWidget(
            build_result_report(solution, self.project, self.result_host))

    def _on_rail_clicked(self, key: str) -> None:
        """活动栏点击：前四个是侧边栏页面，后三个是常驻动作。"""
        if key == "ai":
            self.show_ai_panel()
        elif key == "theme":
            self.act_dark_mode.setChecked(not self.act_dark_mode.isChecked())
        elif key == "help":
            self.show_help()
        else:
            self.show_sidebar_page(key)

    def show_sidebar_page(self, key: str) -> None:
        """显示某一页侧边栏；已经在这一页时再点一下 = 收起（与 VS Code 一致）。"""
        if key not in self._side_keys:
            return
        if self.side_dock.isVisible() and self._side_key == key:
            # 收起要给回话：否则老师点一下只看到左边剩一条图标栏，以为界面坏了
            self.side_dock.hide()
            self.toast("侧边栏已收起 —— 点左侧的图标可以再打开")
            return
        index = self._side_keys.index(key)
        first_time = self._side_key != key or not self.side_dock.isVisible()
        self._side_key = key
        if self.side_pages.currentIndex() != index:
            self.side_pages.setCurrentIndex(index)
        self.side_header.set_title(self._side_pages[index][2])
        self.side_dock.show()
        if first_time:
            motion.swap_in(self.side_pages.currentWidget())
        self._sync_rail_active()

    def _sync_rail_active(self) -> None:
        self.activity_bar.set_active(self._side_key if self.side_dock.isVisible() else None)

    def _sync_editor_header(self) -> None:
        """视图头右侧的图标键跟随 QAction 的勾选状态（菜单里改也要跟上）。"""
        for button, act in getattr(self, "_header_buttons", []):
            if button.isChecked() != act.isChecked():
                button.setChecked(act.isChecked())

    def _build_actions(self) -> None:
        def icon(name: str) -> QIcon:
            """动作图标，按当前主题着色（见 icon_loader.action_icon）。

            不能直接 ``QIcon(路径)``：SVG 的描边色写死在文件里，浅色主题下
            图标会糊在近白的工具栏上看不见；自绘图标集则与活动栏共用同一套形状。
            """
            return action_icon(name)

        def action(text: str, shortcut: str = "", slot=None, tip: str = "",
                   checkable: bool = False, icon_name: str = "") -> QAction:
            act = QAction(text, self)
            if icon_name:
                act.setIcon(icon(icon_name))
                act.setProperty("icon_name", icon_name)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            if tip:
                act.setStatusTip(tip)
                act.setToolTip(tip)
            if checkable:
                act.setCheckable(True)
            if slot is not None:
                act.triggered.connect(slot)
            return act

        self.act_new = action("新建项目", "Ctrl+N", self.new_project, "清空当前项目，重新开始", icon_name="new")
        self.act_open = action("打开项目…", "Ctrl+O", self.open_project, "打开 .seatproj 项目文件", icon_name="open")
        self.act_save = action("保存", "Ctrl+S", self.save_project, "保存到当前项目文件", icon_name="save")
        self.act_save_as = action("另存为…", "Ctrl+Shift+S", self.save_project_as, "保存到新的项目文件", icon_name="save")
        self.act_import = action("导入学生名单…", "Ctrl+I", self.import_excel, "从 Excel 导入名单", icon_name="import")
        self.act_import_text = action("粘贴文本导入名单…", "", self.import_text, "从剪贴板/文本框批量粘贴「学号 姓名」", icon_name="import")
        self.act_roster_template = action(
            "生成名单模板（Excel）…", "", self.save_roster_template,
            "生成一份带填写说明的 Excel 模板，填好后可直接导入",
        )
        self.act_export_excel = action("导出座位表 (Excel)…", "Ctrl+E", self.export_seat_table, "导出带讲台与过道的座位表", icon_name="export")
        self.act_export_png = action("导出座位表 (PNG)…", "Ctrl+Shift+E", self.export_png, "导出座位表图片", icon_name="export")
        self.act_export_roster = action("导出学生名单…", "", self.export_roster, "导出当前名单（含标签与数值属性）", icon_name="export")
        self.act_quit = action("退出", "Ctrl+Q", self.close, "退出程序")

        self.act_undo = action("撤销", "Ctrl+Z", self.undo, "撤销上一步操作（Ctrl+Z）", icon_name="undo")
        self.act_redo = action("重做", "Ctrl+Y", self.redo, "重做被撤销的操作（Ctrl+Y / Ctrl+Shift+Z）", icon_name="redo")
        # 重做给两个快捷键：Ctrl+Y 是 Windows 习惯，但常被输入法 / 截图工具等
        # 全局热键吞掉；Ctrl+Shift+Z 是浏览器与 macOS 的习惯，留一条后路。
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.act_clear_seats = action("清空选中座位", "Delete", self._clear_selected, "把选中的学生移回名单")
        self.act_toggle_disabled = action("留空 / 取消留空", "Ctrl+D", self._toggle_selected_disabled, "留空的座位排位时不安排学生")
        self.act_select_all = action("全选座位", "Ctrl+A", self._select_all_seats, "选中全部座位")
        self.act_assign_pending = action("让选中的学生依次入座", "", self._assign_pending_auto, "把名单里选中的学生依次放进空座位")
        self.act_lock_seats = action("固定选中座位", "Ctrl+L", self._lock_selected, "排位时这几个座位不动")
        self.act_unlock_seats = action("取消全部固定", "Ctrl+Shift+L", self._unlock_seats, "取消所有固定不变的座位")

        self.act_layout = action("教室布局…", "Ctrl+B", self.edit_layout, "配置分组、行列、组间距与讲台方向", icon_name="layout")
        self.act_solve = action("一键排位", "F5", self.solve, "按规则自动排座位", icon_name="solve")
        self.act_solve_again = action("换一批", "Ctrl+R", self.solve, "重新搜索另一个方案", icon_name="solve")
        self.act_ai_rules = action("AI 助手", "", self.show_ai_panel, "用大白话让 AI 生成排座规则，确认后自动排位", icon_name="ai")
        self.act_report = action("查看排位结果", "", self.show_report, "看看哪些要求做到了、整体排得怎么样", icon_name="report")
        self.act_clear_all = action("清空全部座位", "", self.clear_all_seats, "把所有学生移回名单，重新排")

        self.act_tags = action("标签管理…", "Ctrl+T", self.manage_tags, "新增 / 重命名 / 删除标签与配色")

        self.act_dark_mode = QAction("深色模式", self)
        self.act_dark_mode.setCheckable(True)
        self.act_dark_mode.setChecked(theme.is_dark())
        self.act_dark_mode.toggled.connect(self._on_theme_toggled)
        self.act_dark_mode.setStatusTip("在黑夜 / 白天两套界面配色之间切换")

        self.act_show_sid = QAction("显示学号", self)
        self.act_show_sid.setCheckable(True)
        self.act_show_sid.setChecked(True)
        self.act_show_sid.toggled.connect(self._on_show_sid)
        self.act_show_title = QAction("显示组标题", self)
        self.act_show_title.setCheckable(True)
        self.act_show_title.setChecked(True)
        self.act_show_title.toggled.connect(self._on_show_title)
        self.act_show_selection = QAction("显示区域高亮", self)
        self.act_show_selection.setCheckable(True)
        self.act_show_selection.setChecked(True)
        self.act_show_selection.toggled.connect(self._on_show_selection)

        self.size_actions = QActionGroup(self)
        self.act_size: Dict[str, QAction] = {}
        from .style.theme import CARD_SIZE_LABELS

        for name, label in CARD_SIZE_LABELS.items():
            act = QAction("座位卡片：%s" % label, self)
            act.setCheckable(True)
            act.setChecked(name == "medium")
            act.triggered.connect(lambda _checked, n=name: self._on_card_size(n))
            self.size_actions.addAction(act)
            self.act_size[name] = act

        self.act_tour = action("新手引导", "", self.show_onboarding, "四步上手：布局 → 名单 → 规则 → 排位导出")
        self.act_help = action("快捷键与使用说明", "F1", self.show_help, "查看快捷键与上手步骤")
        self.act_about = action("关于", "", self.show_about, "关于本程序")

        self._build_editor_buttons()

    def _build_editor_buttons(self) -> None:
        """中央视图头右侧的图标键。

        每个键都镜像一个已有的 QAction（``trigger`` 转发过去，勾选状态回灌），
        所以菜单里改、视图头里改是同一份状态，不会出现两处对不上。
        """
        header = self.editor_header
        self._header_buttons: List[Tuple[QWidget, QAction]] = []

        def mirror(button, act: QAction):
            button.clicked.connect(act.trigger)
            act.toggled.connect(button.setChecked)
            button.setChecked(act.isChecked())
            self._header_buttons.append((button, act))
            return button

        mirror(header.add_button("students", "在座位卡片上显示学号", checkable=True),
               self.act_show_sid)
        mirror(header.add_button("rules", "显示每组标题（第 1 组 …）", checkable=True),
               self.act_show_title)
        mirror(header.add_button("regions", "高亮选中「常用区域」里的座位", checkable=True),
               self.act_show_selection)

        size_menu = QMenu(self)
        for act in self.act_size.values():
            size_menu.addAction(act)
        header.add_menu_button("layout", "座位卡片大小", size_menu)
        header.add_button("theme", "白天 / 黑夜切换", self.act_dark_mode.trigger)
        header.add_button("report", "查看上一次排位结果", lambda: self.show_bottom(1))

    def _build_menus(self) -> None:
        bar = self.menuBar()
        # 自绘菜单栏（Windows 原生菜单栏不吃 QSS，深色主题下会突兀）
        bar.setNativeMenuBar(False)
        menu_file = bar.addMenu("文件(&F)")
        menu_file.addAction(self.act_new)
        menu_file.addAction(self.act_open)
        self.recent_menu = QMenu("最近打开", self)
        menu_file.addMenu(self.recent_menu)
        menu_file.addSeparator()
        menu_file.addAction(self.act_save)
        menu_file.addAction(self.act_save_as)
        menu_file.addSeparator()
        menu_file.addAction(self.act_import)
        menu_file.addAction(self.act_import_text)
        menu_file.addAction(self.act_roster_template)
        menu_file.addAction(self.act_export_excel)
        menu_file.addAction(self.act_export_png)
        menu_file.addAction(self.act_export_roster)
        menu_file.addSeparator()
        menu_file.addAction(self.act_quit)

        menu_edit = bar.addMenu("编辑(&E)")
        menu_edit.addAction(self.act_undo)
        menu_edit.addAction(self.act_redo)
        menu_edit.addSeparator()
        menu_edit.addAction(self.act_clear_seats)
        menu_edit.addAction(self.act_toggle_disabled)
        menu_edit.addAction(self.act_select_all)
        menu_edit.addAction(self.act_assign_pending)
        menu_edit.addSeparator()
        menu_edit.addAction(self.act_lock_seats)
        menu_edit.addAction(self.act_unlock_seats)
        menu_edit.addSeparator()
        menu_edit.addAction(self.act_layout)
        menu_edit.addAction(self.act_tags)

        menu_view = bar.addMenu("视图(&V)")
        menu_view.addAction(self.act_show_sid)
        menu_view.addAction(self.act_show_title)
        menu_view.addAction(self.act_show_selection)
        menu_size = menu_view.addMenu("座位卡片尺寸")
        for act in self.act_size.values():
            menu_size.addAction(act)
        menu_view.addSeparator()
        menu_view.addAction(self.act_dark_mode)
        menu_view.addSeparator()
        for dock, glyph in ((self.side_dock, "students"), (self.ai_dock, "ai"),
                            (self.bottom_dock, "report")):
            act = dock.toggleViewAction()
            act.setIcon(action_icon(glyph))
            act.setProperty("icon_name", glyph)       # 主题切换时按这个重着色
            act.setStatusTip(act.text())
            menu_view.addAction(act)

        menu_seat = bar.addMenu("排位(&S)")
        menu_seat.addAction(self.act_solve)
        menu_seat.addAction(self.act_solve_again)
        menu_seat.addAction(self.act_ai_rules)
        menu_seat.addAction(self.act_report)
        menu_seat.addSeparator()
        menu_seat.addAction(self.act_clear_all)

        menu_help = bar.addMenu("帮助(&H)")
        menu_help.addAction(self.act_tour)
        menu_help.addAction(self.act_help)
        menu_help.addAction(self.act_about)
        self._install_header(bar)

    def _install_header(self, bar) -> None:
        """菜单栏两端放应用名与版本号，对应设计稿顶部的标题栏（纯装饰）。"""
        brand = QLabel(config.APP_NAME, self)
        brand.setObjectName("Brand")
        bar.setCornerWidget(brand, Qt.Corner.TopLeftCorner)
        version = QLabel("v%s" % config.VERSION, self)
        version.setObjectName("BrandVersion")
        bar.setCornerWidget(version, Qt.Corner.TopRightCorner)

    def _build_toolbar(self) -> None:
        bar = QToolBar("主工具栏", self)
        bar.setObjectName("MainToolBar")
        bar.setMovable(False)
        bar.setIconSize(QSize(16, 16))
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(bar)
        # 工具栏只放一条能走完的主线：布局 → 名单 → 排位 → 导出，
        # 其余（新建 / 粘贴导入 / 名单模板 / 排位报告…）都在菜单里，避免一屏入口。
        bar.addAction(self.act_open)
        bar.addAction(self.act_save)
        bar.addSeparator()
        bar.addAction(self.act_layout)
        bar.addAction(self.act_import)
        bar.addSeparator()
        # AI 排位放在「一键排位」旁边：这是老师最常用的两条排位路径
        bar.addAction(self.act_ai_rules)
        bar.addAction(self.act_solve)
        bar.addAction(self.act_export_excel)
        bar.addSeparator()
        bar.addAction(self.act_undo)
        bar.addAction(self.act_redo)
        self.toolbar = bar

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        self.lbl_summary = QLabel("", self)
        # 冲突数做成可点的：点一下直接打开底部「冲突」页，省得去菜单里找
        self.lbl_conflict = _StatusLink("", self)
        self.lbl_conflict.setObjectName("StatusWarn")
        self.lbl_conflict.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_conflict.setToolTip("点一下看是哪些座位冲突（底部面板）")
        self.lbl_conflict.clicked.connect(lambda: self.show_bottom(0))
        # 自动保存失败要一直挂着，不能用会消失的 toast（见 _autosave）
        self.lbl_autosave = QLabel("", self)
        self.lbl_autosave.setObjectName("StatusWarn")
        bar.addWidget(self.lbl_summary)
        bar.addPermanentWidget(self.lbl_autosave)
        bar.addPermanentWidget(self.lbl_conflict)

    def toast(self, message: str, timeout: int = 4000) -> None:
        self.statusBar().showMessage(message, timeout)

    # 项目事件
    def _on_project_event(self, event: str, payload) -> None:
        if self._suppress_events:
            return
        if event in (EV_ASSIGNMENT, EV_STUDENTS, EV_TAGS, EV_ANY):
            self._update_status()
        if event == EV_LAYOUT:
            self._update_status()
            self.selection_panel.refresh()
        if event in (EV_RULES, EV_SELECTIONS):
            self.selection_panel.refresh()
        if event == EV_HISTORY:
            self.rotation_panel.refresh()
        self.setWindowTitle(self._window_title())

    def _refresh_all(self) -> None:
        self.grid.rebuild()
        self.grid.set_locked_seats(self._locked_seats)
        self._update_conflicts()
        self.student_panel.refresh()
        self.rule_panel.refresh()
        self.selection_panel.refresh()
        self.rotation_panel.refresh()
        self._update_status()
        self._update_history_actions()
        self._update_recent_menu()
        self.setWindowTitle(self._window_title())

    def _window_title(self) -> str:
        name = os.path.basename(self.project.path) if self.project.path else "未命名项目"
        return "%s%s — %s" % ("*" if self.project.dirty else "", name, config.APP_NAME)

    # 状态
    def _update_status(self) -> None:
        layout = self.project.layout
        assigned = len([v for v in self.project.assignment.values() if v])
        text = "座位 %d（留空 %d） · 学生 %d · 已入座 %d · 未入座 %d" % (
            layout.seat_count(),
            len(layout.disabled_seats),
            len(self.project.students),
            assigned,
            max(0, len(self.project.students) - assigned),
        )
        if self._locked_seats:
            text += " · 已固定 %d 个座位" % len(self._locked_seats)
        self.lbl_summary.setText(text)
        if self._conflicts:
            first = next(iter(self._conflicts.values()))
            self.lbl_conflict.setText("有 %d 处冲突：%s" % (len(self._conflicts), first[:48]))
        else:
            self.lbl_conflict.setText("")
        self._update_view_meta()
        self.setWindowTitle(self._window_title())

    def _update_view_meta(self) -> None:
        """视图头上的教室摘要：「3 组 × 7 排 · 42 个座位 · 已排 40 人」。

        窄窗里这行会被自适应收起（它撑宽度），所以同一句话也挂在悬停提示上。
        """
        layout = self.project.layout
        cols = layout.groups[0].cols if layout.groups else 0
        assigned = len([v for v in self.project.assignment.values() if v])
        text = "%d 组 × %d 排 × %d 列 · %d 个座位 · 已排 %d / %d 人" % (
            layout.group_count, layout.max_rows, cols,
            layout.seat_count(), assigned, len(self.project.students))
        self.lbl_view_meta.setText(text)
        self.lbl_view_meta.setToolTip("当前教室：" + text)

    def _update_history_actions(self) -> None:
        can_undo = self.history.can_undo
        can_redo = self.history.can_redo
        self.act_undo.setEnabled(can_undo)
        self.act_redo.setEnabled(can_redo)
        self.act_undo.setToolTip(
            ("撤销（Ctrl+Z）：%s" % self.history.undo_label()) if can_undo
            else "没有可撤销的操作（Ctrl+Z）"
        )
        self.act_redo.setToolTip(
            ("重做（Ctrl+Y / Ctrl+Shift+Z）：%s" % self.history.redo_label()) if can_redo
            else "没有可重做的操作（Ctrl+Y / Ctrl+Shift+Z）"
        )

    # 历史
    def _snapshot_layout(self) -> Dict[str, Any]:
        return self.project.layout.to_dict()

    def _push_history(self, label: str) -> None:
        self.history.push(self.project.assignment, label, self._snapshot_layout())
        self._update_history_actions()

    def _restore(self, snapshot: Snapshot) -> None:
        # 撤销 / 重做都会重建座位表，重建会销毁当前聚焦的座位控件；若不还回去，
        # 主窗口可能连「当前窗口」都不是，于是紧接着按 Ctrl+Y 这类窗口级快捷键
        # 全都发不进来——这正是「重做键不生效」的现场。这里显式恢复焦点与激活。
        focused = self.focusWidget()
        self._suppress_events = True
        try:
            if snapshot.layout_snapshot:
                self.project.layout = Layout.from_dict(snapshot.layout_snapshot)
            self.project.assignment = dict(snapshot.assignment)
            self.project.sanitize_assignment()
        finally:
            self._suppress_events = False
        self.project.notify(EV_LAYOUT)
        self.project.notify(EV_ASSIGNMENT)
        self._update_conflicts()
        self.grid.rebuild()
        self.grid.set_locked_seats(self._locked_seats)
        self._update_status()
        self.student_panel.refresh()
        self.selection_panel.refresh()
        self._sync_view_actions()
        try:
            if focused is not None and focused is not self and focused.isVisible():
                focused.setFocus()
            else:
                self.grid.setFocus()
        except RuntimeError:
            # 聚焦的座位控件已在 rebuild 中被销毁
            self.grid.setFocus()
        if not self.isActiveWindow():
            self.activateWindow()

    def undo(self) -> None:
        snapshot = self.history.undo(self.project.assignment, self._snapshot_layout())
        if snapshot is None:
            self.toast("没有可撤销的操作")
            return
        label = snapshot.label or "上一步操作"
        self._restore(snapshot)
        self.toast("已撤销：%s" % label)

    def redo(self) -> None:
        snapshot = self.history.redo(self.project.assignment, self._snapshot_layout())
        if snapshot is None:
            self.toast("没有可重做的操作")
            return
        self._restore(snapshot)
        self.toast("已重做")

    # 冲突
    def _engine(self) -> RuleEngine:
        return RuleEngine.from_project(self.project)

    def _coords(self, seats) -> List[Coord]:
        """把 ``"g-r-c"`` / ``(g, r, c)`` 混合输入统一成坐标列表（忽略非法值）。"""
        result: List[Coord] = []
        for item in seats or []:
            if item is None:
                continue
            coord = item if isinstance(item, tuple) and len(item) == 3 else try_parse_key(item)
            if coord is None:
                continue
            result.append((int(coord[0]), int(coord[1]), int(coord[2])))
        return result

    def _update_conflicts(self, seats: Optional[Sequence] = None) -> None:
        engine = self._engine()
        focus = None if seats is None else self._coords(seats)
        violations = engine.check_hard(self.project.assignment, focus)
        mapping: Dict[str, str] = {}
        for violation in violations:
            for key in violation.seats:
                mapping.setdefault(key, violation.message)
        if focus is None:
            self._conflicts = mapping
        else:
            affected = {make_key(s) for s in engine.affected_seats(focus)}
            for key in affected:
                self._conflicts.pop(key, None)
            self._conflicts.update(mapping)
        self.grid.set_conflicts(self._conflicts)
        self._refresh_conflict_panel()
        self._update_status()

    def _conflict_message(self) -> str:
        if not self._conflicts:
            return "当前方案满足全部「必须满足」要求"
        return "当前方案有 %d 处硬约束冲突：\n\n%s" % (
            len(self._conflicts),
            describe_violations(self._engine().check_hard(self.project.assignment), 8),
        )

    # 座位操作
    def _selected_seats(self) -> List[Coord]:
        return sorted(self.grid.selected_seats(), key=lambda s: (s[0], s[1], s[2]))

    def _on_selection_changed(self, seats) -> None:
        self.selection_panel.set_current_seats(set(seats))

    def _on_student_selection(self, sids: List[str]) -> None:
        self._pending_sids = [s for s in (sids or []) if s]
        if self._pending_sids:
            student = self.project.get_student(self._pending_sids[0])
            name = student.name if student else self._pending_sids[0]
            self.toast("已选中 %s%s，点击空座位即可入座" % (
                name, "" if len(self._pending_sids) == 1 else " 等 %d 人" % len(self._pending_sids)))

    def _on_seat_clicked(self, seat, modifiers: int) -> None:
        ctrl = bool(modifiers & int(Qt.KeyboardModifier.ControlModifier.value))
        shift = bool(modifiers & int(Qt.KeyboardModifier.ShiftModifier.value))
        if ctrl or shift:
            return
        pending = [sid for sid in self._pending_sids if sid]
        if len(pending) != 1:
            return
        if self.project.assignment.get(make_key(seat), ""):
            return                       # 座位有人：换座请直接拖动座位卡片
        sid = pending[0]
        seated_at = seat_key_of(self.project.assignment, sid)
        if seated_at:
            # 已经入座的学生不再「点一下空座位就挪走」——那样轻轻一点就被挪位太吓人
            self.toast("%s 已在 %s；拖动座位卡片即可换座" % (
                self.project.student_name(sid), self._seat_label(seated_at)))
            return
        self.assign_student(sid, seat)

    def _seat_label(self, seat_key: str) -> str:
        coord = try_parse_key(seat_key)
        if coord is None:
            return str(seat_key)
        return "%s 第%d排 第%d列" % (self.project.layout.group_name(coord[0]),
                                    coord[1] + 1, coord[2] + 1)

    def _on_seat_double_clicked(self, seat) -> None:
        sid = self.project.assignment.get(make_key(seat), "")
        if sid:
            self.edit_student(sid)
        else:
            self._assign_pending_auto()

    def _on_seat_swap(self, source, target) -> None:
        self.swap_seats(source, target)

    def _on_student_dropped(self, sid: str, seat) -> None:
        if self.assign_student(sid, seat):
            # 拖完就放掉名单里的高亮：否则这个学生一直是「待入座」状态，
            # 之后再点任意空座位都会把他挪过去（老师反馈的「点一下就被搬走」）。
            self._pending_sids = []
            self.student_panel.clear_selection()
            if self.student_panel.assign_filter() == ASSIGN_UNASSIGNED:
                # 「未分配」筛选下入座后该行会被筛掉，这里说清楚，免得像学生丢了
                self.toast("已入座；当前筛选是「未入座」，该学生暂时从名单里隐藏", 6000)

    def unassign_seat(self, seat_key: str) -> None:
        """把座位上的学生拖回名单 = 取消入座。"""
        coord = try_parse_key(seat_key)
        if coord is None:
            return
        sid = self.project.assignment.get(make_key(coord), "")
        if not sid:
            self.toast("这个座位本来就是空的")
            return
        name = self.project.student_name(sid)
        if self.clear_seats([coord]):
            self.toast("已把 %s 移回名单（取消入座）" % name)

    def _on_seat_context_menu(self, seat, global_pos) -> None:
        coord = tuple(seat)
        key = make_key(coord)
        sid = self.project.assignment.get(key, "")
        menu = QMenu(self)
        student = self.project.get_student(sid) if sid else None
        if sid:
            act = menu.addAction("清空座位（%s）" % (student.name if student else sid))
            act.triggered.connect(lambda: self.clear_seats([coord]))
            if student is not None:
                act2 = menu.addAction("编辑学生信息…")
                act2.triggered.connect(lambda: self.edit_student(sid))
        else:
            act = menu.addAction("清空座位")
            act.setEnabled(False)
        if self._pending_sids:
            menu.addAction(
                "让选中的学生入座（%d 人）" % len(self._pending_sids),
                lambda: self.assign_student(self._pending_sids[0], coord),
            )
        menu.addSeparator()
        disabled = self.project.layout.is_disabled(coord)
        act_dis = menu.addAction("取消留空" if disabled else "留空（不排人）")
        act_dis.triggered.connect(lambda: self.toggle_disabled_seats([coord]))
        locked = coord in self._locked_seats
        act_lock = menu.addAction("取消固定" if locked else "固定该座位")
        act_lock.triggered.connect(lambda: self._toggle_lock(coord))
        menu.addSeparator()
        label = "第 %d 组 第 %d 排 第 %d 列" % (coord[0] + 1, coord[1] + 1, coord[2] + 1)
        info = menu.addAction(label)
        info.setEnabled(False)
        menu.exec(global_pos)

    # 原子操作
    def assign_student(self, sid: str, seat) -> bool:
        student = self.project.get_student(sid)
        if student is None:
            self.toast("找不到学生：%s" % sid)
            return False
        coord = try_parse_key(seat)
        if coord is None or not self.project.layout.contains(coord):
            self.toast("无效的座位")
            return False
        if self.project.layout.is_disabled(coord):
            self.toast("该座位已留空，请先取消留空")
            return False
        old_key = seat_key_of(self.project.assignment, sid)
        occupant = self.project.assignment.get(make_key(coord), "")
        if old_key == make_key(coord):
            return False
        label = "分配 %s" % student.name
        if occupant and occupant != sid:
            other = self.project.get_student(occupant)
            label = "把 %s 放到 %s 的位置" % (student.name, other.name if other else occupant)
        self._push_history(label)
        service = SeatService(self.project.assignment)
        service.assign(coord, sid)
        self.project.assignment = service.assignment
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh(self._affected(coord, old_key))
        self._after_change(coord, old_key)
        return True

    def swap_seats(self, source, target) -> bool:
        a, b = try_parse_key(source), try_parse_key(target)
        if a is None or b is None or a == b:
            return False
        if self.project.layout.is_disabled(a) or self.project.layout.is_disabled(b):
            self.toast("留空的座位不参与交换")
            return False
        sid_a = self.project.assignment.get(make_key(a), "")
        sid_b = self.project.assignment.get(make_key(b), "")
        if not sid_a and not sid_b:
            self.toast("两个座位都是空的")
            return False
        name_a = self.project.student_name(sid_a) if sid_a else "空位"
        name_b = self.project.student_name(sid_b) if sid_b else "空位"
        self._push_history("交换 %s ↔ %s" % (name_a, name_b))
        service = SeatService(self.project.assignment)
        service.swap(a, b)
        self.project.assignment = service.assignment
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh([a, b])
        self._after_change(a, b)
        self.toast("已交换 %s ↔ %s" % (name_a, name_b))
        return True

    def clear_seats(self, seats: Sequence) -> int:
        coords = [try_parse_key(s) for s in (seats or [])]
        coords = [c for c in coords if c is not None]
        if not coords:
            return 0
        removed = [self.project.assignment.get(make_key(c), "") for c in coords]
        removed = [sid for sid in removed if sid]
        if not removed:
            self.toast("选中的座位本来就是空的")
            return 0
        self._push_history("清空 %d 个座位" % len(removed))
        service = SeatService(self.project.assignment)
        service.clear_many(coords)
        self.project.assignment = service.assignment
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh(coords)
        self._after_change(*coords)
        self.toast("已清空 %d 个座位，学生回到名单" % len(removed))
        return len(removed)

    def clear_all_seats(self) -> None:
        if not any(self.project.assignment.values()):
            self.toast("当前没有已分配的座位")
            return
        if not self._confirm("确定要清空全部座位吗？所有学生将回到名单。"):
            return
        self._push_history("清空全部座位")
        seats = [try_parse_key(k) for k in list(self.project.assignment)]
        self.project.assignment = {}
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh([s for s in seats if s is not None])
        self._update_conflicts()
        self.toast("已清空全部座位")

    def toggle_disabled_seats(self, seats: Sequence) -> None:
        coords = [try_parse_key(s) for s in (seats or [])]
        coords = [c for c in coords if c is not None]
        if not coords:
            return
        target = not all(self.project.layout.is_disabled(c) for c in coords)
        self._push_history("设为留空" if target else "取消留空")
        for coord in coords:
            self.project.layout.set_disabled(coord, target)
            if target:
                self.project.assignment.pop(make_key(coord), None)
        self.project.layout.prune_disabled()
        self.project.notify(EV_LAYOUT)
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh(coords)
        self._update_conflicts(coords)
        self.toast("已把 %d 个座位设为%s" % (len(coords), "留空" if target else "可用"))

    def batch_assign(self, seats: Sequence) -> None:
        coords = sorted(
            [c for c in (try_parse_key(s) for s in (seats or [])) if c is not None],
            key=lambda s: (s[1], s[0], s[2]),
        )
        if not coords:
            self.toast("请先在座位表上选择若干座位")
            return
        sids = list(self._pending_sids)
        if not sids:
            sids = [s.sid for s in sorted(self.project.students, key=lambda s: natural_key(s.sid))]
            sids = unassigned_students(self.project.assignment, sids)
        if not sids:
            self.toast("没有可分配的学生")
            return
        count = min(len(coords), len(sids))
        self._push_history("批量分配 %d 人" % count)
        service = SeatService(self.project.assignment)
        for coord, sid in zip(coords[:count], sids[:count]):
            if self.project.layout.is_disabled(coord):
                continue
            service.assign(coord, sid)
        self.project.assignment = service.assignment
        self.project.notify(EV_ASSIGNMENT)
        self.grid.refresh(coords[:count])
        self._after_change(*coords[:count])
        self.toast("已批量分配 %d 名学生" % count)

    def _assign_pending_auto(self) -> None:
        seats = self._selected_seats()
        if not seats:
            free = [s for s in self.project.layout.available_seats()
                    if not self.project.assignment.get(make_key(s), "")]
            seats = free[:max(1, len(self._pending_sids) or 1)]
        self.batch_assign(seats)

    def _affected(self, *seats) -> List[Coord]:
        result: List[Coord] = self._coords(seats)
        for coord in list(result):
            result.extend(self.project.layout.neighbors(coord))
        return result

    def _after_change(self, *seats) -> None:
        self._update_conflicts(self._coords(seats))
        self._update_status()
        self.student_panel.refresh()

    # 选区操作
    def _select_all_seats(self) -> None:
        self.grid.select_all()
        self.toast("已选中全部 %d 个座位" % self.grid.seat_count())

    def _clear_selected(self) -> None:
        seats = self._selected_seats()
        if not seats:
            self.toast("请先选择座位（拖拽框选或 Ctrl+点击）")
            return
        self.clear_seats(seats)

    def _toggle_selected_disabled(self) -> None:
        seats = self._selected_seats()
        if not seats:
            self.toast("请先选择座位")
            return
        self.toggle_disabled_seats(seats)

    def _lock_selected(self) -> None:
        seats = self._selected_seats()
        if not seats:
            self.toast("请先选择要固定的座位")
            return
        self._locked_seats |= set(seats)
        self.grid.set_locked_seats(self._locked_seats)
        self._update_status()
        self.toast("已锁定 %d 个座位，排位时保持不动" % len(self._locked_seats))

    def _unlock_seats(self) -> None:
        if not self._locked_seats:
            self.toast("当前没有锁定的座位")
            return
        self._locked_seats.clear()
        self.grid.set_locked_seats(self._locked_seats)
        self._update_status()
        self.toast("已解除全部座位锁定")

    def _toggle_lock(self, seat) -> None:
        coord = try_parse_key(seat)
        if coord is None:
            return
        coord = (int(coord[0]), int(coord[1]), int(coord[2]))
        if coord in self._locked_seats:
            self._locked_seats.discard(coord)
            self.toast("已解除锁定")
        else:
            self._locked_seats.add(coord)
            self.toast("已锁定该座位")
        self.grid.set_locked_seats(self._locked_seats)
        self._update_status()

    # 学生
    def add_student(self) -> None:
        from .dialogs.student_edit_dialog import StudentEditDialog

        dialog = StudentEditDialog(self.project, None, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        student = getattr(dialog, "result_student", None)
        if student is None:
            return
        self._push_history("添加学生 %s" % student.name)
        ok, message = self.student_service.add(
            student.sid, student.name, student.gender, student.tags, student.attrs, student.note
        )
        if not ok:
            self.history.drop_last()
            QMessageBox.warning(self, "无法添加", message)
            return
        self._refresh_all()
        self.toast("已添加 %s（%s）" % (student.name, student.sid))

    def edit_student(self, sid: str) -> None:
        student = self.project.get_student(sid)
        if student is None:
            self.toast("找不到学生：%s" % sid)
            return
        from .dialogs.student_edit_dialog import StudentEditDialog

        dialog = StudentEditDialog(self.project, student, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        updated = getattr(dialog, "result_student", None)
        if updated is None:
            return
        self._push_history("编辑学生 %s" % student.name)
        ok, message = self.student_service.update(
            sid, sid=updated.sid, name=updated.name, gender=updated.gender,
            tags=updated.tags, attrs=updated.attrs, note=updated.note,
        )
        if not ok:
            self.history.drop_last()
            QMessageBox.warning(self, "无法保存", message)
            return
        self._refresh_all()
        self.toast("已保存 %s 的信息" % updated.name)

    def delete_students(self, sids: Sequence[str]) -> None:
        sids = [s for s in (sids or []) if s]
        if not sids:
            self.toast("请先在名单里选择学生")
            return
        if not self._confirm("确定要删除选中的 %d 名学生吗？此操作不可恢复。" % len(sids)):
            return
        self._push_history("删除 %d 名学生" % len(sids))
        self.student_service.remove(sids)
        self._refresh_all()
        self.toast("已删除 %d 名学生" % len(sids))

    def batch_tag(self, sids: Sequence[str]) -> None:
        sids = [s for s in (sids or []) if s]
        if not sids:
            self.toast("请先在名单里选择学生")
            return
        tags = self.project.tag_names()
        menu = QMenu(self)
        for tag in tags:
            act = menu.addAction("添加标签：%s" % tag)
            act.triggered.connect(lambda _c, t=tag: self._apply_tag(sids, t, True))
        for tag in tags:
            act = menu.addAction("移除标签：%s" % tag)
            act.triggered.connect(lambda _c, t=tag: self._apply_tag(sids, t, False))
        menu.addSeparator()
        act_new = menu.addAction("新建标签…")
        act_new.triggered.connect(lambda: self._apply_tag(sids, "", True))
        menu.exec(self.mapToGlobal(self.rect().center()))

    def _apply_tag(self, sids: Sequence[str], tag: str, add: bool) -> None:
        if not tag:
            tag, ok = QInputDialog.getText(self, "新建标签", "标签名称：")
            if not ok or not tag.strip():
                return
            tag = tag.strip()
        self._push_history("批量%s标签「%s」" % ("添加" if add else "移除", tag))
        if add:
            count = self.student_service.add_tag(sids, tag)
        else:
            count = self.student_service.remove_tag_from(sids, tag)
        self._refresh_all()
        self.toast("已为 %d 名学生%s标签「%s」" % (count, "添加" if add else "移除", tag))

    def manage_tags(self) -> None:
        from .dialogs.tag_manager_dialog import TagManagerDialog

        dialog = TagManagerDialog(self.project, self)
        dialog.exec()
        self._refresh_all()

    # Excel
    def save_roster_template(self) -> None:
        """生成 Excel 名单导入模板；教师填好后走「导入学生名单」读入。"""
        from ..storage import roster_template

        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存名单导入模板",
            self._default_name(roster_template.TEMPLATE_FILENAME),
            config.EXCEL_FILTER,
        )
        if not path:
            return
        try:
            target = roster_template.write_roster_template(path)
        except excel_io.ExcelError as exc:
            QMessageBox.warning(self, "无法生成模板", str(exc))
            return
        self._remember_dir(str(target))
        self.toast("已生成名单模板：%s" % target)
        QMessageBox.information(
            self,
            "模板已生成",
            "名单模板已保存到：\n%s\n\n"
            "在「名单」工作表里从第 2 行开始逐行填写学生，保存后回到程序点「导入学生名单」，"
            "字段会自动对应，直接确认即可。\n\n"
            "「填写说明」页写了每一列怎么填，「示例」页有一份可以照抄的样例。" % target,
        )

    def import_excel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择学生名单", self._last_dir(), config.EXCEL_FILTER)
        if not path:
            return
        self._remember_dir(path)
        try:
            preview = excel_io.read_preview(path)
        except excel_io.ExcelError as exc:
            QMessageBox.warning(self, "无法读取文件", str(exc))
            return
        from .dialogs.import_mapping_dialog import ImportMappingDialog

        dialog = ImportMappingDialog(preview, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        mapping = getattr(dialog, "mapping", None) or preview.mapping
        skip_invalid = bool(getattr(dialog, "skip_invalid", True))
        try:
            result = excel_io.build_students(
                preview.headers, preview.rows, mapping, skip_invalid,
                existing_sids=self.project.all_sids(),
            )
        except excel_io.ExcelError as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        self._finish_import(result)

    def import_text(self) -> None:
        from .dialogs.text_import_dialog import TextImportDialog

        dialog = TextImportDialog(self.project, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._on_students_imported(list(getattr(dialog, "students", []) or []))

    def _on_students_imported(self, students) -> None:
        """文本 / 其他途径导入的学生列表（由学生面板或本窗口触发）。"""
        students = list(students or [])
        if not students:
            self.toast("没有解析到学生数据")
            return
        before = len(self.project.students)
        self._push_history("导入 %d 名学生" % len(students))
        added = self.project.add_students(students)
        for student in students:
            for tag in student.tags:
                self.project.ensure_tag(tag)
        self.project.notify(EV_STUDENTS)
        self._refresh_all()
        skipped = len(students) - added
        if added == 0:
            self.toast("没有新增学生（%d 条与现有名单重复）" % skipped)
        else:
            self.toast("已导入 %d 名学生（名单 %d → %d 人）%s" % (
                added, before, len(self.project.students),
                "，跳过重复 %d 条" % skipped if skipped else ""))

    def _on_clear_students_seats(self, sids) -> None:
        """把选中的学生从座位上移回未分配池。"""
        seats = []
        for sid in sids or []:
            key = seat_key_of(self.project.assignment, str(sid))
            if key:
                coord = try_parse_key(key)
                if coord is not None:
                    seats.append(coord)
        if not seats:
            self.toast("选中的学生都没有座位")
            return
        self.clear_seats(seats)

    def _finish_import(self, result) -> None:
        if not result.students:
            detail = "\n".join("%s（第 %d 行）" % (e.message, e.row) for e in result.errors[:10])
            QMessageBox.warning(self, "没有可导入的数据", detail or "没有读取到有效数据行")
            return
        self._push_history("导入 %d 名学生" % len(result.students))
        added = self.project.add_students(result.students)
        for student in result.students:
            for tag in student.tags:
                self.project.ensure_tag(tag)
        self.project.notify(EV_STUDENTS)
        self._refresh_all()
        message = "成功导入 %d 名学生" % added
        if result.new_attrs:
            message += "\n新增数值属性：%s" % "、".join(result.new_attrs)
        if result.errors:
            message += "\n跳过 %d 行有问题的数据" % len(result.errors)
        QMessageBox.information(self, "导入完成", message)
        self.toast(message.splitlines()[0])

    def export_seat_table(self) -> None:
        self._export_excel()

    def _export_excel(self) -> None:
        from .dialogs.export_dialog import ExportDialog

        if self._conflicts:
            QMessageBox.warning(self, "导出提醒", self._conflict_message())
        dialog = ExportDialog(self.project, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        mode = getattr(dialog, "mode", "excel")
        chosen = str(getattr(dialog, "path", "") or "")
        if mode == "png":
            self._export_png_with(int(getattr(dialog, "png_scale", 1) or 1), chosen)
            return
        path = chosen
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "导出座位表", self._default_name("座位表.xlsx"),
                                                 config.EXCEL_FILTER)
        if not path:
            return
        options = getattr(dialog, "options", None) or ExportOptions()
        try:
            target = self.export_service.export_seat_table(self.project, path, options)
        except ExportError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.toast("已导出座位表：%s" % target)
        QMessageBox.information(self, "导出成功", "座位表已导出到：\n%s" % target)

    def export_png(self) -> None:
        from .dialogs.export_dialog import ExportDialog

        dialog = ExportDialog(self.project, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._export_png_with(
            int(getattr(dialog, "png_scale", 1) or 1),
            str(getattr(dialog, "path", "") or ""),
        )

    def _export_png_with(self, scale: int, path: str = "") -> None:
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "导出座位表图片", self._default_name("座位表.png"),
                                                  config.PNG_FILTER)
        if not path:
            return
        hidden = []
        if self.act_show_selection.isChecked():
            self.act_show_selection.setChecked(False)
            hidden.append(self.act_show_selection)
        self.grid.clear_selection()
        QApplication.processEvents()
        # 屏幕上用深色，导出的图片要打印，临时切成浅色配色（finally 里还原）
        previous_style = self.grid.styleSheet()
        self.grid.setStyleSheet(PRINT_CANVAS_QSS)
        set_print_mode(True)
        try:
            target = self.export_service.export_png(self.grid, path, scale)
        except ExportError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            for act in hidden:
                act.setChecked(True)
            return
        finally:
            set_print_mode(False)
            self.grid.setStyleSheet(previous_style)
        for act in hidden:
            act.setChecked(True)
        self.toast("已导出图片：%s" % target)
        QMessageBox.information(self, "导出成功", "图片已导出到：\n%s" % target)

    def export_roster(self) -> None:
        if not self.project.students:
            self.toast("名单是空的，无法导出")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出学生名单", self._default_name("学生名单.xlsx"),
                                              config.EXCEL_FILTER)
        if not path:
            return
        try:
            target = self.export_service.export_roster(self.project, path)
        except ExportError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.toast("已导出名单：%s" % target)

    # 布局
    def edit_layout(self) -> None:
        from .dialogs.layout_editor_dialog import LayoutEditorDialog

        dialog = LayoutEditorDialog(self.project, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        new_layout = getattr(dialog, "result_layout", None)
        if new_layout is None:
            return
        self._push_history("修改教室布局")
        self.project.layout = new_layout
        problems = self.project.sanitize_assignment()
        self.project.notify(EV_LAYOUT)
        self.project.notify(EV_ASSIGNMENT)
        self._locked_seats = {s for s in self._locked_seats if self.project.layout.contains(s)}
        self.grid.rebuild()
        self.grid.set_locked_seats(self._locked_seats)
        self._sync_view_actions()
        self._update_conflicts()
        self._update_status()
        self.student_panel.refresh()
        self.selection_panel.refresh()
        if problems:
            QMessageBox.information(self, "布局已更新", "以下座位的分配被清理：\n%s" % "\n".join(problems[:8]))
        self.toast("教室布局已更新：%d 组，共 %d 个座位" % (
            self.project.layout.group_count, self.project.layout.seat_count()))

    # 排位
    def solve(self) -> None:
        if not self.project.students:
            QMessageBox.information(self, "还没有学生", "请先导入或添加学生名单，再执行一键排位。")
            return
        if self.project.layout.available_count() == 0:
            QMessageBox.warning(self, "没有可用座位", "所有座位都被留空了，请先取消部分留空座位。")
            return
        from .dialogs.solver_progress_dialog import SolverProgressDialog

        self._push_history("一键排位")
        dialog = SolverProgressDialog(self.project, self, sorted(self._locked_seats))
        if dialog.exec() != dialog.DialogCode.Accepted:
            self.history.drop_last()
            self._update_history_actions()
            return
        solution = getattr(dialog, "solution", None)
        if solution is None:
            self.history.drop_last()
            self._update_history_actions()
            self.toast("排位已取消")
            return
        self.project.previous_assignment = dict(self.project.assignment)
        self.project.assignment = dict(solution.assignment)
        self.project.notify(EV_ASSIGNMENT)
        self._last_solution = solution
        self.grid.refresh()
        self._update_conflicts()
        self._update_status()
        self.student_panel.refresh()
        self.show_report()
        self.toast("排位完成：软约束得分 %.1f，硬约束违反 %d 条" % (solution.soft_score, solution.hard_count))

    def show_report(self) -> None:
        """打开底部「排位结果」页（排完位也会自动开到这里）。"""
        solution = self._last_solution
        if solution is None:
            engine = self._engine()
            from ..models.assignment import Solution

            evaluation = engine.evaluate(self.project.assignment)
            solution = Solution(
                assignment=dict(self.project.assignment),
                score=evaluation.objective,
                soft_score=evaluation.score,
                hard_violations=engine.check_hard(self.project.assignment),
                rule_scores=evaluation.rule_scores,
            )
        self._fill_result_panel(solution)
        self.show_bottom(1)

    def _on_theme_toggled(self, dark: bool) -> None:
        """黑夜 / 白天切换：重装调色板与 QSS，联动标题栏并记住选择。"""
        theme.apply_theme(QApplication.instance(), dark=dark)
        QSettings(config.ORG_NAME, config.APP_ID).setValue(
            config.SK_THEME, "dark" if dark else "light"
        )
        theme.apply_dark_titlebar(self, dark)
        # 明暗键的图标跟着换成「点一下会切到的那一边」
        self.activity_bar.set_theme_icon(dark)
        self._recolor_action_icons(dark)
        self.grid._apply_rubber_theme()   # 框选橡皮筋跟随主题色

    def _recolor_action_icons(self, dark: bool) -> None:
        """工具栏 / 菜单图标按新主题重新着色（SVG 描边色写死在文件里）。"""
        icon_color(dark)          # 先让 icon_loader 认下当前主题（缓存按颜色区分）
        for act in self.findChildren(QAction):
            name = act.property("icon_name")
            if name:
                act.setIcon(action_icon(name))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 命名
        # 浮动的程序内窗口（停靠面板拖出后）靠近主窗口边缘 / 角落时磁性贴靠
        if event.type() == QEvent.Type.Move and isinstance(obj, QDockWidget):
            if obj.isFloating():
                self._snap_floating_dock(obj)
        return super().eventFilter(obj, event)

    def _snap_floating_dock(self, dock: QDockWidget) -> None:
        frame = dock.frameGeometry()
        target, _edge = motion.compute_dock_snap_target(frame, self.frameGeometry())
        if target is None or target == frame.topLeft():
            return
        if motion.reduced_motion():
            dock.move(target)
            return
        slide = QPropertyAnimation(dock, b"pos", dock)
        slide.setDuration(motion.DUR_SNAP)
        slide.setEasingCurve(motion.ease_in_out())
        slide.setStartValue(frame.topLeft())
        slide.setEndValue(target)
        slide.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def show_ai_panel(self) -> None:
        """打开并聚焦「AI 助手」停靠窗口（工具栏 / 菜单 / 规则面板的统一入口）。"""
        self.ai_dock.show()
        self.ai_dock.raise_()
        self.ai_panel.setFocus()

    def _on_ai_rules_ready(self, rules: list, solve_after: bool) -> None:
        """AI 面板交来的规则草稿：落库、刷新，按需接着自动排位。"""
        added = 0
        for rule in rules:
            if self.project.add_rule(rule):
                added += 1
        if added == 0:
            self._warn("规则没有添加成功（可能与已有规则重复）。")
            return
        self._on_rules_changed()
        self.toast("已添加 %d 条 AI 规则" % added)
        if solve_after:
            self.solve()

    def _on_rules_changed(self) -> None:
        self.rule_panel.refresh()
        self._update_conflicts()
        self._update_status()

    # 选区
    def _on_selection_apply(self, selection_id: str) -> None:
        selection = self.project.get_selection(selection_id)
        if selection is None:
            self.toast("找不到该选区")
            return
        self.grid.set_selected(selection.seats)
        self.toast("已选中选区「%s」（%d 个座位）" % (selection.name, len(selection.seats)))

    def _on_selection_created(self, name: str, seats) -> None:
        if not seats:
            self.toast("请先在座位表上选择座位")
            return
        existing = None
        for selection in self.project.selections:
            if selection.name == name:
                existing = selection
                break
        if existing is not None:
            self.project.update_selection_seats(existing.id, seats)
            self.toast("已更新选区「%s」" % name)
        else:
            self.project.add_selection(name, seats)
            self.toast("已保存选区「%s」（%d 个座位）" % (name, len(set(seats))))
        self.selection_panel.refresh()

    def _on_selection_deleted(self, selection_id: str) -> None:
        if self._confirm("删除该选区？引用它的规则会被停用。"):
            self.project.remove_selection(selection_id)
            self._refresh_all()

    def _on_selection_renamed(self, selection_id: str, name: str) -> None:
        if self.project.rename_selection(selection_id, name):
            self.selection_panel.refresh()
            self.rule_panel.refresh()

    # 轮换
    def _on_rotation_preview(self, plan) -> None:
        self._pending_rotation_preview = plan
        changed = []
        for key, _old, _new in plan.changes:
            coord = try_parse_key(key)
            if coord is not None:
                changed.append(coord)
        if changed:
            self.grid.set_selected(changed)
        self.toast("轮换预览：变动 %d 处%s" % (
            len(plan.changes), "（存在冲突，详见提示）" if plan.warnings else ""))

    def _on_rotation_apply(self, plan) -> None:
        if plan is None:
            return
        if plan.warnings:
            if not self._confirm("轮换后存在问题：\n\n%s\n\n仍然应用吗？" % "\n".join(plan.warnings)):
                return
        self._push_history("应用轮换")
        try:
            record = self.rotation_service.apply(plan, plan.description)
        except RotationError as exc:
            QMessageBox.warning(self, "轮换失败", str(exc))
            return
        self.grid.refresh()
        self._update_conflicts()
        self._update_status()
        self.rotation_panel.refresh()
        self.student_panel.refresh()
        self.toast("已应用轮换，记录为第 %d 周" % record.week)

    def _on_rotation_rollback(self, week: int) -> None:
        if not self._confirm("回退到第 %d 周的座位方案？" % week):
            return
        self._push_history("回退到第 %d 周" % week)
        if self.rotation_service.rollback(int(week)):
            self.grid.refresh()
            self._update_conflicts()
            self._update_status()
            self.toast("已回退到第 %d 周" % week)
        else:
            self.toast("找不到第 %d 周的记录" % week)

    # 视图
    def _on_show_sid(self, flag: bool) -> None:
        if self._syncing_view:
            return
        self._settings().setValue(config.SK_SHOW_SID, bool(flag))
        self.grid.set_show_sid(flag)

    def _on_show_title(self, flag: bool) -> None:
        if self._syncing_view:
            return
        self._settings().setValue(config.SK_SHOW_GROUP_TITLE, bool(flag))
        # 写回 project.layout 才会随项目保存
        if self.project.layout.show_group_title != bool(flag):
            self.project.layout.show_group_title = bool(flag)
            self.project.notify(EV_LAYOUT)
        else:
            self.grid.set_show_group_title(flag)

    def _on_show_selection(self, flag: bool) -> None:
        if self._syncing_view:
            return
        self._settings().setValue(config.SK_SHOW_SELECTION, bool(flag))
        self.grid.set_selection_visible(flag)

    def _on_card_size(self, name: str) -> None:
        if not name:
            return
        for key, act in self.act_size.items():
            act.setChecked(key == name)
        self._settings().setValue(config.SK_CARD_SIZE, name)
        # 同上：座位尺寸也属于教室布局
        if self.project.layout.card_size != name:
            self.project.layout.card_size = name
            self.project.notify(EV_LAYOUT)
        else:
            self.grid.set_card_size(name)

    def _sync_view_actions(self) -> None:
        """把「视图」菜单的勾选状态对齐到当前项目布局与本地设置。"""
        self._syncing_view = True
        try:
            layout = self.project.layout
            self.act_show_title.setChecked(bool(layout.show_group_title))
            act = self.act_size.get(layout.card_size)
            if act is not None:
                act.setChecked(True)
            self.grid.set_show_group_title(bool(layout.show_group_title))
            self.grid.set_card_size(layout.card_size)
            self.grid.set_selection_visible(self.act_show_selection.isChecked())
            self._sync_editor_header()
        finally:
            self._syncing_view = False

    # 文件
    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        self._forget_last_project()
        self._rebind_project(new_project())
        self.toast("已新建项目：默认 3 组 × 6 排 × 2 列")

    def open_project(self, path: str = "") -> None:
        if not path:
            if not self._confirm_discard():
                return
            path, _ = QFileDialog.getOpenFileName(self, "打开项目", self._last_dir(), config.PROJECT_FILTER)
            if not path:
                return
        try:
            project = JsonProjectStore.load(path)
        except ProjectStoreError as exc:
            QMessageBox.warning(self, "无法打开", str(exc))
            return
        self._rebind_project(project)
        self._remember_dir(path)
        self._add_recent(path)
        self._remember_last_project(path)
        self.toast("已打开 %s（%d 名学生）" % (os.path.basename(path), len(project.students)))

    def save_project(self) -> bool:
        if not self.project.path:
            return self.save_project_as()
        try:
            JsonProjectStore.save(self.project, self.project.path)
        except ProjectStoreError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        JsonProjectStore.clear_autosave()
        self._add_recent(self.project.path)
        self._remember_last_project(self.project.path)
        self.setWindowTitle(self._window_title())
        self.toast("已保存到 %s" % self.project.path)
        return True

    def save_project_as(self) -> bool:
        default = self.project.path or self._default_name("座位表.seatproj")
        path, _ = QFileDialog.getSaveFileName(self, "另存为", default, config.PROJECT_FILTER)
        if not path:
            return False
        self.project.path = path
        return self.save_project()

    def _rebind_project(self, project: Project) -> None:
        """切换到另一个 Project：解绑旧项目、重建服务与面板绑定。"""
        previous = self.project
        if previous is not None:
            previous.unsubscribe(self._on_project_event)
        self.project = project
        project.subscribe(self._on_project_event)

        self.student_service = StudentService(project)
        self.rotation_service = RotationService(project)
        self.history.reset(project.assignment, "打开项目")
        self._pending_sids = []
        self._conflicts = {}
        self._locked_seats = set()
        self._last_solution = None
        self._pending_rotation_preview = None
        self.grid.set_project(project)
        self.student_panel.set_project(self.project, self.student_service)
        self.rule_panel.set_project(self.project)
        self.selection_panel.set_project(self.project)
        self.rotation_panel.set_project(self.project)
        self.ai_panel.set_project(self.project)
        self._refresh_all()
        self._sync_view_actions()
        self.grid.set_locked_seats(self._locked_seats)

    # 最近文件
    def _settings(self) -> QSettings:
        return QSettings(config.ORG_NAME, config.APP_ID)

    def _recent_files(self) -> List[str]:
        value = self._settings().value(config.SK_RECENT_FILES, [])
        if isinstance(value, str):
            value = [value]
        return [str(v) for v in (value or []) if v]

    def _add_recent(self, path: str) -> None:
        items = [p for p in self._recent_files() if os.path.normcase(p) != os.path.normcase(path)]
        items.insert(0, path)
        self._settings().setValue(config.SK_RECENT_FILES, items[:MAX_RECENT])
        self._update_recent_menu()

    def _update_recent_menu(self) -> None:
        self.recent_menu.clear()
        items = [p for p in self._recent_files() if os.path.exists(p)]
        if not items:
            act = self.recent_menu.addAction("（暂无）")
            act.setEnabled(False)
            return
        for path in items:
            act = self.recent_menu.addAction(os.path.basename(path))
            act.setToolTip(path)
            act.triggered.connect(lambda _c, p=path: self.open_project(p))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("清除最近记录", self._clear_recent)

    def _clear_recent(self) -> None:
        self._settings().setValue(config.SK_RECENT_FILES, [])
        self._update_recent_menu()

    def _last_dir(self) -> str:
        return str(self._settings().value(config.SK_LAST_DIR, str(Path.home())))

    def _remember_dir(self, path: str) -> None:
        self._settings().setValue(config.SK_LAST_DIR, str(Path(path).parent))

    def _default_name(self, name: str) -> str:
        return str(Path(self._last_dir()) / name)

    # 自动保存
    def _autosave(self) -> None:
        # 只要还有未保存的改动就写自动保存：内容包括教室布局、规则、选区，
        # 不只是学生和座位（否则只调好布局就崩溃会白调）。
        if not self.project.dirty:
            return
        if JsonProjectStore.autosave(self.project) is None:
            self.lbl_autosave.setText("自动保存失败，请手动保存（Ctrl+S）")
            self.lbl_autosave.setToolTip(JsonProjectStore.last_error)
            self.toast("自动保存失败，请手动保存（Ctrl+S）", 8000)
        else:
            self.lbl_autosave.clear()
            self.lbl_autosave.setToolTip("")

    def _maybe_recover(self) -> None:
        info = JsonProjectStore.autosave_info()
        if not info.get("exists"):
            return
        if self.project.path:
            # 已经打开了项目文件：只有自动保存比它更新时才值得恢复
            if float(info.get("mtime") or 0) <= self._project_mtime():
                return
        elif self.project.students or self.project.assignment:
            return
        answer = QMessageBox.question(
            self, "发现自动保存",
            "检测到 %s 的自动保存内容，是否恢复？" % info.get("time", ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            JsonProjectStore.clear_autosave()
            return
        project = JsonProjectStore.load_autosave()
        if project is None:
            self.toast("自动保存内容已损坏，无法恢复")
            return
        self._rebind_project(project)
        self.toast("已恢复自动保存内容")

    def _project_mtime(self) -> float:
        try:
            return float(os.path.getmtime(self.project.path))
        except OSError:
            return 0.0

    def _maybe_welcome(self) -> None:
        """首次启动弹「开始引导」；用户勾了「不再显示」之后才不再弹。"""
        settings = self._settings()
        if settings.value(config.SK_WELCOME_SHOWN, False, type=bool):
            return
        self.show_onboarding()

    def show_onboarding(self) -> None:
        """四步上手引导；步骤按钮直接跳到对应操作，可从「帮助」菜单随时重看。"""
        from .dialogs.onboarding_dialog import OnboardingDialog

        def go_rules() -> None:
            self.show_sidebar_page("rules")
            self.side_dock.raise_()

        steps = (
            ("设置教室布局",
             "教室分几组、几排、几列。点顶部「教室布局」，选个模板就行。",
             "去设置布局", self.edit_layout),
            ("导入学生名单",
             "选 Excel 文件一键导入；没有 Excel 也可以在左侧名单里点「添加」手动输入。",
             "导入名单", self.import_excel),
            ("挑几条排座规则",
             "比如「视力差的坐前排」。不挑也行，程序会按姓名顺序直接排。",
             "去看看", go_rules),
            ("一键排位并导出",
             "按 F5 自动排好，拖一拖微调，满意就导出 Excel 或图片发给班主任群。",
             "一键排位", self.solve),
        )
        dialog = OnboardingDialog(self, steps)
        dialog.exec()
        if dialog.dont_show_again():
            self._settings().setValue(config.SK_WELCOME_SHOWN, True)
        action = dialog.taken_action()
        if action is not None:
            QTimer.singleShot(0, action)

    # 设置
    def _restore_settings(self) -> None:
        settings = self._settings()
        geometry = settings.value(config.SK_GEOMETRY)
        if geometry is not None:
            self.restoreGeometry(geometry)
            self._clamp_geometry_to_screen()
        state = settings.value(config.SK_STATE)
        if state is not None:
            self.restoreState(state)
        self.act_show_sid.setChecked(settings.value(config.SK_SHOW_SID, True, type=bool))
        self.act_show_selection.setChecked(
            settings.value(config.SK_SHOW_SELECTION, True, type=bool))
        # 座位尺寸 / 组标题属于项目本身（布局编辑器里也在改），打开旧项目时
        # 必须听项目的——否则教师刚用「单排」模板调好的小号卡片，会被这台机器
        # 上次留下的偏好覆盖掉。所以只给「全新的空项目」套用偏好。
        if not self._is_fresh_project():
            self.grid.set_show_sid(self.act_show_sid.isChecked())
            return
        size = str(settings.value(config.SK_CARD_SIZE, "", type=str) or "")
        if size in self.act_size:
            self.project.layout.card_size = size
        self.project.layout.show_group_title = settings.value(
            config.SK_SHOW_GROUP_TITLE, self.project.layout.show_group_title, type=bool)
        self.grid.set_show_sid(self.act_show_sid.isChecked())

    def _is_fresh_project(self) -> bool:
        """还没有任何内容的项目（启动时的默认项目）。"""
        project = self.project
        return not (project.students or project.assignment or project.rules
                    or project.selections or project.history or project.path)

    def _clamp_geometry_to_screen(self) -> None:
        """把保存下来的窗口尺寸收回屏幕内。

        上次的尺寸可能来自更大 / 已拔掉的显示器，或来自小屏上缩放比变化之前；
        直接套用会让窗口比屏幕还大、标题栏跑到屏幕外。
        """
        if self.isMaximized() or self.isFullScreen():
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        too_big = (frame.width() > available.width() + 2
                   or frame.height() > available.height() + 2)
        outside = not available.intersects(frame)
        if not (too_big or outside):
            return
        width = max(self.minimumWidth(), min(self.width(), available.width() - 20))
        height = max(self.minimumHeight(), min(self.height(), available.height() - 60))
        self.resize(width, height)
        self.move(
            available.x() + max(0, (available.width() - width) // 2),
            available.y() + max(0, (available.height() - height) // 3),
        )

    def _save_settings(self) -> None:
        settings = self._settings()
        settings.setValue(config.SK_GEOMETRY, self.saveGeometry())
        settings.setValue(config.SK_STATE, self.saveState())
        settings.setValue(config.SK_SHOW_SID, self.act_show_sid.isChecked())
        settings.setValue(config.SK_SHOW_SELECTION, self.act_show_selection.isChecked())
        settings.setValue(config.SK_CARD_SIZE, self.project.layout.card_size)
        settings.setValue(config.SK_SHOW_GROUP_TITLE,
                          bool(self.project.layout.show_group_title))

    # 上次的项目
    def _remember_last_project(self, path: str) -> None:
        self._settings().setValue(config.SK_LAST_PROJECT, str(path or ""))

    def _forget_last_project(self) -> None:
        self._settings().remove(config.SK_LAST_PROJECT)

    def _restore_last_project(self) -> None:
        """启动时自动打开上次编辑的项目。

        否则教师配好的教室布局虽然写进了项目文件，重新打开程序后看到的
        仍是默认布局，等于「设置没有保存下来」。
        """
        path = str(self._settings().value(config.SK_LAST_PROJECT, "", type=str) or "")
        if not path:
            return
        if not os.path.exists(path):
            self._forget_last_project()
            return
        try:
            project = JsonProjectStore.load(path)
        except ProjectStoreError as exc:
            self._forget_last_project()
            self.toast("上次的项目已无法打开：%s" % exc)
            return
        self._rebind_project(project)
        self._add_recent(path)

    # 帮助
    def show_help(self) -> None:
        steps = "\n".join(config.WELCOME_STEPS)
        text = (
            "<b>四步排好一次座位</b><br><pre style='font-family:inherit;'>%s</pre>"
            "<b>常用快捷键</b>"
            "<table cellpadding='3'>"
            "<tr><td>F5</td><td>一键排位（Ctrl+R 换一批）</td></tr>"
            "<tr><td>Ctrl+B</td><td>教室布局（改行列 / 单排单列）</td></tr>"
            "<tr><td>Ctrl+I</td><td>导入学生名单</td></tr>"
            "<tr><td>Ctrl+E</td><td>导出 Excel 座位表</td></tr>"
            "<tr><td>Ctrl+Z / Ctrl+Y</td><td>撤销 / 重做（Ctrl+Shift+Z 亦可）</td></tr>"
            "<tr><td>Delete</td><td>清空选中座位</td></tr>"
            "<tr><td>Ctrl+A</td><td>全选座位</td></tr>"
            "<tr><td>Ctrl+N / Ctrl+O / Ctrl+S</td><td>新建 / 打开 / 保存项目</td></tr>"
            "</table>"
            "<b>鼠标操作</b>"
            "<table cellpadding='3'>"
            "<tr><td>在名单里选中学生 → 点击空座位</td><td>学生入座</td></tr>"
            "<tr><td>从座位拖到另一个座位</td><td>两人交换 / 移动到空位</td></tr>"
            "<tr><td>在空白处拖拽框选 / Ctrl+点击</td><td>选择多个座位</td></tr>"
            "<tr><td>右键座位</td><td>清空 / 留空 / 固定 / 编辑学生</td></tr>"
            "<tr><td>悬停座位</td><td>查看学生完整信息</td></tr>"
            "</table>"
        ) % steps
        box = QMessageBox(self)
        box.setWindowTitle("使用说明")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(text)
        box.exec()

    def show_about(self) -> None:
        QMessageBox.about(self, "关于 %s" % config.APP_NAME, about_text())

    # 杂项
    def _confirm(self, text: str, title: str = "确认") -> bool:
        return confirm(self, text, title)

    def _confirm_discard(self) -> bool:
        if not self.project.dirty:
            return True
        answer = QMessageBox.question(
            self, "尚未保存",
            "当前项目有未保存的改动，是否先保存？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        if answer == QMessageBox.StandardButton.Discard:
            return True
        return False

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._confirm_discard():
            event.ignore()
            return
        self._save_settings()
        JsonProjectStore.clear_autosave()
        event.accept()
