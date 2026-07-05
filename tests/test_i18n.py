"""i18n : traduction fr, fallback msgid, négociation de locale."""

from app.i18n import get_translations, gettext, negotiate_locale, set_locale


class TestTraduction:
    def test_chaine_traduite_en_fr(self):
        set_locale("fr")
        assert gettext("Invalid username or password.") == "Identifiant ou mot de passe invalide."

    def test_fallback_msgid_si_locale_inconnue(self):
        set_locale("de")
        assert gettext("Invalid username or password.") == "Invalid username or password."

    def test_en_renvoie_le_msgid(self):
        set_locale("en")
        assert gettext("Dashboard") == "Dashboard"

    def test_catalogue_fr_charge(self):
        translations = get_translations("fr")
        assert translations.gettext("Cancel") == "Annuler"


class TestNegociation:
    def test_priorite_preference_utilisateur(self):
        assert negotiate_locale("en", "fr", "fr-FR", "fr") == "en"

    def test_puis_cookie(self):
        assert negotiate_locale(None, "en", "fr-FR", "fr") == "en"

    def test_puis_accept_language(self):
        assert negotiate_locale(None, None, "en-US,en;q=0.9", "fr") == "en"

    def test_puis_defaut_reseau(self):
        assert negotiate_locale(None, None, None, "en") == "en"

    def test_fallback_fr(self):
        assert negotiate_locale(None, None, None, None) == "fr"
        assert negotiate_locale("xx", "yy", "zz", "ww") == "fr"
