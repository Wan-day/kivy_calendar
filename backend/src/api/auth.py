"""API key authentication dependency for the backend API."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header

from api.deps import get_settings_dep
from api.errors import ApiError
from core.config import Settings
from core.errors import ErrorCode

BEARER_SCHEME = "bearer"


def verify_api_key(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    settings: Settings = Depends(get_settings_dep),
) -> None:
    """Require a bearer token for protected endpoints.

    The token is compared in constant time against the configured backend API
    token.  Authentication failures are returned as structured
    :class:`~api.errors.ApiError` responses.
    """
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != BEARER_SCHEME or not token:
        raise ApiError(401, ErrorCode.AUTH_ERROR, "missing bearer token")
    if not secrets.compare_digest(token, settings.backend_api_token):
        raise ApiError(401, ErrorCode.AUTH_ERROR, "invalid bearer token")
