# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet
adhère au [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

### Added
- **Sauvegarde complète JSON** (page Import / Export, managers) et **restauration**, aussi en ligne de
  commande (`python -m app.backup export|import`). Format versionné (`format_version`), relisible par
  toutes les versions futures : c'est le chemin de migration garanti entre versions majeures.
- **Instantanés automatiques** de la base dans `data/backups/` : un avant chaque migration de schéma
  (5 conservés), un par jour (7 conservés). Réglables par `GUIPAM_BACKUP_KEEP_PRE_MIGRATION` et
  `GUIPAM_BACKUP_KEEP_DAILY` (0 = désactivé).
- GuiPAM refuse de démarrer sur une base plus récente que son code, au lieu de risquer de l'abîmer.
- **Politique de compatibilité** documentée dans le README.
- Nouvelle IP : le début de l'adresse est pré-rempli depuis le CIDR du VLAN (`192.168.1.` pour un /24),
  il ne reste que la partie hôte à saisir.

### Changed
- **Style** : l'interface reprend guitestyle, le style du Hub de la Guite (couleurs, polices, clair/sombre).
  Les jetons sont une copie locale figée (`app/static/vendor/guitestyle/tokens.css`, v1.0.0, mise à jour
  par `make guitestyle VERSION=x.y.z`) ; les composants Basecoat sont branchés dessus.
- Formulaires : une saisie refusée ne vide plus la modale ; l'erreur s'affiche et le champ fautif passe en rouge.

## [0.2.0] — 2026-11-15

Mise à jour sans rupture : la migration Alembic est appliquée au démarrage (deux nouvelles tables,
trois colonnes facultatives sur le journal d'audit) ; données et interface existantes inchangées.

### Added
- **API JSON `/api/v1`** : VLAN, adresses IP, cibles de suivi, checks à la demande, pannes en cours
  (`/problems`), compteurs, réseau, lecture du journal d'audit. Mêmes règles métier que l'UI.
- **Allocation** : `POST /vlans/{id}/allocate` réserve atomiquement la prochaine IP libre
  (`GET /vlans/{id}/next-free` pour seulement la consulter).
- **Comptes de service et clés d'API** (page « API », managers) : clé affichée une seule fois, stockée
  hachée, en lecture seule par défaut, lecture-écriture réservée aux comptes au rôle `manager`,
  date d'expiration facultative, révocation immédiate, date de dernière utilisation.
- **Audit** : les actions faites par API portent le compte de service et la clé utilisée (badge « API »
  dans le journal) ; la gestion des comptes et des clés est elle-même auditée.
- **Documentation intégrée** : spécification OpenAPI (`/api/v1/openapi.json`) et Swagger UI servie en
  local (`/api/v1/docs`), sans CDN.
- Champs « Matériel » et « Lieu » sur les adresses IP : formulaire, détail, colonnes de la grille,
  recherche plein texte, export/import CSV (alias `matériel`, `lieu`, `emplacement`, `site`…),
  migration Alembic automatique au démarrage.

### Changed
- Les règles de validation et d'audit des VLAN, IP, cibles et du réseau sont regroupées dans
  `app/services/inventory.py`, appelé à la fois par l'UI et par l'API (comportement de l'UI inchangé).

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
