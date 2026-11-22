# GuiPAM — notes pour Claude Code

IPAM auto-hébergé mono-réseau avec suivi dynamique (checks TCP/ICMP, code couleur santé).
Cahier des charges v2 implémenté en v0.1.0 ; v0.2.0 ajoute l'API JSON `/api/v1` et les comptes de service ; v0.3.0 la pause volontaire des hôtes ;
v0.4.0 les réglages du suivi dans l'interface et le code couleur relatif à chaque cible ;
v0.5.0 la case « Rester connecté ».
Specs clés : voir README.md et ROADMAP.md.

## Commandes

```bash
.venv/bin/pytest tests/ -q                 # 148 tests (conflits, santé, TCP réel, CSV, i18n, autz, API, sauvegarde, menu, pause, réglages du suivi, sessions)
make css                                   # recompile app/static/app.css (binaire Tailwind standalone)
PATH="$PWD/.venv/bin:$PATH" make i18n      # extraction + régénération du .po fr + compilation .mo (le Makefile appelle `python`, absent hors venv)
.venv/bin/python -m app.main               # serveur dev (env GUIPAM_* requis, voir .env.example)
```

Env minimal pour lancer : `GUIPAM_DB_PATH`, `GUIPAM_SECRET_KEY` (≥16 car.), `GUIPAM_ADMIN_PASSWORD`,
`GUIPAM_SECURE_COOKIES=false` (hors TLS). L'app refuse de démarrer sans les deux premiers.

## Architecture (décisions non évidentes)

- **Un seul module de modèles** `app/models/__init__.py` (évite les cycles). Dates : UTC naïf via `utcnow()`.
- **Règles de conflit IPAM** centralisées dans `app/services/ipam.py` (`ConflictError` porte un message localisé).
- **Mutations VLAN / IP / cibles / réseau** : uniquement via `app/services/inventory.py` (validation + audit
  + commit, lève `ValidationFailed`). L'UI et l'API l'appellent toutes les deux : ne jamais réécrire une
  règle dans un router, sinon UI et API divergent.
- **API** : sous-application FastAPI montée sur `/api/v1` (`app/api/`), authentifiée par clé de compte de
  service (`Authorization: Bearer`), sans session ni CSRF. Écriture = clé `write` ET compte `manager`.
  Erreurs au format `{"error": {code, message, details}}`. Les descriptions des schémas sont la doc lue par
  les agents : les soigner. L'auteur d'une action API est un `audit.Actor` (compte + clé).
