# Changelog

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le projet
adhère au [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

## [0.4.1] — 2026-11-16

Retouche d'interface sans rupture : ni migration de schéma, ni changement de l'API `/api/v1`.

### Changed
- Détail d'une IP : le statut « up » d'une cible s'affiche en **vert** (couleur de santé) et non plus dans la
  couleur de marque : c'est une information d'état, pas un élément de design.

## [0.4.0] — 2026-11-16

Mise à jour sans rupture de données : une migration additive (quatre colonnes facultatives sur `reseau`)
est appliquée au démarrage ; l'API gagne des champs sur `/network`, rien n'y change de sens pour l'existant.
**Le calcul du code couleur change** (voir « Changed » et « Migration »).

### Added
- **Réglages du suivi dans l'interface** : Administration → Paramètres du réseau → section « Suivi »
  (managers). On y règle l'intervalle par défaut des nouvelles cibles et les trois seuils du code couleur ;
  le changement s'applique immédiatement, sans redémarrage, et il est journalisé. Un champ vidé revient à
  la valeur de l'instance.
- API : `GET /network` expose `default_check_interval`, `health_warn_intervals`, `health_red_failures` et
  `health_dark_red_seconds` (valeurs appliquées) ; `PATCH /network` les modifie (`null` = valeur de l'instance).
- Variables `GUIPAM_HEALTH_WARN_INTERVALS` (2) et `GUIPAM_HEALTH_RED_FAILURES` (10).

### Changed
- **Code couleur relatif à chaque cible** : il ne dépend plus d'une échelle de temps commune qu'il fallait
  accorder aux intervalles. Vert → ambre quand le dernier succès est plus vieux que *N* fois l'intervalle
  **de la cible** (défaut 2, plus un battement du scheduler) ; ambre → rouge après *N* **échecs consécutifs**
  (défaut 10). Une cible vérifiée toutes les 3 minutes et une autre toutes les 30 secondes suivent donc la
  même règle. Pour une cible à 60 s, les défauts donnent le comportement d'avant (ambre ≈ 2 min, rouge ≈ 10 min).
- Rouge → rouge foncé reste une durée sans succès ; son défaut passe d'**1 heure à 1 semaine**.
- Les variables d'environnement du suivi (`GUIPAM_DEFAULT_CHECK_INTERVAL`, seuils) ne sont plus que la
  **valeur initiale** de réglages modifiables dans l'interface.
- L'intervalle par défaut d'une cible créée sans le préciser (UI et API) est celui du réseau.
- Menu **Administration** déplacé tout à droite de l'en-tête, après le menu utilisateur.
- Fenêtres modales : le contenu défile quand il dépasse la hauteur de l'écran.

### Migration
- `GUIPAM_HEALTH_WARN_SECONDS` et `GUIPAM_HEALTH_RED_SECONDS` **ne sont plus lues** (elles peuvent rester
  dans le `.env`, elles sont ignorées) : remplacez-les par `GUIPAM_HEALTH_WARN_INTERVALS` et
  `GUIPAM_HEALTH_RED_FAILURES`, ou réglez les seuils dans l'interface.
- `GUIPAM_HEALTH_DARK_RED_SECONDS` garde son sens : si votre `.env` la fixe (l'ancien exemple indiquait 3600),
  elle continue de s'appliquer. Retirez-la ou passez-la à `604800` pour adopter le nouveau défaut d'une semaine.
- Aucune donnée à convertir : les réglages du réseau sont vides après la mise à jour (valeurs d'instance).

## [0.3.1] — 2026-11-15

Correctif d'interface sans rupture : ni migration de schéma, ni changement de l'API `/api/v1`.

### Fixed
- Menu utilisateur : le sélecteur de langue se refermait dès qu'on cliquait dessus, rendant impossible le
  passage à une autre langue. Un clic à l'intérieur d'un menu déroulant (utilisateur, Réseaux,
  Administration, légende santé) ne le ferme plus ; Échap ferme désormais chacun d'eux.

## [0.3.0] — 2026-11-15

Mise à jour sans rupture : une migration additive (quatre colonnes facultatives sur `ip_address`) est
appliquée au démarrage ; l'API gagne des champs et des routes, rien n'y change de sens pour l'existant.

### Added
- **Pause volontaire d'un hôte** (bouton ⏸ dans la grille et le détail de l'IP, managers) : pour une machine
  éteinte exprès. Elle reste vérifiée, mais sort du panneau « À traiter », du compteur de pannes et de la
  santé de son VLAN. Raison facultative ; reprise **quand l'hôte répond de nouveau** (par défaut : dès
  qu'une cible répond après avoir été en panne), après 1 h / 1 jour / 1 semaine / 30 jours, ou à la main.
  Pause et reprises (manuelles ou automatiques, avec leur cause) sont journalisées.
- Tableau de bord : carte « En pause » discrète (raison, depuis quand, reprise prévue, bouton Reprendre).
- Grille des IP : pictogramme pause à la place de la pastille (état réel en infobulle), badge « En pause »,
  filtre santé « En pause » ; légende complétée.
- API : champs `paused` et `pause` sur les adresses, `POST /ips/{id}/pause` et `POST /ips/{id}/resume`,
  filtre `health=paused`, compteur `paused` dans `/summary`. Les adresses en pause sont exclues de
  `/problems`, de `down` et de la santé des VLAN ; leur champ `health` reste l'état réel.

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
