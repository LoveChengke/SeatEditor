"""重新生成随包分发的 Excel 名单导入模板。

用法::

    .venv\\Scripts\\python.exe scripts\\make_templates.py

生成 ``resources/templates/学生名单导入模板.xlsx``（程序里「文件 → 下载名单导入模板…」
用的是同一段代码，两者内容一致）。名单模板的列定义、示例数据、填写说明都在
``app/storage/roster_template.py``，改那里然后重跑本脚本即可。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.storage import roster_template  # noqa: E402


def main() -> int:
    target = roster_template.write_roster_template(roster_template.RESOURCE_TEMPLATE)
    print("已生成名单模板：%s（%d 字节）" % (target, target.stat().st_size))

    from app.models.layout import LAYOUT_TEMPLATES  # noqa: E402

    print("已有布局模板 %d 个：" % len(LAYOUT_TEMPLATES))
    for name, groups, rows, cols in LAYOUT_TEMPLATES:
        print("  %-14s %d 组 × %d 行 × %d 列" % (name, groups, rows, cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
