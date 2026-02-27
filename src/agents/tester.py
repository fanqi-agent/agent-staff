"""测试工程师 Agent — 测试验证 + 质量报告"""

from pathlib import Path

from src.core.agent import BaseAgent
from src.core.llm_client import LLMClient
from src.core.message_bus import MessageBus
from src.tools.file_ops import FileReadTool, FileWriteTool, ListDirTool
from src.tools.code_executor import CodeExecutorTool


class TesterAgent(BaseAgent):
    role = "tester"
    role_cn = "测试工程师"
    bot_name = ""

    def __init__(self, llm: LLMClient, bus: MessageBus, workspace: Path):
        tools = [
            FileReadTool(workspace),
            FileWriteTool(workspace),
            ListDirTool(workspace),
            CodeExecutorTool(workspace),
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
            ]
        }

    def _load_prompt(self) -> str:
        prompt_path = Path(__file__).parent.parent.parent / "prompts" / "tester.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return "你是一名资深测试工程师，负责测试验证和质量报告。使用中文回复。"
