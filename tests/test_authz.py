"""Autorisation : rôle user en lecture seule (403), garde-fou dernier manager, CSRF."""

from tests.conftest import ADMIN_PASSWORD, get_csrf, login


async def create_user(http, csrf: str, username: str, password: str, role: str) -> None:
    response = await http.post(
        "/users",
        data={"username": username, "password": password, "role": role},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 204, response.text


class TestRoleUser:
    async def test_user_recoit_403_sur_mutation(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        await create_user(client, csrf, "bob", "bobpassword", "user")
        await client.post("/logout", headers={"X-CSRF-Token": csrf})

        csrf_bob = await login(client, "bob", "bobpassword")
        for method, url, data in [
            ("POST", "/subnets", {"name": "x", "cidr": "10.1.0.0/24"}),
            ("POST", "/reseau", {"name": "x"}),
            ("DELETE", "/subnets/1", None),
        ]:
            response = await client.request(
                method, url, data=data, headers={"X-CSRF-Token": csrf_bob}
            )
            assert response.status_code == 403, f"{method} {url} → {response.status_code}"

    async def test_user_ne_voit_pas_les_controles(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        await create_user(client, csrf, "bob", "bobpassword", "user")
        await client.post("/logout", headers={"X-CSRF-Token": csrf})

        await login(client, "bob", "bobpassword")
        response = await client.get("/")
        assert response.status_code == 200
        assert "Lecture seule" in response.text  # badge RO (locale fr par défaut)
        assert "Nouveau VLAN" not in response.text

    async def test_user_interdit_sur_users(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        await create_user(client, csrf, "bob", "bobpassword", "user")
        await client.post("/logout", headers={"X-CSRF-Token": csrf})

        csrf_bob = await login(client, "bob", "bobpassword")
        assert (await client.get("/users")).status_code == 403
        response = await client.post(
            "/users",
            data={"username": "eve", "password": "evepassword", "role": "manager"},
            headers={"X-CSRF-Token": csrf_bob},
        )
        assert response.status_code == 403


class TestDernierManager:
    async def test_retrograder_dernier_manager_refuse(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        response = await client.patch(
            "/users/1", data={"role": "user", "is_active": "on"}, headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 422
        assert "dernier manager" in response.text

    async def test_supprimer_dernier_manager_refuse(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        response = await client.delete("/users/1", headers={"X-CSRF-Token": csrf})
        assert response.status_code == 422

    async def test_retrogradation_possible_avec_un_autre_manager(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        await create_user(client, csrf, "boss2", "boss2password", "manager")
        response = await client.patch(
            "/users/1", data={"role": "user", "is_active": "on"}, headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 204


class TestCsrf:
    async def test_mutation_sans_jeton_refusee(self, client):
        await login(client, "admin", ADMIN_PASSWORD)
        response = await client.post("/subnets", data={"name": "x", "cidr": "10.1.0.0/24"})
        assert response.status_code == 403

    async def test_mutation_avec_jeton_acceptee(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        response = await client.post(
            "/subnets", data={"name": "x", "cidr": "10.1.0.0/24"}, headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 204


class TestAntiBruteForce:
    async def test_backoff_apres_echecs(self, client):
        csrf = await get_csrf(client)
        for _ in range(5):
            response = await client.post(
                "/login",
                data={"username": "admin", "password": "mauvais", "csrf_token": csrf},
            )
            assert response.status_code == 422
        response = await client.post(
            "/login", data={"username": "admin", "password": "mauvais", "csrf_token": csrf}
        )
        assert response.status_code == 429


class TestNonAuthentifie:
    async def test_redirection_login(self, client):
        response = await client.get("/")
        assert response.status_code == 302
        assert response.headers["location"] == "/login"

    async def test_htmx_hx_redirect(self, client):
        response = await client.get("/", headers={"HX-Request": "true"})
        assert response.status_code == 401
        assert response.headers["hx-redirect"] == "/login"


class TestCertificatTls:
    async def test_section_visible_des_managers(self, client):
        from app import tls

        await login(client, "admin", ADMIN_PASSWORD)
        page = (await client.get("/reseau/edit")).text
        info = tls.current()
        assert "data-tls-section" in page and "Certificat TLS" in page
        assert info.sha256 in page and info.spki_sha256 in page and "Auto-signé" in page

    async def test_section_absente_pour_les_utilisateurs(self, client):
        from app import tls

        csrf = await login(client, "admin", ADMIN_PASSWORD)
        await create_user(client, csrf, "bob", "bobpassword", "user")
        await client.post("/logout", headers={"X-CSRF-Token": csrf})

        await login(client, "bob", "bobpassword")
        response = await client.get("/reseau/edit")
        assert response.status_code == 403
        assert "data-tls-section" not in response.text and tls.current().sha256 not in response.text
        # Ni ailleurs dans les pages qu'un utilisateur peut voir.
        for url in ["/", "/dashboard/stats"]:
            page = await client.get(url)
            assert page.status_code == 200
            assert tls.current().sha256 not in page.text and tls.current().spki_sha256 not in page.text
