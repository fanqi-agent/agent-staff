"""消息路由器 — 解析 @mention 并路由到对应 Agent"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)


class MessageRouter:
    """根据消息内容和 @mention 路由到对应 Agent"""

    def __init__(self):
        # bot_username -> agent_role 映射
        self._bot_to_role: dict[str, str] = {}
        # role -> handler 回调
        self._handlers: dict[str, any] = {}

    def register(self, bot_username: str, role: str, handler):
        """注册 Bot 用户名和对应的处理器"""
        self._bot_to_role[bot_username.lower()] = role
        self._handlers[role] = handler
        log.info("Registered route: @%s -> %s", bot_username, role)

    def parse_mentions(self, text: str) -> list[str]:
        """从消息文本中提取 @mentions，返回角色列表"""
        roles = []
        for word in text.split():
            if word.startswith("@"):
                username = word[1:].lower().rstrip(".,!?")
                role = self._bot_to_role.get(username)
                if role:
                    roles.append(role)
        return roles

    def get_handler(self, role: str):
        return self._handlers.get(role)

    @property
    def all_roles(self) -> list[str]:
        return list(self._handlers.keys())
