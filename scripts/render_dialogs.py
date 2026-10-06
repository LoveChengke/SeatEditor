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

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QVBoxLayout  # noqa: E402

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
    from app.ui import motion  # noqa: E402

    motion.set_reduced_motion(True)   # 静态截图走查：关掉动效，避免抓到半透明中间帧

    from app.ui.dialogs.ai_settings_dialog import AISettingsDialog
    from app.ui.dialogs.export_dialog import ExportDialog
    from app.ui.dialogs.onboarding_dialog import OnboardingDialog
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
        # 开始引导：给四个步骤挂空回调，让「去设置布局」这类动作按钮也渲染出来
        ("onboarding", lambda: OnboardingDialog(None, steps=(
            ("设置教室布局", "教室分几组、几排、几列。点顶部「教室布局」，选个模板就行。",
             "去设置布局", lambda: None),
            ("导入学生名单", "选 Excel 文件一键导入；没有 Excel 也可以在左侧名单里点「添加」手动输入。",
             "导入名单", lambda: None),
            ("挑几条排座规则", "比如「视力差的坐前排」。不挑也行，程序会按姓名顺序直接排。",
             "去看看", lambda: None),
            ("一键排位并导出", "按 F5 自动排好，拖一拖微调，满意就导出 Excel 或图片发给班主任群。",
             "一键排位", lambda: None),
        ))),
    )
    def _ai_panel_shell():
        """预填「已生成」状态的 AI 助手面板（包在临时 QDialog 里方便截图）。"""
        from app.services.ai_client import parse_rules_payload
        from app.ui.panels.ai_panel import AIRulePanel
        import json as _json

        dialog = QDialog()
        dialog.setWindowTitle("AI 助手")
        layout = QVBoxLayout(dialog)
        panel = AIRulePanel(project, dialog)
        layout.addWidget(panel)
        panel._input.setPlainText("视力差的坐前排\n班长分散开")
        panel._config_label.setText("当前 AI 服务：https://open.bigmodel.cn/api/paas/v4（glm-4-flash）")
        payload = _json.dumps({"rules": [
            {"kind": "front_required", "params": {"tag": "视力差", "rows": 2}},
            {"kind": "tag_disperse", "params": {"tag": "班干部"}},
        ]})
        rules, problems = parse_rules_payload(payload, project)
        panel._rebuild_results(rules)
        panel._set_problems("\n".join(problems), error=False)
        dialog.resize(380, 560)
        return dialog

    def _about_shell():
        """真造一个 QMessageBox 来截图（``QMessageBox.about`` 是静态方法，抓不到）。"""
        from app import config
        from app.ui.main_window import about_text

        box = QMessageBox()
        box.setWindowTitle("关于 %s" % config.APP_NAME)
        box.setText(about_text())
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.layout().setSizeConstraint(box.layout().SizeConstraint.SetMinimumSize)
        return box

    jobs = jobs + (
        ("about", _about_shell),
        ("ai_settings", lambda: AISettingsDialog(
            "https://open.bigmodel.cn/api/paas/v4", "sk-demo-key", "glm-4-flash")),
        ("ai_panel", _ai_panel_shell),
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
