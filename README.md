# GuiPAM 🌐

**IPAM auto-hébergé avec suivi dynamique** — remplace le fichier Excel de suivi des adresses IP
d'un homelab ou d'une PME, et montre d'un coup d'œil quelles entrées sont encore vivantes
ou probablement mortes.

- **Mono-instance / mono-réseau** : une instance gère un seul réseau, déployée dessus.
- **Inventaire** : VLAN (subnets), adresses IP (statut, hostname, MAC, libellé), vue plan avec les trous.
- **Détection de conflits** : CIDR invalides, chevauchements de VLAN, IP hors subnet, doublons, passerelle hors subnet, capacité.
- **Suivi dynamique** : checks TCP (connexion) ou ICMP (ping) par cible, code couleur par fraîcheur du
  dernier succès (vert → ambre → rouge → rouge foncé « entrée à nettoyer »), rafraîchissement automatique.
- **Pause volontaire** : un hôte éteint exprès (NAS coupé, machine en maintenance) se met en pause. Il reste
  vérifié mais sort de « À traiter » et des compteurs de pannes ; la pause se lève toute seule quand l'hôte
  répond de nouveau, après une durée choisie, ou à la main.
- **Rôles** : `manager` (lecture/écriture) et `user` (lecture seule), journal d'audit de toute mutation.
- **API JSON** pour les scripts, Ansible et les agents IA : comptes de service, clés d'accès en lecture seule
  ou lecture-écriture, allocation de la prochaine IP libre, spécification OpenAPI intégrée.
- **Import / export CSV** tolérant (alias de colonnes Excel) pour migrer puis sauvegarder.
- **FOSS (MIT), sans télémétrie, sans CDN** : tous les assets sont servis en local, fonctionne hors-ligne.

## Stack

