"""对话框集合。

包含：布局编辑 / 导入字段映射 / 导出 / 排位进度 / 冲突报告 / 规则编辑 /
学生编辑 / 标签管理 / 文本导入。除 ``TagManagerDialog``（按契约直接维护
``project.tags``）外，对话框只收集用户输入并返回数据，不直接修改项目。
"""

from __future__ import annotations

from .conflict_report_dialog import ConflictReportDialog
from .export_dialog import ExportDialog
from .import_mapping_dialog import ImportMappingDialog
from .layout_editor_dialog import LayoutEditorDialog
from .rule_edit_dialog import RuleEditDialog
from .solver_progress_dialog import SolverProgressDialog
from .student_edit_dialog import StudentEditDialog
from .tag_manager_dialog import TagManagerDialog
from .text_import_dialog import TextImportDialog

__all__ = [
    "LayoutEditorDialog",
    "ImportMappingDialog",
    "ExportDialog",
    "SolverProgressDialog",
    "ConflictReportDialog",
    "RuleEditDialog",
    "StudentEditDialog",
    "TagManagerDialog",
    "TextImportDialog",
]
