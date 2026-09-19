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


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)

    silence_dialogs()
    QSettings(config.ORG_NAME, config.APP_ID).setValue(config.SK_WELCOME_SHOWN, True)
    app = QApplication([])
    app.setStyle("Fusion")
    from app.ui import load_stylesheet
    from app.ui.style.theme import ensure_font_db

    print("补注册字体数：", ensure_font_db())
    app.setStyleSheet(load_stylesheet())

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
