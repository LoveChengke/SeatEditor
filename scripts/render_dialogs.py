"""把几个主要对话框渲染成 PNG，用于走查深色主题下的对话框排版。

用法：.venv\\Scripts\\python.exe scripts\\render_dialogs.py [输出目录]
输出（默认 docs/preview/dialogs）：export_dialog / layout_editor / rule_edit /
      student_edit / tag_manager / rule_wizard 六张 PNG
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from app.models.layout import Layout  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.rule import RuleKind, make_rule  # noqa: E402
from app.models.student import Student  # noqa: E402


def silence_dialogs() -> None:
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    QMessageBox.exec = lambda self, *a, **k: QDialog.DialogCode.Rejected


def build_project() -> Project:
    project = Project()
    project.layout = Layout.from_template(3, 6, 2)
    for i in range(12):
        project.add_student(Student(
            sid="2024%04d" % (i + 1),
            name="学生%02d" % (i + 1),
            gender="男" if i % 2 == 0 else "女",
            tags=["班干部"] if i % 4 == 0 else [],
            attrs={"身高": 150 + i, "成绩": 70 + i},
        ))
    project.ensure_tag("班干部")
    project.ensure_tag("需关注")
    rule = make_rule(RuleKind.FRONT_REQUIRED)
    rule.params.update({"tag": "班干部", "rows": 2})
    project.add_rule(rule)
    project.add_selection("前排区", project.layout.row_range(0, 0))
    return project


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "preview" / "dialogs"
    out_dir.mkdir(parents=True, exist_ok=True)

    silence_dialogs()
    app = QApplication([])
    from app.ui.style.theme import apply_dark_theme

    apply_dark_theme(app)

    from app.ui.dialogs.export_dialog import ExportDialog
    from app.ui.dialogs.layout_editor_dialog import LayoutEditorDialog
    from app.ui.dialogs.rule_edit_dialog import RuleEditDialog
    from app.ui.dialogs.rule_wizard_dialog import RuleWizardDialog
    from app.ui.dialogs.student_edit_dialog import StudentEditDialog
    from app.ui.dialogs.tag_manager_dialog import TagManagerDialog

    project = build_project()
    jobs = (
        ("export_dialog", lambda: ExportDialog(project)),
        ("layout_editor", lambda: LayoutEditorDialog(project)),
        ("rule_edit", lambda: RuleEditDialog(project, project.rules[0])),
        ("student_edit", lambda: StudentEditDialog(project, project.students[0])),
        ("tag_manager", lambda: TagManagerDialog(project)),
        ("rule_wizard", lambda: RuleWizardDialog(project)),
    )
    for name, factory in jobs:
        dialog = factory()
        dialog.show()
        app.processEvents()
        path = out_dir / ("%s.png" % name)
        dialog.grab().save(str(path), "PNG")
        print("对话框截图：%s (%dx%d)" % (path, dialog.width(), dialog.height()))
        dialog.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