Python 3.12 · FastAPI + Uvicorn · SQLModel / SQLite (WAL) · Alembic · APScheduler ·
Jinja2 + HTMX + Alpine.js · Tailwind CSS + [Basecoat](https://basecoatui.com), habillés par
[guitestyle](https://guitehub.github.io/projets/guitestyle/) (copie locale figée) · Babel (i18n fr/en).
Pas de Node au runtime : le CSS est compilé au build avec le binaire Tailwind standalone.

## Démarrage rapide (Docker)

```bash
git clone https://example.com/guipam.git && cd guipam
cp .env.example .env
# Éditez .env : GUIPAM_SECRET_KEY (openssl rand -hex 32) et GUIPAM_ADMIN_PASSWORD sont requis.
docker compose up -d --build
```

Ouvrez <http://localhost:8080> et connectez-vous avec `GUIPAM_ADMIN_USERNAME` / `GUIPAM_ADMIN_PASSWORD`.

- **Persistance** : tout l'état vit dans le volume `./data` (base SQLite et ses instantanés).
  Voir [Mises à jour, sauvegardes et compatibilité](#mises-à-jour-sauvegardes-et-compatibilité).
- **Ping ICMP** : nécessite `cap_add: [NET_RAW]` (déjà dans le `docker-compose.yml`). Si vous ne
  pouvez pas l'accorder, mettez `GUIPAM_ENABLE_PING=false` : GuiPAM reste pleinement fonctionnel
  avec des checks TCP uniquement.
- **Healthcheck** : `GET /healthz` vérifie la base et le scheduler ; le conteneur passe `healthy` tout seul.

## Mises à jour, sauvegardes et compatibilité

**L'engagement** : une mise à jour de GuiPAM ne fait jamais perdre de données, et une version
majeure reste toujours franchissable.

### Mettre à jour

```bash
git pull            # ou : git checkout vX.Y.Z pour une version précise
docker compose up -d --build
```

C'est tout. Au démarrage, GuiPAM compare le schéma de la base à celui du code et, s'il doit
migrer, prend d'abord un **instantané de la base** dans `data/backups/`
(`guipam-avant-migration-<date>-<révision>.db`), puis applique les migrations.
Lisez le [CHANGELOG](CHANGELOG.md) avant une version **majeure** : toute rupture y est annoncée
avec sa marche à suivre.

### Ce qui protège vos données

| Filet | Quand | Où | Pour revenir en arrière |
|---|---|---|---|
| Instantané avant migration | automatiquement, à chaque changement de schéma (5 conservés) | `data/backups/guipam-avant-migration-*.db` | arrêter, remettre le fichier à la place de `data/guipam.db`, relancer l'ancienne version |
| Instantané quotidien | automatiquement (7 conservés) | `data/backups/guipam-quotidien-*.db` | idem |
| Sauvegarde complète JSON | à la demande : page **Import / Export**, ou `docker exec guipam python -m app.backup export > guipam-backup.json` | où vous voulez | **Restaurer une sauvegarde** dans la même page, ou `python -m app.backup import fichier --yes` |

Les instantanés vivent dans le même volume que la base : ils protègent d'une mauvaise mise à jour
ou d'une fausse manœuvre, **pas de la perte du disque**. Copiez régulièrement `data/` (ou une
sauvegarde JSON) ailleurs — par exemple avec la sauvegarde de la VM ou une tâche planifiée.
La sauvegarde JSON contient les empreintes des mots de passe et des clés d'API : gardez-la privée.

Pour restaurer un instantané : `docker compose down`, copier le fichier choisi sur `data/guipam.db`
(supprimer `guipam.db-wal` et `guipam.db-shm` s'ils existent), `docker compose up -d`.
GuiPAM refuse de démarrer sur une base plus récente que son code (retour arrière d'image sans
restaurer la base) plutôt que de risquer de l'abîmer.

### Politique de compatibilité

Versions [SemVer](https://semver.org/lang/fr/) `MAJEURE.MINEURE.CORRECTIF`, publiées par des tags `vX.Y.Z`.

- **Correctif et mineure** : mise à jour en place, sans intervention. Le schéma n'évolue que par
  ajouts (nouvelles tables, nouvelles colonnes facultatives) ; l'API `/api/v1` ne fait qu'ajouter.
- **Majeure** : seule occasion d'une rupture (schéma restructuré, API `/api/v2`…). Elle est alors
  **toujours migrable**, par au moins l'un de ces chemins, décrit dans le CHANGELOG :
  1. migration automatique au démarrage, comme d'habitude (le cas normal) ;
  2. à défaut, export depuis l'ancienne version puis import dans la nouvelle.
- **La sauvegarde JSON est le contrat** : son format porte un numéro (`format_version`). Toute
  version de GuiPAM sait importer les sauvegardes de **tous** les formats antérieurs — les
  convertisseurs d'anciens formats ne sont jamais retirés. Une sauvegarde faite aujourd'hui reste
  donc importable dans n'importe quelle version future.
- Une rupture qui ne respecterait pas ces règles est un bug, pas une décision.

Ces garanties sont vérifiées par les tests (`tests/test_backup.py`) : migration d'une base v0.1.0
avec données, aller-retour export/import, tolérance aux formats plus anciens.

## Configuration

Toutes les variables sont préfixées `GUIPAM_` — liste complète commentée dans [`.env.example`](.env.example).
Les deux seules obligatoires :

| Variable | Rôle |
|---|---|
| `GUIPAM_SECRET_KEY` | Clé de signature des sessions. L'app **refuse de démarrer** sans clé sérieuse. |
| `GUIPAM_ADMIN_PASSWORD` | Mot de passe du premier compte manager (créé si la base est vide). **Aucun défaut.** |

Seuils du code couleur santé (relatifs au dernier succès d'une cible) :
`GUIPAM_HEALTH_WARN_SECONDS` (vert → ambre), `GUIPAM_HEALTH_RED_SECONDS` (→ rouge),
`GUIPAM_HEALTH_DARK_RED_SECONDS` (→ rouge foncé). Une IP affiche la pire couleur de ses cibles actives.

## Développement local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

make css        # compile app/static/app.css (télécharge le binaire Tailwind au premier appel)
make i18n       # recompile les catalogues de traduction (.po → .mo)

export GUIPAM_DB_PATH=./data/guipam.db \
       GUIPAM_SECRET_KEY=$(openssl rand -hex 32) \
       GUIPAM_ADMIN_PASSWORD=changezmoi \
       GUIPAM_SECURE_COOKIES=false
python -m app.main   # http://localhost:8080

make test       # pytest
```

Sous WSL2, l'app écoute sur `0.0.0.0` : accédez-y depuis Windows via `http://localhost:8080`.

### Migrations de schéma

Le schéma est géré par Alembic et **appliqué automatiquement au démarrage**. Une migration doit
être **additive** (voir la politique de compatibilité) et une révision publiée ne se modifie jamais.
Pour créer une migration après avoir modifié `app/models/` :

```bash
alembic revision --autogenerate -m "description"
```

## Ajouter une langue

Les msgid du code sont en anglais ; le français est fourni complet. Pour ajouter, par exemple, l'espagnol :

```bash
# 1. Extraire les chaînes
pybabel extract -F babel.cfg -o messages.pot .
# 2. Créer le catalogue
pybabel init -i messages.pot -d app/locale -l es
# 3. Traduire app/locale/es/LC_MESSAGES/messages.po
# 4. Compiler (fait automatiquement au build Docker)
pybabel compile -d app/locale
```

Ajoutez ensuite l'option dans le sélecteur de langue (`app/templates/base.html`).
La locale est choisie dans cet ordre : préférence utilisateur → cookie → `Accept-Language` →
locale par défaut du réseau → français.

## API (automatisation)

GuiPAM se pilote aussi depuis des machines : tout ce que l'UI permet sur les VLAN, les IP et la
supervision est disponible en JSON sous `/api/v1`, avec **exactement les mêmes règles métier**.

1. Un manager ouvre **Administration › Comptes de service** dans la barre de navigation, crée un **compte de service** puis une **clé**.
   La clé n'est affichée qu'une fois (seule son empreinte SHA-256 est stockée) ; elle peut avoir une
   date d'expiration et se révoque d'un clic.
2. L'outil envoie la clé à chaque requête : `Authorization: Bearer gpm_…`.

```bash
KEY=gpm_xxxxxxxx_…
curl -H "Authorization: Bearer $KEY" http://guipam.lan:8080/api/v1/vlans
# « Donne-moi la prochaine IP libre du VLAN 3 et réserve-la »
curl -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"hostname": "vm-nouvelle", "description": "réservée par Ansible"}' \
     http://guipam.lan:8080/api/v1/vlans/3/allocate
# Ce qui est en panne
curl -H "Authorization: Bearer $KEY" http://guipam.lan:8080/api/v1/problems
# NAS éteint exprès : pause jusqu'à ce qu'il réponde de nouveau (hors /problems d'ici là)
curl -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"reason": "éteint volontairement"}' http://guipam.lan:8080/api/v1/ips/12/pause
```

- **Documentation** : `/api/v1/docs` (interactive, servie en local) et `/api/v1/openapi.json`
  (spécification OpenAPI, suffisante pour qu'un agent IA utilise l'API sans autre notice).
  Les deux sont publiques : elles décrivent l'API, pas vos données.
- **Moindre privilège** : une clé est en lecture seule par défaut. Une clé en lecture-écriture n'est
  possible que sur un compte de service au rôle `manager` ; rétrograder le compte retire aussitôt
  l'écriture à ses clés. La gestion des comptes et des clés reste réservée à l'UI (managers).
- **Audit** : chaque action faite par API est journalisée avec le compte de service et la clé utilisée.
- **Erreurs** : toujours `{"error": {"code", "message", "details": [{"field", "message"}]}}`
  (`401 unauthorized`, `403 read_only`, `404 not_found`, `422 validation_error`, `409 subnet_full`).
- **Périmètre réseau** : l'API est pensée pour le LAN ou un VPN. Elle n'a pas (encore) de limitation
  du nombre de requêtes : ne l'exposez pas sur Internet, et servez-la en HTTPS si le réseau n'est pas
  de confiance (la clé circule dans un en-tête).

## Sécurité

- Aucun compte ni mot de passe par défaut ; pas d'auto-inscription.
- Sessions signées (cookie `HttpOnly`, `SameSite=Lax`, `Secure` activable via `GUIPAM_SECURE_COOKIES`).
- Jeton anti-CSRF vérifié sur toute requête mutante ; limitation des tentatives de connexion avec backoff.
- Rôle `user` en lecture seule : contrôles masqués dans l'UI **et** mutations refusées (403) côté API.
- Clés d'API : 256 bits d'aléa, stockées hachées (SHA-256), révocables, expirables, jamais journalisées ;
  l'API n'utilise ni cookie ni session (pas de surface CSRF).
- Conteneur non-root, dépendances épinglées, aucun secret dans les logs, journal d'audit complet.

## Licence

[MIT](LICENSE).
