"""Schémas JSON de l'API v1 (les descriptions alimentent la spécification OpenAPI)."""

from datetime import UTC, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models import CheckStatus, IPStatus, KeyScope, Protocol, Role
from app.services.monitor import Health

T = TypeVar("T")

# Les dates sont stockées en UTC naïf : on les publie en ISO 8601 avec le suffixe Z.
UtcDatetime = Annotated[
    datetime,
    PlainSerializer(
        lambda value: value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        return_type=str,
        when_used="json",
    ),
]

STATUS_DOC = "`libre` = free, `utilisee` = in use, `reservee` = reserved."
HEALTH_DOC = (
    "Monitoring health: `ok`, `warn` (stale or recently down), `red` (down), "
    "`dark_red` (down for a long time), `unknown` (never checked). "
    "Thresholds are relative to each target and set on GET /network."
)
MONITORING_RESET_DOC = " Send null to go back to the instance default (GUIPAM_* environment variable)."


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------ Erreurs


class ErrorDetail(BaseModel):
    field: str | None = Field(None, description="Offending field, when known.")
    message: str


class ErrorBody(BaseModel):
    code: str = Field(
        description=(
            "Machine-readable code: `unauthorized`, `read_only`, `not_found`, "
            "`validation_error`, `subnet_full`."
        )
    )
    message: str = Field(description="Human-readable summary (localized via Accept-Language).")
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(description="Number of items matching the filters, before pagination.")
    limit: int
    offset: int


# --------------------------------------------------------------------------- Méta


class WhoAmI(BaseModel):
    service_account: str
    role: Role
    key_name: str
    key_prefix: str
    key_scope: KeyScope
    can_write: bool = Field(
        description="True only if the key scope is `write` AND the service account role is `manager`."
    )
    expires_at: UtcDatetime | None
    version: str = Field(description="GuiPAM version.")


class TlsOut(BaseModel):
    """Certificate served by the instance's HTTPS listener, for a client that wants to pin it."""

    mode: Literal["auto", "off"] = Field(
        description="`auto`: the instance serves HTTPS itself; `off`: plain HTTP only (development, or a reverse "
        "proxy in front terminates TLS). With `off` every other field is null or empty."
    )
    source: Literal["self-signed", "provided"] | None = Field(
        description="`self-signed`: certificate generated and persisted by the instance; `provided`: certificate "
        "given by the administrator (internal CA, ACME…)."
    )
    not_after: UtcDatetime | None = Field(
        description="Expiry. A self-signed certificate is renewed automatically 30 days before, with the same key."
    )
    sha256: str | None = Field(
        description="SHA-256 fingerprint of the certificate (DER), colon-separated uppercase hex, as shown by "
        "browsers and `openssl x509 -fingerprint -sha256`. Changes at every renewal: use it to check by eye."
    )
    spki_sha256: str | None = Field(
        description="Base64 SHA-256 of the certificate public key (SubjectPublicKeyInfo), the format of "
        "`curl --pinnedpubkey sha256//<value>`. Stable across renewals of the self-signed certificate: "
        "this is the value an automated client should pin."
    )
    sans: list[str] = Field(description="DNS names and IP addresses the certificate is valid for.")


class InstanceOut(BaseModel):
    """Identity of this GuiPAM instance."""

    version: str = Field(description="GuiPAM version.")
    tls: TlsOut


class NetworkOut(BaseModel):
    name: str
    description: str | None
    notes: str | None
    root_prefixes: list[str] | None = Field(description="Informational root prefixes (not enforced).")
    default_locale: str
    default_check_interval: int = Field(
        description="Check period (seconds) given to a new monitor target created without `interval_seconds`."
    )
    health_warn_intervals: int = Field(
        description=(
            "Green → amber: a reachable target turns `warn` when its last success is older than this many "
            "times its own `interval_seconds` (its measurements are no longer fresh)."
        )
    )
    health_red_failures: int = Field(
        description="Amber → red: a down target turns `red` after this many consecutive failed checks."
    )
    health_dark_red_seconds: int = Field(
        description=(
            "Red → dark red: a down target turns `dark_red` when its last success is older than this many "
            "seconds (dead service or stale entry)."
        )
    )
    updated_at: UtcDatetime


class NetworkUpdate(Strict):
    name: str | None = None
    description: str | None = None
    notes: str | None = None
    root_prefixes: list[str] | None = None
    default_locale: str | None = Field(None, description="`fr` or `en`.")
    default_check_interval: int | None = Field(None, description="5-86400 seconds." + MONITORING_RESET_DOC)
    health_warn_intervals: int | None = Field(None, description="1-100 intervals." + MONITORING_RESET_DOC)
    health_red_failures: int | None = Field(None, description="1-1000 failed checks." + MONITORING_RESET_DOC)
    health_dark_red_seconds: int | None = Field(
        None, description="60-31622400 seconds." + MONITORING_RESET_DOC
    )


class Summary(BaseModel):
    vlans: int
    recorded_ips: int
    used: int
    reserved: int
    free: int = Field(description="Recorded addresses with status `libre` (unrecorded addresses are free too).")
    down: int = Field(
        description="IP addresses whose health is `red` or `dark_red`, paused ones excluded. See GET /problems."
    )
    paused: int = Field(0, description="IP addresses paused on purpose (see `paused` on IP addresses).")


# ---------------------------------------------------------------------- Supervision


class MonitorOut(BaseModel):
    id: int
    ip_id: int
    protocol: Protocol
    port: int | None = Field(description="TCP port (null for ICMP).")
    label: str | None
    enabled: bool
    interval_seconds: int
    last_status: CheckStatus
    last_checked_at: UtcDatetime | None
    last_ok_at: UtcDatetime | None
    latency_ms: float | None
    consecutive_failures: int
    health: Health = Field(description=HEALTH_DOC)


