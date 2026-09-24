"""Excel 导入 / 导出（openpyxl）。

导入：读取表头 → 自动识别字段 → 校验 → 生成 Student 列表。
导出：座位表（含讲台、过道、样式）+ 名单 + 规则说明。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .. import config
from ..models.layout import Layout
from ..models.project import Project
from ..models.rule import describe_rule
from ..models.student import Student
from ..utils.seat_key import make_key, try_parse_key

try:  # openpyxl 缺失时给出友好提示而不是 ImportError 崩溃
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    OPENPYXL_AVAILABLE = True
except Exception:  # noqa: BLE001  pragma: no cover
    Workbook = None  # type: ignore[assignment]
    load_workbook = None  # type: ignore[assignment]
    OPENPYXL_AVAILABLE = False


class ExcelError(Exception):
    """Excel 读写错误（面向用户的可读消息）。"""


# 字段键
F_IGNORE = ""
F_SID = "sid"
F_NAME = "name"
F_GENDER = "gender"
F_TAGS = "tags"
F_NOTE = "note"
F_ATTR_PREFIX = "attr:"

FIELD_LABELS = {
    F_IGNORE: "（忽略）",
    F_SID: "学号",
    F_NAME: "姓名",
    F_GENDER: "性别",
    F_TAGS: "标签",
    F_NOTE: "备注",
}


# ------------------------------------------------------------------ 导入
@dataclass
class SheetPreview:
    """导入映射对话框需要的预览数据。"""

    path: str
    sheet_names: List[str] = field(default_factory=list)
    sheet: str = ""
    headers: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)   # 数据行（不含表头）
    total_rows: int = 0
    mapping: Dict[str, str] = field(default_factory=dict)  # header -> field key


@dataclass
class ImportIssue:
    """一行导入问题。"""

    row: int                 # Excel 行号（1-based，含表头）
    message: str
    values: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportResult:
    students: List[Student] = field(default_factory=list)
    errors: List[ImportIssue] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    new_attrs: List[str] = field(default_factory=list)
    headers: List[str] = field(default_factory=list)
    mapping: Dict[str, str] = field(default_factory=dict)
    skipped: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.students)

def _norm(text: Any) -> str:
    return re.sub(r"[\s_\-（）()【】\[\]:：]+", "", str(text or "")).strip().lower()


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return ("%g" % value)
    return str(value).strip()


def _cell_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):   # bool 也是 int 的子类
        return float(value)
    text = str(value).strip().replace("，", "").replace(",", "")
    match = re.match(r"^-?\d+(\.\d+)?", text)
    if not match:
        return None
    try:
        # \d 能匹配阿拉伯-印度数字等 Unicode 数字，float() 对它们会抛错
        return float(match.group(0))
    except ValueError:
        return None


def auto_mapping(headers: Sequence[str]) -> Dict[str, str]:
    """按常见别名自动映射表头 -> 字段键。"""
    mapping: Dict[str, str] = {}
    used_fields = set()

    def match(norm_header: str, aliases: Sequence[str]) -> bool:
        for alias in aliases:
            na = _norm(alias)
            if not na:
                continue
            if norm_header == na:
                return True
        for alias in aliases:
            na = _norm(alias)
            if na and na in norm_header:
                return True
        return False

    for header in headers:
        nh = _norm(header)
        if not nh:
            continue
        if F_SID not in used_fields and match(nh, config.SID_ALIASES):
            mapping[header] = F_SID
            used_fields.add(F_SID)
        elif F_NAME not in used_fields and match(nh, config.NAME_ALIASES):
            mapping[header] = F_NAME
            used_fields.add(F_NAME)
        elif F_GENDER not in used_fields and match(nh, config.GENDER_ALIASES):
            mapping[header] = F_GENDER
            used_fields.add(F_GENDER)
        elif F_TAGS not in used_fields and match(nh, config.TAG_ALIASES):
            mapping[header] = F_TAGS
            used_fields.add(F_TAGS)
        elif F_NOTE not in used_fields and match(nh, config.NOTE_ALIASES):
            mapping[header] = F_NOTE
            used_fields.add(F_NOTE)
        else:
            attr_name = _guess_attr_name(header)
            if attr_name:
                mapping[header] = F_ATTR_PREFIX + attr_name
    return mapping


def _guess_attr_name(header: str) -> str:
    text = str(header or "").strip()
    if not text:
        return ""
    norm = _norm(text)
    for alias, canonical in config.KNOWN_ATTR_ALIASES.items():
        if _norm(alias) == norm:
            return canonical
    # 去掉单位后缀，如 “身高(cm)” -> “身高”
    cleaned = re.sub(r"[（(][^）)]*[）)]\s*$", "", text).strip()
    cleaned = re.sub(r"\s*(cm|kg|米|厘米|千克)$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or text


def read_preview(path: str | Path, sheet: str = "") -> SheetPreview:  # type: ignore[valid-type]
    """读取工作簿预览（表头 + 前若干行）。"""
    _require_openpyxl()
    source = Path(path)
    if not source.exists():
        raise ExcelError("文件不存在：%s" % source)
    try:
        workbook = load_workbook(filename=str(source), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ExcelError("无法打开 Excel 文件：%s" % exc) from exc
    try:
        names = list(workbook.sheetnames)
        if not names:
            raise ExcelError("工作簿里没有任何工作表")
        chosen = sheet if sheet in names else names[0]
        worksheet = workbook[chosen]
        rows: List[List[Any]] = []
        for i, row in enumerate(worksheet.iter_rows(values_only=True)):
            rows.append(list(row))
            if i >= 200:  # 预览只取前 200 行
                break
        total = sum(1 for _ in worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    # 跳过完全空白的开头行
    while rows and not any(_cell_text(c) for c in rows[0]):
        rows.pop(0)
    if not rows:
        raise ExcelError("工作表「%s」是空的" % chosen)
    headers = _unique_headers([_cell_text(c) for c in rows[0]])
    data_rows = [r for r in rows[1:] if any(_cell_text(c) for c in r)]
    return SheetPreview(
        path=str(source),
        sheet_names=names,
        sheet=chosen,
        headers=headers,
        rows=data_rows,
        total_rows=max(0, total - 1),
        mapping=auto_mapping(headers),
    )


def _unique_headers(headers: Sequence[str]) -> List[str]:
    """重复/空表头自动改名，保证可作为映射键。"""
    result: List[str] = []
    seen: Dict[str, int] = {}
    for i, header in enumerate(headers):
        name = (header or "").strip() or ("列%d" % (i + 1))
        if name in seen:
            seen[name] += 1
            name = "%s_%d" % (name, seen[name])
        else:
            seen[name] = 0
        result.append(name)
    return result


def _require_openpyxl() -> None:
    if not OPENPYXL_AVAILABLE:
        raise ExcelError(
            "未安装 openpyxl，无法读写 Excel。请执行：pip install openpyxl"
        )


def build_students(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    mapping: Mapping[str, str],
    skip_invalid: bool = True,
    existing_sids: Optional[Iterable[str]] = None,
) -> ImportResult:
    """按字段映射把表格行转换成学生列表。"""
    result = ImportResult(headers=list(headers), mapping=dict(mapping))
    known = set(existing_sids or [])
    seen: Dict[str, int] = {}
    attr_names: List[str] = []

    sid_cols = [i for i, h in enumerate(headers) if mapping.get(h) == F_SID]
    name_cols = [i for i, h in enumerate(headers) if mapping.get(h) == F_NAME]
    if not sid_cols:
        result.errors.append(ImportIssue(1, "没有指定「学号」列，无法导入"))
        return result
    if not name_cols:
        result.errors.append(ImportIssue(1, "没有指定「姓名」列，无法导入"))
        return result

    for offset, row in enumerate(rows):
        excel_row = offset + 2  # +1 表头，+1 转 1-based
        values = [_cell_text(c) for c in row]

        def pick(cols: Sequence[int]) -> str:
            for idx in cols:
                if idx < len(row):
                    text = _cell_text(row[idx])
                    if text:
                        return text
            return ""

        sid = pick(sid_cols)
        name = pick(name_cols)
        raw: Dict[str, Any] = {"学号": sid, "姓名": name}

        if not sid and not name:
            continue  # 整行空白
        if not sid:
            result.errors.append(ImportIssue(excel_row, "学号为空", raw))
            result.skipped += 1
            continue
        if not name:
            result.errors.append(ImportIssue(excel_row, "姓名为空", raw))
            result.skipped += 1
            continue
        if sid in known or sid in seen:
            where = seen.get(sid, -1)
            detail = "（与第 %d 行重复）" % where if where > 0 else "（与已有名单重复）"
            result.errors.append(ImportIssue(excel_row, "学号重复：%s %s" % (sid, detail), raw))
            result.skipped += 1
            continue

        gender = ""
        tags: List[str] = []
        note = ""
        attrs: Dict[str, float] = {}
        for idx, header in enumerate(headers):
            key = mapping.get(header) or F_IGNORE
            if key == F_IGNORE or idx >= len(row):
                continue
            value = row[idx]
            if key == F_GENDER:
                gender = _cell_text(value)
            elif key == F_TAGS:
                tags = [t.strip() for t in re.split(r"[,，;；/、|]+", _cell_text(value)) if t.strip()]
            elif key == F_NOTE:
                note = _cell_text(value)
            elif key.startswith(F_ATTR_PREFIX):
                attr_name = key[len(F_ATTR_PREFIX):].strip()
                number = _cell_number(value)
                if attr_name and number is not None:
                    attrs[attr_name] = number
                    raw[attr_name] = number
                    if attr_name not in attr_names:
                        attr_names.append(attr_name)

        seen[sid] = excel_row
        result.students.append(
            Student(sid=sid, name=name, gender=gender, tags=tags, attrs=attrs, note=note)
        )

    if result.errors and not skip_invalid:
        result.students = []
    result.new_attrs = attr_names
    if result.skipped:
        result.warnings.append("已跳过 %d 行有问题的数据" % result.skipped)
    if not result.students and not result.errors:
        result.warnings.append("没有读取到任何有效数据行")
    return result


# ------------------------------------------------------------------ 导出
@dataclass
class ExportOptions:
    """座位表导出选项。"""

    include_sid: bool = True
    include_group_title: bool = True
    include_roster: bool = True
    include_rules: bool = True
    show_podium: bool = True
    sheet_name: str = "座位表"


_THIN = Side(style="thin", color="FFD9DEE7")
_GRAY_FILL = PatternFill("solid", fgColor="FFF2F4F7")
_PODIUM_FILL = PatternFill("solid", fgColor="FF3A4252")
_HEADER_FILL = PatternFill("solid", fgColor="FFF2F4F7")
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT = Alignment(horizontal="left", vertical="center")


def _seat_cell_text(project: Project, seat_key: str, options: ExportOptions) -> Tuple[str, str]:
    """返回 ``(单元格文本, 标签色)``。"""
    sid = project.assignment.get(seat_key, "")
    if not sid:
        return "", ""
    student = project.get_student(sid)
    if student is None:
        return sid, ""
    text = student.name
    if options.include_sid and student.sid:
        text = "%s\n%s" % (student.name, student.sid)
    color = project.tag_color(student.tags[0]) if student.tags else ""
    return text, color


def export_seat_table(project: Project, path: str | Path, options: Optional[ExportOptions] = None) -> Path:  # type: ignore[valid-type]
    """导出座位表（主表 + 名单 + 规则说明）。"""
    _require_openpyxl()
    options = options or ExportOptions()
    target = Path(path)
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    target.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _safe_sheet_name(options.sheet_name)

    layout: Layout = project.layout
    groups = layout.groups
    max_rows = max([g.rows for g in groups], default=0)

    # 列映射：每个分组占 cols 列，组之间留 gap_after 个空列（过道）
    col_of_group: List[List[int]] = []
    cursor = 1
    for gi, group in enumerate(groups):
        cols = [cursor + c for c in range(group.cols)]
        col_of_group.append(cols)
        cursor += group.cols
        if gi < len(groups) - 1:
            cursor += max(1, int(group.gap_after))  # 过道至少 1 列

    total_cols = cursor - 1
    row_cursor = 1

    # 讲台
    if options.show_podium and layout.podium_side == "top":
        sheet.merge_cells(start_row=row_cursor, start_column=1, end_row=row_cursor, end_column=max(1, total_cols))
        cell = sheet.cell(row=row_cursor, column=1, value="讲　台")
        cell.fill = _PODIUM_FILL
        cell.font = Font(name="微软雅黑", size=16, bold=True, color="FFFFFFFF")
        cell.alignment = _CENTER
        sheet.row_dimensions[row_cursor].height = 36
        row_cursor += 1

    # 组标题
    if options.include_group_title:
        for gi, group in enumerate(groups):
            cols = col_of_group[gi]
            if not cols:
                continue
            sheet.merge_cells(
                start_row=row_cursor, start_column=min(cols), end_row=row_cursor, end_column=max(cols)
            )
            cell = sheet.cell(row=row_cursor, column=min(cols), value=group.name)
            cell.font = Font(name="微软雅黑", size=11, bold=True, color="FF6B7280")
            cell.alignment = _CENTER
        sheet.row_dimensions[row_cursor].height = 22
        row_cursor += 1

    first_seat_row = row_cursor
    for r in range(max_rows):
        sheet.row_dimensions[row_cursor].height = 40
        for gi, group in enumerate(groups):
            if r >= group.rows:
                continue
            for c, col_index in enumerate(col_of_group[gi]):
                seat = (gi, r, c)
                key = make_key(seat)
                cell = sheet.cell(row=row_cursor, column=col_index)
                if layout.is_disabled(seat):
                    cell.value = ""
                    cell.fill = _GRAY_FILL
                    cell.border = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
                else:
                    text, color = _seat_cell_text(project, key, options)
                    cell.value = text or None
                    left = Side(style="thick", color="FF" + color.lstrip("#").upper()) if color else _THIN
                    cell.border = Border(left=left, right=_THIN, top=_THIN, bottom=_THIN)
                cell.alignment = _CENTER
                cell.font = Font(name="微软雅黑", size=11)
        row_cursor += 1

    # 末行讲台
    if options.show_podium and layout.podium_side == "bottom":
        sheet.merge_cells(start_row=row_cursor, start_column=1, end_row=row_cursor, end_column=max(1, total_cols))
        cell = sheet.cell(row=row_cursor, column=1, value="讲　台")
        cell.fill = _PODIUM_FILL
        cell.font = Font(name="微软雅黑", size=16, bold=True, color="FFFFFFFF")
        cell.alignment = _CENTER
        sheet.row_dimensions[row_cursor].height = 36

    for col_index in range(1, max(1, total_cols) + 1):
        sheet.column_dimensions[get_column_letter(col_index)].width = 12

    # 标记座位区（供“名单”页引用）
    if options.include_roster:
        _write_roster(workbook, project, first_seat_row, max_rows)
    if options.include_rules:
        _write_rules(workbook, project)

    try:
        workbook.save(str(target))
    except Exception as exc:  # noqa: BLE001
        raise ExcelError("保存 Excel 失败：%s" % exc) from exc
    finally:
        workbook.close()
    return target


def _safe_sheet_name(name: str) -> str:
    cleaned = re.sub(r"[\\/*?:\[\]]", "_", str(name or "座位表")).strip()
    return (cleaned or "座位表")[:31]


def _write_roster(workbook, project: Project, first_seat_row: int, max_rows: int) -> None:
    sheet = workbook.create_sheet("名单")
    headers = ["学号", "姓名", "性别", "标签", "已分配座位"] + project.attr_names() + ["备注"]
    sheet.append(headers)
    for col in range(1, len(headers) + 1):
        cell = sheet.cell(row=1, column=col)
        cell.font = Font(name="微软雅黑", size=11, bold=True)
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

    from ..utils.natural_sort import natural_key

    seat_labels = _seat_labels(project, first_seat_row)
    for student in sorted(project.students, key=lambda s: natural_key(s.sid)):
        coord = project.seat_of(student.sid)
        row = [
            student.sid,
            student.name,
            student.gender,
            "、".join(student.tags),
            seat_labels.get(coord, ""),
        ]
        row.extend([student.attrs.get(name, "") for name in project.attr_names()])
        row.append(student.note)
        sheet.append(row)

    for col, header in enumerate(headers, start=1):
        width = 12
        if header == "姓名":
            width = 10
        elif header in ("标签", "备注"):
            width = 20
        elif header == "已分配座位":
            width = 18
        sheet.column_dimensions[get_column_letter(col)].width = width
    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=len(headers)):
        for cell in row:
            cell.alignment = _LEFT
            cell.font = Font(name="微软雅黑", size=11)
            cell.border = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _seat_labels(project: Project, first_seat_row: int) -> Dict[Any, str]:
    """``coord -> "第1组 第2排 第3列"``。"""
    labels: Dict[Any, str] = {}
    for gi, group in enumerate(project.layout.groups):
        for r in range(group.rows):
            for c in range(group.cols):
                labels[(gi, r, c)] = "%s 第%d排 第%d列" % (group.name, r + 1, c + 1)
    return labels


def _write_rules(workbook, project: Project) -> None:
    sheet = workbook.create_sheet("规则说明")
    sheet.append(["规则类型", "规则", "说明", "权重", "状态"])
    for col in range(1, 6):
        cell = sheet.cell(row=1, column=col)
        cell.font = Font(name="微软雅黑", size=11, bold=True)
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER

    def sname(sid: str) -> str:
        return project.student_name(sid)

    def selname(selection_id: str) -> str:
        return project.selection_name(selection_id)

    for rule in project.rules:
        sheet.append([
            "硬约束" if rule.is_hard else "软约束",
            rule.label,
            describe_rule(rule, sname, selname),
            "" if rule.is_hard else "%.2f" % rule.weight,
            "启用" if rule.enabled else "停用",
        ])
    if not project.rules:
        sheet.append(["—", "—", "本次排位未使用任何规则", "", ""])

    widths = [10, 16, 46, 8, 8]
    for col, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(col)].width = width
    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=5):
        for cell in row:
            cell.alignment = _LEFT
            cell.font = Font(name="微软雅黑", size=11)


def export_roster(project: Project, path: str | Path) -> Path:  # type: ignore[valid-type]
    """只导出学生名单。"""
    _require_openpyxl()
    target = Path(path)
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "名单"
    headers = ["学号", "姓名", "性别", "标签"] + project.attr_names() + ["备注"]
    sheet.append(headers)
    for col in range(1, len(headers) + 1):
        cell = sheet.cell(row=1, column=col)
        cell.font = Font(name="微软雅黑", size=11, bold=True)
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER

    from ..utils.natural_sort import natural_key

    for student in sorted(project.students, key=lambda s: natural_key(s.sid)):
        row = [student.sid, student.name, student.gender, "、".join(student.tags)]
        row.extend([student.attrs.get(name, "") for name in project.attr_names()])
        row.append(student.note)
        sheet.append(row)
    for col in range(1, len(headers) + 1):
        sheet.column_dimensions[get_column_letter(col)].width = 16
    try:
        workbook.save(str(target))
    except Exception as exc:  # noqa: BLE001
        raise ExcelError("保存 Excel 失败：%s" % exc) from exc
    finally:
        workbook.close()
    return target
