"""图标墨迹自校准：量出每个图标放大多少倍后，墨迹正好占满盒子的 85%。

为什么需要它：每个图标在 16 单位空间里「真正画出来的部分」占比不同（箭头
58%、实心圆 92%），不校正就会出现同一个盒子里图标一大一小——「图标太小」
有一半是这么来的。改图标或新增图标后跑一次，把输出贴进
``app/ui/widgets/icons.py`` 的 ``GLYPH_ZOOM`` 即可。
这是离线测量脚本，不参与程序运行。
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication
app = QApplication([])
from app.ui.widgets import icons

BOX = 48
TARGET = 0.85
print("GLYPH_ZOOM: Dict[str, float] = {")
for name in sorted(icons.GLYPHS):
    best = None
    for zoom_i in range(40, 260):
        zoom = zoom_i / 100.0
        icons.GLYPH_ZOOM[name] = zoom
        box = icons.ink_box(name, float(BOX))
        if not box.isValid():
            continue
        r = max(box.width(), box.height()) / BOX
        if r >= TARGET:
            best = (zoom, r)
            break
    zoom, r = best or (1.0, 0.0)
    icons.GLYPH_ZOOM[name] = zoom
    print('    "%s": %.2f,   # 实测 %d%%' % (name, zoom, round(100 * r)))
print("}")
