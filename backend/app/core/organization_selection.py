"""R3 Task 6: the organization a request works in.

Pages send the selected organization as ``X-Organization-ID``. This pure ASGI middleware
publishes it (or None) to app.services.organization_context.SELECTED_ORGANIZATION for
the whole request, so every profile-dependent read resolves the same organization's
company profile. Membership is checked where it is used; a header naming an
organization the user is not an ACTIVE member of is answered 404.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse

from app.services.organization_context import SELECTED_ORGANIZATION

HEADER = b"x-organization-id"


def _selected(scope) -> UUID | None:
    for name, value in scope.get("headers") or ():
        if name == HEADER:
            try:
                return UUID(value.decode("latin-1").strip())
            except ValueError:
                return None
    return None


class OrganizationSelectionMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = SELECTED_ORGANIZATION.set(_selected(scope))
        try:
            await self.app(scope, receive, send)
        finally:
            SELECTED_ORGANIZATION.reset(token)


async def organization_access_denied(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Organization not found"})
