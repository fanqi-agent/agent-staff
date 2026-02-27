"""LLM 客户端 — OpenAI 协议兼容"""

import logging
from openai import AsyncOpenAI

log = logging.getLogger(__name__)


class LLMClient:
    """统一的 LLM 调用接口，支持 function calling"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> dict:
        """调用 LLM，返回完整 response message"""
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = await self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        msg._raw_response = resp  # 附加原始响应用于 token 统计
        log.debug("LLM response: %s", msg)
        return msg

    async def simple_chat(self, system: str, user: str) -> str:
        """简单对话，直接返回文本"""
        msg = await self.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        return msg.content or ""
