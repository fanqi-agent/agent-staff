# Agent Staff Skills

Skills 是可插拔的知识包，为 Agent 提供特定领域的专业知识和最佳实践。

## 安装位置

下载的 Skills 放到以下任意位置即可自动识别：

| 优先级 | 路径 | 说明 |
|--------|------|------|
| 1 | `workspace/<项目>/skills/` | 项目专属 |
| 2 | `agent-staff/skills/` | **← 框架级（推荐）** |
| 3 | `~/.gemini/antigravity/skills/` | 全局共享 |

## Skill 结构

每个 Skill 是一个文件夹，必须包含 `SKILL.md`：

```
skills/
└── my-skill/
    ├── SKILL.md          # 必须：YAML frontmatter + 内容
    ├── scripts/          # 可选：辅助脚本
    ├── templates/        # 可选：代码模板
    └── data/             # 可选：数据文件
```

## SKILL.md 格式

```markdown
---
name: my-skill
description: "技能描述，一句话说明用途"
---

# 技能标题

详细内容：规范、模板、最佳实践...
```

## Agent 使用方式

Agent 通过工具自动调用：
1. `list_skills` — 查看可用 Skills
2. `read_skill("flask-web-app")` — 读取指定 Skill
