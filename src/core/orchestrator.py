"""编排引擎 — 管理项目开发 Pipeline

流程（每个阶段由对应角色的 Bot 发言）：
  PM 分析需求 → 负责人审核 → Dev 开发实现 → QA 测试 → 有Bug→Dev修→QA复测 → 通知负责人
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.agent import BaseAgent
    from src.telegram.bot_manager import BotManager

log = logging.getLogger(__name__)

MAX_BUG_FIX_ROUNDS = 3


class Orchestrator:
    def __init__(self, bus, workspace: Path):
        self.bus = bus
        self.workspace = workspace
        self.project_dir: Path | None = None
        self.agents: dict[str, "BaseAgent"] = {}
        self.bot_manager: "BotManager | None" = None
        self.current_project: str = ""
        self.project_context: str = ""
        self.current_stage: str = ""

    def register_agent(self, role: str, agent: "BaseAgent"):
        self.agents[role] = agent

    def set_bot_manager(self, bm: "BotManager"):
        self.bot_manager = bm

    def _make_project_dir_name(self, description: str) -> str:
        mapping = {
            "计算器": "calculator", "计算": "calc",
            "聊天": "chat", "游戏": "game", "网站": "website",
            "商城": "shop", "博客": "blog", "工具": "tool",
            "管理": "manager", "系统": "system", "应用": "app",
            "服务": "service", "接口": "api", "测试": "test",
        }
        name = description.lower()
        for cn, en in mapping.items():
            if cn in name:
                name = name.replace(cn, en)
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        name = re.sub(r'_+', '_', name).strip('_')[:40]
        return name or "project"

    async def _send(self, role: str, text: str):
        if self.bot_manager:
            await self.bot_manager.send_message(role, text)

    async def start_project(self, description: str):
        self.current_project = description
        self.project_context = f"项目需求: {description}"

        dir_name = self._make_project_dir_name(description)
        self.project_dir = self.workspace / dir_name
        self.project_dir.mkdir(parents=True, exist_ok=True)

        # 清空上下文（新项目全新开始）
        if self.bot_manager:
            self.bot_manager.reset_context()

        for agent in self.agents.values():
            agent.update_workspace(self.project_dir)
            agent.conversation_history.clear()

        log.info("项目启动: %s -> %s", description, self.project_dir)

        try:
            await self._stage_requirements()
        except Exception:
            log.exception("Pipeline 异常中断")
            await self._send("product_manager", "❌ Pipeline 异常中断，请查看日志")

    # ========== 阶段 1: PM 需求分析 ==========
    async def _stage_requirements(self):
        self.current_stage = "需求分析"
        log.info("=== 阶段1: 需求分析 ===")

        pm = self.agents["product_manager"]
        result = await pm.run(
            f"用户要做一个项目，请分析需求并输出 PRD 文档。\n\n"
            f"【用户的项目需求】: {self.current_project}\n\n"
            f"请输出：\n1. 项目名称和简介\n2. 核心功能列表\n"
            f"3. 用户使用场景\n4. 技术建议\n\n"
            f"只输出 PRD 文档文字，不要写代码。"
        )
        self.project_context += f"\n\n【PRD 文档】\n{result}"

        # PM Bot 发送 PRD
        from src.telegram.formatter import format_agent_response
        await self._send("product_manager", format_agent_response("产品经理", result))
        await self._send("product_manager",
            "⏳ <b>等待负责人审核</b>\n/approve 通过 | /reject 原因 拒绝")

        log.info("PRD 完成，等待负责人审核...")
        approved, feedback = await pm.request_approval(
            content=f"PRD 审核\n\n{result[:2000]}",
            approval_type="owner",
        )
        log.info("审批结果: approved=%s", approved)

        if not approved:
            self.project_context += f"\n\n负责人反馈: {feedback}"
            await self._send("product_manager", f"🔄 负责人要求修改: {feedback}")
            await self._stage_requirements()
            return

        # 审核通过 → Dev Bot 响应
        await self._send("developer",
            "📋 <b>收到 PRD，开始开发</b>\n程序员正在编码实现...")
        await self._stage_development()

    # ========== 阶段 2: Dev 开发 ==========
    async def _stage_development(self):
        self.current_stage = "开发实现"
        log.info("=== 阶段2: 开发实现 ===")

        dev = self.agents["developer"]
        result = await dev.run(
            f"请根据 PRD 进行编码实现。\n\n"
            f"【用户的项目需求】: {self.current_project}\n"
            f"工作目录: {self.project_dir}\n\n"
            f"要求：\n"
            f"1. 用 write_file 创建源代码文件，实现全部功能\n"
            f"2. 用 execute_command 运行验证无语法错误\n"
            f"3. 用 git 初始化仓库并提交代码\n"
            f"4. 列出创建的文件和功能\n\n"
            f"切记：你要实现的是【{self.current_project}】这个项目！",
            context=self.project_context,
        )
        self.project_context += f"\n\n【开发完成】\n{result}"

        # Dev Bot 发送结果
        from src.telegram.formatter import format_agent_response
        await self._send("developer", format_agent_response("程序员", result))

        # 转交 QA
        await self._send("tester",
            "🔍 <b>收到代码，开始测试</b>\n测试工程师正在审查和测试...")
        await self._stage_testing()

    # ========== 阶段 3: QA 测试 ==========
    async def _stage_testing(self, bug_fix_round: int = 0):
        self.current_stage = "测试验证"
        round_info = f"（第 {bug_fix_round + 1} 轮复测）" if bug_fix_round > 0 else ""
        log.info("=== 阶段3: 测试 %s ===", round_info)

        qa = self.agents["tester"]
        result = await qa.run(
            f"项目代码已写完，请测试和审查。{round_info}\n\n"
            f"【用户的项目需求】: {self.current_project}\n"
            f"工作目录: {self.project_dir}\n\n"
            f"步骤：\n"
            f"1. list_directory 查看项目文件\n"
            f"2. read_file 阅读代码\n"
            f"3. execute_command 运行程序测试\n"
            f"4. 编写测试脚本并执行\n\n"
            f"报告格式：测试用例数、通过率、Bug 列表\n"
            f"最后必须给出结论：【测试通过】或【测试不通过】",
            context=self.project_context,
        )
        self.project_context += f"\n\n【测试报告{round_info}】\n{result}"

        # QA Bot 发送报告
        from src.telegram.formatter import format_agent_response
        await self._send("tester", format_agent_response("测试工程师", result))

        if "测试通过" in result and "不通过" not in result:
            await self._stage_delivery()
        else:
            if bug_fix_round >= MAX_BUG_FIX_ROUNDS:
                await self._send("product_manager",
                    f"⚠️ 已达最大修复轮数({MAX_BUG_FIX_ROUNDS})，请负责人决定\n"
                    f"/approve 继续修复 | /reject 终止项目")

                pm = self.agents["product_manager"]
                approved, feedback = await pm.request_approval(
                    content=f"Bug 修复已达 {MAX_BUG_FIX_ROUNDS} 轮，是否继续？",
                    approval_type="owner",
                )
                if approved:
                    await self._send("developer",
                        "🔧 <b>负责人批准继续修复</b>")
                    await self._stage_bug_fix(result, bug_fix_round)
                else:
                    await self._send("product_manager",
                        f"❌ 项目终止: {feedback}")
                return
            # 有 Bug → Dev Bot 修复
            await self._send("developer",
                "🐛 <b>收到 Bug 报告，开始修复</b>\n程序员正在修复...")
            await self._stage_bug_fix(result, bug_fix_round)

    # ========== Bug 修复 ==========
    async def _stage_bug_fix(self, test_report: str, bug_fix_round: int):
        self.current_stage = "Bug 修复"
        log.info("=== Bug 修复（第 %d 轮）===", bug_fix_round + 1)

        dev = self.agents["developer"]
        result = await dev.run(
            f"测试工程师发现了 Bug，请修复。\n\n"
            f"工作目录: {self.project_dir}\n\n"
            f"【测试报告】:\n{test_report[:3000]}\n\n"
            f"要求：查看代码 → 修复 Bug → 运行验证 → Git commit → 说明修复内容",
            context=self.project_context,
        )
        self.project_context += f"\n\n【Bug 修复】\n{result}"

        from src.telegram.formatter import format_agent_response
        await self._send("developer", format_agent_response("程序员", result))

        # 修完 → QA 复测
        await self._send("tester",
            "🔍 <b>Bug 已修复，开始复测</b>\n测试工程师正在验证...")
        await self._stage_testing(bug_fix_round + 1)

    # ========== 交付 ==========
    async def _stage_delivery(self):
        self.current_stage = "交付完成"
        log.info("=== 项目交付 ===")

        await self._send("product_manager",
            f"🎉 <b>项目已完成！所有测试通过 ✅</b>\n\n"
            f"📋 {self.current_project}\n"
            f"📁 {self.project_dir}\n\n"
            f"请负责人查看项目文件。")

    def get_status(self) -> str:
        if not self.current_project:
            return "暂无进行中的项目"
        return (
            f"项目: {self.current_project}\n"
            f"目录: {self.project_dir}\n"
            f"当前: {self.current_stage}"
        )
