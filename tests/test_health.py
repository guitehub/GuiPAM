"""Tests du code couleur santé (§7.3) : chaque transition, et ip_health = pire cible.

Les règles sont relatives à chaque cible : fraîcheur en nombre de ses intervalles, panne en
nombre d'échecs consécutifs ; seul le rouge foncé est une durée.
"""

from datetime import timedelta

from app.config import get_settings
from app.models import CheckStatus, MonitorTarget, utcnow
from app.services.monitor import Health, MonitoringSettings, health, ip_health

RULES = MonitoringSettings(
    default_check_interval=60, health_warn_intervals=2, health_red_failures=10, health_dark_red_seconds=604800
)
DARK = RULES.health_dark_red_seconds
# Le scheduler ne vérifie jamais pile à l'heure : un battement de tolérance sur la fraîcheur.
TICK = get_settings().monitor_tick_seconds

NOW = utcnow()


def target(
    status: CheckStatus,
    ok_age: float | None,
    failures: int = 0,
    enabled: bool = True,
    interval: int = 60,
) -> MonitorTarget:
    return MonitorTarget(
        ip_id=1,
        enabled=enabled,
        interval_seconds=interval,
        last_status=status,
        last_ok_at=NOW - timedelta(seconds=ok_age) if ok_age is not None else None,
        consecutive_failures=failures,
    )


def h(t: MonitorTarget) -> Health:
    return health(t, NOW, rules=RULES)


class TestTransitions:
    def test_jamais_verifie_gris(self):
        assert h(target(CheckStatus.unknown, None)) == Health.unknown

    def test_up_recent_vert(self):
        assert h(target(CheckStatus.up, ok_age=10)) == Health.ok

    def test_up_limite_warn_encore_vert(self):
        assert h(target(CheckStatus.up, ok_age=2 * 60 + TICK)) == Health.ok

    def test_up_vieillissant_ambre(self):
        assert h(target(CheckStatus.up, ok_age=2 * 60 + TICK + 1)) == Health.warn

    def test_down_premiers_echecs_ambre(self):
        assert h(target(CheckStatus.down, ok_age=300, failures=9)) == Health.warn

    def test_down_echecs_repetes_rouge(self):
        assert h(target(CheckStatus.down, ok_age=300, failures=10)) == Health.red

    def test_down_limite_dark_encore_rouge(self):
        assert h(target(CheckStatus.down, ok_age=DARK, failures=5000)) == Health.red

    def test_down_stale_rouge_fonce(self):
        assert h(target(CheckStatus.down, ok_age=DARK + 1, failures=5000)) == Health.dark_red

    def test_jamais_de_succes_echecs_repetes_rouge_fonce(self):
        assert h(target(CheckStatus.down, ok_age=None, failures=3)) == Health.dark_red

    def test_jamais_de_succes_premiers_echecs_rouge(self):
        assert h(target(CheckStatus.down, ok_age=None, failures=1)) == Health.red


class TestRythmePropreAChaqueCible:
    """Une cible lente et une cible rapide suivent la même règle, chacune à son échelle."""

    def test_cible_lente_reste_verte_entre_deux_checks(self):
        # 3 min d'intervalle : 170 s après un succès, elle est simplement entre deux vérifications.
        assert h(target(CheckStatus.up, ok_age=170, interval=180)) == Health.ok
        # La même fraîcheur est déjà douteuse pour une cible vérifiée chaque minute.
        assert h(target(CheckStatus.up, ok_age=170, interval=60)) == Health.warn

    def test_cible_lente_ambre_apres_ses_propres_intervalles(self):
        assert h(target(CheckStatus.up, ok_age=2 * 180 + TICK + 1, interval=180)) == Health.warn

    def test_rouge_au_meme_nombre_d_echecs_quel_que_soit_l_intervalle(self):
        # 10 échecs : ~10 min pour une cible à 60 s, ~30 min pour une cible à 180 s.
        assert h(target(CheckStatus.down, ok_age=600, failures=10, interval=60)) == Health.red
        assert h(target(CheckStatus.down, ok_age=600, failures=3, interval=180)) == Health.warn
        assert h(target(CheckStatus.down, ok_age=1800, failures=10, interval=180)) == Health.red

    def test_rouge_fonce_est_une_duree_meme_avec_peu_d_echecs(self):
        # Cible quotidienne : 8 échecs seulement, mais plus d'une semaine sans succès.
        assert h(target(CheckStatus.down, ok_age=8 * 86400, failures=8, interval=86400)) == Health.dark_red

    def test_seuils_reglables(self):
        strict = MonitoringSettings(
            default_check_interval=60, health_warn_intervals=1, health_red_failures=2, health_dark_red_seconds=3600
        )
        assert health(target(CheckStatus.up, ok_age=60 + TICK + 1), NOW, rules=strict) == Health.warn
        assert health(target(CheckStatus.down, ok_age=200, failures=2), NOW, rules=strict) == Health.red
        assert health(target(CheckStatus.down, ok_age=3601, failures=2), NOW, rules=strict) == Health.dark_red


class TestIpHealth:
    def test_pire_cible_gagne(self):
        targets = [
            target(CheckStatus.up, ok_age=10),
            target(CheckStatus.down, ok_age=DARK + 100),
        ]
        assert ip_health(targets, NOW, rules=RULES) == Health.dark_red

    def test_cibles_desactivees_ignorees(self):
        targets = [
            target(CheckStatus.up, ok_age=10),
            target(CheckStatus.down, ok_age=DARK + 100, enabled=False),
        ]
        assert ip_health(targets, NOW, rules=RULES) == Health.ok

    def test_aucune_cible_active(self):
        assert ip_health([], NOW, rules=RULES) is None
        assert ip_health([target(CheckStatus.up, 10, enabled=False)], NOW, rules=RULES) is None

    def test_unknown_pire_que_ok(self):
        targets = [target(CheckStatus.up, ok_age=10), target(CheckStatus.unknown, None)]
        assert ip_health(targets, NOW, rules=RULES) == Health.unknown
