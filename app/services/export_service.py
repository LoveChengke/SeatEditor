"""导出服务：Excel 座位表 / 名单，PNG 座位表截屏。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from ..models.project import Project
from ..storage import excel_io
from ..storage.excel_io import ExportOptions


class ExportError(Exception):
    """导出失败（面向用户的可读消息）。"""


class ExportService:
    """导出入口。"""

    # ------------------------------------------------------------ Excel
    @staticmethod
    def export_seat_table(
        project: Project, path: str | Path, options: Optional[ExportOptions] = None  # type: ignore[valid-type]
    ) -> Path:
        try:
            return excel_io.export_seat_table(project, path, options)
        except excel_io.ExcelError as exc:
            raise ExportError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ExportError("导出 Excel 失败：%s" % exc) from exc

    @staticmethod
    def export_roster(project: Project, path: str | Path) -> Path:  # type: ignore[valid-type]
        try:
            return excel_io.export_roster(project, path)
        except excel_io.ExcelError as exc:
            raise ExportError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ExportError("导出名单失败：%s" % exc) from exc

    # ------------------------------------------------------------ PNG
    @staticmethod
    def export_png(widget: Any, path: str | Path, scale: int = 1) -> Path:  # type: ignore[valid-type]
        """把座位表控件截图保存为 PNG（``scale`` 为 1 / 2 倍）。"""
        try:
            from PyQt6.QtCore import Qt
        except Exception as exc:  # noqa: BLE001  pragma: no cover
            raise ExportError("未安装 PyQt6，无法导出图片") from exc

        target = Path(path)
        if target.suffix.lower() != ".png":
            target = target.with_suffix(".png")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            pixmap = widget.grab()
            if pixmap.isNull():
                raise ExportError("座位表为空，无法导出图片")
            factor = max(1, int(scale or 1))
            if factor != 1:
                image = pixmap.toImage().scaled(
                    pixmap.width() * factor,
                    pixmap.height() * factor,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if not image.save(str(target), "PNG"):
                    raise ExportError("图片保存失败：%s" % target)
            else:
                if not pixmap.save(str(target), "PNG"):
                    raise ExportError("图片保存失败：%s" % target)
        except ExportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ExportError("导出图片失败：%s" % exc) from exc
        return target

    # ------------------------------------------------------------ 汇总
