"""Logique IPAM centralisée : validation, détection de conflits, dérivés.

Toutes les règles de conflit (§6 du cahier des charges) vivent ici.
Les messages sont localisés via gettext au moment où l'erreur est levée.
"""

import ipaddress
import re
from dataclasses import dataclass

from app.i18n import gettext as _
from app.models import IPAddress, Subnet

# Au-delà de cette taille, la vue plan est tronquée (un /16 = 65 534 lignes).
PLAN_MAX_HOSTS = 4096


class ConflictError(Exception):
    """Erreur de validation IPAM, message localisé prêt pour l'UI."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


def parse_cidr(cidr: str) -> ipaddress.IPv4Network:
    """Valide un CIDR IPv4 strict (l'adresse doit être l'adresse réseau)."""
    value = (cidr or "").strip()
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError:
        try:
            loose = ipaddress.ip_network(value, strict=False)
        except ValueError:
            raise ConflictError(
                _("Invalid CIDR: “%s” is not a valid IPv4 network.") % value, "cidr"
            ) from None
        raise ConflictError(
            _("Invalid CIDR: “%(value)s” has host bits set (network address is %(network)s).")
            % {"value": value, "network": str(loose)},
            "cidr",
        ) from None
    if network.version != 4:
        raise ConflictError(_("Only IPv4 is supported in this version."), "cidr")
    return network


def parse_address(address: str) -> ipaddress.IPv4Address:
    value = (address or "").strip()
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        raise ConflictError(
            _("“%s” is not a valid IPv4 address.") % value, "address"
        ) from None
    if parsed.version != 4:
        raise ConflictError(_("Only IPv4 is supported in this version."), "address")
    return parsed


_MAC_CLEAN_RE = re.compile(r"[^0-9a-fA-F]")


def normalize_mac(mac: str | None) -> str | None:
    """Normalise une MAC vers le format canonique aa:bb:cc:dd:ee:ff."""
    if not mac or not mac.strip():
        return None
    digits = _MAC_CLEAN_RE.sub("", mac)
    if len(digits) != 12:
        raise ConflictError(_("“%s” is not a valid MAC address.") % mac.strip(), "mac")
    digits = digits.lower()
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def validate_subnet(
    cidr: str,
    gateway: str | None,
    existing_subnets: list[Subnet],
    exclude_id: int | None = None,
) -> ipaddress.IPv4Network:
    """CIDR valide, pas de chevauchement avec un autre VLAN, gateway dans le CIDR."""
    network = parse_cidr(cidr)
    for other in existing_subnets:
        if exclude_id is not None and other.id == exclude_id:
            continue
        other_net = ipaddress.ip_network(other.cidr)
        if network.overlaps(other_net):
            raise ConflictError(
                _("CIDR %(cidr)s overlaps VLAN “%(name)s” (%(other)s).")
                % {"cidr": str(network), "name": other.name, "other": other.cidr},
                "cidr",
            )
    if gateway and gateway.strip():
        gw = parse_address(gateway)
        if gw not in network:
            raise ConflictError(
                _("Gateway %(gateway)s is outside subnet %(cidr)s.")
                % {"gateway": str(gw), "cidr": str(network)},
                "gateway",
            )
    return network


def address_prefix(cidr: str) -> str:
    """Octets communs à toutes les adresses du subnet, prêts à compléter : « 192.168.1. ».

    Seuls les octets entièrement fixés par le masque sont repris (/24 → 3 octets,
    /16 à /23 → 2, /8 à /15 → 1, en dessous → rien).
    """
    try:
        network = ipaddress.ip_network(cidr)
    except ValueError:
        return ""
    fixed = min(network.prefixlen // 8, 3)
    octets = str(network.network_address).split(".")[:fixed]
    return ".".join(octets) + "." if octets else ""


def subnet_capacity(network: ipaddress.IPv4Network) -> int:
    """Nombre d'hôtes utilisables (RFC 3021 pour /31, hôte unique pour /32)."""
    if network.prefixlen >= 31:
        return network.num_addresses
    return network.num_addresses - 2


