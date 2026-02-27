"""全局配置 — 从 .env 加载，支持 Agent 独立模型配置"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    bot_token_pm: str
    bot_token_dev: str
    bot_token_qa: str
    group_chat_id: int
    owner_user_id: int

    # 代理
    proxy_url: str = ""

    # LLM 全局默认
    llm_api_key: str
    llm_base_url: str = ""
    llm_model: str = ""

    # PM 独立配置（不填则用全局）
    pm_llm_api_key: str = ""
    pm_llm_base_url: str = ""
    pm_llm_model: str = ""

    # Dev 独立配置
    dev_llm_api_key: str = ""
    dev_llm_base_url: str = ""
    dev_llm_model: str = ""

    # QA 独立配置
    qa_llm_api_key: str = ""
    qa_llm_base_url: str = ""
    qa_llm_model: str = ""

    # Workspace
    workspace_dir: Path = Path("./workspace")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def get_llm_config(self, role: str) -> dict:
        """获取指定角色的 LLM 配置，优先用独立配置，否则回退全局"""
        prefix_map = {
            "product_manager": "pm",
            "developer": "dev",
            "tester": "qa",
        }
        prefix = prefix_map.get(role, "")

        if prefix:
            key = getattr(self, f"{prefix}_llm_api_key", "") or self.llm_api_key
            url = getattr(self, f"{prefix}_llm_base_url", "") or self.llm_base_url
            model = getattr(self, f"{prefix}_llm_model", "") or self.llm_model
        else:
            key, url, model = self.llm_api_key, self.llm_base_url, self.llm_model

        return {"api_key": key, "base_url": url, "model": model}


settings = Settings()  # type: ignore[call-arg]
