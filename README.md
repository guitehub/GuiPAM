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
- **HTTPS natif** : certificat auto-signé persistant créé au premier démarrage (ou le vôtre), empreintes
  affichées pour l'épinglage, redirection du HTTP ; un écouteur dédié accueille un reverse proxy.
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

Ouvrez <https://localhost:8443> et connectez-vous avec `GUIPAM_ADMIN_USERNAME` / `GUIPAM_ADMIN_PASSWORD`.
Le navigateur prévient que le certificat n'est pas reconnu : c'est le certificat **auto-signé** que GuiPAM
a créé au premier démarrage (comme Proxmox VE ou Cockpit). Avant de l'accepter, comparez son empreinte
SHA-256 à celle qu'affiche `docker exec guipam python -m app.tls show`. Voir [HTTPS et certificat](#https-et-certificat).

- **Persistance** : tout l'état vit dans le volume `./data` (base SQLite, ses instantanés, certificat TLS).
  Voir [Mises à jour, sauvegardes et compatibilité](#mises-à-jour-sauvegardes-et-compatibilité).
- **Ping ICMP** : nécessite `cap_add: [NET_RAW]` (déjà dans le `docker-compose.yml`). Si vous ne
  pouvez pas l'accorder, mettez `GUIPAM_ENABLE_PING=false` : GuiPAM reste pleinement fonctionnel
  avec des checks TCP uniquement.
- **Healthcheck** : `GET /healthz` vérifie la base et le scheduler ; le conteneur passe `healthy` tout seul,
  quel que soit le mode de l'écouteur HTTP.

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

### Migrer depuis 0.5

La 0.6 sert **HTTPS sur le port 8443** par défaut, et le port 8080 ne fait plus que **rediriger** vers
l'HTTPS (308). Selon votre déploiement :

- **Accès direct** (`http://ip:8080`) : publiez `8443` (le `docker-compose.yml` d'exemple le fait) et passez
  à `https://ip:8443`. Gardez `8080` publié pendant la transition : les anciens favoris sont redirigés.
  Ajoutez à `GUIPAM_TLS_SANS` les noms et IP par lesquels on joint GuiPAM.
- **Derrière un reverse proxy** qui vise `:8080` : ajoutez `GUIPAM_HTTP_MODE=proxy` et
  `GUIPAM_TRUSTED_PROXIES=<IP ou réseau du proxy>` (voir [Derrière un reverse proxy](#derrière-un-reverse-proxy)),
  ou faites viser `https://…:8443` au proxy en acceptant le certificat auto-signé.
- **Clients d'API** en `http://…:8080/api/v1` : passez en `https://…:8443/api/v1` (avec `--cacert` ou
  l'épingle SPKI, voir plus bas), ou restez sur l'écouteur `proxy` dans un réseau interne.
- **`GUIPAM_SECURE_COOKIES=false`** dans votre `.env` : retirez-la (GuiPAM avertit au démarrage).
- **`GUIPAM_PORT`** : renommée `GUIPAM_HTTP_PORT` ; l'ancien nom marche encore, avec un avertissement.
- Pour retrouver exactement le comportement 0.5 (HTTP seul) : `GUIPAM_TLS=off`, réservé au développement.

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

### Suivi : intervalle par défaut et seuils du code couleur

Ils se règlent dans l'interface — **Administration → Paramètres du réseau → Suivi** (managers) — ou par
l'API (`PATCH /api/v1/network`), et s'appliquent immédiatement. Les variables d'environnement n'en sont
que la **valeur initiale**, utilisée tant qu'un réglage n'a pas été redéfini (ou a été vidé).

| Réglage | Variable (valeur initiale) | Défaut |
|---|---|---|
| Intervalle proposé pour une nouvelle cible (modifiable à sa création) | `GUIPAM_DEFAULT_CHECK_INTERVAL` | 60 s |
| Vert → ambre : dernier succès plus vieux que *N* fois l'intervalle de la cible | `GUIPAM_HEALTH_WARN_INTERVALS` | 2 |
| Ambre → rouge : *N* échecs consécutifs | `GUIPAM_HEALTH_RED_FAILURES` | 10 |
| Rouge → rouge foncé : durée sans succès | `GUIPAM_HEALTH_DARK_RED_SECONDS` | 604800 (1 semaine) |

Chaque cible est ainsi jugée **à son propre rythme** : une cible vérifiée toutes les 5 minutes et une autre
toutes les 30 secondes suivent la même règle, sans seuil à réajuster. Seul le rouge foncé (« morte depuis
longtemps, entrée à nettoyer ») est une durée. Une IP affiche la pire couleur de ses cibles actives.

## HTTPS et certificat

GuiPAM chiffre lui-même ses accès. Deux écouteurs tournent dans le même processus :

| Écouteur | Port | Rôle |
|---|---|---|
| HTTPS | `GUIPAM_HTTPS_PORT` (8443) | Accès principal, à publier. |
| HTTP | `GUIPAM_HTTP_PORT` (8080) | Selon `GUIPAM_HTTP_MODE` : `redirect` (défaut, 308 vers l'HTTPS, seul `/healthz` y répond), `proxy` (application complète pour un reverse proxy qui termine le TLS, à ne pas publier) ou `off`. |

Si le port HTTPS publié diffère du port interne (`-p 443:8443`), indiquez-le dans `GUIPAM_PUBLIC_HTTPS_PORT`
pour que les redirections visent le bon port.

### Le certificat

- **Par défaut**, GuiPAM crée au premier démarrage un certificat **auto-signé** (clé ECDSA P-256) dans
  `data/tls/` (`guipam.crt`, `guipam.key` en `0600`). Il est valable pour `localhost`, `127.0.0.1`, `::1`, le
  nom d'hôte et la liste **`GUIPAM_TLS_SANS`** (noms DNS et IP séparés par des virgules, ex.
  `guipam.lan,192.168.1.10`). Le nom d'hôte d'un conteneur n'est pas parlant : renseignez `GUIPAM_TLS_SANS`.
- Il vit dans le volume : mises à jour et recréations du conteneur le conservent, **l'empreinte ne change pas**.
- Il est valable 825 jours et se **renouvelle tout seul** 30 jours avant l'échéance (vérification quotidienne,
  rechargé sans redémarrage), **avec la même clé**. Modifier `GUIPAM_TLS_SANS` le réémet, avec la même clé aussi.
- **Votre propre certificat** (CA interne, ACME…) : montez-le dans le conteneur et définissez
  `GUIPAM_TLS_CERTFILE` (PEM, chaîne intermédiaire comprise) et `GUIPAM_TLS_KEYFILE` (PEM sans mot de passe).
  Ils priment sur l'auto-signé. Un fichier remplacé sur disque (renouvellement externe) est relu chaque jour,
  ou au redémarrage.

### Empreintes et épinglage

Deux valeurs identifient le certificat :

- l'**empreinte SHA-256** du certificat : celle qu'affiche le navigateur, pour vérifier à l'œil. Elle change
  à chaque renouvellement ;
- l'**épingle SPKI SHA-256** (empreinte de la clé publique, en base64) : celle qu'un client automatisé
  épingle. Elle reste **stable d'un renouvellement à l'autre**.

Elles sont journalisées au démarrage, affichées aux managers dans **Paramètres du réseau → Certificat TLS**,
renvoyées par `GET /api/v1/instance`, et lisibles depuis l'hôte avant tout contact réseau :

```bash
docker exec guipam python -m app.tls show          # ou --json
# Client épinglé : la connexion échoue si la clé publique n'est pas celle attendue
curl --pinnedpubkey 'sha256//<épingle SPKI>' -k https://guipam.lan:8443/api/v1/instance -H "Authorization: Bearer $KEY"
# Ou faire confiance au certificat lui-même (copié depuis data/tls/guipam.crt)
curl --cacert guipam.crt https://guipam.lan:8443/api/v1/vlans -H "Authorization: Bearer $KEY"
```

### Derrière un reverse proxy

Le proxy termine le TLS et vise l'écouteur `proxy` sur le réseau interne. Déclarez son IP (ou son réseau)
dans `GUIPAM_TRUSTED_PROXIES` : GuiPAM lit alors `X-Forwarded-For` et `X-Forwarded-Proto`, mais **seulement**
venant de ces adresses. Sans cette déclaration, tous les clients ont l'IP du proxy (journal, et verrouillage
anti-brute-force partagé). Le cookie de session reste `Secure`, puisque le navigateur voit de l'HTTPS.

```yaml
# docker-compose.yml (extrait) : Traefik dans le même réseau Docker
services:
  guipam:
    environment:
      GUIPAM_HTTP_MODE: proxy
      GUIPAM_TRUSTED_PROXIES: 172.16.0.0/12   # réseau Docker du proxy
    labels:
      traefik.http.routers.guipam.rule: Host(`guipam.example.lan`)
      traefik.http.routers.guipam.tls: "true"
      traefik.http.services.guipam.loadbalancer.server.port: "8080"
```

```caddyfile
# Caddyfile
guipam.example.lan {
    reverse_proxy guipam:8080
}
```

L'accès direct `https://…:8443` reste disponible en parallèle : c'est la voie de secours si le proxy ou le
DNS tombent. Autre possibilité : faire viser `https://guipam:8443` au proxy (en lui faisant accepter le
certificat auto-signé, ou en lui fournissant `data/tls/guipam.crt`).

## Développement local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

make css        # compile app/static/app.css (télécharge le binaire Tailwind au premier appel)
make i18n       # recompile les catalogues de traduction (.po → .mo)

export GUIPAM_DB_PATH=./data/guipam.db \
       GUIPAM_SECRET_KEY=$(openssl rand -hex 32) \
       GUIPAM_ADMIN_PASSWORD=changezmoi
python -m app.server   # https://localhost:8443 (certificat auto-signé dans ./data/tls)
# ou, en HTTP seul : GUIPAM_TLS=off GUIPAM_SECURE_COOKIES=false python -m app.server   # http://localhost:8080

make test       # pytest
```

Sous WSL2, l'app écoute sur `0.0.0.0` : accédez-y depuis Windows via `https://localhost:8443`.

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
# Certificat auto-signé : --cacert guipam.crt ou --pinnedpubkey (voir HTTPS et certificat) ; omis ci-dessous.
curl -H "Authorization: Bearer $KEY" https://guipam.lan:8443/api/v1/vlans
# « Donne-moi la prochaine IP libre du VLAN 3 et réserve-la »
curl -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"hostname": "vm-nouvelle", "description": "réservée par Ansible"}' \
     https://guipam.lan:8443/api/v1/vlans/3/allocate
# Ce qui est en panne
curl -H "Authorization: Bearer $KEY" https://guipam.lan:8443/api/v1/problems
# NAS éteint exprès : pause jusqu'à ce qu'il réponde de nouveau (hors /problems d'ici là)
curl -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"reason": "éteint volontairement"}' https://guipam.lan:8443/api/v1/ips/12/pause
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
- **Identité de l'instance** : `GET /api/v1/instance` renvoie la version et les empreintes du certificat
  (`tls.sha256`, `tls.spki_sha256`), pour épingler l'instance à la première connexion puis la vérifier ensuite.
