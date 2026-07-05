"""Import / export CSV : import tolérant (alias Excel courants), export round-trip."""

import csv
import io
from dataclasses import dataclass, field

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.i18n import gettext as _
from app.models import IPAddress, IPStatus, Subnet, utcnow
from app.services import ipam

# En-têtes canoniques de l'export (le round-trip import/export les réutilise).
EXPORT_COLUMNS = ["subnet_cidr", "address", "status", "hostname", "mac", "device_label", "description"]

# Alias de colonnes tolérés à l'import (clés normalisées : minuscules, sans accents).
COLUMN_ALIASES: dict[str, str] = {
    # subnet
    "subnet_cidr": "subnet_cidr", "subnet": "subnet_cidr", "cidr": "subnet_cidr",
    "vlan": "subnet_cidr", "reseau": "subnet_cidr", "network": "subnet_cidr",
    "plage": "subnet_cidr",
    # address
    "address": "address", "ip": "address", "adresse": "address",
    "adresse ip": "address", "ip address": "address", "addresse": "address",
    # status
    "status": "status", "statut": "status", "etat": "status", "state": "status",
    # hostname
    "hostname": "hostname", "host": "hostname", "nom": "hostname",
    "nom d'hote": "hostname", "machine": "hostname", "dns": "hostname",
    # mac
    "mac": "mac", "adresse mac": "mac", "mac address": "mac", "macaddress": "mac",
    # device_label
    "device_label": "device_label", "device": "device_label", "appareil": "device_label",
    "equipement": "device_label", "label": "device_label", "libelle": "device_label",
    "type": "device_label", "modele": "device_label",
    # description
    "description": "description", "commentaire": "description", "comment": "description",
    "notes": "description", "note": "description", "remarque": "description",
}

STATUS_ALIASES: dict[str, IPStatus] = {
    "libre": IPStatus.libre, "free": IPStatus.libre, "disponible": IPStatus.libre,
    "utilisee": IPStatus.utilisee, "utilise": IPStatus.utilisee, "used": IPStatus.utilisee,
    "active": IPStatus.utilisee, "actif": IPStatus.utilisee, "en service": IPStatus.utilisee,
    "reservee": IPStatus.reservee, "reserve": IPStatus.reservee, "reserved": IPStatus.reservee,
    "dhcp": IPStatus.reservee,
}

_ACCENT_MAP = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")


def _normalize_key(raw: str) -> str:
    return raw.strip().lower().translate(_ACCENT_MAP).replace("_", " ").replace("-", " ").strip()


def map_columns(header: list[str]) -> dict[int, str]:
    """Associe chaque index de colonne du CSV à un champ canonique (colonnes inconnues ignorées)."""
    mapping: dict[int, str] = {}
    seen: set[str] = set()
    for idx, raw in enumerate(header):
        key = _normalize_key(raw)
        canonical = COLUMN_ALIASES.get(key) or COLUMN_ALIASES.get(key.replace(" ", "_"))
        if canonical and canonical not in seen:
            mapping[idx] = canonical
            seen.add(canonical)
    return mapping


def parse_status(raw: str | None) -> IPStatus:
    if not raw or not raw.strip():
        return IPStatus.utilisee
    key = _normalize_key(raw)
    return STATUS_ALIASES.get(key, IPStatus.utilisee)


@dataclass
class ImportReport:
    created: int = 0
    subnets_created: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _sniff_reader(text: str) -> csv.reader:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return csv.reader(io.StringIO(text), dialect)


async def import_csv(session: AsyncSession, content: bytes) -> ImportReport:
    """Import tolérant : alias de colonnes, doublons ignorés, subnets auto-créés."""
    report = ImportReport()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = _sniff_reader(text)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        report.errors.append(_("The file is empty."))
        return report

    mapping = map_columns(rows[0])
    if "address" not in mapping.values():
        report.errors.append(_("No IP address column found in the file."))
        return report

    subnets = list((await session.exec(select(Subnet))).all())
    ips_by_subnet: dict[int, list[IPAddress]] = {}
    for subnet in subnets:
        result = await session.exec(select(IPAddress).where(IPAddress.subnet_id == subnet.id))
        ips_by_subnet[subnet.id] = list(result.all())

    for line_no, row in enumerate(rows[1:], start=2):
        record = {field: row[idx].strip() if idx < len(row) else "" for idx, field in mapping.items()}
        address = record.get("address", "")
        if not address:
            report.skipped += 1
            continue
        try:
            parsed = ipam.parse_address(address)
        except ipam.ConflictError as exc:
            report.errors.append(_("Line %(line)d: %(error)s") % {"line": line_no, "error": exc.message})
            continue

        subnet = _find_subnet(subnets, parsed, record.get("subnet_cidr"))
        if subnet is None:
            subnet, error = await _create_subnet_for(session, subnets, parsed, record.get("subnet_cidr"))
            if error:
                report.errors.append(_("Line %(line)d: %(error)s") % {"line": line_no, "error": error})
                continue
            subnets.append(subnet)
            ips_by_subnet[subnet.id] = []
            report.subnets_created += 1

        existing = ips_by_subnet[subnet.id]
        if any(ip.address_int == int(parsed) for ip in existing):
            report.skipped += 1
            continue
        try:
            ipam.validate_ip(str(parsed), subnet, existing)
            mac = ipam.normalize_mac(record.get("mac") or None)
        except ipam.ConflictError as exc:
            report.errors.append(_("Line %(line)d: %(error)s") % {"line": line_no, "error": exc.message})
            continue

        ip = IPAddress(
            subnet_id=subnet.id,
            address=str(parsed),
            address_int=int(parsed),
            hostname=record.get("hostname") or None,
            mac=mac,
            device_label=record.get("device_label") or None,
            description=record.get("description") or None,
            status=parse_status(record.get("status")),
        )
        session.add(ip)
        existing.append(ip)
        report.created += 1

    await session.commit()
    return report


def _find_subnet(subnets: list[Subnet], address, cidr_hint: str | None) -> Subnet | None:
    import ipaddress as ipa

    if cidr_hint and cidr_hint.strip():
        for subnet in subnets:
            if subnet.cidr == cidr_hint.strip():
                return subnet
    for subnet in subnets:
        if address in ipa.ip_network(subnet.cidr):
            return subnet
    return None


async def _create_subnet_for(
    session: AsyncSession, subnets: list[Subnet], address, cidr_hint: str | None
) -> tuple[Subnet | None, str | None]:
    """Crée le subnet depuis l'indice CIDR, ou un /24 englobant par défaut."""
    import ipaddress as ipa

    if cidr_hint and cidr_hint.strip():
        cidr = cidr_hint.strip()
    else:
        cidr = str(ipa.ip_network(f"{address}/24", strict=False))
    try:
        network = ipam.validate_subnet(cidr, None, subnets)
    except ipam.ConflictError as exc:
        return None, exc.message
    subnet = Subnet(name=str(network), cidr=str(network))
    session.add(subnet)
    await session.flush()
    return subnet, None


async def export_csv(session: AsyncSession) -> str:
    """Export cohérent avec le format d'import (round-trip)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    result = await session.exec(
        select(IPAddress, Subnet.cidr)
        .join(Subnet, IPAddress.subnet_id == Subnet.id)  # type: ignore[arg-type]
        .order_by(Subnet.cidr, IPAddress.address_int)
    )
    for ip, cidr in result.all():
        writer.writerow(
            [
                cidr,
                ip.address,
                ip.status.value,
                ip.hostname or "",
                ip.mac or "",
                ip.device_label or "",
                ip.description or "",
            ]
        )
    return buffer.getvalue()
