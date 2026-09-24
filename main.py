"""教室自动排座位程序 —— 入口。

用法：
    python main.py                  # 启动图形界面
    python main.py 某班级.seatproj   # 启动并打开指定项目
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402


def _install_excepthook() -> None:
    """未捕获异常：写日志 + 弹窗提示，不让教师看到 traceback。"""
    log_path = config.AUTOSAVE_DIR / "error.log"

    def hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            config.AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(detail + "\n")
        except OSError:
            pass
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                QMessageBox.critical(
                    None, "程序遇到问题",
                    "很抱歉，出现了一个未预期的错误：\n\n%s\n\n"
                    "详细信息已记录到：\n%s\n\n"
                    "建议先保存项目（Ctrl+S）后重试。" % (exc_value, log_path),
                )
        except Exception:
            sys.stderr.write(detail)

    sys.excepthook = hook


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    _install_excepthook()

    try:
        from PyQt6.QtGui import QFont
        from PyQt6.QtWidgets import QApplication
    except ImportError as exc:  # 环境问题
        sys.stderr.write(
            "未安装 PyQt6（%s）。\n请先执行：pip install -r requirements.txt\n" % exc
        )
        return 1

    from app.ui.main_window import MainWindow
    from app.ui.style.theme import FONT_APP, FONT_FAMILIES

    QApplication.setApplicationName(config.APP_NAME)
    QApplication.setApplicationDisplayName(config.APP_NAME)
    QApplication.setOrganizationName(config.ORG_NAME)
    QApplication.setApplicationVersion(config.VERSION)

    app = QApplication(argv)
    app.setStyle("Fusion")

    from app.ui import load_stylesheet
    from app.ui.style.theme import ensure_font_db

    ensure_font_db()
    app.setStyleSheet(load_stylesheet())

    font = QFont()
    font.setFamilies(list(FONT_FAMILIES))
    font.setPixelSize(FONT_APP)
    app.setFont(font)

    window = MainWindow()
    for arg in argv[1:]:
        if arg.lower().endswith(config.PROJECT_EXT) and os.path.exists(arg):
            window.open_project(arg)
            break
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
