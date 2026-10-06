"""生成应用图标：从 resources/app_icon.svg 出多尺寸 .ico 与预览图。

用法：.venv\\Scripts\\python.exe scripts\\make_app_icon.py

为什么要有这个脚本：图标要以好几种尺寸存在（Windows 任务栏要 16/24/32，
Alt+Tab 与资源管理器要大图，安装包要 256），而 SVG 是矢量、只能当源文件。
改图标只改 `resources/app_icon.svg`，然后跑一次这里，别去手工导出十几张图。

ICO 是手工拼的：Qt 的 ico 插件写不出多尺寸文件，而 ICO 容器格式很简单
（6 字节头 + 每张图 16 字节目录项 + PNG 数据，Vista 以后支持直接塞 PNG）。
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt6.QtSvg import QSvgRenderer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)
# 小于等于这个尺寸用「小尺寸版」构图：完整版的 3×2 座位网格缩到 16px 会糊成
# 一片（座位 2.9px、间隙 0.9px），换成「讲台 + 一个座位 + 人」才认得出来
SMALL_MAX = 32
SOURCE = ROOT / "resources" / "app_icon.svg"
SOURCE_SMALL = ROOT / "resources" / "app_icon_small.svg"
ICO_PATH = ROOT / "resources" / "app_icon.ico"
PNG_PATH = ROOT / "resources" / "app_icon.png"
PREVIEW_PATH = ROOT / "docs" / "preview" / "app_icon.png"


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    """把矢量图标渲染成 size×size 的 PNG 字节（保留透明边角）。

    注意 ``QBuffer`` 必须挂在一个**活着的** ``QByteArray`` 上：写
    ``QBuffer(QByteArray())`` 会让那个临时对象当场析构，Qt 接着往已释放的内存里写，
    进程直接段错误（这个脚本第一版就是这么崩的，而且崩得连一句输出都没有）。
    """
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()

    storage = QByteArray()
    buffer = QBuffer(storage)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(storage)


def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    """按 ICO 容器格式写多尺寸图标（每张图直接塞 PNG 数据）。"""
    header = struct.pack("<HHH", 0, 1, len(images))          # 保留位 / 类型=图标 / 张数
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, data in images:
        # 目录项：宽高（256 记作 0）、调色板数、保留位、位深、数据长度、数据偏移
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32,
                               len(data), offset)
        payload += data
        offset += len(data)
    path.write_bytes(header + entries + payload)


def main() -> int:
    print("渲染中…", flush=True)
    app = QApplication([])
    if not SOURCE.exists():
        print("找不到源文件：", SOURCE)
        return 1
    renderers = {}
    for small, source in ((True, SOURCE_SMALL), (False, SOURCE)):
        if not source.exists():
            print("找不到源文件：", source)
            return 1
        # QByteArray 要留个引用：QSvgRenderer 只持有裸指针，临时对象析构后它就悬空了
        data = QByteArray(source.read_bytes())
        renderer = QSvgRenderer(data)
        if not renderer.isValid():
            print("SVG 解析失败：", source)
            return 1
        renderers[small] = (renderer, data)

    images = []
    for size in SIZES:
        renderer, _keep = renderers[size <= SMALL_MAX]
        images.append((size, render_png(renderer, size)))
        print("  已渲染 %-4dpx（%s）" % (size, "小尺寸构图" if size <= SMALL_MAX else "完整构图"),
              flush=True)
    write_ico(ICO_PATH, images)
    PNG_PATH.write_bytes(dict(images)[256])
    print("应用图标：%s（%d 个尺寸：%s）" % (ICO_PATH.name, len(images),
                                   "/".join(str(s) for s in SIZES)))
    print("单张 PNG：%s（256）" % PNG_PATH.name)

    # 预览图：各尺寸排一行，浅色底与深色底各一行，方便肉眼核对小尺寸糊不糊
    columns = len(SIZES)
    cell_w, cell_h = 300, 300
    preview = QImage(cell_w * columns, cell_h * 2, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(preview)
    for row, background in enumerate(("#F3F5F9", "#0F141A")):
        painter.fillRect(0, row * cell_h, preview.width(), cell_h, QColor(background))
        for index, (size, data) in enumerate(images):
            pixmap = QImage.fromData(QByteArray(data))
            scale = min(1.0, 200.0 / size) if size < 200 else 0.75
            shown = int(size * scale)
            left = index * cell_w + (cell_w - shown) // 2
            top = row * cell_h + (cell_h - shown) // 2
            painter.drawImage(left, top, pixmap.scaled(shown, shown,
                                                       Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))
    painter.end()
    PREVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    preview.save(str(PREVIEW_PATH), "PNG")
    print("预览图：", PREVIEW_PATH, "（上排浅底 / 下排深底）")

    # 顺手报一下每个尺寸的「墨迹占比」，小尺寸如果塌了这里能看出来
    for size, data in images:
        image = QImage.fromData(QByteArray(data))
        opaque = sum(1 for y in range(size) for x in range(size)
                     if image.pixelColor(x, y).alpha() > 40)
        print("  %-4d 不透明像素占比 %.0f%%" % (size, 100.0 * opaque / (size * size)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
