"""布局编辑器对话框：配置教室分组、行列、组名、组间距与讲台方向。

左侧参数面板 + 右侧实时预览，快速模板取自 ``models.layout.LAYOUT_TEMPLATES``。
编辑始终在 ``project.layout.clone()`` 上进行，取消不会影响项目。
"""

from __future__ import annotations

from typing import Optional, Tuple

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from ..common import CollapsibleSection, fit_to_screen, hline
from ...models.layout import (
    CARD_SIZES, LAYOUT_TEMPLATES, MAX_COLS, MAX_GAP, MAX_GROUPS, MAX_ROWS, MIN_COLS,
    MIN_GAP, MIN_ROWS, PODIUM_SIDES, Layout, SeatGroup, template_layout,
)
from ..style.theme import (
    CARD_SIZE_LABELS, FONT_PODIUM, GRID_SPACING, PODIUM_HEIGHT, RADIUS_CARD,
    Color, aisle_width, seat_size,
)

# ``_combo`` 约定每项是 (显示文字, 内部值)
PODIUM_LABELS = (("讲台在上方", "top"), ("讲台在下方", "bottom"))
CARD_ORDER = ("small", "medium", "large")
TEMPLATE_CUSTOM = "（自定义）"

# 期望的打开尺寸（默认 3 组 × 2 列恰好能完整预览）；最小尺寸在此基础上
# 取「布局内容真实需求」与下限的较大者——显式最小尺寸一旦小于内容所需，
# 布局就会把控件压缩到互相重叠。
PREFERRED_WIDTH = 1040
PREFERRED_HEIGHT = 660
MIN_WIDTH = 720
MIN_HEIGHT = 560


