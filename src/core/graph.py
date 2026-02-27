"""LangGraph 编排引擎 — 用状态图管理项目开发 Pipeline

流程图：
  PM需求分析 → 负责人审核 → Dev开发 → QA测试 → (Bug→Dev修→QA复测) → 交付
"""

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import TypedDict, Literal, Any, TYPE_CHECKING

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command

from src.tools.screenshot import screenshot_project

if TYPE_CHECKING:
    from src.core.agent import BaseAgent
    from src.telegram.bot_manager import BotManager

log = logging.getLogger(__name__)

MAX_BUG_FIX_ROUNDS = 3


# ============ 状态定义 ============

class ProjectState(TypedDict, total=False):
    """Pipeline 状态，在节点间传递"""
    description: str        # 项目描述
    project_dir: str        # 项目目录
    prd: str                # PM 输出的 PRD
    dev_result: str         # 开发结果
    test_report: str        # 测试报告
    bug_fix_round: int      # Bug 修复轮数
    stage: str              # 当前阶段名
    context: str            # 累积上下文
    timestamps: dict        # 各阶段耗时 {stage: seconds}
    result: str             # 最终结论


# ============ Pipeline 引擎 ============

class PipelineEngine:
    """基于 LangGraph 的项目开发 Pipeline"""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.agents: dict[str, "BaseAgent"] = {}
        self.bot_manager: "BotManager | None" = None
        self.checkpointer = InMemorySaver()
        self.graph = None
        self._thread_counter = 0
        self._current_thread_id: str | None = None

    def register_agent(self, role: str, agent: "BaseAgent"):
        self.agents[role] = agent

    def set_bot_manager(self, bm: "BotManager"):
        self.bot_manager = bm
        self._build_graph()

    async def _send(self, role: str, text: str):
        if self.bot_manager:
            await self.bot_manager.send_message(role, text)

    def _progress_bar(self, current: int, total: int = 5) -> str:
        filled = '■' * current
        empty = '□' * (total - current)
        return f"[{filled}{empty}] {current}/{total}"

    def _get_file_tree(self, directory: Path, prefix: str = "", max_depth: int = 3, current_depth: int = 0) -> str:
        if current_depth >= max_depth or not directory.exists():
            return ""
        lines = []
        items = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
        for i, item in enumerate(items):
            if item.name.startswith('.') and item.name != '.gitignore':
                continue
            is_last = i == len(items) - 1
            connector = '└─ ' if is_last else '├─ '
            lines.append(f"{prefix}{connector}{item.name}")
            if item.is_dir():
                extension = '   ' if is_last else '│  '
                lines.append(self._get_file_tree(item, prefix + extension, max_depth, current_depth + 1))
        return '\n'.join(filter(None, lines))

    # ============ 图节点 ============

    async def _node_pm_analyze(self, state: ProjectState) -> dict:
        """PM 分析需求"""
        t0 = time.time()
        await self._send("product_manager",
            f"📍 <b>阶段 1/4: 需求分析</b> {self._progress_bar(1, 4)}\n"
            f"产品经理正在分析需求...")

        pm = self.agents["product_manager"]
        prd = await pm.run(
            f"用户要做一个项目，请分析需求并输出 PRD 文档。\n\n"
            f"【用户的项目需求】: {state['description']}\n\n"
            f"请输出：\n1. 项目名称和简介\n2. 核心功能列表\n"
            f"3. 用户使用场景\n4. 技术建议\n\n"
            f"只输出 PRD 文档文字，不要写代码。"
        )

        # 保存 PRD 文件
        project_dir = Path(state["project_dir"])
        docs_dir = project_dir / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "prd.md").write_text(prd, encoding="utf-8")

        from src.telegram.formatter import format_agent_response
        await self._send("product_manager", format_agent_response("产品经理", prd))

        elapsed = round(time.time() - t0, 1)
        timestamps = dict(state.get("timestamps", {}))
        timestamps["需求分析"] = elapsed

        return {
            "prd": prd,
            "stage": "需求分析完成",
            "context": state.get("context", "") + f"\n\n【PRD 文档】\n{prd}",
            "timestamps": timestamps,
        }

    async def _node_owner_review(self, state: ProjectState) -> dict:
        """负责人审核（人工介入）"""
        await self._send("product_manager",
            "⏳ <b>等待负责人审核 PRD</b>\n"
            "/approve 通过 | /reject 原因 拒绝")

        # interrupt 会阻塞直到 resume
        decision = interrupt({"type": "owner_review", "content": "PRD 审核"})

        log.info("审核结果: %s", decision)
        return {"stage": f"审核结果: {decision}"}

    async def _node_dev_implement(self, state: ProjectState) -> dict:
        """Dev 编码实现"""
        t0 = time.time()
        await self._send("developer",
            f"📍 <b>阶段 2/4: 编码实现</b> {self._progress_bar(2, 4)}\n"
            f"📋 收到 PRD，程序员开始编码...")

        dev = self.agents["developer"]
        result = await dev.run(
            f"请根据 PRD 进行编码实现。\n\n"
            f"【用户的项目需求】: {state['description']}\n"
            f"工作目录: {state['project_dir']}\n\n"
            f"开发规范：\n"
            f"1. 用 write_file 创建源代码文件，实现全部功能\n"
            f"2. 用 execute_command 运行验证无语法错误\n"
            f"3. 用 git 初始化仓库并提交代码\n"
            f"4. 先实现核心功能，再处理辅助文件，高效利用工具调用\n"
            f"5. 如果是 Web 项目，API 地址必须用 http://localhost:PORT 格式\n"
            f"   绝对不能用 file:// 协议！HTML 中的 API 请求也必须用 http://\n"
            f"6. 如果启动了服务（如 Flask/Express），请在后台运行\n\n"
            f"切记：实现的是【{state['description']}】这个项目！",
            context=state.get("context", ""),
        )

        from src.telegram.formatter import format_agent_response
        await self._send("developer", format_agent_response("程序员", result))

        elapsed = round(time.time() - t0, 1)
        timestamps = dict(state.get("timestamps", {}))
        timestamps["编码实现"] = elapsed

        # 尝试截图
        await self._try_screenshot(state)

        return {
            "dev_result": result,
            "stage": "开发完成",
            "context": state.get("context", "") + f"\n\n【开发完成】\n{result}",
            "timestamps": timestamps,
        }

    async def _try_screenshot(self, state: ProjectState):
        """尝试对项目做截图（如果是 Web 项目）"""
        try:
            for port in [5000, 8000, 3000, 8080]:
                png = await screenshot_project(Path(state["project_dir"]), port=port)
                if png:
                    bot = self.bot_manager.bots.get("developer") if self.bot_manager else None
                    if bot:
                        await bot.send_photo(
                            chat_id=self.bot_manager.group_chat_id,
                            photo=png,
                            caption=f"📸 项目截图 (localhost:{port})"
                        )
                    return
        except Exception:
            log.debug("截图跳过（非 Web 项目或服务未启动）")

    async def _node_qa_test(self, state: ProjectState) -> dict:
        """QA 测试"""
        t0 = time.time()
        bug_round = state.get("bug_fix_round", 0)
        round_info = f"（第 {bug_round + 1} 轮复测）" if bug_round > 0 else ""
        await self._send("tester",
            f"📍 <b>阶段 3/4: 测试验证{round_info}</b> {self._progress_bar(3, 4)}\n"
            f"🔍 测试工程师正在审查和测试...")

        qa = self.agents["tester"]
        report = await qa.run(
            f"项目代码已写完，请测试和审查。{round_info}\n\n"
            f"【用户的项目需求】: {state['description']}\n"
            f"工作目录: {state['project_dir']}\n\n"
            f"步骤：\n"
            f"1. list_directory 查看项目文件\n"
            f"2. read_file 阅读代码\n"
            f"3. execute_command 运行程序测试\n"
            f"4. 编写测试脚本并执行\n\n"
            f"最后必须给出结论：【测试通过】或【测试不通过】",
            context=state.get("context", ""),
        )

        # 保存测试报告
        project_dir = Path(state["project_dir"])
        docs_dir = project_dir / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        report_file = "test_report.md" if bug_round == 0 else f"test_report_round{bug_round + 1}.md"
        (docs_dir / report_file).write_text(report, encoding="utf-8")

        from src.telegram.formatter import format_agent_response
        await self._send("tester", format_agent_response("测试工程师", report))

        elapsed = round(time.time() - t0, 1)
        timestamps = dict(state.get("timestamps", {}))
        test_key = f"测试{round_info}" if round_info else "测试验证"
        timestamps[test_key] = elapsed

        return {
            "test_report": report,
            "stage": "测试完成",
            "context": state.get("context", "") + f"\n\n【测试报告{round_info}】\n{report}",
            "timestamps": timestamps,
        }

    async def _node_dev_fix_bug(self, state: ProjectState) -> dict:
        """Dev 修 Bug"""
        t0 = time.time()
        bug_round = state.get("bug_fix_round", 0) + 1
        await self._send("developer",
            f"🐛 <b>Bug 修复（第 {bug_round} 轮）</b>\n程序员正在修复...")

        dev = self.agents["developer"]
        result = await dev.run(
            f"测试发现 Bug，请修复。\n\n"
            f"工作目录: {state['project_dir']}\n\n"
            f"【测试报告】:\n{state.get('test_report', '')[:3000]}\n\n"
            f"要求：查看代码 → 修复 Bug → 运行验证 → Git commit",
            context=state.get("context", ""),
        )

        from src.telegram.formatter import format_agent_response
        await self._send("developer", format_agent_response("程序员", result))

        elapsed = round(time.time() - t0, 1)
        timestamps = dict(state.get("timestamps", {}))
        timestamps[f"Bug修复第{bug_round}轮"] = elapsed

        return {
            "dev_result": result,
            "bug_fix_round": bug_round,
            "stage": f"Bug修复第{bug_round}轮完成",
            "context": state.get("context", "") + f"\n\n【Bug修复】\n{result}",
            "timestamps": timestamps,
        }

    async def _node_escalate(self, state: ProjectState) -> dict:
        """超过最大 Bug 修复轮数，请负责人决定"""
        await self._send("product_manager",
            f"⚠️ 已达最大修复轮数({MAX_BUG_FIX_ROUNDS})，请负责人决定\n"
            f"/approve 继续修复 | /reject 终止项目")

        decision = interrupt({"type": "escalation", "content": "Bug 修复超限"})

        log.info("负责人决定: %s", decision)
        return {"stage": f"负责人决定: {decision}"}

    async def _node_deliver(self, state: ProjectState) -> dict:
        """交付报告"""
        timestamps = state.get("timestamps", {})
        time_report = "\n".join(f"  • {k}: {v}s" for k, v in timestamps.items())
        total = sum(timestamps.values())

        # 文件树
        project_dir = Path(state["project_dir"])
        file_tree = self._get_file_tree(project_dir)

        # Token 统计
        token_lines = []
        for role, agent in self.agents.items():
            usage = agent.get_token_usage()
            if usage["total_tokens"] > 0:
                token_lines.append(f"  • {agent.role_cn}: {usage['total_tokens']} tokens")
        token_report = "\n".join(token_lines) if token_lines else "  无数据"

        report = (
            f"🎉 <b>项目完成！</b> {self._progress_bar(4, 4)} ✅\n\n"
            f"📋 {state['description']}\n"
            f"📁 {state['project_dir']}\n\n"
            f"🗂 <b>文件结构：</b>\n<pre>{file_tree}</pre>\n\n"
            f"⏱ <b>耗时：</b>\n{time_report}\n  Total: {round(total, 1)}s\n\n"
            f"📊 <b>Token 用量：</b>\n{token_report}"
        )
        await self._send("product_manager", report)

        # 发送流程图
        await self._send_pipeline_graph(state)

        return {"stage": "交付完成", "result": "success"}

    # ============ 条件边 ============

    def _route_review(self, state: ProjectState) -> str:
        """审核结果路由"""
        stage = state.get("stage", "")
        if "approved" in stage.lower() or "通过" in stage:
            return "dev_implement"
        return "pm_analyze"  # 拒绝 → 重做 PRD

    def _route_test(self, state: ProjectState) -> str:
        """测试结果路由"""
        report = state.get("test_report", "")
        if "测试通过" in report and "不通过" not in report:
            return "deliver"
        bug_round = state.get("bug_fix_round", 0)
        if bug_round >= MAX_BUG_FIX_ROUNDS:
            return "escalate"
        return "dev_fix_bug"

    def _route_escalate(self, state: ProjectState) -> str:
        """负责人介入路由"""
        stage = state.get("stage", "")
        if "approved" in stage.lower() or "通过" in stage or "继续" in stage:
            return "dev_fix_bug"
        return "__end__"

    # ============ 构建图 ============

    def _build_graph(self):
        """构建 LangGraph 状态图"""
        builder = StateGraph(ProjectState)

        # 添加节点
        builder.add_node("pm_analyze", self._node_pm_analyze)
        builder.add_node("owner_review", self._node_owner_review)
        builder.add_node("dev_implement", self._node_dev_implement)
        builder.add_node("qa_test", self._node_qa_test)
        builder.add_node("dev_fix_bug", self._node_dev_fix_bug)
        builder.add_node("escalate", self._node_escalate)
        builder.add_node("deliver", self._node_deliver)

        # 添加边
        builder.add_edge(START, "pm_analyze")
        builder.add_edge("pm_analyze", "owner_review")
        builder.add_conditional_edges("owner_review", self._route_review)
        builder.add_edge("dev_implement", "qa_test")
        builder.add_conditional_edges("qa_test", self._route_test)
        builder.add_edge("dev_fix_bug", "qa_test")
        builder.add_conditional_edges("escalate", self._route_escalate)
        builder.add_edge("deliver", END)

        self.graph = builder.compile(checkpointer=self.checkpointer)
        log.info("LangGraph Pipeline 已构建")

    # ============ 公开方法 ============

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

    async def start_project(self, description: str):
        """启动新项目"""
        # 创建项目目录
        dir_name = self._make_project_dir_name(description)
        project_dir = self.workspace / dir_name
        project_dir.mkdir(parents=True, exist_ok=True)

        # 清空上下文
        if self.bot_manager:
            self.bot_manager.reset_context()
        for agent in self.agents.values():
            agent.update_workspace(project_dir)
            agent.conversation_history.clear()

        # 生成 thread_id
        self._thread_counter += 1
        self._current_thread_id = f"project-{self._thread_counter}"

        log.info("项目启动: %s -> %s (thread=%s)",
                 description, project_dir, self._current_thread_id)

        await self._send("product_manager",
            f"🚀 <b>项目已创建</b>\n"
            f"📋 {description}\n"
            f"📁 <code>{project_dir}</code>")

        # 初始状态
        initial_state: ProjectState = {
            "description": description,
            "project_dir": str(project_dir),
            "prd": "",
            "dev_result": "",
            "test_report": "",
            "bug_fix_round": 0,
            "stage": "开始",
            "context": f"项目需求: {description}",
            "timestamps": {},
            "result": "",
        }

        config = {"configurable": {"thread_id": self._current_thread_id}}

        try:
            # 运行图直到完成或 interrupt
            async for event in self.graph.astream(initial_state, config):
                log.info("Graph event: %s", list(event.keys()))
        except Exception:
            log.exception("Pipeline 异常")
            await self._send("product_manager", "❌ Pipeline 异常中断，请查看日志")

    async def resume(self, decision: str):
        """恢复被 interrupt 阻塞的图执行"""
        if not self._current_thread_id:
            log.warning("没有活跃的 Pipeline")
            return

        config = {"configurable": {"thread_id": self._current_thread_id}}

        try:
            async for event in self.graph.astream(
                Command(resume=decision), config
            ):
                log.info("Graph resume event: %s", list(event.keys()))
        except Exception:
            log.exception("Pipeline resume 异常")
            await self._send("product_manager", "❌ Pipeline 恢复异常，请查看日志")

    async def _send_pipeline_graph(self, state: ProjectState):
        """发送 Pipeline 流程图到群聊"""
        try:
            # 生成 mermaid 文本
            mermaid_text = self.graph.get_graph().draw_mermaid()

            # 保存为文件
            project_dir = Path(state["project_dir"])
            docs_dir = project_dir / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "pipeline.mmd").write_text(mermaid_text, encoding="utf-8")

            # 尝试生成 PNG
            try:
                png_bytes = self.graph.get_graph().draw_mermaid_png()
                png_path = docs_dir / "pipeline.png"
                png_path.write_bytes(png_bytes)
                # 发送图片到群聊
                bot = self.bot_manager.bots.get("product_manager")
                if bot:
                    await bot.send_photo(
                        chat_id=self.bot_manager.group_chat_id,
                        photo=png_bytes,
                        caption="📊 Pipeline 流程图"
                    )
                    log.info("流程图已发送")
                    return
            except Exception:
                log.warning("PNG 生成失败，发送 Mermaid 文本")

            # 降级：发送 mermaid 文本
            await self._send("product_manager",
                f"📊 <b>Pipeline 流程图</b>\n\n<pre>{mermaid_text}</pre>")

        except Exception:
            log.exception("发送流程图失败")

    def get_status(self) -> str:
        if not self._current_thread_id:
            return "暂无进行中的项目"

        config = {"configurable": {"thread_id": self._current_thread_id}}
        try:
            snapshot = self.graph.get_state(config)
            state = snapshot.values
            return (
                f"项目: {state.get('description', '?')}\n"
                f"目录: {state.get('project_dir', '?')}\n"
                f"阶段: {state.get('stage', '?')}"
            )
        except Exception:
            return "状态查询失败"