def usable_range(
    network: ipaddress.IPv4Network,
) -> tuple[ipaddress.IPv4Address, ipaddress.IPv4Address]:
    if network.prefixlen >= 31:
        return network.network_address, network.broadcast_address
    return network.network_address + 1, network.broadcast_address - 1


def ensure_capacity(subnet: Subnet, existing_count: int) -> None:
    """Refuse d'ajouter une IP si le subnet a déjà atteint sa capacité utilisable."""
    network = ipaddress.ip_network(subnet.cidr)
    capacity = subnet_capacity(network)
    if existing_count >= capacity:
        raise ConflictError(
            _("Subnet %(cidr)s is full (%(capacity)d usable addresses).")
            % {"cidr": subnet.cidr, "capacity": capacity},
            "address",
        )


def validate_ip(
    address: str,
    subnet: Subnet,
    existing_ips: list[IPAddress],
    exclude_id: int | None = None,
) -> ipaddress.IPv4Address:
    """IP dans le CIDR du VLAN, pas réseau/broadcast, unique, capacité respectée."""
    parsed = parse_address(address)
    network = ipaddress.ip_network(subnet.cidr)
    if parsed not in network:
        raise ConflictError(
            _("Address %(address)s is outside subnet %(cidr)s.")
            % {"address": str(parsed), "cidr": subnet.cidr},
            "address",
        )
    if network.prefixlen < 31:
        if parsed == network.network_address:
            raise ConflictError(
                _("%s is the network address and cannot be assigned.") % str(parsed), "address"
            )
        if parsed == network.broadcast_address:
            raise ConflictError(
                _("%s is the broadcast address and cannot be assigned.") % str(parsed), "address"
            )
    others = [ip for ip in existing_ips if exclude_id is None or ip.id != exclude_id]
    if any(ip.address_int == int(parsed) for ip in others):
        raise ConflictError(
            _("Address %(address)s already exists in VLAN “%(name)s”.")
            % {"address": str(parsed), "name": subnet.name},
            "address",
        )
    if exclude_id is None:
        ensure_capacity(subnet, len(others))
    return parsed


@dataclass
class SubnetStats:
    network_address: str
    netmask: str
    broadcast: str
    first_usable: str
    last_usable: str
    capacity: int
    used: int

    @property
    def occupancy_percent(self) -> float:
        if self.capacity <= 0:
            return 0.0
        return round(100.0 * self.used / self.capacity, 1)


def subnet_stats(subnet: Subnet, used_count: int) -> SubnetStats:
    network = ipaddress.ip_network(subnet.cidr)
    first, last = usable_range(network)
    return SubnetStats(
        network_address=str(network.network_address),
        netmask=str(network.netmask),
        broadcast=str(network.broadcast_address),
        first_usable=str(first),
        last_usable=str(last),
        capacity=subnet_capacity(network),
        used=used_count,
    )


@dataclass
class PlanEntry:
    address: str
    ip: IPAddress | None  # None = trou (adresse libre non saisie)


def build_plan(subnet: Subnet, ips: list[IPAddress]) -> tuple[list[PlanEntry], bool]:
    """Plan complet du CIDR, trous intercalés. Retourne (entrées, tronqué)."""
    network = ipaddress.ip_network(subnet.cidr)
    by_int = {ip.address_int: ip for ip in ips}
    first, last = usable_range(network)
    entries: list[PlanEntry] = []
    truncated = False
    current = int(first)
    end = int(last)
    while current <= end:
        if len(entries) >= PLAN_MAX_HOSTS:
            truncated = True
            break
        addr = ipaddress.ip_address(current)
        entries.append(PlanEntry(address=str(addr), ip=by_int.get(current)))
        current += 1
    return entries, truncated
