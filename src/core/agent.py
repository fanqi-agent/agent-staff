"""Agent 基类 — 所有角色继承此类

核心循环：think → tool_call → observe → think → ... → speak
增强：自动续写（达到轮数上限时）+ Token 用量统计
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.llm_client import LLMClient
from src.core.message_bus import BusMessage, MessageBus, MessageType
from src.tools.base import Tool

if TYPE_CHECKING:
    from src.approval.manager import ApprovalManager

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 25       # 单次 run 最大工具调用轮数
MAX_AUTO_CONTINUE = 3      # 自动续写最大次数


class BaseAgent:
    """Agent 基类"""

    role: str = ""
    role_cn: str = ""
    bot_name: str = ""
    system_prompt: str = ""

    def __init__(
        self,
        llm: LLMClient,
        bus: MessageBus,
        workspace: Path | None = None,
        tools: list[Tool] | None = None,
    ):
        self.llm = llm
        self.bus = bus
        self.workspace = workspace
        self.tools: dict[str, Tool] = {}
        self.conversation_history: list[dict] = []
        self.approval_manager: "ApprovalManager | None" = None

        # Token 统计
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0

        if tools:
            for t in tools:
                self.tools[t.name] = t

        bus.subscribe(f"agent:{self.role}", self._on_message)

    def update_workspace(self, new_workspace: Path):
        self.workspace = new_workspace
        self._rebuild_tools(new_workspace)

    def _rebuild_tools(self, workspace: Path):
        pass

    def set_approval_manager(self, manager: "ApprovalManager"):
        self.approval_manager = manager

    def set_skill_manager(self, skill_manager):
        """注入 Skills 工具到 Agent"""
        from src.tools.skill_tools import ListSkillsTool, ReadSkillTool
        self.tools[ListSkillsTool.name] = ListSkillsTool(skill_manager)
        self.tools[ReadSkillTool.name] = ReadSkillTool(skill_manager)

    def _build_messages(self, user_input: str) -> list[dict]:
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.conversation_history[-20:])
        messages.append({"role": "user", "content": user_input})
        return messages

    def _get_tool_schemas(self) -> list[dict] | None:
        if not self.tools:
            return None
        return [t.to_openai_tool() for t in self.tools.values()]

    def get_token_usage(self) -> dict:
        return {
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
        }

    async def run(self, user_input: str, context: str = "") -> str:
        """
        核心执行循环 + 自动续写：
        达到工具轮数上限时，自动续写最多 MAX_AUTO_CONTINUE 次
        """
        prompt = user_input
        if context:
            prompt = f"【上下文】\n{context}\n\n【任务】\n{user_input}"

        messages = self._build_messages(prompt)
        tool_schemas = self._get_tool_schemas()

        final_reply = ""
        for continue_i in range(MAX_AUTO_CONTINUE + 1):
            result = await self._run_loop(messages, tool_schemas)

            if result["finished"]:
                final_reply = result["reply"]
                break

            # 达到轮数上限，自动续写
            if continue_i < MAX_AUTO_CONTINUE:
                log.info("[%s] 轮数上限，自动续写 (%d/%d)",
                         self.role, continue_i + 1, MAX_AUTO_CONTINUE)
                messages.append({
                    "role": "user",
                    "content": "继续完成未完成的工作。不要重复已做的事情，"
                               "从上次停下的地方继续。"
                })
            else:
                # 最后一次：请求总结
                log.warning("[%s] 已达自动续写上限，请求总结", self.role)
                messages.append({
                    "role": "user",
                    "content": "工具调用次数已用尽，请总结你已完成的所有工作，"
                               "列出创建/修改的文件和功能。不要再调用工具。"
                })
                try:
                    summary = await self.llm.chat(messages, tools=None)
                    self._track_usage(summary)
                    final_reply = summary.content or "已完成部分工作"
                except Exception:
                    final_reply = "已完成部分工作（达到工具上限）"
                break

        self.conversation_history.append({"role": "user", "content": prompt})
        self.conversation_history.append({"role": "assistant", "content": final_reply})
        return final_reply

    async def _run_loop(self, messages: list[dict], tool_schemas) -> dict:
        """单次工具调用循环，返回 {finished: bool, reply: str}"""
        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.llm.chat(messages, tools=tool_schemas)
            self._track_usage(response)

            if not response.tool_calls:
                return {"finished": True, "reply": response.content or ""}

            messages.append({
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in response.tool_calls
                ],
            })

            for tc in response.tool_calls:
                func_name = tc.function.name
                tool = self.tools.get(func_name)

                if not tool:
                    result = f"工具 {func_name} 不存在"
                else:
                    try:
                        args = Tool.parse_arguments(tc.function.arguments)
                        log.info("[%s] 工具 %s(%s)", self.role, func_name,
                                 str(args)[:100])
                        result = await tool.execute(**args)
                    except Exception as e:
                        log.exception("Tool error")
                        result = f"工具执行失败: {e}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        return {"finished": False, "reply": ""}

    def _track_usage(self, response):
        """从 LLM 响应中提取 token 用量"""
        try:
            usage = getattr(response, '_raw_response', None)
            if usage and hasattr(usage, 'usage') and usage.usage:
                self.total_prompt_tokens += usage.usage.prompt_tokens or 0
                self.total_completion_tokens += usage.usage.completion_tokens or 0
        except Exception:
            pass

    async def _on_message(self, msg: BusMessage):
        if msg.type == MessageType.TASK_ASSIGN:
            log.info("[%s] 任务: %s", self.role, msg.content[:100])
            reply = await self.run(msg.content, context=msg.data.get("context", ""))
            await self.bus.publish(BusMessage(
                type=MessageType.TASK_RESULT,
                sender=self.role,
                content=reply,
                target=msg.sender,
                data={"stage": msg.data.get("stage", "")},
            ))

    async def request_approval(
        self, content: str, approval_type: str = "owner"
    ) -> tuple[bool, str]:
        if not self.approval_manager:
            log.warning("No approval manager, auto-approving")
            return True, "auto-approved"
        return await self.approval_manager.request_approval(
            requester=self.role,
            content=content,
            approval_type=approval_type,
        )
