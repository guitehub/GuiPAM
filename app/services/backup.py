"""Continuité des données : sauvegarde complète versionnée (JSON) et instantanés SQLite.

Deux filets de sécurité complémentaires :

1. **Instantanés** de la base (`/data/backups/*.db`) : pris automatiquement avant toute
   migration de schéma et une fois par jour. Restauration = remettre le fichier en place.
2. **Export / import JSON** : format indépendant du schéma interne, identifié par
   `format_version`. C'est le chemin de migration garanti entre versions majeures :
   une version N+1 sait toujours relire un export de la version N.

Règle de compatibilité du format : le dump est générique (toutes les tables, toutes
les colonnes), donc un changement de schéma **additif** ne change pas `FORMAT_VERSION`
(à l'import, une colonne absente prend sa valeur par défaut, une colonne ou une table
inconnue est ignorée). Tout changement **non additif** (renommage, suppression,
restructuration) incrémente `FORMAT_VERSION` et ajoute dans `UPGRADERS` la fonction
qui convertit l'ancien format vers le nouveau. On ne retire jamais un upgrader.
"""

import enum
import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, Table
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app import __version__
from app.i18n import gettext as _
from app.models import utcnow

logger = logging.getLogger("guipam.backup")

FORMAT_NAME = "guipam-backup"
FORMAT_VERSION = 1

# format_version N → fonction qui transforme un export N en export N+1.
UPGRADERS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}

SNAPSHOT_DIR = "backups"
PRE_MIGRATION_PREFIX = "guipam-avant-migration-"
DAILY_PREFIX = "guipam-quotidien-"


class BackupError(Exception):
    """Sauvegarde illisible ou refusée (message localisé)."""


def _tables() -> list[Table]:
    return list(SQLModel.metadata.sorted_tables)  # ordre compatible avec les clés étrangères


def _dump(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _load(column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(column.type, SAEnum) and column.type.enum_class is not None and isinstance(value, str):
        return column.type.enum_class(value)
    return value


async def export_data(session: AsyncSession) -> dict[str, Any]:
    """Toutes les données de l'instance, dans le format d'échange versionné."""
    conn = await session.connection()
    revision = (await conn.exec_driver_sql("SELECT version_num FROM alembic_version")).scalar()
    data: dict[str, list[dict[str, Any]]] = {}
    for table in _tables():
        result = await conn.execute(table.select().order_by(*table.primary_key.columns))
        data[table.name] = [{k: _dump(v) for k, v in row.items()} for row in result.mappings().all()]
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "schema_revision": revision,
        "exported_at": utcnow().isoformat() + "Z",
        "data": data,
    }


def upgrade_payload(payload: Any) -> dict[str, Any]:
    """Valide l'enveloppe et amène un export ancien au format courant."""
    if not isinstance(payload, dict) or payload.get("format") != FORMAT_NAME:
        raise BackupError(_("This file is not a GuiPAM backup."))
    version = payload.get("format_version")
    if not isinstance(version, int) or version < 1 or not isinstance(payload.get("data"), dict):
        raise BackupError(_("This file is not a GuiPAM backup."))
    if version > FORMAT_VERSION:
        raise BackupError(
            _("This backup was made by a newer GuiPAM (format %(found)d, this version reads up to %(max)d). Update GuiPAM first.")
            % {"found": version, "max": FORMAT_VERSION}
        )
    while version < FORMAT_VERSION:
        payload = UPGRADERS[version](payload)
        version += 1
        payload["format_version"] = version
    return payload


async def import_data(session: AsyncSession, payload: Any) -> dict[str, int]:
    """Remplace TOUTES les données par celles de la sauvegarde (une seule transaction).

    Retourne le nombre de lignes restaurées par table. En cas d'erreur, rien n'est modifié.
    """
    payload = upgrade_payload(payload)
    data = payload["data"]
    managers = [
        u for u in data.get("user", []) if u.get("role") == "manager" and u.get("is_active", True)
    ]
    if not managers:
        raise BackupError(_("This backup contains no active manager account: restoring it would lock you out."))

    counts: dict[str, int] = {}
    try:
        conn = await session.connection()
        tables = _tables()
        for table in reversed(tables):
            await conn.execute(table.delete())
        for table in tables:
            rows = data.get(table.name) or []
            if not rows:
                continue
            # Colonnes inconnues ignorées ; colonnes absentes → valeur par défaut du schéma.
            columns = [c for c in table.columns if any(c.name in row for row in rows)]
            await conn.execute(
                table.insert(), [{c.name: _load(c, row.get(c.name)) for c in columns} for row in rows]
            )
            counts[table.name] = len(rows)
        await session.commit()
    except BackupError:
        raise
    except Exception as exc:
        await session.rollback()
        logger.exception("Restauration refusée")
        raise BackupError(_("The backup could not be restored (nothing was changed): %s") % exc) from exc
    return counts


# ---------------------------------------------------------------------- Instantanés


def _prune(directory: Path, prefix: str, keep: int) -> None:
    files = sorted(directory.glob(f"{prefix}*.db"))
    for old in files[: max(0, len(files) - keep)]:
        old.unlink(missing_ok=True)


def snapshot(db_path: str, prefix: str, label: str, keep: int) -> Path | None:
    """Copie cohérente de la base (API de sauvegarde SQLite, sûre en WAL, à chaud)."""
    source_path = Path(db_path)
    if keep <= 0 or not source_path.exists():
        return None
    directory = source_path.parent / SNAPSHOT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{prefix}{label}.db"
    source = sqlite3.connect(source_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    _prune(directory, prefix, keep)
    return destination


def current_revision(db_path: str) -> str | None:
    """Révision Alembic de la base, None si elle n'existe pas encore ou n'est pas versionnée."""
    if not Path(db_path).exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return row[0] if row else None


def snapshot_before_migration(db_path: str, head: str | None, keep: int) -> Path | None:
    """Instantané pris seulement si le démarrage va réellement migrer le schéma."""
    revision = current_revision(db_path)
    if revision is None or revision == head:
        return None
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    path = snapshot(db_path, PRE_MIGRATION_PREFIX, f"{stamp}-{revision}", keep)
    if path:
        logger.warning("Migration de schéma %s → %s : instantané préalable dans %s", revision, head, path)
    return path


def daily_snapshot(db_path: str, keep: int) -> Path | None:
    """Un instantané par jour (idempotent : le fichier du jour est simplement rafraîchi)."""
    return snapshot(db_path, DAILY_PREFIX, utcnow().strftime("%Y%m%d"), keep)
