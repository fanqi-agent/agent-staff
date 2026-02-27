"""产品经理 Agent — 需求分析 + 质量监察"""

from pathlib import Path

from src.core.agent import BaseAgent
from src.core.llm_client import LLMClient
from src.core.message_bus import MessageBus
from src.tools.file_ops import FileReadTool, ListDirTool


class ProductManagerAgent(BaseAgent):
    role = "product_manager"
    role_cn = "产品经理"
    bot_name = ""

    def __init__(self, llm: LLMClient, bus: MessageBus, workspace: Path):
        tools = [
            FileReadTool(workspace),
            ListDirTool(workspace),
        ]
        super().__init__(llm, bus, workspace, tools)
        self.system_prompt = self._load_prompt()

    def _rebuild_tools(self, workspace: Path):
        """重建工具指向新工作目录"""
        self.tools = {
            t.name: t for t in [
                FileReadTool(workspace),
                ListDirTool(workspace),
            ]
        }

    def _load_prompt(self) -> str:
        prompt_path = Path(__file__).parent.parent.parent / "prompts" / "product_manager.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return "你是一名资深产品经理，负责需求分析和质量监察。使用中文回复。"
