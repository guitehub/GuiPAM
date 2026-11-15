"""Navigation principale : menu « Réseaux » (VLAN triés numériquement) et « Administration » selon le rôle."""

from app.services.ipam import network_sort_key
from tests.conftest import ADMIN_PASSWORD, login
from tests.test_authz import create_user


def nav_html(page: str) -> str:
    start = page.index('aria-label="Menu principal"')
    return page[start : page.index("</nav>", start)]


async def create_vlan(http, csrf: str, name: str, cidr: str) -> None:
    response = await http.post("/subnets", data={"name": name, "cidr": cidr}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204, response.text


def test_network_sort_key_numerique():
    cidrs = ["192.168.1.0/24", "10.0.10.0/24", "10.0.2.0/24", "10.0.0.0/16"]
    assert sorted(cidrs, key=network_sort_key) == ["10.0.0.0/16", "10.0.2.0/24", "10.0.10.0/24", "192.168.1.0/24"]


async def test_menu_reseaux_liste_les_vlan_dans_l_ordre(client):
    csrf = await login(client, "admin", ADMIN_PASSWORD)
    await create_vlan(client, csrf, "Clients", "10.0.10.0/24")
    await create_vlan(client, csrf, "Serveurs", "10.0.2.0/24")

    nav = nav_html((await client.get("/subnets/1")).text)
    assert "Réseaux" in nav
    assert nav.index("Serveurs") < nav.index("Clients")
    # VLAN courant mis en évidence, l'autre non.
    assert 'href="/subnets/1"' in nav
    current = nav[nav.index('href="/subnets/1"') :]
    assert 'aria-current="page"' in current[: current.index("</a>")]
    assert "Nouveau VLAN" in nav
    for entry in ("Paramètres du réseau", "Journal d'audit", "Utilisateurs", "Comptes de service"):
        assert entry in nav


async def test_menu_lecture_seule_sans_entrees_manager(client):
    csrf = await login(client, "admin", ADMIN_PASSWORD)
    await create_vlan(client, csrf, "Clients", "10.0.10.0/24")
    await create_user(client, csrf, "bob", "bobpassword", "user")
    await client.post("/logout", headers={"X-CSRF-Token": csrf})

    await login(client, "bob", "bobpassword")
    nav = nav_html((await client.get("/audit")).text)
    assert "Clients" in nav and "Journal d'audit" in nav
    for entry in ("Nouveau VLAN", "Paramètres du réseau", "Utilisateurs", "Comptes de service"):
        assert entry not in nav
