"""Pickup-point models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PickupPoint(BaseModel):
    """A parcel pickup or locker point."""

    point_id: str
    provider: str
    name: str
    address: str
    postal_code: str
    city: str
    country_code: str = "PL"
    latitude: float | None = None
    longitude: float | None = None
    opening_hours: list[str] = Field(default_factory=list)
    distance_km: float | None = None
