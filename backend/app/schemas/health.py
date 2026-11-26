"""Pydantic schemas for the Day 1 endpoints."""

from typing import Literal

from pydantic import BaseModel


class RootResponse(BaseModel):
    name: str
    version: str
    environment: str
    docs_url: str
    health_url: str


class HealthResponse(BaseModel):
    """Liveness: the API process is running. Dependencies are checked separately."""

    status: Literal["ok"]
    service: str
    version: str
    environment: str


class ServiceHealth(BaseModel):
    """Readiness of one dependency, based on a REAL connection attempt."""

    status: Literal["ok", "unavailable"]
    service: Literal["database", "redis"]
    detail: str | None = None


class ErrorResponse(BaseModel):
    detail: str
