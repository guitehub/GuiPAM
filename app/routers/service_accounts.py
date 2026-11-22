"""Comptes de service et clés d'API (manager uniquement)."""

from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app import tls
from app.config import get_settings
from app.deps import ManagerUser, SessionDep, csrf_protect
from app.flash import flash
from app.i18n import gettext as _
from app.models import ApiKey, KeyScope, Role, ServiceAccount, utcnow
from app.services import apikeys, audit
from app.templating import hx_refresh, render

router = APIRouter(dependencies=[Depends(csrf_protect)])


async def _get_account(session: SessionDep, account_id: int) -> ServiceAccount:
    result = await session.exec(
        select(ServiceAccount)
        .where(ServiceAccount.id == account_id)
        .options(selectinload(ServiceAccount.keys))  # type: ignore[arg-type]
    )
    account = result.first()
    if account is None:
        raise HTTPException(status_code=404, detail=_("Service account not found."))
    return account


def _account_dict(account: ServiceAccount) -> dict:
    return {
        "name": account.name,
        "description": account.description,
        "role": account.role.value,
        "is_active": account.is_active,
    }


def _key_dict(key: ApiKey) -> dict:
    return {
        "name": key.name,
        "prefix": key.prefix,
        "scope": key.scope.value,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "revoked": key.revoked_at is not None,
    }


def _parse_role(raw: str) -> Role:
    try:
        return Role(raw)
    except ValueError:
        return Role.user


@router.get("/service-accounts")
async def accounts_page(request: Request, user: ManagerUser, session: SessionDep):
    result = await session.exec(
        select(ServiceAccount)
        .options(selectinload(ServiceAccount.keys))  # type: ignore[arg-type]
        .order_by(ServiceAccount.name)
    )
    return render(
        request,
        "service_accounts.html",
        {"accounts": result.all(), "key_state": apikeys.key_state, "now": utcnow()},
    )


@router.get("/service-accounts/new")
async def account_new_form(request: Request, user: ManagerUser):
    return render(request, "partials/_service_account_form.html", {"account": None, "errors": []})


@router.get("/service-accounts/{account_id}/edit")
async def account_edit_form(request: Request, user: ManagerUser, session: SessionDep, account_id: int):
    account = await _get_account(session, account_id)
    return render(request, "partials/_service_account_form.html", {"account": account, "errors": []})


async def _validate_account(
    session: SessionDep, name: str, exclude_id: int | None = None
) -> list[str]:
    errors: list[str] = []
    if not name:
        errors.append(_("Name is required."))
    else:
        existing = (await session.exec(select(ServiceAccount).where(ServiceAccount.name == name))).first()
        if existing is not None and existing.id != exclude_id:
            errors.append(_("A service account named “%s” already exists.") % name)
    return errors


@router.post("/service-accounts")
async def create_account(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = "user",
):
    name = name.strip()
    errors = await _validate_account(session, name)
    if errors:
        return render(
            request,
            "partials/_service_account_form.html",
            {"account": None, "errors": errors},
            status_code=422,
        )
    account = ServiceAccount(name=name, description=description.strip() or None, role=_parse_role(role))
    session.add(account)
    await session.flush()
    await audit.record(
        session, user, "create", "service_account", account.id, audit.diff({}, _account_dict(account))
    )
    await session.commit()
    flash(request, _("Service account “%s” created. Add a key to use it.") % name)
    return hx_refresh()


@router.patch("/service-accounts/{account_id}")
async def update_account(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    account_id: int,
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = "user",
    is_active: Annotated[str, Form()] = "",
):
    account = await _get_account(session, account_id)
    name = name.strip()
    errors = await _validate_account(session, name, exclude_id=account_id)
    if errors:
        return render(
            request,
            "partials/_service_account_form.html",
            {"account": account, "errors": errors},
            status_code=422,
        )
    before = _account_dict(account)
    account.name = name
    account.description = description.strip() or None
    account.role = _parse_role(role)
    account.is_active = is_active == "on"
    session.add(account)
    await audit.record(
        session, user, "update", "service_account", account.id, audit.diff(before, _account_dict(account))
    )
    await session.commit()
    flash(request, _("Service account “%s” updated.") % account.name)
    return hx_refresh()


