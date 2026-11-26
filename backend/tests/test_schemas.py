"""Pydantic validation of the response schemas."""

import pytest
from pydantic import ValidationError

from app.schemas.health import ErrorResponse, HealthResponse, RootResponse, ServiceHealth


def test_service_health_accepts_valid_values():
    assert ServiceHealth(status="ok", service="database").detail is None
    assert ServiceHealth(status="unavailable", service="redis", detail="down").status == "unavailable"


@pytest.mark.parametrize("bad", [
    {"status": "maybe", "service": "database"},
    {"status": "ok", "service": "kafka"},
    {"service": "database"},
])
def test_service_health_rejects_invalid_values(bad):
    with pytest.raises(ValidationError):
        ServiceHealth(**bad)


def test_health_response_only_allows_ok_status():
    HealthResponse(status="ok", service="s", version="1", environment="test")
    with pytest.raises(ValidationError):
        HealthResponse(status="degraded", service="s", version="1", environment="test")


def test_root_and_error_schemas_require_fields():
    with pytest.raises(ValidationError):
        RootResponse(name="x")
    with pytest.raises(ValidationError):
        ErrorResponse()
