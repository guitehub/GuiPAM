"""Tests des règles de conflit IPAM (§6)."""

import pytest

from app.models import IPAddress, Subnet
from app.services import ipam


def subnet(cidr: str, name: str = "Test", gateway: str | None = None, id: int = 1) -> Subnet:
    return Subnet(id=id, name=name, cidr=cidr, gateway=gateway)


def ip(address: str, subnet_id: int = 1, id: int = 1) -> IPAddress:
    import ipaddress

    return IPAddress(id=id, subnet_id=subnet_id, address=address, address_int=int(ipaddress.ip_address(address)))


class TestParseCidr:
    def test_cidr_valide(self):
        assert str(ipam.parse_cidr("192.168.10.0/24")) == "192.168.10.0/24"

    def test_cidr_invalide(self):
        with pytest.raises(ipam.ConflictError):
            ipam.parse_cidr("pas-un-cidr")

    def test_cidr_bits_hote(self):
        with pytest.raises(ipam.ConflictError) as exc:
            ipam.parse_cidr("192.168.10.5/24")
        assert "192.168.10.0" in exc.value.message

    def test_ipv6_refuse(self):
        with pytest.raises(ipam.ConflictError):
            ipam.parse_cidr("2001:db8::/64")


class TestValidateSubnet:
    def test_chevauchement_interdit(self):
        existing = [subnet("192.168.10.0/24")]
        with pytest.raises(ipam.ConflictError) as exc:
            ipam.validate_subnet("192.168.10.128/25", None, existing)
        assert "192.168.10.128/25" in exc.value.message

    def test_chevauchement_englobant(self):
        existing = [subnet("192.168.10.0/24")]
        with pytest.raises(ipam.ConflictError):
            ipam.validate_subnet("192.168.0.0/16", None, existing)

    def test_pas_de_chevauchement(self):
        existing = [subnet("192.168.10.0/24")]
        network = ipam.validate_subnet("192.168.20.0/24", None, existing)
        assert str(network) == "192.168.20.0/24"

    def test_exclusion_de_soi_meme(self):
        existing = [subnet("192.168.10.0/24", id=7)]
        ipam.validate_subnet("192.168.10.0/24", None, existing, exclude_id=7)

    def test_gateway_hors_subnet(self):
        with pytest.raises(ipam.ConflictError) as exc:
            ipam.validate_subnet("192.168.10.0/24", "192.168.99.1", [])
        assert exc.value.field == "gateway"

    def test_gateway_dans_subnet(self):
        ipam.validate_subnet("192.168.10.0/24", "192.168.10.1", [])


class TestValidateIp:
    def test_ip_hors_subnet(self):
        with pytest.raises(ipam.ConflictError) as exc:
            ipam.validate_ip("10.0.0.5", subnet("192.168.10.0/24"), [])
        assert exc.value.field == "address"

    def test_ip_invalide(self):
        with pytest.raises(ipam.ConflictError):
            ipam.validate_ip("999.1.1.1", subnet("192.168.10.0/24"), [])

    def test_doublon(self):
        existing = [ip("192.168.10.5")]
        with pytest.raises(ipam.ConflictError) as exc:
            ipam.validate_ip("192.168.10.5", subnet("192.168.10.0/24"), existing)
        assert "existe" in exc.value.message or "already exists" in exc.value.message

    def test_doublon_exclu_en_edition(self):
        existing = [ip("192.168.10.5", id=3)]
        ipam.validate_ip("192.168.10.5", subnet("192.168.10.0/24"), existing, exclude_id=3)

    def test_adresse_reseau_refusee(self):
        with pytest.raises(ipam.ConflictError):
            ipam.validate_ip("192.168.10.0", subnet("192.168.10.0/24"), [])

    def test_broadcast_refuse(self):
        with pytest.raises(ipam.ConflictError):
            ipam.validate_ip("192.168.10.255", subnet("192.168.10.0/24"), [])

    def test_capacite_slash_31(self):
        # RFC 3021 : /31 = 2 adresses utilisables, réseau et broadcast autorisés
        s = subnet("192.168.10.0/31")
        ipam.validate_ip("192.168.10.0", s, [])
        ipam.validate_ip("192.168.10.1", s, [ip("192.168.10.0")])


class TestCapacity:
    def test_slash_24(self):
        import ipaddress

        assert ipam.subnet_capacity(ipaddress.ip_network("192.168.10.0/24")) == 254

    def test_capacite_depassee_signalee(self):
        s = subnet("192.168.10.0/30")  # 2 hôtes utilisables
        with pytest.raises(ipam.ConflictError) as exc:
            ipam.ensure_capacity(s, 2)
        assert "2" in exc.value.message

    def test_capacite_restante_ok(self):
        ipam.ensure_capacity(subnet("192.168.10.0/30"), 1)


class TestNormalizeMac:
    def test_formats_tolerants(self):
        for raw in ["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "AABB.CCDD.EEFF", "aabbccddeeff"]:
            assert ipam.normalize_mac(raw) == "aa:bb:cc:dd:ee:ff"

    def test_mac_invalide(self):
        with pytest.raises(ipam.ConflictError):
            ipam.normalize_mac("zz:zz:zz:zz:zz:zz")

    def test_vide(self):
        assert ipam.normalize_mac(None) is None
        assert ipam.normalize_mac("  ") is None


class TestPlan:
    def test_trous_intercales(self):
        s = subnet("192.168.10.0/29")  # 6 hôtes utilisables
        entries, truncated = ipam.build_plan(s, [ip("192.168.10.3")])
        assert not truncated
        assert len(entries) == 6
        assert [e.address for e in entries] == [f"192.168.10.{i}" for i in range(1, 7)]
        assert entries[2].ip is not None and entries[0].ip is None
