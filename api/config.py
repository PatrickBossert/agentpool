# api/config.py
from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


class Settings(BaseSettings):
    anthropic_api_key: str
    litellm_proxy_url: str = "http://localhost:4000"
    chroma_host: str = "localhost"
    chroma_port: int = 8002
    chroma_api_key: Optional[str] = None
    chroma_tenant: str = "default_tenant"
    chroma_database: str = "default_database"
    database_dir: str = "./data"
    data_dir: str = "data"
    projects_dir: str = "./projects"
    jwt_secret: str
    admin_username: str
    admin_password: str
    tavily_api_key: Optional[str] = None
    public_url: str = "http://localhost:3000"
    elevenlabs_api_key: str = ""
    deepgram_api_key: str = ""
    resend_api_key: str = ""
    # Platform mail (the welcome email) sends from this entire. A project's mail takes only
    # the *domain* from it and mints a role address on that domain from the correspondent's
    # agent id - see api/services/outbound_mail.py. There is deliberately no second setting
    # for the domain: one that disagreed with this would half-move a deployment.
    from_email: str = "TaskReimagination.ai <noreply@taskreimagination.ai>"
    # Where a project holding mail (`dev_mode`) sends it instead. One address, and every
    # audience's mail arrives at it - see api/services/outbound_mail.py.
    #
    # This was a hardcoded constant in api/services/pam_report_job.py, which is one
    # person's address in source, in the module that happened to need it first. It is
    # still that person's address by default, because changing where held mail goes is
    # not this change's business - but it is now overridable per deployment, and the
    # default is one line to edit rather than an import other services reach for.
    #
    # Sub-project D's test mode replaces this with the project's own administrators. That
    # is a larger change than it looks: a redirect resolving to administrators must refuse
    # to send when a project has none, never fall back to the intended recipients, because
    # this is the one setting whose failure must not be open.
    dev_mode_address: str = "Patrick@FutureEdge.consulting"
    # The one organisation every engagement belongs to. Not one organisation per client:
    # this is a project-based application that happens to hold organisation entities, so the
    # organisation is the consultancy and an org_admin appointed in it reaches every
    # engagement. init_system_db seeds this row, and project creation registers against it
    # whenever the creator's own token carries no org_id - which is every sysadmin.
    #
    # Configurable so a fork of this deployment is not obliged to be Future Edge, and looked
    # up by slug rather than by "the only row" so that a second organisation appearing later
    # cannot quietly change which one new projects are registered to.
    home_org_slug: str = "future-edge"
    home_org_name: str = "Future Edge Consulting"

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
