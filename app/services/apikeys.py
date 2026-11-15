"""Clés d'API des comptes de service : génération, hachage, authentification.

Format : `gpm_<préfixe>_<secret>`. Le préfixe (public) identifie la clé ; seul le
SHA-256 de la clé complète est stocké (secret à forte entropie : pas besoin de
bcrypt). La clé n'est connue en clair qu'au moment de sa création.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import ApiKey, KeyScope, Role, ServiceAccount, utcnow

KEY_TAG = "gpm"
# On ne réécrit pas `last_used_at` à chaque requête (une écriture par lecture sinon).
LAST_USED_GRANULARITY_SECONDS = 60


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_key() -> tuple[str, str, str]:
    """Retourne (clé en clair, préfixe, hash)."""
    prefix = secrets.token_hex(4)
    raw = f"{KEY_TAG}_{prefix}_{secrets.token_urlsafe(32)}"
    return raw, prefix, hash_key(raw)


def key_state(key: ApiKey, now: datetime | None = None) -> str:
    """`active`, `revoked` ou `expired`."""
    if key.revoked_at is not None:
        return "revoked"
    if key.expires_at is not None and key.expires_at <= (now or utcnow()):
        return "expired"
    return "active"


def can_write(account: ServiceAccount, key: ApiKey) -> bool:
    """Écriture = clé en écriture ET compte de service au rôle manager."""
    return key.scope == KeyScope.write and account.role == Role.manager


@dataclass
class Authenticated:
    account: ServiceAccount
    key: ApiKey


async def authenticate(session: AsyncSession, raw: str) -> Authenticated | None:
    """Valide une clé présentée ; None si inconnue, révoquée, expirée ou compte inactif."""
    parts = (raw or "").strip().split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_TAG:
        return None
    key = (await session.exec(select(ApiKey).where(ApiKey.prefix == parts[1]))).first()
    if key is None or not hmac.compare_digest(key.key_hash, hash_key(raw.strip())):
        return None
    now = utcnow()
    if key_state(key, now) != "active":
        return None
    account = await session.get(ServiceAccount, key.service_account_id)
    if account is None or not account.is_active:
        return None
    if (
        key.last_used_at is None
        or (now - key.last_used_at).total_seconds() >= LAST_USED_GRANULARITY_SECONDS
    ):
        key.last_used_at = now
        session.add(key)
        await session.commit()
    return Authenticated(account=account, key=key)
