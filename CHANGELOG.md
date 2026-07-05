# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet
adhère au [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

## [0.1.0] — 2026-07-05

### Added
- Inventaire IPAM mono-réseau : VLAN (subnets CIDR, tag 802.1Q facultatif, gateway), adresses IP
  (statut libre/utilisée/réservée, hostname, MAC normalisée, libellé d'appareil), vue plan avec trous.
- Détection de conflits : CIDR invalide, chevauchement de VLAN, IP hors subnet, doublon d'IP,
  passerelle hors subnet, capacité dépassée.
- Suivi dynamique : cibles de check TCP (connexion) et ICMP (ping) par IP, scheduler intégré,
  code couleur par fraîcheur du dernier succès (gris/vert/ambre/rouge/rouge foncé),
  pastilles auto-rafraîchies en HTMX, check manuel « Vérifier ».
- Tableau de bord : statistiques, panneau « à traiter » trié par gravité, occupation par VLAN.
- Authentification par session, rôles `manager` (RW) / `user` (RO), journal d'audit de toute mutation.
- Sécurité : bootstrap admin depuis l'environnement (aucun défaut), clé de session obligatoire,
  CSRF, anti-brute-force, cookies durcis, conteneur non-root.
- Import CSV tolérant (alias de colonnes Excel, doublons ignorés, VLAN auto-créés) et export round-trip.
- Internationalisation Babel/gettext : français complet, structure prête pour d'autres langues.
- Packaging Docker multi-stage (CSS Tailwind standalone compilé au build, catalogues i18n),
  docker-compose avec volume unique `/data`, endpoint `/healthz` pour le HEALTHCHECK.
