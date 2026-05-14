"""Configuration validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from allegro_mcp.config import Environment, Settings


def _base_kwargs(tmp_path: Path) -> dict[str, object]:
    return {
        "client_id": SecretStr("id"),
        "client_secret": SecretStr("secret"),
        "user_agent": "allegro-mcp/0.1 (you@example.com)",
        "token_db_path": tmp_path / "tokens.db",
        "history_db_path": tmp_path / "history.db",
    }


def test_production_urls_default(tmp_path: Path) -> None:
    settings = Settings(**_base_kwargs(tmp_path))  # type: ignore[arg-type]
    assert settings.api_base_url == "https://api.allegro.pl"
    assert settings.auth_base_url == "https://allegro.pl"
    assert settings.token_endpoint == "https://allegro.pl/auth/oauth/token"
    assert settings.device_authorization_endpoint == "https://allegro.pl/auth/oauth/device"


def test_sandbox_urls(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[arg-type]
        **_base_kwargs(tmp_path),
        environment=Environment.SANDBOX,
    )
    assert settings.api_base_url == "https://api.allegro.pl.allegrosandbox.pl"
    assert settings.auth_base_url == "https://allegro.pl.allegrosandbox.pl"


def test_module_list_parses_comma_separated(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[arg-type]
        **_base_kwargs(tmp_path),
        mcp_modules="search, deep_search ,offer",
    )
    assert settings.module_list == ("search", "deep_search", "offer")


def test_module_list_default_includes_all_buy_side(tmp_path: Path) -> None:
    settings = Settings(**_base_kwargs(tmp_path))  # type: ignore[arg-type]
    for name in (
        "search",
        "deep_search",
        "offer",
        "product",
        "category",
        "seller",
        "purchases",
        "messaging",
        "bidding",
        "ratings",
        "disputes",
        "compare",
        "intel",
        "purchase_handoff",
    ):
        assert name in settings.module_list


def test_blank_user_agent_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[arg-type]
            **{**_base_kwargs(tmp_path), "user_agent": "   "},
        )


def test_rate_limit_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[arg-type]
            **_base_kwargs(tmp_path),
            rate_limit_rps=0,
        )
