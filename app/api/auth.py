"""Authentification de l'API : clé de compte de service en `Authorization: Bearer`."""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.deps import SessionDep
from app.i18n import gettext as _
from app.models import ApiKey, ServiceAccount
from app.services import apikeys
from app.services.audit import Actor


class ApiError(Exception):
    """Erreur renvoyée au format commun `{"error": {code, message, details}}`."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.headers = headers


bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="ApiKey",
    bearerFormat="gpm_<prefix>_<secret>",
    description=(
        "Service-account API key, created by a manager in the GuiPAM web UI "
        "(Service accounts page). Send it as `Authorization: Bearer gpm_…`."
    ),
)


@dataclass
class Principal:
    account: ServiceAccount
    key: ApiKey
    can_write: bool

    @property
    def actor(self) -> Actor:
        """Auteur consigné dans l'audit : compte de service + clé."""
        return Actor(
            username=self.account.name,
            service_account_id=self.account.id,
            api_key_id=self.key.id,
            api_key_label=f"{self.key.name} ({self.key.prefix})",
        )


async def require_key(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    authenticated = None
    if credentials is not None:
        authenticated = await apikeys.authenticate(session, credentials.credentials)
    if authenticated is None:
        raise ApiError(
            401,
            "unauthorized",
            _("Missing, invalid, expired or revoked API key."),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Principal(
        account=authenticated.account,
        key=authenticated.key,
        can_write=apikeys.can_write(authenticated.account, authenticated.key),
    )


async def require_write_key(principal: Annotated[Principal, Depends(require_key)]) -> Principal:
    if not principal.can_write:
        raise ApiError(403, "read_only", _("This API key is read-only: action not allowed."))
    return principal


Reader = Annotated[Principal, Depends(require_key)]
Writer = Annotated[Principal, Depends(require_write_key)]
