"""审批管理器 — 两级审批（负责人 + PM 监察）"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Coroutine, Any

log = logging.getLogger(__name__)


class ApprovalType(str, Enum):
    OWNER = "owner"     # 负责人审核
    PM = "pm"           # PM 监察


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION = "revision"   # 需要修改


@dataclass
class ApprovalRequest:
    id: str
    requester: str
    content: str
    approval_type: ApprovalType
    status: ApprovalStatus = ApprovalStatus.PENDING
    feedback: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    event: asyncio.Event = field(default_factory=asyncio.Event)


# 发送审批消息到 Telegram 的回调
SendApprovalFunc = Callable[[ApprovalRequest], Coroutine[Any, Any, None]]


class ApprovalManager:
    """管理审批流程（阻塞等待模式）"""

    def __init__(self):
        self._requests: dict[str, ApprovalRequest] = {}
        self._counter = 0
        self._send_func: SendApprovalFunc | None = None

    def set_send_func(self, func: SendApprovalFunc):
        """设置发送审批通知的回调（由 Telegram 模块注入）"""
        self._send_func = func

    async def request_approval(
        self, requester: str, content: str, approval_type: str = "owner"
    ) -> tuple[bool, str]:
        """
        请求审批，阻塞等待直到负责人/PM 回复。
        返回 (是否通过, 反馈内容)
        """
        self._counter += 1
        req_id = f"approval-{self._counter}"

        req = ApprovalRequest(
            id=req_id,
            requester=requester,
            content=content,
            approval_type=ApprovalType(approval_type),
        )
        self._requests[req_id] = req

        # 发送审批通知到 Telegram
        if self._send_func:
            await self._send_func(req)
        else:
            log.warning("No send function, cannot send approval to Telegram")

        # 阻塞等待
        log.info("等待审批 %s ...", req_id)
        await req.event.wait()

        approved = req.status == ApprovalStatus.APPROVED
        return approved, req.feedback

    def resolve(self, req_id: str, approved: bool, feedback: str = ""):
        """解决审批请求（由 Telegram 回调触发）"""
        req = self._requests.get(req_id)
        if not req:
            log.warning("审批请求 %s 不存在", req_id)
            return False
        req.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        req.feedback = feedback
        req.event.set()
        log.info("审批 %s: %s (%s)", req_id, req.status, feedback)
        return True

    def get_pending(self) -> list[ApprovalRequest]:
        """获取所有待审批项"""
        return [r for r in self._requests.values() if r.status == ApprovalStatus.PENDING]

    def get_request(self, req_id: str) -> ApprovalRequest | None:
        return self._requests.get(req_id)
