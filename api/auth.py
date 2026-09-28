"""Bearer-token authentication for API requests."""

import secrets

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import agent.config as config
from agent.rbac import Principal, configured_api_principal


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
        if _is_public_path(request.url.path):
            return await call_next(request)
        if not expected:
            request.state.principal = configured_api_principal()
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
            request.state.principal = configured_api_principal()
            return await call_next(request)

        return JSONResponse(
            {"detail": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_request_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return principal


def require_permissions(*permissions: str):
    def dependency(request: Request) -> Principal:
        principal = get_request_principal(request)
        missing = principal.missing(permissions)
        if missing:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Permission denied",
                    "missing_permissions": missing,
                },
            )
        return principal

    return dependency
