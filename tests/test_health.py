"""Tests du code couleur santé (§7.3) : chaque transition, et ip_health = pire cible."""

from datetime import timedelta

from app.models import CheckStatus, MonitorTarget, utcnow
from app.services.monitor import Health, health, ip_health

WARN = 120
RED = 600
DARK = 3600

NOW = utcnow()


def target(status: CheckStatus, ok_age: float | None, failures: int = 0, enabled: bool = True) -> MonitorTarget:
    return MonitorTarget(
        ip_id=1,
        enabled=enabled,
        last_status=status,
        last_ok_at=NOW - timedelta(seconds=ok_age) if ok_age is not None else None,
        consecutive_failures=failures,
    )


def h(t: MonitorTarget) -> Health:
    return health(t, NOW, warn_seconds=WARN, red_seconds=RED, dark_red_seconds=DARK)


class TestTransitions:
    def test_jamais_verifie_gris(self):
        assert h(target(CheckStatus.unknown, None)) == Health.unknown

    def test_up_recent_vert(self):
        assert h(target(CheckStatus.up, ok_age=10)) == Health.ok

    def test_up_limite_warn_encore_vert(self):
        assert h(target(CheckStatus.up, ok_age=WARN)) == Health.ok

    def test_up_vieillissant_ambre(self):
        assert h(target(CheckStatus.up, ok_age=WARN + 1)) == Health.warn

    def test_down_recent_ambre(self):
        assert h(target(CheckStatus.down, ok_age=RED)) == Health.warn

    def test_down_un_moment_rouge(self):
        assert h(target(CheckStatus.down, ok_age=RED + 1)) == Health.red

    def test_down_limite_dark_encore_rouge(self):
        assert h(target(CheckStatus.down, ok_age=DARK)) == Health.red

    def test_down_stale_rouge_fonce(self):
        assert h(target(CheckStatus.down, ok_age=DARK + 1)) == Health.dark_red

    def test_jamais_de_succes_echecs_repetes_rouge_fonce(self):
        assert h(target(CheckStatus.down, ok_age=None, failures=3)) == Health.dark_red

    def test_jamais_de_succes_premiers_echecs_rouge(self):
        assert h(target(CheckStatus.down, ok_age=None, failures=1)) == Health.red


class TestIpHealth:
    def test_pire_cible_gagne(self):
        targets = [
            target(CheckStatus.up, ok_age=10),
            target(CheckStatus.down, ok_age=DARK + 100),
        ]
        assert ip_health(targets, NOW) == Health.dark_red

    def test_cibles_desactivees_ignorees(self):
        targets = [
            target(CheckStatus.up, ok_age=10),
            target(CheckStatus.down, ok_age=DARK + 100, enabled=False),
        ]
        assert ip_health(targets, NOW) == Health.ok

    def test_aucune_cible_active(self):
        assert ip_health([], NOW) is None
        assert ip_health([target(CheckStatus.up, 10, enabled=False)], NOW) is None

    def test_unknown_pire_que_ok(self):
        targets = [target(CheckStatus.up, ok_age=10), target(CheckStatus.unknown, None)]
        assert ip_health(targets, NOW) == Health.unknown
