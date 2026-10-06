"""矢量小图标集：活动栏、面板头、编辑器头里的那些单色线条图标。

为什么不用 SVG 文件（``resources/icons`` 里那些是给菜单/工具栏用的）：
- 主题切换要**跟着变色**。``QIcon`` 读 SVG 时颜色写在文件里，黑白两套就得
  各存一份、切换时重设一遍图标；这里直接用当前主题色画，切换即时生效。
- 字形坑。微软雅黑没有 ✕(U+2715) / ▶ / ⚠ 这些码位，用字符当图标会变方框
  （``common.DockCloseButton`` 当年就是这么踩的），画线条没有这个问题。

坐标一律按 16×16 设计，:func:`paint_glyph` 会按目标矩形缩放，
线宽也跟着缩放（``stroke`` 是 16 单位空间里的宽度，16px 图标下就是像素值）。
"""

from __future__ import annotations

from typing import Callable, Dict

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

UNIT = 16.0
GLYPHS: Dict[str, Callable[[QPainter, QColor, float], None]] = {}


def glyph(name: str):
    def register(func):
        GLYPHS[name] = func
        return func

    return register


# ------------------------------------------------------------------ 几何小工具
def _line(p: QPainter, x1: float, y1: float, x2: float, y2: float) -> None:
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _polyline(p: QPainter, points) -> None:
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    p.drawPath(path)


def _arrow_head(p: QPainter, tip, left, right) -> None:
    color = p.pen().color()
    _polyline(p, [left, tip, right])
    p.save()
    p.setBrush(color)
    path = QPainterPath(QPointF(*left))
    path.lineTo(QPointF(*tip))
    path.lineTo(QPointF(*right))
    path.closeSubpath()
    p.drawPath(path)
    p.restore()


# ------------------------------------------------------------------ 图标
@glyph("students")
def _students(p: QPainter, color: QColor, stroke: float) -> None:
    p.drawEllipse(QPointF(8, 5.3), 2.6, 2.6)
    p.drawArc(QRectF(3.4, 8.4, 9.2, 9.4), 0, 180 * 16)


@glyph("rules")
def _rules(p: QPainter, color: QColor, stroke: float) -> None:
    for y in (4.4, 8.0, 11.6):
        _line(p, 6.4, y, 13.2, y)
    p.save()
    p.setBrush(color)
    for y in (4.4, 8.0, 11.6):
        p.drawEllipse(QPointF(3.6, y), 1.0, 1.0)
    p.restore()


@glyph("regions")
def _regions(p: QPainter, color: QColor, stroke: float) -> None:
    p.drawRoundedRect(QRectF(2.6, 2.6, 4.4, 4.4), 1.2, 1.2)
    p.drawRoundedRect(QRectF(9.0, 2.6, 4.4, 4.4), 1.2, 1.2)
    p.drawRoundedRect(QRectF(2.6, 9.0, 4.4, 4.4), 1.2, 1.2)
    p.save()
    p.setBrush(color)
    p.drawRoundedRect(QRectF(9.0, 9.0, 4.4, 4.4), 1.2, 1.2)
    p.restore()


@glyph("rotation")
def _rotation(p: QPainter, color: QColor, stroke: float) -> None:
    p.drawArc(QRectF(2.8, 2.8, 10.4, 10.4), 60 * 16, 250 * 16)
    _arrow_head(p, (11.0, 3.4), (13.4, 3.6), (12.2, 6.0))


@glyph("ai")
def _ai(p: QPainter, color: QColor, stroke: float) -> None:
    """AI：一大一小两颗实心星。实心比线框在小尺寸下认得出来。"""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for cx, cy, r in ((6.0, 5.8, 4.4), (11.9, 11.4, 2.6)):
        path = QPainterPath(QPointF(cx, cy - r))
        path.quadTo(QPointF(cx + r * 0.34, cy - r * 0.34), QPointF(cx + r, cy))
        path.quadTo(QPointF(cx + r * 0.34, cy + r * 0.34), QPointF(cx, cy + r))
        path.quadTo(QPointF(cx - r * 0.34, cy + r * 0.34), QPointF(cx - r, cy))
        path.quadTo(QPointF(cx - r * 0.34, cy - r * 0.34), QPointF(cx, cy - r))
        p.drawPath(path)
    p.restore()


