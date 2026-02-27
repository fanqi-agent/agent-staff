"""程序员 Agent — 架构设计 + 代码实现"""

from pathlib import Path

from src.core.agent import BaseAgent
from src.core.llm_client import LLMClient
from src.core.message_bus import MessageBus
from src.tools.file_ops import FileReadTool, FileWriteTool, ListDirTool
from src.tools.code_executor import CodeExecutorTool, WriteAndRunTool
from src.tools.git_tool import GitTool


class DeveloperAgent(BaseAgent):
    role = "developer"
    role_cn = "程序员"
    bot_name = ""

    def __init__(self, llm: LLMClient, bus: MessageBus, workspace: Path):
        tools = [
            FileReadTool(workspace),
            FileWriteTool(workspace),
            ListDirTool(workspace),
            CodeExecutorTool(workspace),
            WriteAndRunTool(workspace),
            GitTool(workspace),
        ]
        super().__init__(llm, bus, workspace, tools)
        self.system_prompt = self._load_prompt()

    def _rebuild_tools(self, workspace: Path):
        """重建工具指向新工作目录"""
        self.tools = {
            t.name: t for t in [
                FileReadTool(workspace),
                FileWriteTool(workspace),
                ListDirTool(workspace),
                CodeExecutorTool(workspace),
                WriteAndRunTool(workspace),
                GitTool(workspace),
            ]
        }

    def _load_prompt(self) -> str:
        prompt_path = Path(__file__).parent.parent.parent / "prompts" / "developer.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return "你是一名全栈高级程序员兼架构师，负责技术设计和代码实现。使用中文回复。"
