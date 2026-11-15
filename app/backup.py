"""Sauvegarde / restauration en ligne de commande (utile hors UI, ex. migration majeure).

    python -m app.backup export > guipam-backup.json
    python -m app.backup export -o /data/guipam-backup.json
    python -m app.backup import /data/guipam-backup.json --yes

Dans Docker : `docker exec guipam python -m app.backup export > guipam-backup.json`.
L'import REMPLACE toutes les données de l'instance par celles du fichier.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.database import dispose_engine, init_engine, session_factory
from app.i18n import set_locale
from app.services import backup


async def _run(args: argparse.Namespace) -> int:
    from app.main import run_migrations

    settings = get_settings()
    set_locale(settings.default_locale)
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(run_migrations, settings)
    init_engine(settings.database_url)
    try:
        async with session_factory()() as session:
            if args.command == "export":
                text = json.dumps(await backup.export_data(session), ensure_ascii=False, indent=1)
                if args.output:
                    Path(args.output).write_text(text, encoding="utf-8")
                    print(f"Sauvegarde écrite dans {args.output}", file=sys.stderr)
                else:
                    sys.stdout.write(text + "\n")
                return 0
            if not args.yes:
                print("Refusé : l'import remplace toutes les données. Ajoutez --yes pour confirmer.", file=sys.stderr)
                return 2
            try:
                payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
                counts = await backup.import_data(session, payload)
            except (OSError, ValueError, backup.BackupError) as exc:
                print(f"Échec : {exc}", file=sys.stderr)
                return 1
            print("Restauré : " + ", ".join(f"{n} {t}" for t, n in counts.items()), file=sys.stderr)
            return 0
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.backup", description="Sauvegarde complète de GuiPAM (JSON).")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="écrit la sauvegarde sur la sortie standard (ou -o fichier)")
    export.add_argument("-o", "--output")
    restore = sub.add_parser("import", help="remplace toutes les données par celles du fichier")
    restore.add_argument("file")
    restore.add_argument("--yes", action="store_true", help="confirme le remplacement des données")
    sys.exit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
