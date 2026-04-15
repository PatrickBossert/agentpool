# tests/test_litellm_routing.py
"""
Tests that LiteLLM config resolves the correct model for each llm_mode.
Does NOT call external APIs — validates config structure only.
"""
import pytest
import yaml
from pathlib import Path


def load_litellm_config() -> dict:
    path = Path(__file__).parent.parent / "litellm_config.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def test_config_has_required_model_aliases():
    config = load_litellm_config()
    model_names = [m["model_name"] for m in config["model_list"]]
    assert "claude-opus" in model_names
    assert "claude-sonnet" in model_names
    assert "claude-haiku" in model_names
    assert "local-qwen3" in model_names


def test_sensitive_alias_points_to_llamacpp():
    config = load_litellm_config()
    local_model = next(m for m in config["model_list"] if m["model_name"] == "local-qwen3")
    litellm_params = local_model["litellm_params"]
    api_base = str(litellm_params.get("api_base", ""))
    assert "localhost:10000" in api_base


def test_all_claude_models_have_api_key_env_var():
    config = load_litellm_config()
    claude_models = [m for m in config["model_list"] if m["model_name"].startswith("claude-")]
    for m in claude_models:
        api_key = m["litellm_params"].get("api_key", "")
        assert "ANTHROPIC_API_KEY" in str(api_key), f"{m['model_name']} missing ANTHROPIC_API_KEY ref"
