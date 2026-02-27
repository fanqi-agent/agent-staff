"""代码执行工具 — 本地 subprocess"""

import asyncio
import logging
import tempfile
from pathlib import Path

from src.tools.base import Tool

log = logging.getLogger(__name__)

# 允许执行的命令白名单前缀
ALLOWED_COMMANDS = ["python", "node", "npm", "pip", "pytest", "git", "cat", "ls", "dir"]


class CodeExecutorTool(Tool):
    name = "execute_command"
    description = (
        "在项目工作区中执行 shell 命令。可用于运行代码、安装依赖、执行测试等。"
        "命令会在工作区目录下执行。超时 60 秒。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令",
            }
        },
        "required": ["command"],
    }

    def __init__(self, workspace: Path, timeout: int = 60):
        self.workspace = workspace
        self.timeout = timeout

    async def execute(self, **kwargs) -> str:
        command = kwargs["command"]
        log.info("Executing: %s (in %s)", command, self.workspace)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )

            result_parts = []
            if stdout:
                out = stdout.decode("utf-8", errors="replace").strip()
                if len(out) > 5000:
                    out = out[:5000] + "\n... (truncated)"
                result_parts.append(f"📤 STDOUT:\n{out}")
            if stderr:
                err = stderr.decode("utf-8", errors="replace").strip()
                if len(err) > 3000:
                    err = err[:3000] + "\n... (truncated)"
                result_parts.append(f"⚠️ STDERR:\n{err}")

            exit_code = proc.returncode
            result_parts.insert(0, f"退出码: {exit_code}")

            return "\n\n".join(result_parts) if result_parts else "（无输出）"

        except asyncio.TimeoutError:
            return f"❌ 命令超时（>{self.timeout}秒）"
        except Exception as e:
            return f"❌ 执行失败：{e}"


class WriteAndRunTool(Tool):
    name = "write_and_run"
    description = (
        "写入代码到文件并立即执行。适合快速测试代码片段。"
        "自动检测语言（.py -> python, .js -> node）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "文件名（如 test.py, app.js）",
            },
            "code": {
                "type": "string",
                "description": "代码内容",
            },
        },
        "required": ["filename", "code"],
    }

    def __init__(self, workspace: Path, timeout: int = 60):
        self.workspace = workspace
        self.timeout = timeout

    async def execute(self, **kwargs) -> str:
        filename = kwargs["filename"]
        code = kwargs["code"]

        filepath = self.workspace / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(code, encoding="utf-8")

        # 根据扩展名选择运行命令
        ext = filepath.suffix.lower()
        runners = {".py": "python", ".js": "node", ".ts": "npx ts-node"}
        runner = runners.get(ext)
        if not runner:
            return f"✅ 文件已写入 {filename}，但不知道如何运行 {ext} 文件"

        executor = CodeExecutorTool(self.workspace, self.timeout)
        run_result = await executor.execute(command=f"{runner} {filename}")
        return f"✅ 文件已写入 {filename}\n\n{run_result}"
