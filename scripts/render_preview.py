"""把主窗口渲染成 PNG，用于人工走查视觉效果。

用法：.venv\\Scripts\\python.exe scripts\\render_preview.py [输出目录]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402


def silence_dialogs() -> None:
    """渲染走查不需要交互，把模态弹窗换成桩，避免脚本被卡住。"""
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.about = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    QMessageBox.exec = lambda self, *a, **k: QDialog.DialogCode.Accepted
    QDialog.exec = lambda self, *a, **k: QDialog.DialogCode.Rejected

from app import config  # noqa: E402
from app.models.layout import Layout  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.rule import RuleKind, make_rule  # noqa: E402
from app.models.student import Student  # noqa: E402
from app.services.rule_engine import RuleEngine  # noqa: E402
from app.services.solver import Solver  # noqa: E402

SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
GIVEN = ["子涵", "浩然", "欣怡", "雨泽", "梓萱", "俊杰", "思远", "佳怡", "宇航", "雨欣",
         "明轩", "诗涵", "宇轩", "梦琪", "皓轩", "静怡", "泽宇", "雅静", "文博", "嘉怡"]
TAGS = ["视力差", "近视", "班干部", "需关注", "优等生", "内向"]


def build_project(count: int = 42) -> Project:
    project = Project()
    project.layout = Layout.from_template(3, 7, 2)
    for i in range(count):
        tags = []
        if i % 9 == 0:
            tags.append("视力差")
        if i % 5 == 0:
            tags.append("班干部")
        if i % 11 == 0:
            tags.append("需关注")
        if i % 6 == 0:
            tags.append("优等生")
        project.add_student(Student(
            sid="2024%04d" % (i + 1),
            name=SURNAMES[i % len(SURNAMES)] + GIVEN[i % len(GIVEN)],
            gender="男" if i % 2 == 0 else "女",
            tags=tags,
            attrs={"身高": 148 + (i * 5) % 32, "成绩": 62 + (i * 13) % 38},
        ))
    for tag in TAGS:
        project.ensure_tag(tag)
    project.add_selection("前排区", project.layout.row_range(0, 0))
    front = project.selections[-1]
    project.add_selection("第 1 组", project.layout.seats_in_group(0))

    rules = [
        (RuleKind.FRONT_REQUIRED, {"tag": "视力差", "rows": 2}),
        (RuleKind.REGION_REQUIRED, {"tag": "需关注", "selection": front.id}),
        (RuleKind.TAG_DISPERSE, {"tag": "班干部"}),
        (RuleKind.DESK_PAIR, {"tag_a": "优等生", "tag_b": "需关注", "mode": "same"}),
        (RuleKind.ATTR_ORDER, {"attr": "身高", "direction": "asc", "axis": "row"}),
        (RuleKind.ATTR_TIER, {"attr": "成绩", "tiers": 3, "mode": "group"}),
        (RuleKind.GENDER_ALTERNATE, {}),
    ]
    for kind, params in rules:
        rule = make_rule(kind)
        rule.params.update(params)
        project.add_rule(rule)
    return project


def _render_icon_strip(path, palette, app) -> None:
    """把 app/ui/widgets/icons.py 里全部图标画成一条对照图（走查 / 回归用）。"""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QPainter, QPixmap

    from app.ui.widgets import icons

    names = sorted(icons.GLYPHS)
    cell = 64
    strip = QPixmap(cell * len(names), 120)
    strip.fill(QColor(palette["BG_RAIL"]))
    painter = QPainter(strip)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for index, name in enumerate(names):
        left = index * cell
        painter.fillRect(left, 0, cell, 60, QColor(palette["BG_PANEL"]))
        # 上排：活动栏尺寸的静止 / 选中色
        icons.paint_glyph(painter, name, QRectF(left + 8, 16, 28, 28),
                          QColor(palette["ICON_MUTED"]))
        icons.paint_glyph(painter, name, QRectF(left + 38, 20, 20, 20),
                          QColor(palette["PRIMARY"]))
        # 下排：面板头尺寸（18px），走在骨架底色上
        painter.fillRect(left, 60, cell, 60, QColor(palette["BG_TABBAR"]))
        icons.paint_glyph(painter, name, QRectF(left + 14, 74, 18, 18),
                          QColor(palette["ICON_MUTED"]))
        icons.paint_glyph(painter, name, QRectF(left + 38, 78, 14, 14),
                          QColor(palette["TEXT_PRIMARY"]))
    painter.end()
    strip.save(str(path), "PNG")
    print("图标对照条：", path, "|", " ".join(names))


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)

    silence_dialogs()
    QSettings(config.ORG_NAME, config.APP_ID).setValue(config.SK_WELCOME_SHOWN, True)
    app = QApplication([])
    from app.ui.style.theme import apply_dark_theme, ensure_font_db

    print("补注册字体数：", ensure_font_db())
    apply_dark_theme(app)
    from app.ui import motion  # noqa: E402

    motion.set_reduced_motion(True)   # 静态截图走查：关掉动效，避免抓到半透明中间帧

    project = build_project()
    engine = RuleEngine.from_project(project)
    solver = Solver(engine, project.students, time_limit=2.0, seed=2024)
    solver.prepare()
    solution = solver.solve()
    project.assignment = dict(solution.assignment)
    project.mark_clean()

    from app.ui.main_window import MainWindow

    window = MainWindow(project)
    window._last_solution = solution
    window._refresh_all()
    window.resize(1500, 940)
    window.show()
    app.processEvents()
    window.grid.refresh()
    app.processEvents()

    full = out_dir / "main_window.png"
    window.grab().save(str(full), "PNG")
    grid = out_dir / "seat_grid.png"
    window.grid.grab().save(str(grid), "PNG")

    # 冲突态截图：故意把“禁止相邻”的两名学生放到一起（用真正的交换操作，避免弄丢学生）
    a = project.students[0].sid
    b = project.students[1].sid
    rule = make_rule(RuleKind.FORBID_ADJACENT)
    rule.params.update({"sid_a": a, "sid_b": b})
    project.add_rule(rule)
    key_a = next(k for k, v in project.assignment.items() if v == a)
    key_b = next(k for k, v in project.assignment.items() if v == b)
    coord_a = tuple(int(x) for x in key_a.split("-"))
    coord_b = tuple(int(x) for x in key_b.split("-"))
    neighbors = [s for s in project.layout.neighbors(coord_a)
                 if s != coord_b and not project.layout.is_disabled(s)]
    if neighbors:
        window.swap_seats(coord_b, neighbors[0])
        app.processEvents()
        conflict = out_dir / "conflict_state.png"
        window.grid.grab().save(str(conflict), "PNG")
        print("冲突态截图：", conflict, "冲突数：", len(window._conflicts))
        # 底部面板两页各来一张：冲突清单 / 排位结果（走查底部面板排版用）
        window.show_bottom(0)
        app.processEvents()
        window.grab().save(str(out_dir / "bottom_conflicts.png"), "PNG")
        window.show_report()
        app.processEvents()
        window.grab().save(str(out_dir / "bottom_result.png"), "PNG")
        window.bottom_dock.hide()
        app.processEvents()

    # 白天模式整窗一张：两套配色都要走查（暗色下看得清的边界，亮色下常糊掉）
    from PyQt6.QtWidgets import QApplication as _QApp

    from app.ui.style import theme as _theme

    _theme.apply_theme(_QApp.instance(), dark=False)
    app.processEvents()
    # 切换主题后顺手核一下控件尺寸没被 QSS 压扁（历史 bug：切主题把活动栏格子
    # 从 44px 压回 20px，浅色预览图里就是这么一副「缩在一起」的样子）
    rail_h = window.activity_bar.button("students").height()
    print("切浅色后活动栏格子高度：", rail_h, "（应保持 44）")
    window.grab().save(str(out_dir / "main_window_light.png"), "PNG")
    # 顺便把活动栏切到「排座规则」页留一张：验证页面栈与图标选中态
    window.show_sidebar_page("rules")
    app.processEvents()
    window.grab().save(str(out_dir / "main_window_light_rules.png"), "PNG")
    window.show_sidebar_page("students")
    _theme.apply_theme(_QApp.instance(), dark=True)
    app.processEvents()

    # 自适应三档：同一个界面在不同窗口尺寸下长什么样必须能一眼比对
    # （窄窗收摘要 / 矮窗收底部面板 / 活动栏图标收紧，见主窗口 _apply_responsive_layout）
    # 先关掉可有可无的面板，让截图专注在「侧边栏 + 座位表」这份最小组合上
    # （开着 AI 面板时最小宽度会被顶到 1038，窗口根本到不了 1000/780）
    window.ai_dock.close()
    window.bottom_dock.close()
    app.processEvents()
    for name, (width, height) in (("narrow", (1000, 720)), ("tiny", (780, 600))):
        window.resize(width, height)
        app.processEvents()
        window.grab().save(str(out_dir / ("main_window_%s.png" % name)), "PNG")
        print("自适应截图 %s：%dx%d → 中央 %d，侧边栏 %s，活动栏格子 %d"
              % (name, window.width(), window.height(), window.central_area.width(),
                 "开" if window.side_dock.isVisible() else "收",
                 window.activity_bar.button("students").height()))
    # 图标对照条：每个图标在活动栏尺寸（28px）与面板头尺寸（18px）下各画一遍，
    # 深浅两套底色，用来看「图标是不是太小 / 有没有画歪」，也方便核对墨迹大小一致
    for tag, dark in (("dark", True), ("light", False)):
        palette = _theme.DARK_PALETTE if dark else _theme.LIGHT_PALETTE
        _render_icon_strip(out_dir / ("icons_%s.png" % tag), palette, app)

    window.resize(1500, 940)
    app.processEvents()

    print("主窗口截图：", full)
    print("座位表截图：", grid)
    print("布局：%d 组 × %d 行 × %d 列 = %d 个座位，学生 %d 人，已排 %d 人"
          % (project.layout.group_count, project.layout.max_rows,
             project.layout.groups[0].cols, project.layout.seat_count(),
             len(project.students), len(project.assignment)))
    print("求解：软约束 %.1f 分，硬约束违反 %d 条，重启 %d 次，交换 %d 次，用时 %.2fs"
          % (solution.soft_score, solution.hard_count, solution.restarts,
             solution.iterations, solution.elapsed))
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
