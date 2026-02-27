"""文件操作工具"""

import os
from pathlib import Path

from src.tools.base import Tool


class FileReadTool(Tool):
    name = "read_file"
    description = "读取指定文件的内容。用于查看代码、文档等文件。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对于工作区的文件路径",
            }
        },
        "required": ["path"],
    }

    def __init__(self, workspace: Path):
        self.workspace = workspace

    async def execute(self, **kwargs) -> str:
        path = self.workspace / kwargs["path"]
        if not path.exists():
            return f"错误：文件 {kwargs['path']} 不存在"
        if not path.is_file():
            return f"错误：{kwargs['path']} 不是文件"
        try:
            content = path.read_text(encoding="utf-8")
            if len(content) > 10000:
                content = content[:10000] + "\n... (truncated)"
            return content
        except Exception as e:
            return f"读取失败：{e}"


class FileWriteTool(Tool):
    name = "write_file"
    description = "创建或覆盖写入文件。自动创建父目录。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对于工作区的文件路径",
            },
            "content": {
                "type": "string",
                "description": "文件内容",
            },
        },
        "required": ["path", "content"],
    }

    def __init__(self, workspace: Path):
        self.workspace = workspace

    async def execute(self, **kwargs) -> str:
        path = self.workspace / kwargs["path"]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(kwargs["content"], encoding="utf-8")
            return f"✅ 文件已写入：{kwargs['path']}（{len(kwargs['content'])} 字符）"
        except Exception as e:
            return f"写入失败：{e}"


class ListDirTool(Tool):
    name = "list_directory"
    description = "列出目录下的文件和子目录。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "相对于工作区的目录路径，留空表示根目录",
                "default": ".",
            }
        },
    }

    def __init__(self, workspace: Path):
        self.workspace = workspace

    async def execute(self, **kwargs) -> str:
        path = self.workspace / kwargs.get("path", ".")
        if not path.exists():
            return f"目录不存在：{kwargs.get('path', '.')}"
        items = []
        for item in sorted(path.iterdir()):
            prefix = "📁" if item.is_dir() else "📄"
            rel = item.relative_to(self.workspace)
            size = ""
            if item.is_file():
                size = f" ({item.stat().st_size} bytes)"
            items.append(f"{prefix} {rel}{size}")
        return "\n".join(items) if items else "（空目录）"
