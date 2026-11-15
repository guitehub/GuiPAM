"""API JSON v1 de GuiPAM, montée sous `/api/v1` (sous-application FastAPI).

Spécification OpenAPI : `/api/v1/openapi.json` ; documentation interactive :
`/api/v1/docs`. Les deux sont publiques (elles ne révèlent aucune donnée) pour
qu'un outil ou un agent puisse découvrir l'API avant d'avoir une clé.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.auth import ApiError
from app.api.routes import router
from app.services.inventory import SubnetFullError, ValidationFailed

DESCRIPTION = """
Programmatic access to a GuiPAM instance: VLANs (subnets), IP addresses and liveness monitoring.
Everything the web UI can do on these objects is available here, with the very same business
rules (CIDR overlap, address inside its subnet, duplicates, capacity…).

## Authentication

Every endpoint requires a service-account API key: `Authorization: Bearer gpm_<prefix>_<secret>`.
Keys are created (and shown once) by a manager in the web UI, page **Service accounts**.
A key is either `read` (default) or `write`; writing also requires the service account to have
the `manager` role. Call `GET /whoami` to check what your key can do.
Mutating endpoints answer `403 read_only` to a read-only key.

## Conventions

- JSON in, JSON out. Timestamps are UTC, ISO 8601 with a `Z` suffix.
- `PATCH` is partial: only the fields present in the body are changed; send `null` to clear an
  optional field.
- IP status values are `libre` (free), `utilisee` (in use), `reservee` (reserved).
- An address that is not recorded at all is free. Storage is sparse: only documented addresses exist.
- In this API a "VLAN" is a subnet with one CIDR; `vlan_tag` is its optional 802.1Q tag, while
  `vlan_id` on other objects is the `id` of the VLAN resource.
- Errors always look like `{"error": {"code": "...", "message": "...", "details": [{"field": "...", "message": "..."}]}}`.
  Messages are localized with `Accept-Language` (`en` by default, `fr` available).
- Every mutation is recorded in the audit log with the service account and the key that made it.

## Typical tasks

- **Reserve an IP for a new VM**: `GET /vlans` to find the VLAN, then
  `POST /vlans/{vlan_id}/allocate` with `{"hostname": "...", "description": "..."}`.
  Once the VM is live, `PATCH /ips/{ip_id}` with `{"status": "utilisee"}`.
- **See what is down**: `GET /problems`.
- **Document a device**: `GET /ips?q=<hostname or address>` then `PATCH /ips/{ip_id}`.
- **Monitor a service**: `POST /ips/{ip_id}/monitors` with `{"protocol": "tcp", "port": 443}`.
"""

TAGS = [
    {"name": "meta", "description": "Identity of the caller and global counters."},
    {"name": "network", "description": "The single network managed by this instance."},
    {"name": "vlans", "description": "VLANs / subnets."},
    {"name": "ips", "description": "IP addresses, search and allocation."},
    {"name": "monitoring", "description": "Monitor targets, health and on-demand checks."},
    {"name": "audit", "description": "Audit log (read-only)."},
]


def _error(status_code: int, code: str, message: str, details=None, headers=None) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details or []}},
        status_code=status_code,
        headers=headers,
    )


def create_api() -> FastAPI:
    api = FastAPI(
        title="GuiPAM API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url=None,  # servie ci-dessous avec Swagger UI en local (aucun CDN)
        redoc_url=None,
        generate_unique_id_function=lambda route: route.name if isinstance(route, APIRoute) else "",
    )

    @api.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return _error(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @api.exception_handler(ValidationFailed)
    async def validation_failed(request: Request, exc: ValidationFailed):
        details = [{"field": e.field, "message": e.message} for e in exc.errors]
        if isinstance(exc, SubnetFullError):
            return _error(409, "subnet_full", str(exc), details)
        return _error(422, "validation_error", str(exc), details)

    @api.exception_handler(RequestValidationError)
    async def request_invalid(request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body") or None, "message": err["msg"]}
            for err in exc.errors()
        ]
        message = "; ".join(
            f"{d['field']}: {d['message']}" if d["field"] else d["message"] for d in details
        )
        return _error(422, "validation_error", message, details)

    @api.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "error")
        return _error(exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None))

    @api.get("/docs", include_in_schema=False)
    async def docs(request: Request):
        return get_swagger_ui_html(
            openapi_url=f"{request.scope.get('root_path', '')}/openapi.json",
            title="GuiPAM API",
            swagger_js_url="/static/vendor/swagger-ui-bundle.js",
            swagger_css_url="/static/vendor/swagger-ui.css",
            swagger_favicon_url="data:,",
        )

    api.include_router(router)
    return api