- **Clés d'API** : seul le SHA-256 est stocké ; la clé en clair n'existe que dans la réponse de création.
- **Pause volontaire** (`IPAddress.paused_at` …, propriété `is_paused`) : l'IP reste vérifiée, `health` reste
  l'état réel ; c'est l'**affichage** qui l'écarte (À traiter, compteurs, santé VLAN, `/problems`, filtres où elle
  n'apparaît que sous `paused`). Mutations dans `inventory.pause_ip/resume_ip` ; reprises auto dans
  `inventory.resume_due_pauses` (appelée par le scheduler et les checks manuels), déclenchées par l'échéance ou
  par un **retour** (`apply_result` renvoie True sur une transition down → up, pas sur un premier succès).
- **Règles de santé** centralisées dans `app/services/monitor.py` : `health()` / `ip_health()` (= pire cible active).
  Gravité : ok < unknown < warn < red < dark_red. Elles sont **relatives à la cible** : ambre si le dernier succès
  dépasse N × son intervalle (+ un tick), rouge après N échecs consécutifs ; seul le rouge foncé est une durée.
- **Réglages du suivi** (`MonitoringSettings` : intervalle par défaut + 3 seuils) : colonnes facultatives de `reseau`,
  NULL = valeur d'instance `GUIPAM_*` du même nom. `health()` reste synchrone grâce à un cache
  (`monitor.monitoring()`), rafraîchi au démarrage, par `update_reseau`, après une restauration et à chaque requête
  d'interface. Ne jamais lire ces réglages dans `get_settings()` directement : passer par `monitor.monitoring()`.
  Ajouter un réglage = champ du dataclass + colonne + réglage `Settings` de même nom + borne dans
  `inventory.MONITORING_LIMITS`.
- **Migrations Alembic appliquées au démarrage** (lifespan, via thread) ; env.py sync (pas d'async nécessaire).
- **Contrat formulaires HTMX** : erreur → 422 + partial re-rendu, dont `app.js` ne reprend que le bloc
  `[data-form-errors]` (saisie conservée, champs de `error_fields` en rouge via `aria-invalid`) ; succès → 204 + `HX-Refresh`
  + toast flashé en session (`app/flash.py`). Les vrais swaps partiels : pastilles santé (polling),
  filtres (tbody), bouton « Vérifier » (ligne), détail IP (accordéon).
- **CSRF** : dépendance `csrf_protect` sur chaque router mutateur ; jeton dans header HTMX
  (`hx-headers` sur `<body>`) ou champ `csrf_token` des formulaires classiques.
- **bcrypt en direct** (pas passlib), mot de passe tronqué à 72 octets.
- **Session** : middleware maison `app/session.py` (format de cookie Starlette conservé). Durée selon la clé
  `remember` de la session : cookie de navigateur + `GUIPAM_SESSION_MAX_AGE` d'inactivité, ou persistant
  `GUIPAM_REMEMBER_MAX_AGE`. Ouvrir/fermer une session : `services.auth.start_login` / `end_login` ; l'empreinte
  du mot de passe en session (`pwd`) invalide les sessions quand il change.

## i18n — règles impératives

- Les **msgid sont en anglais**, le catalogue fr est la traduction. Toute nouvelle chaîne UI passe par `_()`.
- Dans les templates Jinja (gettext newstyle) : les placeholders se passent **à `_()` directement** :
  `_("Delete %(name)s?", name=x)` — jamais `_("...") | format(...)` (KeyError à l'exécution).
- Nouvelle chaîne = ajouter la traduction dans `scripts/gen_fr_po.py` (dict `FR`) puis `make i18n`.
  Le script échoue listant les chaînes manquantes : c'est le garde-fou.

## Style : guitestyle

- Couleurs et polices viennent de **guitestyle** (jetons du Hub de la Guite), copie figée committée dans
  `app/static/vendor/guitestyle/tokens.css` — ne pas l'éditer ; mise à jour : `make guitestyle VERSION=x.y.z && make css`.
- `app/static/src/input.css` branche les variables Basecoat sur les jetons (`--primary` → `--accent`,
  `--background` → `--bg`, `--muted-foreground` → `--fg-soft`…). **Ne jamais écrire de couleur en dur** dans les
  templates ou le CSS : passer par une variable (exceptions assumées : pastilles santé de `health.css`, `--destructive`).
- Piège de noms : `--accent` et `--border` existent chez Basecoat ET guitestyle. Les jetons sont réimportés
  après Basecoat dans `input.css` pour gagner ; le « accent » de Basecoat (fond de survol) passe par
  `--color-accent` → `--bg-soft`. La classe `bg-accent` reste donc un gris de survol, pas la couleur de marque
  (pour la marque : `bg-primary` / `text-primary`).
- Mode sombre : toujours poser **les deux** marqueurs sur `<html>` — `data-theme="light|dark"` (guitestyle) et
  la classe `.dark` (Basecoat/Tailwind `dark:`). Fait par le script anti-FOUC de `base.html` et la bascule de `app.js`.

## Mise en page (conventions)

- Largeur : classe `page-container` (définie dans `input.css`, max 1600px) pour en-tête, fil d'Ariane, contenu,
  pied — jamais de `max-w-*` local. Carte ne contenant qu'un tableau : `card table-card` + `<section>`.
- Grille des IP = écran principal : elle doit tenir **sans défilement horizontal** jusqu'à ~700px. Texte libre
  → `cell-wrap` (retour à la ligne seulement si nécessaire) ; identifiants (adresse, nom d'hôte, MAC) en nowrap ;
  colonnes secondaires masquées par priorité (`hidden xl:table-cell`…), leur contenu restant dans le détail.
- Actions de ligne : boutons icônes `btn-sm-icon-ghost` + `title` + `aria-label`, icônes via
  `{% from "partials/_icons.html" import icon %}` (tracés Lucide en ligne, pas de bibliothèque).

## Pièges UI connus (déjà mordu)

- **Basecoat ne style que `input[type=…]` explicites** : toujours mettre `type="text"` (etc.) sur les inputs.
- **Pas de `| tojson` dans un attribut HTML à guillemets doubles** (x-data…) : les quotes du JSON cassent
  l'attribut. Utiliser des littéraux à quotes simples.
- `app/static/app.css` est **généré** (gitignoré) : après modification de templates avec de nouvelles
  classes Tailwind, relancer `make css`.

## Continuité des données — règles impératives

L'instance est en usage réel. Engagement publié dans le README (« Politique de compatibilité ») :
aucune mise à jour ne perd de données, et une version majeure est toujours migrable.

- **Schéma** : toute évolution = une **nouvelle** révision Alembic **additive** (table nouvelle, colonne
  nullable ou avec défaut). Ni renommage, ni suppression, ni changement de type hors version majeure.
  Une révision déjà committée n'est **jamais** modifiée ni supprimée.
- **Rupture** (schéma non additif, changement cassant de `/api/v1`) : interdite hors version **majeure**.
  Avant de l'écrire : prévenir l'utilisateur et obtenir son accord. Elle doit livrer dans le même commit
  son chemin de migration (migration Alembic qui convertit les données, sinon upgrader d'export) et son
  entrée CHANGELOG « Migration ». Pas de chemin de migration = pas de rupture.
- **Sauvegarde JSON** (`app/services/backup.py`) : dump générique de toutes les tables, `FORMAT_VERSION`.
  Changement additif → rien à faire (colonne absente = défaut, inconnue = ignorée). Changement non additif →
  incrémenter `FORMAT_VERSION` **et** ajouter l'upgrader `UPGRADERS[n]` (ancien → nouveau). Ne jamais retirer
  un upgrader : toute version doit relire tous les anciens exports.
- **Nouvelle table** : elle est sauvegardée automatiquement (dump générique) ; vérifier seulement qu'elle a
  une clé primaire et que ses colonnes obligatoires ont un défaut.
- **Tests garde-fous** (`tests/test_backup.py`) : migration d'une base v0.1.0 peuplée, aller-retour
  export/import, tolérance d'un export plus ancien. Ne pas les affaiblir ; à chaque version publiée qui change
  le schéma, étendre le test de migration (données dans les nouvelles tables).
- Instantanés SQLite automatiques dans `<data>/backups` (avant migration, quotidien) : filet de sécurité,
  pas une excuse pour une migration risquée.

## Vérification

Toujours vérifier en réel (pas seulement pytest) : lancer le serveur, dérouler login → création → check.
Pas de `python3-venv` sur ce poste : créer le venv avec `~/.local/bin/virtualenv .venv`.
Captures d'écran (revue UI) : Playwright + Chromium dans un venv jetable ; les bibliothèques manquantes
s'obtiennent sans sudo : `apt-get download libnspr4 libnss3 libasound2t64`, `dpkg-deb -x` dans un dossier,
puis `LD_LIBRARY_PATH=<dossier>/usr/lib/x86_64-linux-gnu`. Mesurer `scrollWidth` vs `clientWidth` du tableau.
Docker est disponible sur ce poste : l'image se build et démarre (validé le 2026-11-15, v0.2.0).
Le port 8080 y est pris par Nextcloud → conteneur de test sur un autre port :
`docker build -t guipam:test . && docker run -d --name guipam-test -p 127.0.0.1:8081:8080 -v guipam-test-data:/data
--cap-add NET_RAW -e GUIPAM_SECRET_KEY=… -e GUIPAM_ADMIN_PASSWORD=… -e GUIPAM_SECURE_COOKIES=false guipam:test`.
Le `docker-compose.yml` (port 8080) n'a pas été lancé ici.