@router.delete("/service-accounts/{account_id}")
async def delete_account(request: Request, user: ManagerUser, session: SessionDep, account_id: int):
    account = await _get_account(session, account_id)
    before = _account_dict(account)
    name = account.name
    await session.delete(account)  # cascade : clés
    await audit.record(session, user, "delete", "service_account", account_id, audit.diff(before, {}))
    await session.commit()
    flash(request, _("Service account “%s” deleted (its keys no longer work).") % name)
    return hx_refresh()


@router.get("/service-accounts/{account_id}/keys/new")
async def key_new_form(request: Request, user: ManagerUser, session: SessionDep, account_id: int):
    account = await _get_account(session, account_id)
    return render(request, "partials/_api_key_form.html", {"account": account, "errors": []})


@router.post("/service-accounts/{account_id}/keys")
async def create_key(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    account_id: int,
    name: Annotated[str, Form()] = "",
    scope: Annotated[str, Form()] = "read",
    expires_on: Annotated[str, Form()] = "",
):
    account = await _get_account(session, account_id)
    errors: list[str] = []
    name = name.strip()
    if not name:
        errors.append(_("Name is required."))
    key_scope = KeyScope.write if scope == "write" else KeyScope.read
    if key_scope == KeyScope.write and account.role != Role.manager:
        errors.append(_("A read/write key requires a service account with the manager role."))
    expires_at: datetime | None = None
    if expires_on.strip():
        try:
            # Valable jusqu'à la fin du jour choisi (UTC).
            expires_at = datetime.combine(date.fromisoformat(expires_on.strip()), time.max)
        except ValueError:
            errors.append(_("Invalid expiry date."))
        else:
            if expires_at <= utcnow():
                errors.append(_("The expiry date must be in the future."))
    if errors:
        return render(
            request,
            "partials/_api_key_form.html",
            {"account": account, "errors": errors},
            status_code=422,
        )
    raw, prefix, key_hash = apikeys.generate_key()
    key = ApiKey(
        service_account_id=account.id,
        name=name,
        prefix=prefix,
        key_hash=key_hash,
        scope=key_scope,
        expires_at=expires_at,
        created_by=user.username,
    )
    session.add(key)
    await session.flush()
    await audit.record(session, user, "create", "api_key", key.id, audit.diff({}, _key_dict(key)))
    await session.commit()
    # Seul moment où la clé existe en clair : elle n'est ni stockée ni journalisée.
    return render(
        request,
        "partials/_api_key_created.html",
        {
            "account": account,
            "key": key,
            "raw_key": raw,
            "base_url": str(request.base_url).rstrip("/"),
            "pin": _self_signed_pin(request),
        },
    )


def _self_signed_pin(request: Request) -> str | None:
    """Épingle SPKI à mettre dans l'exemple curl si la page est servie en direct par le certificat auto-signé.

    Le port local de la connexion désigne l'écouteur : derrière un reverse proxy (écouteur proxy), c'est le
    certificat du proxy que voit le client, l'épingle de l'instance n'y servirait à rien.
    """
    info = tls.current()
    server = request.scope.get("server") or (None, None)
    if info is None or info.source != tls.SELF_SIGNED or server[1] != get_settings().https_port:
        return None
    return info.spki_sha256


@router.post("/api-keys/{key_id}/revoke")
async def revoke_key(request: Request, user: ManagerUser, session: SessionDep, key_id: int):
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail=_("API key not found."))
    if key.revoked_at is None:
        before = _key_dict(key)
        key.revoked_at = utcnow()
        session.add(key)
        await audit.record(session, user, "update", "api_key", key.id, audit.diff(before, _key_dict(key)))
        await session.commit()
    flash(request, _("Key “%s” revoked.") % key.name)
    return hx_refresh()
