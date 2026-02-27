"""Skills 工具 — 让 Agent 能够发现和使用 Skills"""

from src.tools.base import Tool
from src.core.skill_manager import SkillManager


class ListSkillsTool(Tool):
    """列出所有可用的 Skills"""

    name = "list_skills"
    description = "列出所有可用的 Skills（技能包）。Skills 包含专业知识和最佳实践，可以帮助你更好地完成任务。"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, skill_manager: SkillManager):
        self.skill_manager = skill_manager

    async def execute(self, **kwargs) -> str:
        return self.skill_manager.list_skills()


class ReadSkillTool(Tool):
    """读取指定 Skill 的完整内容"""

    name = "read_skill"
    description = "读取指定 Skill 的完整内容。先用 list_skills 查看有哪些，再用此工具读取需要的 Skill。"
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill 名称，如 'ui-ux-pro-max'",
            },
        },
        "required": ["name"],
    }

    def __init__(self, skill_manager: SkillManager):
        self.skill_manager = skill_manager

    async def execute(self, name: str = "", **kwargs) -> str:
        if not name:
            return "请指定 Skill 名称。" + self.skill_manager.list_skills()
        return self.skill_manager.read_skill(name)
