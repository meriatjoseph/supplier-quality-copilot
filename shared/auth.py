"""
Shared static API-key auth dependency.

NOTE: this is a simplified stand-in for real service-to-service auth
(e.g. mTLS, OAuth2 client-credentials). A single shared secret checked via
a static header is NOT production-grade security -- it is used here only
to demonstrate that every inter-agent call is authenticated at all, per
the take-home scope.
"""
import os

from fastapi import Header, HTTPException, status

API_KEY = os.environ.get("SHARED_API_KEY", "dev-shared-secret-change-me")
API_KEY_HEADER = "X-API-Key"


async def verify_api_key(x_api_key: str = Header(default=None, alias=API_KEY_HEADER)) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
        )
