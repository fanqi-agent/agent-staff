"""Git 操作工具"""

import logging
from pathlib import Path

from git import Repo, InvalidGitRepositoryError

from src.tools.base import Tool

log = logging.getLogger(__name__)


class GitTool(Tool):
    name = "git"
    description = (
        "执行 Git 操作。支持: init, status, add, commit, log, diff。"
        "在项目工作区中操作。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["init", "status", "add", "commit", "log", "diff"],
                "description": "Git 操作类型",
            },
            "message": {
                "type": "string",
                "description": "commit 消息（仅 commit 操作需要）",
            },
            "files": {
                "type": "string",
                "description": "文件路径（add 操作使用，默认 '.'）",
                "default": ".",
            },
        },
        "required": ["action"],
    }

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def _get_repo(self) -> Repo:
        try:
            return Repo(self.workspace)
        except InvalidGitRepositoryError:
            return Repo.init(self.workspace)

    async def execute(self, **kwargs) -> str:
        action = kwargs["action"]
        try:
            if action == "init":
                repo = Repo.init(self.workspace)
                return "✅ Git 仓库已初始化"

            repo = self._get_repo()

            if action == "status":
                status = repo.git.status()
                return f"📋 Git Status:\n{status}"

            elif action == "add":
                files = kwargs.get("files", ".")
                repo.git.add(files)
                return f"✅ 已暂存: {files}"

            elif action == "commit":
                message = kwargs.get("message", "auto commit")
                repo.git.add(".")
                repo.index.commit(message)
                return f"✅ 已提交: {message}"

            elif action == "log":
                logs = repo.git.log("--oneline", "-10")
                return f"📋 最近提交:\n{logs}" if logs else "暂无提交记录"

            elif action == "diff":
                diff = repo.git.diff()
                if not diff:
                    diff = repo.git.diff("--cached")
                if len(diff) > 5000:
                    diff = diff[:5000] + "\n... (truncated)"
                return f"📋 Diff:\n{diff}" if diff else "无变更"

            else:
                return f"未知操作: {action}"

        except Exception as e:
            return f"❌ Git 操作失败: {e}"
