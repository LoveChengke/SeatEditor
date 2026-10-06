"""动效系统 —— 按 beUI 动效指南（beui.dev/docs/motion-patterns）实现。

令牌与原则（原样取自该指南）：
- EASE_OUT    cubic-bezier(0.16, 1, 0.3, 1)   入场/退场：立即响应、安静收敛
- EASE_IN_OUT cubic-bezier(0.77, 0, 0.175, 1) 屏上已有对象的移动
- 入场用 ease-out，移动用 ease-in-out，进度用 linear，手势用 spring
- 界面动效默认 <300ms；按压反馈 100~160ms；弹层 200~500ms
- 内容交换：离场快于进场（exit 120ms/-4px，enter 180ms/+4px）
- 内容揭示：220ms，opacity 0→1、位移 8px→0
- 高频操作（一天上百次）不加编排；动效要能说清目的，说不清就删掉
- 降级（reduced motion）：保留 opacity/颜色等即时反馈，去掉位移

Qt 约束：只有**顶层窗口**（对话框 / 主窗口）做位移——它们不受布局管理；
布局管理的子控件（页签页、结果行）move() 会被布局打回去，一律只做淡入。
所有助手在系统开启「减少动态效果」时自动降级为直接到位。
"""

from __future__ import annotations

import sys
from typing import List, Optional, Sequence, Tuple

from PyQt6.QtCore import (
    QAbstractAnimation, QEvent, QObject, QPoint, QPointF, QRect, QEasingCurve,
    QPropertyAnimation, QTimer,
)
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

# ---------------------------------------------------------------- 时长（毫秒）
DUR_PRESS = 130        # 按压反馈（指南：100~160ms）
DUR_SWAP_OUT = 120     # 内容交换·离场（translateY -4px；Qt 切换器瞬时完成，等效最快离场）
DUR_SWAP_IN = 180      # 内容交换·进场（translateY +4px）
DUR_REVEAL = 220       # 内容揭示（opacity 0→1，位移 8px→0）
DUR_SNAP = 200         # 窗口吸边滑入（屏上移动，EASE_IN_OUT）
STAGGER_STEP = 60      # 相邻元素的错峰间隔（指南警示不要长 stagger）
_STAGGER_MAX = 5       # 超过这个数量就整组一次揭示，不做长 stagger


def ease_out() -> QEasingCurve:
    """cubic-bezier(0.16, 1, 0.3, 1) —— 入场/退场。"""
    return _bezier(0.16, 1.0, 0.3, 1.0)


def ease_in_out() -> QEasingCurve:
    """cubic-bezier(0.77, 0, 0.175, 1) —— 屏上移动。"""
    return _bezier(0.77, 0.0, 0.175, 1.0)


def _bezier(x1: float, y1: float, x2: float, y2: float) -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1.0, 1.0))
    return curve


# ---------------------------------------------------------------- 降级开关
def system_reduced_motion() -> bool:
    """读取 Windows「减少动态效果」辅助功能设置（SPI_GETCLIENTAREAANIMATION）。"""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        enabled = ctypes.c_bool(True)
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
        return bool(ok) and not enabled.value
    except Exception:
        return False


_REDUCED: Optional[bool] = None


def reduced_motion() -> bool:
    """全局降级开关：读系统设置，进程内缓存一次；测试可用 set_reduced_motion 覆盖。"""
    global _REDUCED
    if _REDUCED is None:
        _REDUCED = system_reduced_motion()
    return _REDUCED


def set_reduced_motion(flag: bool) -> None:
    """手动覆盖降级开关（测试 / 用户偏好用）。"""
    global _REDUCED
    _REDUCED = bool(flag)


def _start_all(anims: Sequence[QAbstractAnimation]) -> None:
    for anim in anims:
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def _drop_effect(widget: QWidget) -> None:
    """透明度特效会强制控件离屏渲染，动画结束后必须摘掉（表格这类控件很贵）。"""
    try:
        if widget.graphicsEffect() is not None:
            widget.setGraphicsEffect(None)
    except RuntimeError:
        pass   # 控件已销毁


def _fade(widget: QWidget, duration: int) -> QPropertyAnimation:
    """给控件挂透明度动画（进场 0→1）。动画随控件销毁，效果用完即摘。"""
    old = widget.graphicsEffect()
    if old is not None:
        old.deleteLater()
        widget.setGraphicsEffect(None)
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setEasingCurve(ease_out())
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.finished.connect(lambda w=widget: _drop_effect(w))
    return anim


