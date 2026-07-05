# GuiPAM 🌐

**IPAM auto-hébergé avec suivi dynamique** — remplace le fichier Excel de suivi des adresses IP
d'un homelab ou d'une PME, et montre d'un coup d'œil quelles entrées sont encore vivantes
ou probablement mortes.

- **Mono-instance / mono-réseau** : une instance gère un seul réseau, déployée dessus.
- **Inventaire** : VLAN (subnets), adresses IP (statut, hostname, MAC, libellé), vue plan avec les trous.
- **Détection de conflits** : CIDR invalides, chevauchements de VLAN, IP hors subnet, doublons, passerelle hors subnet, capacité.
- **Suivi dynamique** : checks TCP (connexion) ou ICMP (ping) par cible, code couleur par fraîcheur du
  dernier succès (vert → ambre → rouge → rouge foncé « entrée à nettoyer »), rafraîchissement automatique.
- **Rôles** : `manager` (lecture/écriture) et `user` (lecture seule), journal d'audit de toute mutation.
- **Import / export CSV** tolérant (alias de colonnes Excel) pour migrer puis sauvegarder.
- **FOSS (MIT), sans télémétrie, sans CDN** : tous les assets sont servis en local, fonctionne hors-ligne.

## Stack

Python 3.12 · FastAPI + Uvicorn · SQLModel / SQLite (WAL) · Alembic · APScheduler ·
Jinja2 + HTMX + Alpine.js · Tailwind CSS + [Basecoat](https://basecoatui.com) · Babel (i18n fr/en).
Pas de Node au runtime : le CSS est compilé au build avec le binaire Tailwind standalone.

## Démarrage rapide (Docker)

```bash
git clone https://example.com/guipam.git && cd guipam
cp .env.example .env
# Éditez .env : GUIPAM_SECRET_KEY (openssl rand -hex 32) et GUIPAM_ADMIN_PASSWORD sont requis.
docker compose up -d --build
```

Ouvrez <http://localhost:8080> et connectez-vous avec `GUIPAM_ADMIN_USERNAME` / `GUIPAM_ADMIN_PASSWORD`.

- **Persistance** : tout l'état vit dans le volume `./data` (base SQLite). Sauvegardez ce dossier
  comme vous voulez — aucune autre pièce à sauvegarder.
- **Ping ICMP** : nécessite `cap_add: [NET_RAW]` (déjà dans le `docker-compose.yml`). Si vous ne
  pouvez pas l'accorder, mettez `GUIPAM_ENABLE_PING=false` : GuiPAM reste pleinement fonctionnel
  avec des checks TCP uniquement.
- **Healthcheck** : `GET /healthz` vérifie la base et le scheduler ; le conteneur passe `healthy` tout seul.

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

Le schéma est géré par Alembic et **appliqué automatiquement au démarrage** — mettre à jour
GuiPAM ne perd jamais de données. Pour créer une migration après avoir modifié `app/models/` :

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

## Sécurité

- Aucun compte ni mot de passe par défaut ; pas d'auto-inscription.
- Sessions signées (cookie `HttpOnly`, `SameSite=Lax`, `Secure` activable via `GUIPAM_SECURE_COOKIES`).
- Jeton anti-CSRF vérifié sur toute requête mutante ; limitation des tentatives de connexion avec backoff.
- Rôle `user` en lecture seule : contrôles masqués dans l'UI **et** mutations refusées (403) côté API.
- Conteneur non-root, dépendances épinglées, aucun secret dans les logs, journal d'audit complet.

## Licence

[MIT](LICENSE).
