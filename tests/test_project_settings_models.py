# tests/test_project_settings_models.py
"""A setting absent from ProjectSettings is discarded in both directions.

Pydantic v2 defaults to extra='ignore', so an undeclared field is dropped inbound;
update_project_settings writes model_dump() as the whole config_json, deleting anything
previously stored; and response_model=ProjectSettings strips it outbound. The press budget
shipped dead this way with a passing UI test that mocked the API client.
"""
import pytest

_MODEL_FIELDS = (
    "anthropic_fast_model",
    "anthropic_deep_model",
    "local_fast_model",
    "local_fast_url",
    "local_deep_model",
    "local_deep_url",
)


def test_every_model_setting_is_declared():
    from api.models import ProjectSettings
    missing = [f for f in _MODEL_FIELDS if f not in ProjectSettings.model_fields]
    assert not missing, f"undeclared settings are silently discarded: {missing}"


@pytest.mark.asyncio
async def test_the_model_settings_survive_a_round_trip(client):
    """Driven through the real endpoints, not a mocked client."""
    await client.post("/projects", json={
        "client_slug": "modelsettings", "llm_mode": "standard", "sector": "test",
        "stakeholder_groups": [], "value_stream_labels": [], "crews_enabled": [],
        "review_gates": True, "slack_channel": "",
    })
    r = await client.get("/projects/modelsettings/settings")
    body = r.json()
    body["local_deep_model"] = "qwen27b:reasoning"
    body["local_deep_url"] = "http://localhost:11500/v1"
    assert (await client.patch("/projects/modelsettings/settings", json=body)).status_code == 200

    back = (await client.get("/projects/modelsettings/settings")).json()
    assert back["local_deep_model"] == "qwen27b:reasoning"
    assert back["local_deep_url"] == "http://localhost:11500/v1"
