# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet
adhère au [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

## [0.2.1] — 2026-11-15

Mise à jour d'interface sans rupture : ni migration de schéma, ni changement de l'API `/api/v1`.

### Changed
- Barre de navigation réorganisée : **Tableau de bord**, menu **Réseaux** (accès direct à chaque VLAN,
  VLAN courant mis en évidence, « Tous les VLAN », « Nouveau VLAN » pour les managers) et menu
  **Administration** (paramètres du réseau, journal d'audit, import/export, utilisateurs, comptes de
  service, documentation de l'API). L'entrée « API » devient « Comptes de service ».
- Mise en page élargie (jusqu'à 1600 px, au lieu de 1152 px) : la grille des adresses IP tient sans
  défilement horizontal dans une fenêtre de ~1400 px. Les actions des lignes (vérifier, modifier,
  supprimer) deviennent des boutons icônes avec infobulle ; les textes libres (appareil, matériel, lieu)
  passent à la ligne seulement si la place manque ; sur fenêtre étroite, les colonnes secondaires se
  masquent par priorité (MAC < 1280 px ; matériel, lieu, nombre de cibles < 1024 px ; dernier check
  < 768 px), leur contenu reste dans le détail de l'IP et dans la recherche.
- Tableaux bord à bord dans leur carte (plus de bande vide au-dessus et au-dessous).

### Fixed
- VLAN triés dans l'ordre numérique des adresses (10.0.2.0/24 avant 10.0.10.0/24) et non plus
  alphabétique, sur le tableau de bord comme dans le menu.
- Statut d'une IP au singulier (« Utilisée », « Libre », « Réservée ») ; les compteurs du tableau de
  bord deviennent « IP utilisées », « IP libres », « IP réservées ».
- Texte des listes déroulantes de filtre centré verticalement (il était décalé vers le bas).
- En-tête de colonne « Cible » (au lieu de « Vérifier ») dans les cibles de suivi d'une IP.

### Interne
- Build reproductible : version de Tailwind figée (v4.3.5) dans le Dockerfile et le Makefile, au lieu de `latest`.
- Intégration continue GitHub Actions : tests et construction de l'image Docker à chaque push, tag et pull request.

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
