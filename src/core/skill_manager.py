"""Skills 管理器 — 发现和加载项目级/全局 Skills

Skills 目录搜索顺序：
1. 项目级: <project>/skills/
2. 框架级: <agent-staff>/skills/
3. 全局:   ~/.gemini/antigravity/skills/
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)


class SkillManager:
    """管理 Skills 的发现和读取"""

    def __init__(self, search_paths: list[Path] | None = None):
        self.search_paths: list[Path] = search_paths or []
        self._cache: dict[str, dict] = {}  # name -> {path, description, content}

    def add_search_path(self, path: Path):
        """添加 Skills 搜索路径"""
        if path not in self.search_paths:
            self.search_paths.append(path)

    def discover(self) -> dict[str, dict]:
        """扫描所有搜索路径，发现可用 Skills"""
        self._cache.clear()
        for base in self.search_paths:
            if not base.exists():
                continue
            for skill_dir in sorted(base.iterdir()):
                if not skill_dir.is_dir():
                    continue
                skill_file = skill_dir / "SKILL.md"
                if not skill_file.exists():
                    continue
                name = skill_dir.name
                if name in self._cache:
                    continue  # 优先级：先找到的优先
                desc = self._parse_description(skill_file)
                self._cache[name] = {
                    "name": name,
                    "path": str(skill_dir),
                    "description": desc,
                }
        log.info("发现 %d 个 Skills: %s", len(self._cache), list(self._cache.keys()))
        return self._cache

    def list_skills(self) -> str:
        """列出所有可用 Skills（给 Agent 用的文本格式）"""
        skills = self.discover()
        if not skills:
            return "当前没有可用的 Skills。"
        lines = ["可用 Skills：", ""]
        for name, info in skills.items():
            lines.append(f"• {name}: {info['description']}")
            lines.append(f"  路径: {info['path']}")
        return "\n".join(lines)

    def read_skill(self, name: str) -> str:
        """读取指定 Skill 的完整内容"""
        if not self._cache:
            self.discover()

        info = self._cache.get(name)
        if not info:
            return f"Skill '{name}' 不存在。可用: {', '.join(self._cache.keys())}"

        skill_file = Path(info["path"]) / "SKILL.md"
        try:
            content = skill_file.read_text(encoding="utf-8")
            # 检查是否有附属脚本/数据
            extras = []
            for sub in ["scripts", "data", "templates", "examples"]:
                sub_dir = Path(info["path"]) / sub
                if sub_dir.exists():
                    files = [f.name for f in sub_dir.iterdir() if f.is_file()]
                    extras.append(f"  {sub}/: {', '.join(files)}")

            result = content
            if extras:
                result += f"\n\n---\n附属资源：\n" + "\n".join(extras)
            return result
        except Exception as e:
            return f"读取 Skill '{name}' 失败: {e}"

    def _parse_description(self, skill_file: Path) -> str:
        """从 SKILL.md 的 YAML frontmatter 提取 description"""
        try:
            text = skill_file.read_text(encoding="utf-8")
            if not text.startswith("---"):
                # 没有 frontmatter，取第一行非空内容
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        return line[:200]
                return "(无描述)"

            # 解析 YAML frontmatter
            end = text.index("---", 3)
            frontmatter = text[3:end].strip()
            for line in frontmatter.splitlines():
                if line.startswith("description:"):
                    desc = line[len("description:"):].strip().strip('"').strip("'")
                    return desc[:200]
            return "(无描述)"
        except Exception:
            return "(无描述)"
