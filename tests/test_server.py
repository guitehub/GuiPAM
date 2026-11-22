"""Écouteurs réels (sockets) : HTTPS, redirection, proxy de confiance, cookies Secure, TLS off."""

import asyncio
import contextlib
import hashlib
import socket
import ssl
from datetime import timedelta

import httpx
import pytest
from cryptography import x509

import app.config as config_module
from app import server, tls
from app.services.auth import login_rate_limiter
from tests.conftest import ADMIN_PASSWORD


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def ports(test_env, monkeypatch):
    https_port, http_port = free_port(), free_port()
    monkeypatch.setenv("GUIPAM_HOST", "127.0.0.1")
    monkeypatch.setenv("GUIPAM_HTTPS_PORT", str(https_port))
    monkeypatch.setenv("GUIPAM_HTTP_PORT", str(http_port))
    monkeypatch.setenv("GUIPAM_SECURE_COOKIES", "true")
    config_module.get_settings.cache_clear()
    return https_port, http_port


@contextlib.asynccontextmanager
async def running(**env):
    """Démarre les écouteurs comme `python -m app.server` (sans signaux), les arrête en sortie."""
    import os

    for key, value in env.items():
        os.environ[f"GUIPAM_{key.upper()}"] = value
    config_module.get_settings.cache_clear()
    try:
        settings = config_module.get_settings()
        info = tls.prepare(settings)
        from app.main import create_app

        listeners = server.build_listeners(settings, create_app(), info)
        stop = asyncio.Event()
        task = asyncio.create_task(server.serve_listeners(listeners, install_signal_handlers=False, shutdown=stop))
        for _ in range(200):  # tous les écouteurs acceptent des connexions
            if all([await _accepts(listener.config.port) for listener in listeners]):
                break
            assert not task.done(), task.result()
            await asyncio.sleep(0.05)
        try:
            yield settings
        finally:
            stop.set()
            assert await asyncio.wait_for(task, 10) == 0
    finally:
        for key in env:
            os.environ.pop(f"GUIPAM_{key.upper()}", None)


async def _accepts(port: int) -> bool:
    try:
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
    except OSError:
        return False
    writer.close()
    return True


def served_sha256(port: int) -> str:
    pem = ssl.get_server_certificate(("127.0.0.1", port))
    der = ssl.PEM_cert_to_DER_cert(pem)
    return ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest())


def cookie_header(response: httpx.Response) -> dict:
    """En-tête Cookie rejoué à la main : httpx (à raison) ne renvoie pas un cookie Secure sur http://,
    alors que derrière un proxy TLS c'est bien ce que fait le navigateur, qui voit de l'HTTPS."""
    pairs = [value.split(";", 1)[0] for value in response.headers.get_list("set-cookie")]
    return {"cookie": "; ".join(pairs)} if pairs else {}


async def login_form(http: httpx.AsyncClient, base: str, headers=None, password=ADMIN_PASSWORD) -> httpx.Response:
    headers = headers or {}
    page = await http.get(f"{base}/login", headers=headers)
    marker = 'name="csrf_token" value="'
    start = page.text.index(marker) + len(marker)
    csrf = page.text[start : page.text.index('"', start)]
    return await http.post(
        f"{base}/login",
        data={"username": "admin", "password": password, "csrf_token": csrf},
        headers={**headers, **cookie_header(page)},
    )