@glyph("theme")
def _theme(p: QPainter, color: QColor, stroke: float) -> None:
    """半明半暗的圆：一眼看出「这里是明暗切换」，与 VS Code 的图标同构。"""
    p.save()
    p.setBrush(color)
    path = QPainterPath()
    path.moveTo(8, 1.6)
    path.arcTo(QRectF(1.6, 1.6, 12.8, 12.8), 90, 180)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(8, 8), 6.4, 6.4)
    p.restore()


@glyph("help")
def _help(p: QPainter, color: QColor, stroke: float) -> None:
    """圆圈 + 问号。问号用线条画，不用 drawText。

    原来是用 ``drawText`` 画「?」的：字号写在 16 单位空间里，缩放之后
    比圆圈还大，问号会溢出圆边（实测墨迹 bbox 22×22 已经贴到盒边），
    浅色模式下看着就是个怪符号。线条画没有字体依赖，也不会溢出。
    """
    p.drawEllipse(QPointF(8, 8), 5.4, 5.4)
    p.save()
    fin = QPen(p.pen())
    fin.setWidthF(max(1.0, stroke * 0.85))
    p.setPen(fin)
    # 问号的钩：从左边起笔右上弯，再往下收
    path = QPainterPath(QPointF(6.2, 6.6))
    path.cubicTo(QPointF(6.4, 4.6), QPointF(9.8, 4.6), QPointF(9.8, 6.6))
    path.cubicTo(QPointF(9.8, 8.0), QPointF(8.0, 8.0), QPointF(8.0, 9.4))
    p.drawPath(path)
    p.setBrush(color)
    p.drawEllipse(QPointF(8, 11.4), 0.85, 0.85)
    p.restore()


@glyph("sun")
def _sun(p: QPainter, color: QColor, stroke: float) -> None:
    """太阳：亮色模式下活动栏显示它（点一下切到黑夜）。"""
    p.drawEllipse(QPointF(8, 8), 3.3, 3.3)
    for i in range(8):
        angle = i * 45.0
        import math

        rad = math.radians(angle)
        inner, outer = 5.0, 6.7
        _line(p, 8 + inner * math.cos(rad), 8 + inner * math.sin(rad),
              8 + outer * math.cos(rad), 8 + outer * math.sin(rad))


@glyph("moon")
def _moon(p: QPainter, color: QColor, stroke: float) -> None:
    """月亮：暗色模式下活动栏显示它（点一下切到白天）。"""
    outer = QPainterPath()
    outer.addEllipse(QRectF(2.2, 2.2, 11.6, 11.6))
    inner = QPainterPath()
    inner.addEllipse(QRectF(5.6, 0.6, 11.6, 11.6))
    p.save()
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(outer.subtracted(inner))
    p.restore()


@glyph("theme")
def _theme(p: QPainter, color: QColor, stroke: float) -> None:
    """半明半暗的圆（太阳 / 月亮的备用拼接图形，跟着主题换成 sun / moon）。"""
    p.save()
    p.setBrush(color)
    path = QPainterPath()
    path.moveTo(8, 1.6)
    path.arcTo(QRectF(1.6, 1.6, 12.8, 12.8), 90, 180)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(8, 8), 6.4, 6.4)
    p.restore()


@glyph("close")
def _close(p: QPainter, color: QColor, stroke: float) -> None:
    _line(p, 4.2, 4.2, 11.8, 11.8)
    _line(p, 11.8, 4.2, 4.2, 11.8)


@glyph("dots")
def _dots(p: QPainter, color: QColor, stroke: float) -> None:
    p.save()
    p.setBrush(color)
    for x in (3.4, 8.0, 12.6):
        p.drawEllipse(QPointF(x, 8), 1.15, 1.15)
    p.restore()


@glyph("chevron-down")
def _chevron_down(p: QPainter, color: QColor, stroke: float) -> None:
    _polyline(p, [(4.4, 6.2), (8, 9.8), (11.6, 6.2)])


@glyph("chevron-up")
def _chevron_up(p: QPainter, color: QColor, stroke: float) -> None:
    _polyline(p, [(4.4, 9.8), (8, 6.2), (11.6, 9.8)])


@glyph("report")
def _report(p: QPainter, color: QColor, stroke: float) -> None:
    _line(p, 2.8, 13.2, 13.2, 13.2)
    _line(p, 5.0, 13.0, 5.0, 8.6)
    _line(p, 8.0, 13.0, 8.0, 4.4)
    _line(p, 11.0, 13.0, 11.0, 6.6)


@glyph("search")
def _search(p: QPainter, color: QColor, stroke: float) -> None:
    p.drawEllipse(QPointF(7.0, 7.0), 3.8, 3.8)
    _line(p, 9.9, 9.9, 13.2, 13.2)


