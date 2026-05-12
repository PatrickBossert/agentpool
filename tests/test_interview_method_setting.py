"""Tests for interview_method ProjectSettings field."""
import pytest
from pydantic import ValidationError


def test_interview_method_default_is_none():
    from api.models import ProjectSettings
    s = ProjectSettings(sector="rail")
    assert s.interview_method == "none"


def test_interview_method_accepts_agent():
    from api.models import ProjectSettings
    s = ProjectSettings(sector="rail", interview_method="agent")
    assert s.interview_method == "agent"


def test_interview_method_accepts_listenlabs():
    from api.models import ProjectSettings
    s = ProjectSettings(sector="rail", interview_method="listenlabs")
    assert s.interview_method == "listenlabs"


def test_interview_method_rejects_invalid():
    from api.models import ProjectSettings
    with pytest.raises(ValidationError):
        ProjectSettings(sector="rail", interview_method="magic")