class TestRedirect:
    async def test_308_vers_https_et_healthz_direct(self, ports):
        https_port, http_port = ports
        async with running():
            async with httpx.AsyncClient() as http:
                response = await http.get(f"http://127.0.0.1:{http_port}/subnets/3?q=a%20b")
                assert response.status_code == 308
                assert response.headers["location"] == f"https://127.0.0.1:{https_port}/subnets/3?q=a%20b"
                post = await http.post(f"http://127.0.0.1:{http_port}/login", data={"a": "b"})
                assert post.status_code == 308  # 308 : la méthode et le corps sont conservés
                ipv6 = await http.get(f"http://127.0.0.1:{http_port}/", headers={"host": "[fd00::1]:8080"})
                assert ipv6.headers["location"] == f"https://[fd00::1]:{https_port}/"
                bad = await http.get(f"http://127.0.0.1:{http_port}/", headers={"host": "evil/x"})
                assert bad.status_code == 400
                health = await http.get(f"http://127.0.0.1:{http_port}/healthz")
                assert health.status_code == 200 and health.json() == {"status": "ok"}
                # La redirection ne sert rien de l'application, pas même la page de connexion.
                api = await http.get(f"http://127.0.0.1:{http_port}/api/v1/openapi.json")
                assert api.status_code == 308

    async def test_port_public_different(self, ports):
        _https_port, http_port = ports
        async with running(public_https_port="443"):
            async with httpx.AsyncClient() as http:
                response = await http.get(f"http://127.0.0.1:{http_port}/x", headers={"host": "guipam.example.net"})
                assert response.headers["location"] == "https://guipam.example.net/x"


class TestHttps:
    async def test_certificat_servi_et_connexion_cookie_secure(self, ports):
        https_port, _http_port = ports
        async with running():
            info = tls.current()
            assert await asyncio.to_thread(served_sha256, https_port) == info.sha256
            # Client qui fait confiance au certificat épinglé (pas de verify=False).
            context = ssl.create_default_context(cafile=str(info.certfile))
            async with httpx.AsyncClient(verify=context) as http:
                base = f"https://localhost:{https_port}"
                response = await login_form(http, base)
                assert response.status_code == 303
                set_cookie = response.headers["set-cookie"].lower()
                assert "secure" in set_cookie and "httponly" in set_cookie
                dashboard = await http.get(f"{base}/", headers=cookie_header(response))
                assert dashboard.status_code == 200 and "/logout" in dashboard.text

    async def test_https_ignore_x_forwarded_for(self, ports):
        https_port, _http_port = ports
        async with running(http_mode="proxy", trusted_proxies="127.0.0.1"):
            async with httpx.AsyncClient(verify=False) as http:
                await login_form(http, f"https://127.0.0.1:{https_port}", {"x-forwarded-for": "203.0.113.9"}, "bad")
        assert ("127.0.0.1", "admin") in login_rate_limiter._states
        assert ("203.0.113.9", "admin") not in login_rate_limiter._states

    async def test_rechargement_a_chaud(self, ports):
        https_port, _http_port = ports
        async with running() as settings:
            first = tls.current()
            assert tls.refresh(settings, now=first.not_after - timedelta(days=5)) is True
            renewed = await asyncio.to_thread(served_sha256, https_port)
            assert renewed == tls.current().sha256 != first.sha256
            pem = await asyncio.to_thread(ssl.get_server_certificate, ("127.0.0.1", https_port))
            assert tls.spki_sha256(x509.load_pem_x509_certificate(pem.encode())) == first.spki_sha256


class TestProxy:
    async def test_application_servie_ip_du_proxy_de_confiance(self, ports):
        _https_port, http_port = ports
        async with running(http_mode="proxy", trusted_proxies="10.9.0.0/16, 127.0.0.1"):
            async with httpx.AsyncClient() as http:
                base = f"http://127.0.0.1:{http_port}"
                headers = {"x-forwarded-for": "203.0.113.9", "x-forwarded-proto": "https"}
                assert (await login_form(http, base, headers, "bad")).status_code == 422
                assert ("203.0.113.9", "admin") in login_rate_limiter._states
                # Connexion via le proxy : le navigateur voit de l'HTTPS, le cookie Secure est valide.
                response = await login_form(http, base, headers)
                assert response.status_code == 303 and "secure" in response.headers["set-cookie"].lower()
                dashboard = await http.get(f"{base}/", headers={**headers, **cookie_header(response)})
                assert dashboard.status_code == 200 and "/logout" in dashboard.text

    async def test_x_forwarded_for_ignore_hors_proxies_de_confiance(self, ports):
        _https_port, http_port = ports
        async with running(http_mode="proxy", trusted_proxies="10.9.0.1"):
            async with httpx.AsyncClient() as http:
                await login_form(http, f"http://127.0.0.1:{http_port}", {"x-forwarded-for": "203.0.113.9"}, "bad")
        assert ("127.0.0.1", "admin") in login_rate_limiter._states
        assert ("203.0.113.9", "admin") not in login_rate_limiter._states

    async def test_sans_proxies_declares(self, ports):
        _https_port, http_port = ports
        async with running(http_mode="proxy"):
            async with httpx.AsyncClient() as http:
                await login_form(http, f"http://127.0.0.1:{http_port}", {"x-forwarded-for": "203.0.113.9"}, "bad")
        assert list(login_rate_limiter._states) == [("127.0.0.1", "admin")]


