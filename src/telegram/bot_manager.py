"""Telegram 多 Bot 管理器

核心设计：
- 命令去重：用 message_id 防止 3 Bot 重复处理
- /project → PM Bot 收到 → LangGraph Pipeline 启动
- /approve → LangGraph resume("approved")
- /reject → LangGraph resume("rejected: 原因")
- @某Bot → 该 Bot 回复
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram import Update, Bot
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    Application,
)

from src.telegram.formatter import format_approval_message, format_agent_response, truncate
from src.approval.manager import ApprovalManager, ApprovalRequest

if TYPE_CHECKING:
    from src.core.agent import BaseAgent
    from src.core.graph import PipelineEngine

log = logging.getLogger(__name__)


class BotManager:
    def __init__(
        self,
        tokens: dict[str, str],
        group_chat_id: int,
        owner_user_id: int,
        approval_manager: ApprovalManager,
        proxy_url: str = "",
    ):
        self.tokens = tokens
        self.group_chat_id = group_chat_id
        self.owner_user_id = owner_user_id
        self.approval_manager = approval_manager
        self.proxy_url = proxy_url
        self.pipeline: "PipelineEngine | None" = None

        self.apps: dict[str, Application] = {}
        self.agents: dict[str, "BaseAgent"] = {}
        self.bots: dict[str, Bot] = {}
        self._username_to_role: dict[str, str] = {}
        self._chat_history: list[str] = []

        # 命令去重
        self._processed_msg_ids: set[int] = set()

    def set_pipeline(self, pipeline: "PipelineEngine"):
        self.pipeline = pipeline

    def register_agent(self, role: str, agent: "BaseAgent", bot_username: str):
        self.agents[role] = agent
        self._username_to_role[bot_username.lower()] = role

    def _dedup(self, message_id: int) -> bool:
        """去重：返回 True 表示已处理过，应跳过"""
        if message_id in self._processed_msg_ids:
            return True
        self._processed_msg_ids.add(message_id)
        if len(self._processed_msg_ids) > 200:
            oldest = sorted(self._processed_msg_ids)[:100]
            self._processed_msg_ids -= set(oldest)
        return False

    def reset_context(self):
        """新项目时清空上下文"""
        self._chat_history.clear()
        log.info("群聊上下文已清空")

    def _add_to_chat_history(self, sender: str, text: str):
        entry = f"[{sender}]: {text}"
        self._chat_history.append(entry)
        if len(self._chat_history) > 50:
            self._chat_history = self._chat_history[-50:]

    def get_chat_context(self) -> str:
        if not self._chat_history:
            return ""
        return "\n".join(self._chat_history[-30:])

    async def send_message(self, role: str, text: str, parse_mode: str = "HTML"):
        """通过指定角色的 Bot 发送消息"""
        bot = self.bots.get(role)
        if not bot:
            log.error("Bot for role %s not found", role)
            return
        text = truncate(text)
        try:
            await bot.send_message(chat_id=self.group_chat_id, text=text, parse_mode=parse_mode)
        except Exception:
            try:
                await bot.send_message(chat_id=self.group_chat_id, text=text)
            except Exception:
                log.exception("Failed to send message for role %s", role)

    async def send_approval_notification(self, req: ApprovalRequest):
        text = format_approval_message(req.id, req.requester, req.content)
        await self.send_message("product_manager", text)

    def _find_mentioned_role(self, text: str) -> str | None:
        for word in text.split():
            if word.startswith("@"):
                username = word[1:].lower().rstrip(".,!?;:")
                role = self._username_to_role.get(username)
                if role:
                    return role
        return None

    # ======== 消息处理 ========

    def _create_message_handler(self, this_role: str):
        """每个 Bot 只在自己被 @mention 时回复"""
        async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not update.message or not update.message.text:
                return
            if update.message.chat_id != self.group_chat_id:
                return

            text = update.message.text
            user = update.message.from_user
            user_name = user.first_name if user else "Unknown"
            user_id = user.id if user else 0

            for bot in self.bots.values():
                if user_id == bot.id:
                    return

            # 主 Bot 记录上下文
            if this_role == "product_manager":
                self._add_to_chat_history(user_name, text)

            # 只处理 @自己的
            mentioned_role = self._find_mentioned_role(text)
            if mentioned_role != this_role:
                return

            if self._dedup(update.message.message_id):
                return

            agent = self.agents.get(this_role)
            if not agent:
                return

            log.info("[@%s] 收到消息 from %s: %s", this_role, user_name, text[:80])
            asyncio.create_task(self._run_agent_and_reply(this_role, agent, text, user_name))

        return handler

    async def _run_agent_and_reply(self, role: str, agent, text: str, user_name: str):
        try:
            chat_ctx = self.get_chat_context()
            reply = await agent.run(text, context=chat_ctx)
            if reply:
                await self.send_message(role, format_agent_response(agent.role_cn, reply))
        except Exception:
            log.exception("Agent %s execution error", role)
            await self.send_message(role, f"⚠️ {agent.role_cn} 执行出错，请重试")

    # ======== 命令处理（全部去重） ========

    def _create_cmd_handler(self, cmd_func):
        """包装命令处理函数，加入去重"""
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if self._dedup(update.message.message_id):
                return
            await cmd_func(update, context)
        return wrapper

    async def start(self):
        self.approval_manager.set_send_func(self.send_approval_notification)

        for role, token in self.tokens.items():
            builder = ApplicationBuilder().token(token)
            if self.proxy_url:
                req = HTTPXRequest(proxy=self.proxy_url, connect_timeout=30, read_timeout=30)
                get_req = HTTPXRequest(proxy=self.proxy_url, connect_timeout=30, read_timeout=30)
                builder = builder.request(req).get_updates_request(get_req)

            app = builder.build()

            # 所有 Bot 注册所有命令（用去重保证只处理一次）
            app.add_handler(CommandHandler("start", self._create_cmd_handler(self._cmd_start)))
            app.add_handler(CommandHandler("status", self._create_cmd_handler(self._cmd_status)))
            app.add_handler(CommandHandler("approve", self._create_cmd_handler(self._cmd_approve)))
            app.add_handler(CommandHandler("reject", self._create_cmd_handler(self._cmd_reject)))
            app.add_handler(CommandHandler("project", self._create_cmd_handler(self._cmd_project)))

            # @mention 消息处理
            msg_filter = (
                filters.TEXT
                & ~filters.COMMAND
                & (filters.ChatType.SUPERGROUP | filters.ChatType.GROUP)
            )
            app.add_handler(MessageHandler(msg_filter, self._create_message_handler(role)))

            self.apps[role] = app
            await app.initialize()
            self.bots[role] = app.bot
            info = await app.bot.get_me()
            log.info("Bot [%s]: @%s (id=%s)", role, info.username, info.id)
            if info.username:
                self._username_to_role[info.username.lower()] = role

        for role, app in self.apps.items():
            await app.start()
            await app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=["message"],
            )
            log.info("Bot [%s] polling started", role)

    async def stop(self):
        for role, app in self.apps.items():
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except Exception:
                log.exception("Error stopping bot %s", role)

    # ======== 具体命令 ========

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # 只让 PM Bot 回复
        await self.send_message("product_manager",
            "🤖 <b>Agent Staff 协作系统已就绪</b>\n\n"
            "/project 描述 — 发起新项目\n"
            "/approve — 通过审批\n"
            "/reject 原因 — 拒绝审批\n"
            "/status — 查看状态\n"
            "@Bot名 消息 — 对话某角色")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.pipeline:
            await update.message.reply_text("编排引擎未初始化")
            return
        await update.message.reply_text(f"📋 {self.pipeline.get_status()}")

    async def _cmd_approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        log.info("/approve 收到, user=%s", update.message.from_user.id)
        if update.message.from_user.id != self.owner_user_id:
            await update.message.reply_text("⛔ 仅负责人可审批")
            return
        if not self.pipeline:
            await update.message.reply_text("⚠️ 编排引擎未初始化")
            return

        await update.message.reply_text("✅ 已通过审批")
        asyncio.create_task(self.pipeline.resume("approved"))

    async def _cmd_reject(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        log.info("/reject 收到, user=%s", update.message.from_user.id)
        if update.message.from_user.id != self.owner_user_id:
            await update.message.reply_text("⛔ 仅负责人可审批")
            return
        if not self.pipeline:
            await update.message.reply_text("⚠️ 编排引擎未初始化")
            return

        args = context.args
        reason = " ".join(args) if args else "未说明原因"

        await update.message.reply_text(f"❌ 已拒绝: {reason}")
        asyncio.create_task(self.pipeline.resume(f"rejected: {reason}"))

    async def _cmd_project(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        log.info("/project 收到, user=%s", update.message.from_user.id)
        if update.message.from_user.id != self.owner_user_id:
            await update.message.reply_text("⛔ 仅负责人可发起项目")
            return
        args = context.args
        if not args:
            await update.message.reply_text("用法: /project 项目描述")
            return

        description = " ".join(args)

        # PM Bot 响应
        await self.send_message("product_manager",
            f" <b>收到项目需求</b>\n{description}\n\n产品经理开始分析需求...")

        self._add_to_chat_history("负责人", f"发起项目: {description}")

        if self.pipeline:
            asyncio.create_task(self.pipeline.start_project(description))
        else:
            await update.message.reply_text("⚠️ 编排引擎未初始化")
