# GuiPAM — notes pour Claude Code

IPAM auto-hébergé mono-réseau avec suivi dynamique (checks TCP/ICMP, code couleur santé).
Cahier des charges v2 intégralement implémenté en v0.1.0. Specs clés : voir README.md et ROADMAP.md.

## Commandes

```bash
.venv/bin/pytest tests/ -q                 # 69 tests (conflits, santé, TCP réel, CSV, i18n, autz)
make css                                   # recompile app/static/app.css (binaire Tailwind standalone)
make i18n                                  # extraction + régénération du .po fr + compilation .mo
.venv/bin/python -m app.main               # serveur dev (env GUIPAM_* requis, voir .env.example)
```

Env minimal pour lancer : `GUIPAM_DB_PATH`, `GUIPAM_SECRET_KEY` (≥16 car.), `GUIPAM_ADMIN_PASSWORD`,
`GUIPAM_SECURE_COOKIES=false` (hors TLS). L'app refuse de démarrer sans les deux premiers.

## Architecture (décisions non évidentes)

- **Un seul module de modèles** `app/models/__init__.py` (évite les cycles). Dates : UTC naïf via `utcnow()`.
- **Règles de conflit IPAM** centralisées dans `app/services/ipam.py` (`ConflictError` porte un message localisé).
- **Seuils santé** centralisés dans `app/services/monitor.py` : `health()` / `ip_health()` (= pire cible active).
  Gravité : ok < unknown < warn < red < dark_red.
- **Migrations Alembic appliquées au démarrage** (lifespan, via thread) ; env.py sync (pas d'async nécessaire).
- **Contrat formulaires HTMX** : erreur → 422 + partial re-rendu dans `#modal` ; succès → 204 + `HX-Refresh`
  + toast flashé en session (`app/flash.py`). Les vrais swaps partiels : pastilles santé (polling),
  filtres (tbody), bouton « Vérifier » (ligne), détail IP (accordéon).
- **CSRF** : dépendance `csrf_protect` sur chaque router mutateur ; jeton dans header HTMX
  (`hx-headers` sur `<body>`) ou champ `csrf_token` des formulaires classiques.
- **bcrypt en direct** (pas passlib), mot de passe tronqué à 72 octets.

## i18n — règles impératives

- Les **msgid sont en anglais**, le catalogue fr est la traduction. Toute nouvelle chaîne UI passe par `_()`.
- Dans les templates Jinja (gettext newstyle) : les placeholders se passent **à `_()` directement** :
  `_("Delete %(name)s?", name=x)` — jamais `_("...") | format(...)` (KeyError à l'exécution).
- Nouvelle chaîne = ajouter la traduction dans `scripts/gen_fr_po.py` (dict `FR`) puis `make i18n`.
  Le script échoue listant les chaînes manquantes : c'est le garde-fou.

## Pièges UI connus (déjà mordu)

- **Basecoat ne style que `input[type=…]` explicites** : toujours mettre `type="text"` (etc.) sur les inputs.
- **Pas de `| tojson` dans un attribut HTML à guillemets doubles** (x-data…) : les quotes du JSON cassent
  l'attribut. Utiliser des littéraux à quotes simples.
- `app/static/app.css` est **généré** (gitignoré) : après modification de templates avec de nouvelles
  classes Tailwind, relancer `make css`.

## Vérification

Toujours vérifier en réel (pas seulement pytest) : lancer le serveur, dérouler login → création → check.
Docker indisponible sur cette machine WSL : le Dockerfile/compose n'ont **jamais été buildés** — à valider
sur une machine avec Docker au premier changement de packaging.
