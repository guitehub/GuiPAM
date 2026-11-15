"""Modèles SQLModel de GuiPAM.

Un seul module logique pour éviter les cycles d'import.
Toutes les dates sont stockées en UTC naïf (convention SQLite).
"""

import enum
from datetime import UTC, datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

RESEAU_SINGLETON_ID = 1


def utcnow() -> datetime:
    """Horodatage UTC naïf, cohérent partout (DB, santé, audit)."""
    return datetime.now(UTC).replace(tzinfo=None)


class IPStatus(str, enum.Enum):
    libre = "libre"
    utilisee = "utilisee"
    reservee = "reservee"


class Protocol(str, enum.Enum):
    tcp = "tcp"
    icmp = "icmp"


class CheckStatus(str, enum.Enum):
    up = "up"
    down = "down"
    unknown = "unknown"


class Role(str, enum.Enum):
    manager = "manager"
    user = "user"


class KeyScope(str, enum.Enum):
    read = "read"
    write = "write"


class Reseau(SQLModel, table=True):
    """Singleton (id=1) : le réseau géré par cette instance."""

    __tablename__ = "reseau"

    id: int | None = Field(default=RESEAU_SINGLETON_ID, primary_key=True)
    name: str
    description: str | None = None
    notes: str | None = None
    root_prefixes: list[str] | None = Field(default=None, sa_column=Column(JSON))
    default_locale: str = "fr"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Subnet(SQLModel, table=True):
    """Affiché « VLAN » dans l'UI. Un seul CIDR par VLAN."""

    __tablename__ = "subnet"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str | None = None
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    cidr: str = Field(unique=True, index=True)
    gateway: str | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    ips: list["IPAddress"] = Relationship(
        back_populates="subnet",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class IPAddress(SQLModel, table=True):
    """Stockage sparse : une ligne par IP réellement saisie."""

    __tablename__ = "ip_address"
    __table_args__ = (UniqueConstraint("subnet_id", "address_int", name="uq_subnet_address"),)

    id: int | None = Field(default=None, primary_key=True)
    subnet_id: int = Field(foreign_key="subnet.id", index=True)
    address: str
    address_int: int = Field(index=True)
    hostname: str | None = None
    mac: str | None = None
    device_label: str | None = None
    hardware: str | None = None
    location: str | None = None
    description: str | None = None
    status: IPStatus = Field(default=IPStatus.utilisee)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    subnet: Subnet = Relationship(back_populates="ips")
    monitors: list["MonitorTarget"] = Relationship(
        back_populates="ip",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class MonitorTarget(SQLModel, table=True):
    __tablename__ = "monitor_target"

    id: int | None = Field(default=None, primary_key=True)
    ip_id: int = Field(foreign_key="ip_address.id", index=True)
    protocol: Protocol = Field(default=Protocol.tcp)
    port: int | None = Field(default=None, ge=1, le=65535)
    label: str | None = None
    enabled: bool = True
    interval_seconds: int = 60
    last_checked_at: datetime | None = None
    last_ok_at: datetime | None = None
    last_status: CheckStatus = Field(default=CheckStatus.unknown)
    latency_ms: float | None = None
    consecutive_failures: int = 0

    ip: IPAddress = Relationship(back_populates="monitors")


class User(SQLModel, table=True):
    __tablename__ = "user"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    hashed_password: str
    role: Role = Field(default=Role.user)
    is_active: bool = True
    locale: str | None = None
    last_login_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = None
    username: str
    ts: datetime = Field(default_factory=utcnow, index=True)
    action: str  # create / update / delete / login / check / import / export
    entity_type: str  # reseau / subnet / ip / monitor / user / service_account / api_key
    entity_id: int | None = None
    changes: dict | None = Field(default=None, sa_column=Column(JSON))
    # Renseignés quand l'action vient de l'API : `username` porte alors le nom du
    # compte de service. Dénormalisé : la trace survit à la suppression de la clé.
    service_account_id: int | None = None
    api_key_id: int | None = None
    api_key_label: str | None = None


class ServiceAccount(SQLModel, table=True):
    """Identité non humaine (script, Ansible, agent IA) : s'authentifie par clé d'API."""

    __tablename__ = "service_account"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str | None = None
    # Même sémantique que les utilisateurs : seul un compte `manager` peut porter
    # une clé en écriture.
    role: Role = Field(default=Role.user)
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)

    keys: list["ApiKey"] = Relationship(
        back_populates="account",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "ApiKey.id"},
    )


class ApiKey(SQLModel, table=True):
    """Clé d'API : seul le SHA-256 est stocké, le secret n'est montré qu'à la création."""

    __tablename__ = "api_key"

    id: int | None = Field(default=None, primary_key=True)
    service_account_id: int = Field(foreign_key="service_account.id", index=True)
    name: str
    prefix: str = Field(unique=True, index=True)  # partie publique, identifie la clé
    key_hash: str
    scope: KeyScope = Field(default=KeyScope.read)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    created_by: str | None = None

    account: ServiceAccount = Relationship(back_populates="keys")
