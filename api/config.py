# api/config.py
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


class Settings(BaseSettings):
    anthropic_api_key: str
    litellm_proxy_url: str = "http://localhost:4000"
    llamacpp_base_url: str = "http://localhost:10000"
    chroma_host: str = "localhost"
    chroma_port: int = 8002
    database_dir: str = "/Users/pboagents/Documents/agentpool1/data"
    projects_dir: str = "/Users/pboagents/Documents/agentpool1/projects"
    jwt_secret: str

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()


def load_project_config(project_dir: Path) -> dict:
    config_path = Path(project_dir) / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No config.yaml found in {project_dir}")
    with open(config_path) as f:
        return yaml.safe_load(f)
