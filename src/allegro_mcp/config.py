"""Environment-driven configuration via pydantic-settings."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Allegro environment selector."""

    PRODUCTION = "production"
    SANDBOX = "sandbox"


_DEFAULT_MODULES = (
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
)


class Settings(BaseSettings):
    """Server configuration. All fields read from environment or `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ALLEGRO_",
        case_sensitive=False,
        extra="ignore",
    )

    client_id: SecretStr
    client_secret: SecretStr
    user_agent: str
    environment: Environment = Environment.PRODUCTION

    token_db_path: Path = Path("~/.allegro-mcp/tokens.db").expanduser()
    history_db_path: Path = Path("~/.allegro-mcp/history.db").expanduser()

    mcp_port: int = 8765
    mcp_bind: str = "127.0.0.1"
    mcp_modules: str = ",".join(_DEFAULT_MODULES)

    default_postal_code: str | None = None
    rate_limit_rps: Annotated[float, Field(gt=0)] = 60.0
    rate_limit_burst: Annotated[int, Field(gt=0)] = 100

    internal_secret: SecretStr | None = None

    @field_validator("token_db_path", "history_db_path", mode="before")
    @classmethod
    def _expand_path(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value).expanduser()
        return value

    @field_validator("user_agent")
    @classmethod
    def _validate_user_agent(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("ALLEGRO_USER_AGENT must be set; Allegro REST API terms require it")
        return value.strip()

    @property
    def api_base_url(self) -> str:
        """REST API base URL for the selected environment."""
        if self.environment is Environment.SANDBOX:
            return "https://api.allegro.pl.allegrosandbox.pl"
        return "https://api.allegro.pl"

    @property
    def auth_base_url(self) -> str:
        """OAuth endpoint base URL for the selected environment."""
        if self.environment is Environment.SANDBOX:
            return "https://allegro.pl.allegrosandbox.pl"
        return "https://allegro.pl"

    @property
    def device_authorization_endpoint(self) -> str:
        return f"{self.auth_base_url}/auth/oauth/device"

    @property
    def token_endpoint(self) -> str:
        return f"{self.auth_base_url}/auth/oauth/token"

    @property
    def revoke_endpoint(self) -> str:
        return f"{self.auth_base_url}/auth/oauth/revoke"

    @property
    def module_list(self) -> tuple[str, ...]:
        """Parsed module list from `mcp_modules`."""
        return tuple(name.strip() for name in self.mcp_modules.split(",") if name.strip())


def load_settings() -> Settings:
    """Load and validate settings. Raises if required env vars are missing."""
    return Settings()  # type: ignore[call-arg]
