"""En-tête : menu « Réseaux » (VLAN triés numériquement) et menu « Administration », tout à droite, selon le rôle."""

from app.services.ipam import network_sort_key
from tests.conftest import ADMIN_PASSWORD, login
from tests.test_authz import create_user


def nav_html(page: str) -> str:
    start = page.index('aria-label="Menu principal"')
    return page[start : page.index("</nav>", start)]


def header_html(page: str) -> str:
    """En-tête de page complet : navigation principale, puis outils, utilisateur et Administration."""
    start = page.index("<header")
    return page[start : page.index("</header>", start)]


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
    header = header_html((await client.get("/subnets/1")).text)
    for entry in ("Paramètres du réseau", "Journal d'audit", "Utilisateurs", "Comptes de service"):
        assert entry in header


async def test_menu_administration_tout_a_droite_apres_l_utilisateur(client):
    await login(client, "admin", ADMIN_PASSWORD)
    page = (await client.get("/audit")).text
    header = header_html(page)
    # Hors de la navigation principale, et dernier élément de l'en-tête : après le menu utilisateur.
    assert "Administration" not in nav_html(page)
    assert header.index("</nav>") < header.index('action="/logout"') < header.index("Administration")
    # Son panneau s'ouvre aligné à droite pour ne pas sortir de l'écran.
    panel = header[header.index("Administration") :]
    assert "absolute right-0" in panel[: panel.index("Journal d'audit")]


async def test_menu_lecture_seule_sans_entrees_manager(client):
    csrf = await login(client, "admin", ADMIN_PASSWORD)
    await create_vlan(client, csrf, "Clients", "10.0.10.0/24")
    await create_user(client, csrf, "bob", "bobpassword", "user")
    await client.post("/logout", headers={"X-CSRF-Token": csrf})

    await login(client, "bob", "bobpassword")
    header = header_html((await client.get("/audit")).text)
    assert "Clients" in header and "Journal d'audit" in header
    for entry in ("Nouveau VLAN", "Paramètres du réseau", "Utilisateurs", "Comptes de service"):
        assert entry not in header