def _spin(minimum: int, maximum: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(int(minimum), int(maximum))
    return spin


def _combo(pairs) -> QComboBox:
    combo = QComboBox()
    for text, data in pairs:
        combo.addItem(text, data)
    return combo


class LayoutEditorDialog(QDialog):
    """编辑教室布局；接受后 ``result_layout`` 为新的 ``Layout``。"""

    def __init__(self, project, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self.result_layout: Optional[Layout] = None
        self._layout: Layout = project.layout.clone()
        self._loading = False
        self.setWindowTitle("编辑教室布局")
        self._build_ui()

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._rebuild_preview)

        self._sync_level_controls()
        self._sync_template_combo()
        self._refresh_group_list(0)
        self._rebuild_preview()
        self._fit_to_content()

    # 界面
    def _build_ui(self) -> None:
        self._loading = True
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        title = QLabel("教室布局")
        title.setObjectName("PanelTitle")
        root.addWidget(title)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("快速模板"))
        self._template_combo = _combo(
            [(TEMPLATE_CUSTOM, -1)]
            + [(name, index) for index, (name, _g, _r, _c) in enumerate(LAYOUT_TEMPLATES)]
        )
        self._template_combo.setMinimumWidth(200)
        top.addWidget(self._template_combo)
        top.addStretch(1)
        hint = QLabel("选模板 → 右侧看效果 → 确定")
        hint.setObjectName("Hint")
        top.addWidget(hint)
        root.addLayout(top)
        root.addWidget(hline())

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_left(), 0)
        body.addWidget(self._build_preview(), 1)
        root.addLayout(body, 1)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = box.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("确定")
        ok.setObjectName("Primary")
        ok.setDefault(True)
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self._template_combo.currentIndexChanged.connect(self._apply_template)
        self._loading = False

    def _build_left(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)
        caption = QLabel("分组")
        caption.setObjectName("PanelTitle")
        box.addWidget(caption)

        self._shape_label = QLabel("")
        self._shape_label.setObjectName("Hint")
        self._shape_label.setWordWrap(True)
        box.addWidget(self._shape_label)

        self._group_list = QListWidget()
        self._group_list.setMinimumHeight(80)
        self._group_list.currentRowChanged.connect(self._load_group)
        box.addWidget(self._group_list, 1)

        self._add_btn = QPushButton("添加分组")
        self._del_btn = QPushButton("删除")
        self._del_btn.setObjectName("Danger")
        self._up_btn = QPushButton("上移")
        self._down_btn = QPushButton("下移")
        self._add_btn.clicked.connect(self._add_group)
        self._del_btn.clicked.connect(self._remove_group)
        self._up_btn.clicked.connect(lambda: self._move_group(-1))
        self._down_btn.clicked.connect(lambda: self._move_group(1))
        for buttons in ((self._add_btn, self._del_btn), (self._up_btn, self._down_btn)):
            row = QHBoxLayout()
            row.setSpacing(6)
            for button in buttons:
                row.addWidget(button)
            box.addLayout(row)

        form = QFormLayout()
        form.setSpacing(6)
        self._name_edit = QLineEdit()
        self._rows_spin = _spin(MIN_ROWS, MAX_ROWS)
        self._cols_spin = _spin(MIN_COLS, MAX_COLS)
        self._gap_spin = _spin(MIN_GAP, MAX_GAP)
        form.addRow("组名", self._name_edit)
        form.addRow("行数（排）", self._rows_spin)
        form.addRow("列数（座）", self._cols_spin)
        form.addRow("组间距", self._gap_spin)
        box.addLayout(form)

        # 单排 / 单列：一排一排、一列一列地加减，不用去数数字框
        stepper = QGridLayout()
        stepper.setSpacing(6)
        self._row_minus_btn = QPushButton("－ 一排")
        self._row_plus_btn = QPushButton("＋ 一排")
        self._col_minus_btn = QPushButton("－ 一列")
        self._col_plus_btn = QPushButton("＋ 一列")
        self._row_minus_btn.setToolTip("当前分组减少一排")
        self._row_plus_btn.setToolTip("当前分组增加一排")
        self._col_minus_btn.setToolTip("当前分组减少一列（减到 1 列就是单列）")
        self._col_plus_btn.setToolTip("当前分组增加一列（加到 8 列就是单排）")
        self._row_minus_btn.clicked.connect(lambda: self._step_rows(-1))
        self._row_plus_btn.clicked.connect(lambda: self._step_rows(1))
        self._col_minus_btn.clicked.connect(lambda: self._step_cols(-1))
        self._col_plus_btn.clicked.connect(lambda: self._step_cols(1))
        stepper.addWidget(self._row_minus_btn, 0, 0)
        stepper.addWidget(self._row_plus_btn, 0, 1)
        stepper.addWidget(self._col_minus_btn, 1, 0)
        stepper.addWidget(self._col_plus_btn, 1, 1)
        box.addLayout(stepper)

        self._podium_combo = _combo(list(PODIUM_LABELS))
        podium_form = QFormLayout()
        podium_form.setSpacing(6)
        podium_form.addRow("讲台方向", self._podium_combo)
        box.addLayout(podium_form)

        self._advanced = CollapsibleSection("高级选项", tooltip="座位尺寸、是否显示组标题")
        level_form = QFormLayout()
        level_form.setSpacing(6)
        self._card_combo = _combo([(CARD_SIZE_LABELS[key], key) for key in CARD_ORDER])
        self._title_check = QCheckBox("显示组标题")
        level_form.addRow("座位尺寸", self._card_combo)
        level_form.addRow("", self._title_check)
        level_host = QWidget()
        level_host.setLayout(level_form)
        self._advanced.body_layout.addWidget(level_host)
        box.addWidget(self._advanced)

        self._name_edit.textEdited.connect(self._on_name_edited)
        for spin in (self._rows_spin, self._cols_spin, self._gap_spin):
            spin.valueChanged.connect(self._on_group_changed)
        self._podium_combo.currentIndexChanged.connect(self._on_level_changed)
        self._card_combo.currentIndexChanged.connect(self._on_level_changed)
        self._title_check.toggled.connect(self._on_level_changed)

        # 参数区放进滚动区：屏幕矮的时候可以滚动，而不是把控件压到互相重叠
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(panel)
        area.setMinimumWidth(324)
        area.setMaximumWidth(392)
        return area

    def _build_preview(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)
        caption = QLabel("预览")
        caption.setObjectName("PanelTitle")
        box.addWidget(caption)

        # 预览内容放在「上下左右都带弹簧」的容器里：容器随滚动区视口伸缩，
        # 座位网格保持自然大小并居中，超出视口时才出现滚动条。
        self._preview_host = QWidget()
        self._preview_host.setObjectName("Canvas")
        host_box = QVBoxLayout(self._preview_host)
        host_box.setContentsMargins(0, 0, 0, 0)
        host_box.addStretch(1)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        self._preview_grid = QGridLayout()
        self._preview_grid.setContentsMargins(8, 8, 8, 8)
        self._preview_grid.setSpacing(GRID_SPACING)
        row.addLayout(self._preview_grid)
        row.addStretch(1)
        host_box.addLayout(row)
        host_box.addStretch(1)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self._preview_host)
        box.addWidget(area, 1)
        return panel

    def _fit_to_content(self) -> None:
        """打开时按内容需要设定尺寸，并保证最小尺寸不会把控件压到重叠。

        显式的最小尺寸会覆盖布局自身的最小尺寸（Qt 的 SetDefaultConstraint
        语义）：一旦设得比内容所需更小，布局就会把控件压缩到互相重叠。
        这里统一取「下限」与「内容真实需求」的较大者，再用屏幕可用区域封顶
        （高 DPI / 小屏笔记本上，写死的尺寸会把「确定」按钮顶到屏幕外）。
        """
        hint = self.minimumSizeHint()
        min_width = max(MIN_WIDTH, int(hint.width()))
        min_height = max(MIN_HEIGHT, int(hint.height()))
        width = max(PREFERRED_WIDTH, int(hint.width()))
        height = max(PREFERRED_HEIGHT, int(hint.height()))
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            max_width = max(520, available.width() - 40)
            max_height = max(420, available.height() - 60)
            min_width = min(min_width, max_width)
            min_height = min(min_height, max_height)
            width = min(width, max_width)
            height = min(height, max_height)
        self.setMinimumSize(min_width, min_height)
        self.resize(max(min_width, width), max(min_height, height))

    # 数据同步
    def _group_at(self, row: int) -> Optional[SeatGroup]:
        if 0 <= int(row) < len(self._layout.groups):
            return self._layout.groups[int(row)]
        return None

    def _current_group(self) -> Optional[SeatGroup]:
        return self._group_at(self._group_list.currentRow())

    def _sync_level_controls(self) -> None:
        self._loading = True
        self._podium_combo.setCurrentIndex(max(0, self._podium_combo.findData(self._layout.podium_side)))
        self._card_combo.setCurrentIndex(max(0, self._card_combo.findData(self._layout.card_size)))
        self._title_check.setChecked(bool(self._layout.show_group_title))
        self._loading = False

    def _sync_template_combo(self) -> None:
        self._loading = True
        index = 0
        for i, (_name, groups, rows, cols) in enumerate(LAYOUT_TEMPLATES, start=1):
            if groups == self._layout.group_count and all(
                g.rows == rows and g.cols == cols for g in self._layout.groups
            ):
                index = i
                break
        self._template_combo.setCurrentIndex(index)
        self._loading = False

    def _refresh_group_list(self, select: Optional[int] = None) -> None:
        self._loading = True
        self._group_list.clear()
        for group in self._layout.groups:
            self._group_list.addItem(
                QListWidgetItem("%s（%d 行 × %d 列）" % (group.name, group.rows, group.cols))
            )
        count = self._group_list.count()
        index = 0 if select is None else int(select)
        index = max(0, min(count - 1, index)) if count else -1
        if count:
            self._group_list.setCurrentRow(index)
        self._loading = False
        self._load_group(index)
        self._update_buttons()

    def _load_group(self, row: int) -> None:
        group = self._group_at(row)
        if group is None or self._loading:
            return
        self._loading = True
        self._name_edit.setText(group.name)
        self._rows_spin.setValue(group.rows)
        self._cols_spin.setValue(group.cols)
        self._gap_spin.setValue(group.gap_after)
        self._loading = False
        self._update_buttons()

    def _update_buttons(self) -> None:
        row = self._group_list.currentRow()
        count = len(self._layout.groups)
        self._up_btn.setEnabled(row > 0)
        self._down_btn.setEnabled(0 <= row < count - 1)
        self._del_btn.setEnabled(count > 1 and row >= 0)
        self._add_btn.setEnabled(count < MAX_GROUPS)
        has_group = self._group_at(row) is not None
        self._row_minus_btn.setEnabled(has_group and self._rows_spin.value() > MIN_ROWS)
        self._row_plus_btn.setEnabled(has_group and self._rows_spin.value() < MAX_ROWS)
        self._col_minus_btn.setEnabled(has_group and self._cols_spin.value() > MIN_COLS)
        self._col_plus_btn.setEnabled(has_group and self._cols_spin.value() < MAX_COLS)
        self._update_shape_label()

    def _update_shape_label(self) -> None:
        """一句话说清当前布局形状（单排 / 单列会被点名）。"""
        layout = self._layout
        groups = layout.groups
        total = layout.seat_count()
        if not groups:
            self._shape_label.setText("还没有分组")
            return
        rows = max([g.rows for g in groups])
        cols = groups[0].cols
        same = all(g.rows == rows and g.cols == cols for g in groups)
        if len(groups) == 1 and rows == 1:
            shape = "单排：1 排 × %d 列" % cols
        elif len(groups) == 1 and cols == 1:
            shape = "单列：%d 排 × 1 列" % rows
        elif same and cols == 1:
            shape = "%d 组单列：每组 %d 排" % (len(groups), rows)
        elif same and rows == 1:
            shape = "%d 组，每组都是单排：%d 排 × %d 列" % (len(groups), rows, cols)
        elif same:
            shape = "%d 组 × %d 排 × %d 列" % (len(groups), rows, cols)
        else:
            shape = "%d 组（每组行列不同）" % len(groups)
        self._shape_label.setText("%s，共 %d 个座位" % (shape, total))

    def _step_rows(self, delta: int) -> None:
        """加 / 减一整排（当前分组）。"""
        self._rows_spin.setValue(self._rows_spin.value() + int(delta))

    def _step_cols(self, delta: int) -> None:
        """加 / 减一整列（当前分组）；减到 1 列就是单列布局。"""
        self._cols_spin.setValue(self._cols_spin.value() + int(delta))

    def _update_list_text(self, row: int) -> None:
        group = self._group_at(row)
        item = self._group_list.item(row)
        if group is not None and item is not None:
            item.setText("%s（%d 行 × %d 列）" % (group.name, group.rows, group.cols))

    def _schedule_preview(self) -> None:
        timer = getattr(self, "_preview_timer", None)
        if timer is None:
            self._rebuild_preview()
        else:
            timer.start()

    # 交互
    def _on_name_edited(self, text: str) -> None:
        if self._loading:
            return
        row = self._group_list.currentRow()
        group = self._group_at(row)
        if group is None:
            return
        group.name = str(text).strip() or ("第 %d 组" % (row + 1))
        self._update_list_text(row)
        self._schedule_preview()

    def _on_group_changed(self, *_args) -> None:
        if self._loading:
            return
        row = self._group_list.currentRow()
        group = self._group_at(row)
        if group is None:
            return
        group.rows = self._rows_spin.value()
        group.cols = self._cols_spin.value()
        group.gap_after = self._gap_spin.value()
        self._layout.prune_disabled()
        self._update_list_text(row)
        self._update_buttons()
        self._schedule_preview()

    def _on_level_changed(self, *_args) -> None:
        if self._loading:
            return
        # 只接受合法取值：写进布局的非法值会被 from_dict 静默改回默认值，
        # 表现为「设置完下次打开又变回去了」。
        podium = str(self._podium_combo.currentData() or "")
        self._layout.podium_side = podium if podium in PODIUM_SIDES else "top"
        card = str(self._card_combo.currentData() or "")
        self._layout.card_size = card if card in CARD_SIZES else "medium"
        self._layout.show_group_title = self._title_check.isChecked()
        self._schedule_preview()

    def _apply_template(self, _index: int) -> None:
        if self._loading:
            return
        try:
            index = int(self._template_combo.currentData())
        except (TypeError, ValueError):
            return
        if index < 0:
            return
        try:
            fresh = template_layout(index)
        except Exception:  # 模板异常不应崩溃
            return
        disabled = set(self._layout.disabled_seats)
        self._layout = fresh
        self._layout.disabled_seats = {s for s in disabled if self._layout.contains(s)}
        self._sync_level_controls()
        self._refresh_group_list(0)
        self._rebuild_preview()

    def _add_group(self) -> None:
        if len(self._layout.groups) >= MAX_GROUPS:
            QMessageBox.information(self, "无法添加", "最多支持 %d 个分组" % MAX_GROUPS)
            return
        base = self._current_group()
        if self._layout.add_group(rows=base.rows if base else 6,
                                  cols=base.cols if base else 2) is None:
            return
        self._refresh_group_list(len(self._layout.groups) - 1)
        self._rebuild_preview()

    def _remove_group(self) -> None:
        row = self._group_list.currentRow()
        group = self._group_at(row)
        if group is None or len(self._layout.groups) <= 1:
            QMessageBox.information(self, "无法删除", "至少需要保留 1 个分组")
            return
        answer = QMessageBox.question(self, "删除分组", "确定删除「%s」吗？" % group.name)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._layout.remove_group(row)
        self._refresh_group_list(min(row, len(self._layout.groups) - 1))
        self._rebuild_preview()

    def _move_group(self, delta: int) -> None:
        row = self._group_list.currentRow()
        if row < 0 or not self._layout.move_group(row, delta):
            return
        self._refresh_group_list(row + delta)
        self._rebuild_preview()

    # 预览
    def _podium_widget(self) -> QWidget:
        frame = QFrame()
        frame.setFixedHeight(PODIUM_HEIGHT)
        frame.setMinimumWidth(160)
        frame.setStyleSheet("QFrame { background: %s; border: none; border-radius: %dpx; }"
                            % (Color.PODIUM, RADIUS_CARD))
        label = QLabel("讲　台", frame)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: %s; font-size: %dpx; font-weight: bold; background: transparent;"
                            % (Color.BG_PANEL, FONT_PODIUM))
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        return frame

    def _seat_preview(self, gi: int, row: int, col: int, size: Tuple[int, int, int]) -> QWidget:
        width, height, radius = size
        frame = QFrame()
        frame.setFixedSize(width, height)
        if self._layout.is_disabled((gi, row, col)):
            background, border, style = Color.SEAT_DISABLED, Color.DASHED, "dashed"
        else:
            background, border, style = Color.SEAT_DEFAULT, Color.BORDER, "solid"
        frame.setStyleSheet("QFrame { background: %s; border: 1px %s %s; border-radius: %dpx; }"
                            % (background, style, border, radius))
        frame.setToolTip("第 %d 组 第 %d 排 第 %d 列%s"
                         % (gi + 1, row + 1, col + 1, "（空置）" if style == "dashed" else ""))
        return frame

    def _rebuild_preview(self) -> None:
        grid = self._preview_grid
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        layout = self._layout
        groups = layout.groups
        total_cols = sum(g.cols for g in groups) + max(0, len(groups) - 1)
        row = 0
        if layout.podium_side == "top":
            grid.addWidget(self._podium_widget(), row, 0, 1, max(1, total_cols))
            row += 1
        if layout.show_group_title:
            cursor = 0
            for group in groups:
                label = QLabel(group.name)
                label.setObjectName("PanelTitle")
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                grid.addWidget(label, row, cursor, 1, group.cols)
                cursor += group.cols + 1
            row += 1

        size = seat_size(layout.card_size)
        max_rows = max([g.rows for g in groups], default=1)
        seat_top = row
        # 组间距列跨越所有行，只需插入一次；放在行循环里会按行数重复叠加。
        cursor = 0
        for gi, group in enumerate(groups):
            cursor += group.cols
            if gi < len(groups) - 1:
                spacer = QWidget()
                spacer.setFixedWidth(aisle_width(group.gap_after))
                grid.addWidget(spacer, seat_top, cursor, max_rows, 1)
            cursor += 1
        for r in range(max_rows):
            cursor = 0
            for gi, group in enumerate(groups):
                if r < group.rows:
                    for c in range(group.cols):
                        grid.addWidget(self._seat_preview(gi, r, c, size), seat_top + r, cursor + c)
                cursor += group.cols + 1
        if layout.podium_side == "bottom":
            grid.addWidget(self._podium_widget(), seat_top + max_rows, 0, 1, max(1, total_cols))

    # 结果
    def accept(self) -> None:
        self._layout.prune_disabled()
        if not self._layout.groups:
            QMessageBox.warning(self, "布局不完整", "至少需要保留 1 个分组")
            return
        self.result_layout = self._layout
        super().accept()
