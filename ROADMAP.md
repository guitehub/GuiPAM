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

## v0.2 — Piloter l'IPAM depuis des machines

- [x] Comptes de service + clés d'API (lecture seule / lecture-écriture, affichage unique, révocation, expiration)
- [x] API JSON `/api/v1` : VLAN, IP, supervision, pannes, audit ; mêmes règles métier que l'UI
- [x] Allocation atomique de la prochaine IP libre
- [x] Audit des actions automatisées (compte + clé)
- [x] Spécification OpenAPI + documentation interactive servies en local

## Continuité des données

- [x] Sauvegarde complète JSON versionnée + restauration (UI et ligne de commande)
- [x] Instantanés automatiques (avant migration, quotidiens)
- [x] Politique de compatibilité + tests garde-fous de migration

## Backlog

- [ ] API : limitation du nombre de requêtes
- [ ] API : droits plus fins (clé limitée à un VLAN, par exemple)
- [ ] Serveur MCP intégré
- [ ] Notifications quand une cible tombe (webhook générique, e-mail SMTP)
- [ ] Historique des checks + sparkline par cible
- [ ] IPv6
- [ ] Scan de subnet (découverte) pour pré-remplir les IP vivantes
- [ ] Vue plan avancée (heatmap compacte, regroupement des plages libres)
- [ ] Catalogue `en` complet relu + autres langues communautaires
- [ ] Changement de mot de passe par l'utilisateur lui-même (profil)
- [ ] Forcer le changement du mot de passe admin au premier login