class TestModes:
    async def test_http_off(self, ports):
        https_port, http_port = ports
        async with running(http_mode="off") as settings:
            assert [listener.name for listener in server.build_listeners(settings, None, tls.current())] == ["https"]
            assert not await _accepts(http_port)
            async with httpx.AsyncClient(verify=False) as http:
                assert (await http.get(f"https://127.0.0.1:{https_port}/healthz")).status_code == 200

    async def test_tls_off_comportement_0_5(self, ports):
        https_port, http_port = ports
        async with running(tls="off", secure_cookies="false"):
            assert tls.current().mode == "off"
            assert not await _accepts(https_port)
            async with httpx.AsyncClient() as http:
                response = await login_form(http, f"http://127.0.0.1:{http_port}")
                assert response.status_code == 303 and "secure" not in response.headers["set-cookie"].lower()


class TestStartup:
    def test_echec_de_demarrage_port_occupe(self, ports):
        https_port, _ = ports
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", https_port))
            busy.listen()
            settings = config_module.get_settings()
            info = tls.prepare(settings)
            from app.main import create_app

            listeners = server.build_listeners(settings, create_app(), info)
            assert asyncio.run(server.serve_listeners(listeners, install_signal_handlers=False)) != 0


class TestConfig:
    def make(self, **values):
        from app.config import Settings

        return Settings(_env_file=None, **values)

    def test_defauts(self):
        settings = self.make()
        assert (settings.tls, settings.http_mode, settings.https_port, settings.http_port) == ("auto", "redirect", 8443, 8080)
        assert settings.secure_cookies is True and settings.startup_warnings() == []

    def test_alias_port_deprecie(self, monkeypatch):
        monkeypatch.setenv("GUIPAM_PORT", "9000")
        settings = self.make()
        assert settings.http_port == 9000
        assert any("GUIPAM_PORT est dépréciée" in w for w in settings.startup_warnings())
        monkeypatch.setenv("GUIPAM_HTTP_PORT", "9100")
        settings = self.make()
        assert settings.http_port == 9100
        assert any("GUIPAM_PORT est ignorée" in w for w in settings.startup_warnings())

    def test_avertissements(self):
        assert any("GUIPAM_TLS=off" in w for w in self.make(tls="off").startup_warnings())
        assert any("SECURE_COOKIES=false" in w for w in self.make(secure_cookies=False).startup_warnings())
        # TLS off + cookies non Secure : configuration 0.5 assumée, un seul avertissement (TLS off).
        assert len(self.make(tls="off", secure_cookies=False).startup_warnings()) == 1
        assert any("TRUSTED_PROXIES" in w for w in self.make(http_mode="proxy").startup_warnings())
        assert self.make(http_mode="proxy", trusted_proxies="172.18.0.0/16").startup_warnings() == []

    def test_valeurs_insensibles_a_la_casse(self):
        assert self.make(tls="OFF", http_mode=" Proxy").http_mode == "proxy"

    def test_proxies_invalides_refuses(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="ni une adresse IP ni un réseau CIDR"):
            self.make(trusted_proxies="10.0.0.1, traefik")
        assert self.make(trusted_proxies=" 10.0.0.1 ,fd00::/8,").trusted_proxy_list == ["10.0.0.1", "fd00::/8"]

    def test_mode_proxy_sans_proxies_n_active_pas_les_en_tetes(self):
        settings = self.make(http_mode="proxy")
        listeners = server.build_listeners(settings, None, tls.TlsInfo(mode="auto", certfile="c", keyfile="k"))
        assert [listener.name for listener in listeners] == ["https", "http-proxy"]
        assert listeners[1].config.proxy_headers is False and listeners[0].config.proxy_headers is False