- **Périmètre réseau** : l'API est pensée pour le LAN ou un VPN. Elle n'a pas (encore) de limitation
  du nombre de requêtes : ne l'exposez pas sur Internet. Elle est servie en HTTPS, comme l'interface ;
  vérifiez le certificat côté client (la clé circule dans un en-tête).

## Sécurité

- Aucun compte ni mot de passe par défaut ; pas d'auto-inscription.
- HTTPS par défaut, y compris pour l'accès direct par IP (certificat auto-signé persistant ou fourni) ; le HTTP
  ne fait que rediriger, sauf l'écouteur `proxy` destiné à un reverse proxy.
- Sessions signées (cookie `HttpOnly`, `SameSite=Lax`, `Secure` par défaut via `GUIPAM_SECURE_COOKIES`).
  Par défaut, le cookie disparaît à la fermeture du navigateur et la session expire après 12 h d'inactivité
  (`GUIPAM_SESSION_MAX_AGE`) ; la case **« Rester connecté »** le rend persistant 30 jours
  (`GUIPAM_REMEMBER_MAX_AGE`, renouvelés à chaque visite). Changer le mot de passe d'un compte ferme ses
  sessions ouvertes.
- Jeton anti-CSRF vérifié sur toute requête mutante ; limitation des tentatives de connexion avec backoff.
- Rôle `user` en lecture seule : contrôles masqués dans l'UI **et** mutations refusées (403) côté API.
- Clés d'API : 256 bits d'aléa, stockées hachées (SHA-256), révocables, expirables, jamais journalisées ;
  l'API n'utilise ni cookie ni session (pas de surface CSRF).
- Conteneur non-root, dépendances épinglées, aucun secret dans les logs, journal d'audit complet.

## Licence

[MIT](LICENSE).