class MonitorCreate(Strict):
    protocol: Protocol = Field(Protocol.tcp, description="`tcp` (connect to a port) or `icmp` (ping).")
    port: int | None = Field(None, description="Required for `tcp` (1-65535); ignored for `icmp`.")
    label: str | None = Field(None, description="Free label, e.g. `ssh`, `https`.")
    interval_seconds: int | None = Field(
        None, description="Check period, 5-86400. Defaults to `default_check_interval` of GET /network."
    )
    enabled: bool = True


class MonitorUpdate(Strict):
    protocol: Protocol | None = None
    port: int | None = None
    label: str | None = None
    interval_seconds: int | None = None
    enabled: bool | None = None


# ----------------------------------------------------------------------------- IP


class IpFields(Strict):
    hostname: str | None = None
    mac: str | None = Field(None, description="Any common notation; stored as `aa:bb:cc:dd:ee:ff`.")
    device_label: str | None = Field(None, description="Short device name / role.")
    hardware: str | None = Field(None, description="Hardware model.")
    location: str | None = Field(None, description="Physical location.")
    description: str | None = None


class IpCreate(IpFields):
    address: str = Field(description="IPv4 address inside the VLAN CIDR.", examples=["192.168.10.20"])
    status: IPStatus = Field(IPStatus.utilisee, description=STATUS_DOC)


class IpAllocate(IpFields):
    status: IPStatus = Field(
        IPStatus.reservee, description="Status given to the allocated address: `reservee` or `utilisee`."
    )


class IpUpdate(IpFields):
    address: str | None = Field(None, description="New address (must stay inside the same VLAN).")
    status: IPStatus | None = Field(None, description=STATUS_DOC)


class PauseOut(BaseModel):
    since: UtcDatetime = Field(description="When the pause started.")
    reason: str | None = Field(description="Free text, e.g. `powered off on purpose`.")
    until: UtcDatetime | None = Field(description="Automatic resume at this date; null if none.")
    until_recovery: bool = Field(
        description="Automatic resume as soon as one enabled target answers again after having been down."
    )


class PauseIn(Strict):
    reason: str | None = Field(None, description="Why the host is paused (max 200 characters).")
    until: datetime | None = Field(
        None,
        description="Resume automatically at this date (ISO 8601; without timezone = UTC). Must be in the future.",
    )
    until_recovery: bool = Field(
        True,
        description=(
            "Resume automatically when the host comes back (one enabled target answers again after "
            "having been down). With `until` too, the first condition met wins. Both unset = manual resume."
        ),
    )


class IpOut(BaseModel):
    id: int
    vlan_id: int = Field(description="`id` of the VLAN resource owning this address.")
    address: str
    status: IPStatus = Field(description=STATUS_DOC)
    hostname: str | None
    mac: str | None
    device_label: str | None
    hardware: str | None
    location: str | None
    description: str | None
    health: Health | None = Field(
        description=HEALTH_DOC
        + " Worst of the enabled monitor targets; null without any. Real state, even while paused."
    )
    paused: bool = Field(
        description=(
            "Paused on purpose (e.g. host powered off): still checked, but left out of GET /problems, "
            "of `down` counters and of the VLAN health."
        )
    )
    pause: PauseOut | None = Field(description="Pause details; null when not paused.")
    last_checked_at: UtcDatetime | None
    monitors: list[MonitorOut]
    created_at: UtcDatetime
    updated_at: UtcDatetime


class NextFree(BaseModel):
    address: str = Field(description="Lowest allocatable address right now (not reserved by this call).")


# --------------------------------------------------------------------------- VLAN


class VlanCreate(Strict):
    name: str
    cidr: str = Field(description="IPv4 network, strict CIDR. Must not overlap another VLAN.", examples=["192.168.10.0/24"])
    vlan_tag: int | None = Field(None, description="Optional 802.1Q tag, 1-4094.")
    gateway: str | None = Field(None, description="Optional gateway, inside the CIDR.")
    description: str | None = None
    notes: str | None = None


class VlanUpdate(Strict):
    name: str | None = None
    cidr: str | None = Field(None, description="All recorded addresses must remain inside the new CIDR.")
    vlan_tag: int | None = None
    gateway: str | None = None
    description: str | None = None
    notes: str | None = None


class VlanOut(BaseModel):
    id: int
    name: str
    description: str | None
    vlan_tag: int | None = Field(description="802.1Q tag (not the resource id).")
    cidr: str
    gateway: str | None
    notes: str | None
    netmask: str
    first_usable: str
    last_usable: str
    capacity: int = Field(description="Number of usable host addresses.")
    recorded_ips: int = Field(description="Addresses recorded in this VLAN, whatever their status.")
    occupancy_percent: float
    health: Health | None = Field(
        description="Worst health among the VLAN addresses (paused ones excluded); null if nothing is monitored."
    )
    created_at: UtcDatetime
    updated_at: UtcDatetime


class Problem(BaseModel):
    health: Health
    last_ok_at: UtcDatetime | None = Field(description="Last successful check, null if never.")
    vlan_id: int
    vlan_name: str
    ip: IpOut


# -------------------------------------------------------------------------- Audit


class AuditOut(BaseModel):
    id: int
    ts: UtcDatetime
    username: str = Field(description="User name, or service-account name for API actions.")
    via_api: bool
    api_key: str | None = Field(description="Name and prefix of the API key used, for API actions.")
    action: str
    entity_type: str
    entity_id: int | None
    changes: dict[str, Any] | None = Field(description="Per-field `{before, after}`.")
