"""Bearer-token authentication for API requests."""

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import agent.config as config


_PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}


def _is_public_path(path: str) -> bool:
    return path in _PUBLIC_PATHS or path.startswith("/ui")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Require a bearer token when API_AUTH_TOKEN is configured."""

    async def dispatch(self, request: Request, call_next):
        expected = config.API_AUTH_TOKEN
        if not expected or _is_public_path(request.url.path):
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, separator, token = header.partition(" ")
        valid = (
            separator == " "
            and scheme.lower() == "bearer"
            and bool(token)
            and secrets.compare_digest(token, expected)
        )
        if valid:
            return await call_next(request)

        return JSONResponse(
            {"detail": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
