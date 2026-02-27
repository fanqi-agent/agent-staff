"""Tool 基类 — 所有工具继承此类"""

import json
from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Agent 可调用的工具"""

    name: str
    description: str
    parameters: dict  # JSON Schema

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """执行工具，返回文本结果"""
        ...

    def to_openai_tool(self) -> dict:
        """转为 OpenAI function calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @staticmethod
    def parse_arguments(arguments: str) -> dict[str, Any]:
        """解析 LLM 返回的 tool call 参数"""
        return json.loads(arguments)
