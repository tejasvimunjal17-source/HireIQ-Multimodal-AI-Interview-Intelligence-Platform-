"""Day 6: REPORT_ACCESS_TOKEN setting (needs pydantic-settings)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE = {"DATABASE_URL": "sqlite://", "SECRET_KEY": "x" * 48}


def make(monkeypatch, **env):
    monkeypatch.delenv("REPORT_ACCESS_TOKEN", raising=False)
    for k, v in {**BASE, **env}.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)


def test_token_defaults_to_none_and_blank_means_disabled(monkeypatch):
    assert make(monkeypatch).report_access_token is None
    assert make(monkeypatch, REPORT_ACCESS_TOKEN="").report_access_token is None


def test_short_token_is_rejected(monkeypatch):
    with pytest.raises(ValidationError):
        make(monkeypatch, REPORT_ACCESS_TOKEN="short")


def test_token_is_secret_and_never_in_repr(monkeypatch):
    s = make(monkeypatch, REPORT_ACCESS_TOKEN="a-long-enough-token-1234")
    assert s.report_access_token.get_secret_value() == "a-long-enough-token-1234"
    assert "a-long-enough-token-1234" not in repr(s) and "a-long-enough-token-1234" not in str(s)
