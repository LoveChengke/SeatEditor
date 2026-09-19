"""把左侧「学生名单」面板单独渲染成图片，用于走查底部按钮与表格排版。

用法：.venv\\Scripts\\python.exe scripts\\grab_student_panel.py
输出：docs/preview/student_panel.png（280 × 面板高度）
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

from app import config  # noqa: E402
from app.models.layout import Layout  # noqa: E402
from app.models.student import Student  # noqa: E402


def main() -> int:
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    QMessageBox.exec = lambda self, *a, **k: QDialog.DialogCode.Rejected

    QSettings(config.ORG_NAME, config.APP_ID).setValue(config.SK_WELCOME_SHOWN, True)

    app = QApplication([])
    app.setStyle("Fusion")
    from app.ui import load_stylesheet
    from app.ui.style.theme import ensure_font_db

    ensure_font_db()
    app.setStyleSheet(load_stylesheet())

    from app.ui.main_window import MainWindow

    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    app.processEvents()

    project = window.project
    project.layout = Layout.from_template(3, 6, 2)
    with project.suspend():
        for i in range(20):
            project.add_student(Student(
                "2024%04d" % i,
                "学生%02d" % (i + 1),
                gender="男" if i % 2 else "女",
            ))
    window._refresh_all()
    app.processEvents()

    pixmap = window.student_panel.grab()
    out = ROOT / "docs" / "preview" / "student_panel.png"
    pixmap.save(str(out), "PNG")
    print("学生面板截图：%s (%dx%d)" % (out, pixmap.width(), pixmap.height()))
    window.project.dirty = False
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