@glyph("plus")
def _plus(p: QPainter, color: QColor, stroke: float) -> None:
    _line(p, 8, 3.6, 8, 12.4)
    _line(p, 3.6, 8, 12.4, 8)


@glyph("layout")
def _layout(p: QPainter, color: QColor, stroke: float) -> None:
    p.drawRoundedRect(QRectF(2.8, 2.8, 4.5, 4.5), 1.2, 1.2)
    p.drawRoundedRect(QRectF(8.7, 2.8, 4.5, 4.5), 1.2, 1.2)
    p.drawRoundedRect(QRectF(2.8, 8.7, 4.5, 4.5), 1.2, 1.2)
    p.drawRoundedRect(QRectF(8.7, 8.7, 4.5, 4.5), 1.2, 1.2)


# ------------------------------------------------------------------ 绘制入口
# 每个图标的墨迹（真正画出来的部分）在 16 单位空间里占多大不一样：
# 箭头和 × 只占 58%，而实心圆占 92%。不校正的话同一个盒子里图标看着一大一小
# ——「图标太小」有一半是这么来的。这里按实测把每个图标的墨迹归一化到 ~85%，
# 数值 = 0.85 ÷ 实测占比（见 tools 里的量法与 tests/test_shell.py 的断言）。
GLYPH_ZOOM: Dict[str, float] = {
    "ai": 1.06,
    "chevron-down": 1.68,
    "chevron-up": 1.68,
    "close": 1.59,
    "dots": 1.05,
    "help": 1.12,
    "layout": 1.16,
    "moon": 1.17,
    "plus": 1.38,
    "regions": 1.12,
    "report": 1.17,
    "rotation": 1.12,
    "rules": 1.12,
    "search": 1.19,
    "students": 1.14,
    "sun": 0.91,
    "theme": 0.94,
}


def ink_box(name: str, box: float = 64.0) -> "QRectF":
    """量一个图标在给定盒子里真正画出来的范围（做图标大小回归测试用）。"""
    from PyQt6.QtGui import QPixmap

    pixmap = QPixmap(int(box), int(box))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint_glyph(painter, name, QRectF(0, 0, box, box), "#FFFFFF")
    painter.end()
    image = pixmap.toImage()
    xs, ys = [], []
    for x in range(int(box)):
        for y in range(int(box)):
            if image.pixelColor(x, y).alpha() > 40:
                xs.append(x)
                ys.append(y)
    if not xs:
        return QRectF()
    return QRectF(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def paint_glyph(painter: QPainter, name: str, rect: QRectF, color,
                stroke: float = 1.4) -> bool:
    """把 ``name`` 图标画进 ``rect``（按短边等比缩放居中）；未知名字返回 False。"""
    draw = GLYPHS.get(name)
    if draw is None:
        return False
    size = float(min(rect.width(), rect.height()))
    if size <= 0:
        return False
    qcolor = QColor(color)
    zoom = GLYPH_ZOOM.get(name, 1.0)
    scaled = size * zoom
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # 关键：按「缩放后」的尺寸居中。只按 size 居中再乘 zoom 的话，放大后的图形
    # 会从盒子左上角往外长、右下角被切掉——自校准脚本里量出「箭头只占 10%」
    # 这种荒唐值，根因就在这里。
    painter.translate(QPointF(rect.center().x() - scaled / 2.0,
                              rect.center().y() - scaled / 2.0))
    painter.scale(scaled / UNIT, scaled / UNIT)
    # 线宽按比例缩回：缩放只该放大图形的尺寸，不该让线条变粗
    pen = QPen(qcolor)
    pen.setWidthF(stroke / zoom)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    try:
        draw(painter, qcolor, stroke / zoom)
    finally:
        painter.restore()
    return True


def glyph_color(icon: str, color: str, size: int = 16) -> "QPixmap":
    """把图标画成 QPixmap（需要 QIcon 的地方用，例如菜单项）。"""
    from PyQt6.QtGui import QPixmap

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint_glyph(painter, icon, QRectF(0, 0, size, size), color)
    painter.end()
    return pixmap


def paint_widget_glyph(widget: QWidget, name: str, color: str,
                       margin: float = 0.0) -> None:
    """在控件自身矩形里居中画图标（自绘控件 paintEvent 的便捷调用）。"""
    painter = QPainter(widget)
    rect = QRectF(widget.rect()).adjusted(margin, margin, -margin, -margin)
    paint_glyph(painter, name, rect, color)
