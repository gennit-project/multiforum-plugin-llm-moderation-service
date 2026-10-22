import secrets

from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    supplied = x_api_key or ""
    if not secrets.compare_digest(supplied.encode(), settings.api_key.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
