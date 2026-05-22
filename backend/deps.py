"""
backend/deps.py
───────────────
FastAPI dependency injection: JWT decode, current-user lookup, role gates.

FIX: TokenData.username was missing, causing AttributeError downstream.
     JWT subject ("sub") is set to the username string at login time.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

# ── JWT config ────────────────────────────────────────────────────
SECRET_KEY  = os.environ.get("JWT_SECRET", "CHANGE_ME_IN_PRODUCTION")
ALGORITHM   = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── TokenData — THE FIX ──────────────────────────────────────────
class TokenData(BaseModel):
    username: str          # was missing; sub claim carries username
    role: str  = "viewer"
    tenant_id: str | None = None


# ── DB import (lazy to avoid circular) ───────────────────────────
def _get_db():
    """Import here to avoid circular imports at module load."""
    from database import get_conn, release_conn  # noqa: PLC0415
    return get_conn, release_conn


def decode_token(token: str) -> TokenData:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        if not username:
            raise credentials_exc
        return TokenData(
            username=username,
            role=payload.get("role", "viewer"),
            tenant_id=payload.get("tenant_id"),
        )
    except JWTError:
        raise credentials_exc


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> TokenData:
    return decode_token(token)


def require_role(*allowed: str):
    """
    Factory: returns a dependency that raises 403 unless user.role is in allowed.

    Usage:
        @router.post("/...", dependencies=[Depends(require_role("admin", "senior_underwriter"))])
    """
    async def _check(user: Annotated[TokenData, Depends(get_current_user)]):
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted. Required: {list(allowed)}",
            )
        return user
    return _check


# ── Convenience aliases ───────────────────────────────────────────
CurrentUser   = Annotated[TokenData, Depends(get_current_user)]
AdminOnly     = Annotated[TokenData, Depends(require_role("admin", "super_admin"))]
UWOrAbove     = Annotated[TokenData, Depends(require_role(
    "underwriter", "senior_underwriter", "admin", "super_admin"
))]
