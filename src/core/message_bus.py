"""异步消息总线 — Agent 间通信"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine

log = logging.getLogger(__name__)


class MessageType(str, Enum):
    CHAT = "chat"                    # 群聊消息
    TASK_ASSIGN = "task_assign"      # 任务分配
    TASK_RESULT = "task_result"      # 任务结果
    APPROVAL_REQUEST = "approval_request"   # 请求审批
    APPROVAL_RESPONSE = "approval_response" # 审批回复
    STAGE_COMPLETE = "stage_complete"       # 阶段完成
    SYSTEM = "system"                # 系统消息


@dataclass
class BusMessage:
    type: MessageType
    sender: str              # agent 角色名
    content: str
    data: dict = field(default_factory=dict)
    target: str | None = None   # 目标 agent，None=广播
    timestamp: datetime = field(default_factory=datetime.now)


# 订阅回调类型
Subscriber = Callable[[BusMessage], Coroutine[Any, Any, None]]


class MessageBus:
    """简单的发布-订阅消息总线"""

    def __init__(self):
        self._subscribers: dict[str, list[Subscriber]] = {}  # topic -> callbacks
        self._global_subscribers: list[Subscriber] = []
        self._queue: asyncio.Queue[BusMessage] = asyncio.Queue()
        self._running = False

    def subscribe(self, topic: str, callback: Subscriber):
        """订阅特定主题"""
        self._subscribers.setdefault(topic, []).append(callback)

    def subscribe_all(self, callback: Subscriber):
        """订阅所有消息"""
        self._global_subscribers.append(callback)

    async def publish(self, message: BusMessage):
        """发布消息"""
        await self._queue.put(message)

    async def start(self):
        """启动消息分发循环"""
        self._running = True
        log.info("MessageBus started")
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            # 分发给全局订阅者
            for cb in self._global_subscribers:
                try:
                    await cb(msg)
                except Exception:
                    log.exception("Global subscriber error")

            # 分发给主题订阅者
            topic = msg.type.value
            for cb in self._subscribers.get(topic, []):
                try:
                    await cb(msg)
                except Exception:
                    log.exception("Subscriber error for topic %s", topic)

            # 如果有目标 agent，也发给该 agent 的专属主题
            if msg.target:
                for cb in self._subscribers.get(f"agent:{msg.target}", []):
                    try:
                        await cb(msg)
                    except Exception:
                        log.exception("Agent subscriber error")

    async def stop(self):
        self._running = False
        log.info("MessageBus stopped")
