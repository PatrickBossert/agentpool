# tests/test_config.py
import pytest
from pathlib import Path


def test_settings_loads_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("JWT_SECRET", "s3cr3t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("LITELLM_PROXY_URL", "http://localhost:4000")
    monkeypatch.setenv("LLAMACPP_BASE_URL", "http://localhost:10000")
    monkeypatch.setenv("CHROMA_HOST", "localhost")
    monkeypatch.setenv("CHROMA_PORT", "8002")

    # Re-import to pick up monkeypatched env
    import importlib
    import api.config as cfg_module
    importlib.reload(cfg_module)

    assert cfg_module.settings.jwt_secret == "s3cr3t"
    assert cfg_module.settings.anthropic_api_key == "sk-test"


def test_load_project_config(tmp_path):
    from api.config import load_project_config

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
client_slug: test-co
llm_mode: standard
sector: finance
stakeholder_groups: [Finance, Operations]
value_stream_labels: [Revenue, Cost]
roadmap_time_axis: quarters
crews_enabled: [discovery, value_design]
review_gates: true
slack_channel: "#test"
""")
    config = load_project_config(tmp_path)
    assert config["client_slug"] == "test-co"
    assert config["llm_mode"] == "standard"
    assert "discovery" in config["crews_enabled"]


def test_load_project_config_missing_raises(tmp_path):
    from api.config import load_project_config
    with pytest.raises(FileNotFoundError):
        load_project_config(tmp_path / "nonexistent")
