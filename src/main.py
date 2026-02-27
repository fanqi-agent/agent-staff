"""Agent Staff — 入口"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Settings
from src.core.llm_client import LLMClient
from src.core.message_bus import MessageBus
from src.core.graph import PipelineEngine
from src.approval.manager import ApprovalManager
from src.telegram.bot_manager import BotManager
from src.agents.product_manager import ProductManagerAgent
from src.agents.developer import DeveloperAgent
from src.agents.tester import TesterAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("agent-staff")


def _create_llm(settings: Settings, role: str) -> LLMClient:
    """为指定角色创建独立的 LLMClient"""
    cfg = settings.get_llm_config(role)
    log.info("[%s] LLM: model=%s base_url=%s", role, cfg["model"], cfg["base_url"])
    return LLMClient(api_key=cfg["api_key"], base_url=cfg["base_url"], model=cfg["model"])


async def run():
    settings = Settings()  # type: ignore[call-arg]

    workspace = settings.workspace_dir.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    log.info("工作区: %s", workspace)

    bus = MessageBus()
    approval_manager = ApprovalManager()

    # 每个 Agent 独立 LLM
    pm_llm = _create_llm(settings, "product_manager")
    dev_llm = _create_llm(settings, "developer")
    qa_llm = _create_llm(settings, "tester")

    pm_agent = ProductManagerAgent(pm_llm, bus, workspace)
    dev_agent = DeveloperAgent(dev_llm, bus, workspace)
    qa_agent = TesterAgent(qa_llm, bus, workspace)
    pm_agent.set_approval_manager(approval_manager)
    dev_agent.set_approval_manager(approval_manager)
    qa_agent.set_approval_manager(approval_manager)

    # Skills
    from src.core.skill_manager import SkillManager
    skill_mgr = SkillManager()
    # 搜索路径：项目级 → 框架级 → 全局
    skill_mgr.add_search_path(workspace / "skills")
    skill_mgr.add_search_path(Path(__file__).resolve().parent.parent / "skills")
    skill_mgr.add_search_path(Path.home() / ".gemini" / "antigravity" / "skills")
    skill_mgr.discover()

    pm_agent.set_skill_manager(skill_mgr)
    dev_agent.set_skill_manager(skill_mgr)
    qa_agent.set_skill_manager(skill_mgr)

    # LangGraph Pipeline
    pipeline = PipelineEngine(workspace)
    pipeline.register_agent("product_manager", pm_agent)
    pipeline.register_agent("developer", dev_agent)
    pipeline.register_agent("tester", qa_agent)

    # Telegram
    tokens = {
        "product_manager": settings.bot_token_pm,
        "developer": settings.bot_token_dev,
        "tester": settings.bot_token_qa,
    }
    bot_manager = BotManager(
        tokens=tokens,
        group_chat_id=settings.group_chat_id,
        owner_user_id=settings.owner_user_id,
        approval_manager=approval_manager,
        proxy_url=settings.proxy_url,
    )
    bot_manager.register_agent("product_manager", pm_agent, "pm_bot")
    bot_manager.register_agent("developer", dev_agent, "dev_bot")
    bot_manager.register_agent("tester", qa_agent, "qa_bot")

    bot_manager.set_pipeline(pipeline)
    pipeline.set_bot_manager(bot_manager)

    log.info("=" * 50)
    log.info("🚀 Agent Staff (LangGraph) 启动...")
    log.info("=" * 50)

    bus_task = asyncio.create_task(bus.start())

    try:
        await bot_manager.start()
        log.info("=" * 50)
        log.info("✅ 就绪 | /project <描述> | @Bot <消息>")
        log.info("=" * 50)

        stop_event = asyncio.Event()
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGINT, lambda: stop_event.set())
            loop.add_signal_handler(signal.SIGTERM, lambda: stop_event.set())
        except NotImplementedError:
            pass
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        await bot_manager.stop()
        await bus.stop()
        bus_task.cancel()
        log.info("已退出")


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
