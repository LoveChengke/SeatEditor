"""对话框集合。

包含：布局编辑 / 导入字段映射 / 导出 / 排位进度 / 冲突报告 / 规则编辑 /
学生编辑 / 标签管理 / 文本导入。除 ``TagManagerDialog``（按契约直接维护
``project.tags``）外，对话框只收集用户输入并返回数据，不直接修改项目。

各对话框按需在函数内导入，例如
``from app.ui.dialogs.export_dialog import ExportDialog``。
"""