# ---------------------------------------------------------------- 助手
def reveal_window(widget, offset_y: int = 8) -> None:
    """内容揭示：顶层窗口首次显示时 opacity 0→1 + 上滑 8px，220ms EASE_OUT。

    必须在窗口 show 之前调用（挂一次性 show 钩子；最终位置以 show 时 Qt 摆放的
    为准，再从 +8px 处滑入）。降级或最大化/全屏窗口只做淡入（去掉位移）。
    动的是 ``windowOpacity`` 而非图形特效——特效只影响窗口内容绘制，
    恢复不了整窗透明度，会让对话框在真实窗口系统里保持全透明。
    """
    if reduced_motion():
        return
    widget.setWindowOpacity(0.0)
    state = {"started": False}

    def _start() -> None:
        if state["started"]:
            return
        state["started"] = True
        widget.removeEventFilter(hook)
        fade = QPropertyAnimation(widget, b"windowOpacity", widget)
        fade.setDuration(DUR_REVEAL)
        fade.setEasingCurve(ease_out())
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        anims: List[QAbstractAnimation] = [fade]
        if not (widget.isMaximized() or widget.isFullScreen()):
            final = widget.pos()
            widget.move(final + QPoint(0, offset_y))
            slide = QPropertyAnimation(widget, b"pos", widget)
            slide.setDuration(DUR_REVEAL)
            slide.setEasingCurve(ease_out())
            slide.setStartValue(final + QPoint(0, offset_y))
            slide.setEndValue(final)
            anims.append(slide)
        _start_all(anims)

    class _ShowHook(QObject):
        def eventFilter(self, obj, event) -> bool:  # noqa: N802
            if event.type() == QEvent.Type.Show:
                QTimer.singleShot(0, _start)
            return False

    hook = _ShowHook(widget)
    widget.installEventFilter(hook)


def swap_in(widget) -> None:
    """内容交换·进场：180ms EASE_OUT 淡入（离场由切换器瞬时完成，等效最快离场）。

    页签页是布局管理的子控件，不做位移（会被布局打回去），只做淡入。
    """
    if reduced_motion() or widget is None:
        return
    _fade(widget, DUR_SWAP_IN).start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def stagger_reveal(widgets: Sequence[QWidget]) -> None:
    """内容揭示的错峰版：每个元素 220ms EASE_OUT 淡入，相邻间隔 STAGGER_STEP。

    指南警示不要做长 stagger：元素超过 _STAGGER_MAX 时整组一次揭示。
    子控件不做位移（布局管理），只做淡入。
    """
    widgets = [w for w in widgets if w is not None]
    if reduced_motion() or not widgets:
        return
    if len(widgets) > _STAGGER_MAX:
        _fade(widgets[0], DUR_REVEAL).start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        return
    for index, widget in enumerate(widgets):
        effect_holder = {"effect": None}

        def _start(w=widget, holder=effect_holder) -> None:
            try:
                current = w.graphicsEffect()
            except RuntimeError:
                return   # 控件已被销毁（如结果行重建），动画作废
            if current is not holder["effect"]:
                return
            anim = QPropertyAnimation(w.graphicsEffect(), b"opacity", w)
            anim.setDuration(DUR_REVEAL)
            anim.setEasingCurve(ease_out())
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.finished.connect(lambda w=w: _drop_effect(w))
            anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        effect_holder["effect"] = effect
        QTimer.singleShot(index * STAGGER_STEP, _start)


# ---------------------------------------------------------------- 窗口吸边
SNAP_THRESHOLD = 24      # 距屏幕可用边缘多少像素内触发吸附
SNAP_HYSTERESIS = 12     # 吸附动画途中用户又拖离多少像素就停止动画还控制权
SNAP_EDGES = ("left", "right", "top")   # 仿 Windows 贴靠：下缘是任务栏，不吸


def compute_snap_target(frame: QRect, available: QRect,
                        threshold: int = SNAP_THRESHOLD,
                        edges: Sequence[str] = SNAP_EDGES) -> Tuple[Optional[QPoint], str]:
    """磁性吸附的纯函数：窗口 frame + 参照区域 → 应吸附到的位置。

    ``edges`` 决定参与吸附的方向：主窗口仿 Windows 贴靠只吸上 / 左 / 右；
    程序内浮动窗口传全部四向（含下缘），即可贴到左下角 / 右下角这类角落——
    相邻两个方向同时命中时自动组合成角（如 "left+bottom"）。
    返回 ``(QPoint | None, 边名)``；不需要吸附时返回 ``(None, "")``。
    可脱离 Qt 界面单测。
    """
    x, y = frame.left(), frame.top()
    edge = ""
    if "left" in edges and frame.left() - available.left() <= threshold:
        x, edge = available.left(), "left"
    elif "right" in edges and available.right() - frame.right() <= threshold:
        x, edge = available.right() - frame.width() + 1, "right"
    if "top" in edges and frame.top() - available.top() <= threshold:
        y, edge = available.top(), ("top" if edge == "" else edge + "+top")
    elif "bottom" in edges and available.bottom() - frame.bottom() <= threshold:
        y = available.bottom() - frame.height() + 1
        edge = "bottom" if edge == "" else edge + "+bottom"
    if edge == "":
        return None, ""
    return QPoint(x, y), edge


def compute_dock_snap_target(frame: QRect, main_window_rect: QRect,
                             threshold: int = SNAP_THRESHOLD) -> Tuple[Optional[QPoint], str]:
    """程序内浮动窗口的贴靠：参照主窗口矩形，四向全开（含左下 / 右下角）。"""
    return compute_snap_target(
        frame, main_window_rect, threshold,
        edges=("left", "right", "top", "bottom"),
    )
