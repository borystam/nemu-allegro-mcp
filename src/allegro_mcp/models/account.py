"""Account models."""

from __future__ import annotations

from pydantic import BaseModel


class Account(BaseModel):
    """The authenticated user's account profile (`/me`)."""

    account_id: str
    login: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    company_name: str | None = None
    is_business: bool | None = None
    country_code: str | None = None
