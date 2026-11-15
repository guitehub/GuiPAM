"""Environnement Jinja2 partagé : i18n, filtres santé et dates."""

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import get_settings
from app.i18n import format_datetime, format_relative, get_locale, gettext, ngettext
from app.services.auth import CSRF_SESSION_KEY
from app.services.ipam import address_prefix
from app.services.monitor import SEVERITY, Health, health, ip_health

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Classes CSS des pastilles de santé (définies dans static/health.css).
HEALTH_CSS = {
    Health.unknown: "health-unknown",
    Health.ok: "health-ok",
    Health.warn: "health-warn",
    Health.red: "health-red",
    Health.dark_red: "health-dark-red",
    None: "health-none",
}

HEALTH_LABELS = {
    Health.unknown: "Never checked",
    Health.ok: "OK",
    Health.warn: "Warning",
    Health.red: "Down",
    Health.dark_red: "Down for a long time (stale?)",
    None: "No monitor target",
}

templates = Jinja2Templates(directory=str(TEMPLATES_DIR), extensions=["jinja2.ext.i18n"])
templates.env.policies["ext.i18n.trimmed"] = True
templates.env.install_gettext_callables(gettext, ngettext, newstyle=True)  # type: ignore[attr-defined]

templates.env.filters["relative"] = format_relative
templates.env.filters["dt"] = format_datetime
templates.env.filters["address_prefix"] = address_prefix
templates.env.filters["health_css"] = lambda h: HEALTH_CSS.get(h, "health-none")
templates.env.filters["health_label"] = lambda h: gettext(HEALTH_LABELS.get(h, "No monitor target"))

STATUS_CSS = {"libre": "badge-outline", "utilisee": "badge-primary", "reservee": "badge-secondary"}
STATUS_LABELS = {"libre": "Free", "utilisee": "Used", "reservee": "Reserved"}

templates.env.filters["status_css"] = lambda s: STATUS_CSS.get(getattr(s, "value", s), "badge-outline")
templates.env.filters["status_label"] = lambda s: gettext(STATUS_LABELS.get(getattr(s, "value", s), str(s)))


def ip_last_checked(ip) -> object:
    """Dernier check parmi les cibles actives d'une IP (None si aucune)."""
    return max((t.last_checked_at for t in ip.monitors if t.enabled and t.last_checked_at), default=None)


templates.env.globals["ip_last_checked"] = ip_last_checked
templates.env.globals["app_version"] = __version__
templates.env.globals["health"] = health
templates.env.globals["ip_health"] = ip_health
templates.env.globals["Health"] = Health
templates.env.globals["SEVERITY"] = SEVERITY


def hx_refresh() -> Response:
    """Réponse vide qui demande à HTMX de recharger la page (toast via flash)."""
    return Response(status_code=204, headers={"HX-Refresh": "true"})


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    """Rend un template avec le contexte commun (user, réseau, CSRF, locale)."""
    settings = get_settings()
    ctx: dict[str, Any] = {
        "user": getattr(request.state, "user", None),
        "reseau": getattr(request.state, "reseau", None),
        "nav_subnets": getattr(request.state, "nav_subnets", []),
        "csrf_token": request.session.get(CSRF_SESSION_KEY, ""),
        "locale": get_locale(),
        "settings": settings,
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(
        request=request, name=name, context=ctx, status_code=status_code, headers=headers
    )
