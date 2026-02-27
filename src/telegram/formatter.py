"""Telegram 消息格式化"""


def escape_md(text: str) -> str:
    """转义 Telegram MarkdownV2 特殊字符"""
    special = r"_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def truncate(text: str, max_len: int = 4000) -> str:
    """截断消息（Telegram 单条消息上限 4096）"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n\n... (消息过长，已截断)"


def format_approval_message(req_id: str, requester: str, content: str) -> str:
    """格式化审批请求消息"""
    return (
        f"🔒 <b>审批请求</b> [{req_id}]\n"
        f"来自: {requester}\n\n"
        f"{truncate(content, 3000)}\n\n"
        f"请回复:\n"
        f"✅ 通过 — 回复 <code>/approve {req_id}</code>\n"
        f"❌ 拒绝 — 回复 <code>/reject {req_id} 原因</code>\n"
        f"📝 修改 — 回复 <code>/revise {req_id} 修改意见</code>"
    )


def format_agent_response(role_cn: str, content: str) -> str:
    """格式化 Agent 回复"""
    return f"🤖 <b>{role_cn}</b>\n\n{truncate(content)}"
