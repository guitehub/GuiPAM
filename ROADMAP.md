# Roadmap GuiPAM

## v0.1 — MVP (checklist)

- [x] Socle : FastAPI, SQLModel/SQLite (WAL), Alembic dès la v1, config `GUIPAM_*`
- [x] Auth session + rôles `manager` / `user` (lecture seule réelle : UI masquée + 403 API)
- [x] Sécurité : pas d'admin par défaut, clé de session requise, CSRF, anti-brute-force, non-root
- [x] Réseau singleton éditable (nom, description, notes, préfixes racine informatifs)
- [x] CRUD VLAN (tag 802.1Q facultatif, CIDR unique, gateway) avec taux d'occupation
- [x] CRUD IP (statut, hostname, MAC normalisée, libellé, description), tri numérique, stockage sparse
- [x] Détection de conflits : CIDR invalide, chevauchement, IP hors subnet, doublon, gateway hors subnet, capacité
- [x] Suivi dynamique : cibles TCP/ICMP, scheduler APScheduler, code couleur par fraîcheur (§seuils configurables)
- [x] Pastilles auto-rafraîchies (HTMX), bouton « Vérifier » par cible et par IP
- [x] Tableau de bord : stats, panneau « à traiter » (rouges d'abord), liste des VLAN avec rollup santé
- [x] Vue VLAN (grille filtrable) + vue plan (trous intercalés) + détail IP en accordéon
- [x] Gestion des utilisateurs (garde-fou dernier manager) + journal d'audit filtrable
- [x] Import CSV tolérant (alias Excel, doublons ignorés) + export round-trip
- [x] i18n Babel/gettext : français complet, anglais (msgid), sélection de locale
- [x] Docker multi-stage (Tailwind standalone, .mo compilés), HEALTHCHECK, volume unique `/data`
- [x] Tests pytest : conflits, transitions de santé, check TCP réel, CSV, i18n, autorisations

## v0.2 — Backlog

- [ ] Notifications quand une cible tombe (webhook générique, e-mail SMTP)
- [ ] Historique des checks + sparkline par cible
- [ ] IPv6
- [ ] Scan de subnet (découverte) pour pré-remplir les IP vivantes
- [ ] Tokens d'API (accès programmatique read-only puis read-write)
- [ ] Vue plan avancée (heatmap compacte, regroupement des plages libres)
- [ ] Catalogue `en` complet relu + autres langues communautaires
- [ ] Changement de mot de passe par l'utilisateur lui-même (profil)
- [ ] Forcer le changement du mot de passe admin au premier login
