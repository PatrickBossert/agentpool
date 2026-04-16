# api/config.py
from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


class Settings(BaseSettings):
    anthropic_api_key: str
    litellm_proxy_url: str = "http://localhost:4000"
    llamacpp_base_url: str = "http://localhost:10000"
    chroma_host: str = "localhost"
    chroma_port: int = 8002
    chroma_api_key: Optional[str] = None
    chroma_tenant: str = "default_tenant"
    chroma_database: str = "default_database"
    database_dir: str = "./data"
    projects_dir: str = "./projects"
    jwt_secret: str
    admin_username: str = "admin"
    admin_password: str = "changeme"
    tavily_api_key: Optional[str] = None
    n8n_webhook_url: Optional[str] = None
    frontend_url: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_project_config(project_dir: Path) -> dict:
    config_path = Path(project_dir) / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No config.yaml found in {project_dir}")
    with open(config_path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"config.yaml in {project_dir} is empty or not a valid YAML mapping")
    return data
