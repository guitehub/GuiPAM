"""Session : « Rester connecté », expiration, invalidation au changement de mot de passe."""

import json
import time
from base64 import b64encode

import itsdangerous
from httpx import AsyncClient

from app.session import SessionMiddleware
from tests.conftest import ADMIN_PASSWORD, get_csrf

SECRET = "test-secret-key-0123456789abcdef"


def session_set_cookie(response) -> str:
    cookies = [c for c in response.headers.get_list("set-cookie") if c.startswith("session=")]
    assert cookies, "pas de cookie de session"
    return cookies[-1]


async def post_login(http, remember: bool, password: str = ADMIN_PASSWORD):
    csrf = await get_csrf(http)
    data = {"username": "admin", "password": password, "csrf_token": csrf}
    if remember:
        data["remember"] = "true"
    response = await http.post("/login", data=data)
    assert response.status_code == 303, response.text
    return response, csrf


class TestRememberMe:
    async def test_sans_case_cookie_de_navigateur(self, client):
        response, _ = await post_login(client, remember=False)
        cookie = session_set_cookie(response)
        assert "Max-Age" not in cookie
        assert "httponly" in cookie.lower()

    async def test_avec_case_cookie_persistant(self, client):
        response, _ = await post_login(client, remember=True)
        assert "Max-Age=2592000" in session_set_cookie(response)
        # Reste persistant sur les requêtes suivantes (renouvellement glissant).
        page = await client.get("/")
        assert page.status_code == 200
        assert "Max-Age=2592000" in session_set_cookie(page)

    async def test_case_affichee_sur_la_page_de_connexion(self, client):
        page = await client.get("/login")
        assert 'name="remember"' in page.text
        assert "30" in page.text

    async def test_deconnexion_efface_le_cookie(self, client):
        _, csrf = await post_login(client, remember=True)
        response = await client.post("/logout", headers={"X-CSRF-Token": csrf})
        assert "1970" in session_set_cookie(response)
        assert (await client.get("/")).status_code == 302


class TestPasswordChange:
    async def test_changement_de_mot_de_passe_ferme_les_autres_sessions(self, client):
        _, csrf = await post_login(client, remember=True)
        # Seconde session du même compte (autre navigateur).
        async with AsyncClient(transport=client._transport, base_url="http://test") as other:
            await post_login(other, remember=True)
            assert (await other.get("/")).status_code == 200

            response = await client.post(
                "/users/1/password", data={"password": "nouveaumotdepasse"},
                headers={"X-CSRF-Token": csrf},
            )
            assert response.status_code == 204, response.text
            # La session qui a changé son propre mot de passe reste ouverte…
            assert (await client.get("/")).status_code == 200
            # … l'autre est fermée.
            assert (await other.get("/")).status_code == 302


def make_cookie(session: dict, age: float) -> str:
    """Cookie signé comme par le middleware, daté de ``age`` secondes."""
    signer = itsdangerous.TimestampSigner(SECRET)
    signer.get_timestamp = lambda: int(time.time() - age)  # type: ignore[method-assign]
    return signer.sign(b64encode(json.dumps(session).encode())).decode()


class TestExpiry:
    def middleware(self) -> SessionMiddleware:
        return SessionMiddleware(None, SECRET, max_age=3600, remember_max_age=86400)  # type: ignore[arg-type]

    def test_session_ordinaire_expire_apres_inactivite(self):
        mw = self.middleware()
        assert mw._load(make_cookie({"user_id": 1}, age=60)) == {"user_id": 1}
        assert mw._load(make_cookie({"user_id": 1}, age=7200)) == {}

    def test_rester_connecte_dure_plus_longtemps(self):
        mw = self.middleware()
        session = {"user_id": 1, "remember": True}
        assert mw._load(make_cookie(session, age=7200)) == session
        assert mw._load(make_cookie(session, age=90000)) == {}

    def test_cookie_falsifie_ou_illisible(self):
        mw = self.middleware()
        assert mw._load("n'importe quoi") == {}
        forged = itsdangerous.TimestampSigner("autre-cle").sign(b64encode(b'{"user_id": 1}')).decode()
        assert mw._load(forged) == {}
        assert mw._load(itsdangerous.TimestampSigner(SECRET).sign(b64encode(b"[1]")).decode()) == {}
