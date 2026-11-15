"""Import CSV tolérant + export round-trip, sauvegarde complète JSON et restauration."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response

from app.deps import CurrentUser, ManagerUser, SessionDep, csrf_protect
from app.i18n import gettext as _
from app.models import utcnow
from app.services import audit, backup, csv_io
from app.templating import render

router = APIRouter(dependencies=[Depends(csrf_protect)])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_BACKUP_BYTES = 200 * 1024 * 1024


@router.get("/import")
async def import_page(request: Request, user: CurrentUser):
    return render(request, "import_export.html", {"report": None})


@router.post("/import")
async def import_csv(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        report = csv_io.ImportReport(errors=[_("File is too large (5 MB max).")])
        return render(request, "partials/_import_report.html", {"report": report}, status_code=422)
    report = await csv_io.import_csv(session, content)
    await audit.record(
        session,
        user,
        "import",
        "ip",
        changes={
            "created": {"before": None, "after": report.created},
            "skipped": {"before": None, "after": report.skipped},
            "errors": {"before": None, "after": len(report.errors)},
        },
    )
    await session.commit()
    status_code = 422 if report.errors and not report.created else 200
    return render(request, "partials/_import_report.html", {"report": report}, status_code=status_code)


@router.get("/export.csv")
async def export_csv(request: Request, user: CurrentUser, session: SessionDep):
    content = await csv_io.export_csv(session)
    await audit.record(session, user, "export", "ip")
    await session.commit()
    return PlainTextResponse(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="guipam-export.csv"'},
    )


@router.get("/backup.json")
async def download_backup(request: Request, user: ManagerUser, session: SessionDep):
    """Sauvegarde complète (toutes les tables). Réservée aux managers : contient les
    empreintes des mots de passe et des clés d'API."""
    payload = await backup.export_data(session)
    await audit.record(session, user, "export", "backup")
    await session.commit()
    filename = f"guipam-backup-{utcnow():%Y%m%d-%H%M}.json"
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=1),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore")
async def restore_backup(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
):
    """Remplace toutes les données par celles d'une sauvegarde, puis déconnecte."""
    username = user.username
    content = await file.read(MAX_BACKUP_BYTES + 1)
    try:
        if len(content) > MAX_BACKUP_BYTES:
            raise backup.BackupError(_("File is too large."))
        try:
            payload = json.loads(content)
        except ValueError:
            raise backup.BackupError(_("This file is not a GuiPAM backup.")) from None
        counts = await backup.import_data(session, payload)
    except backup.BackupError as exc:
        return render(request, "partials/_restore_error.html", {"error": str(exc)}, status_code=422)
    # L'auteur est consigné par son nom : son identifiant peut ne plus exister après restauration.
    await audit.record(
        session,
        audit.Actor(username=username),
        "import",
        "backup",
        changes={table: {"before": None, "after": count} for table, count in counts.items()},
    )
    await session.commit()
    # Les comptes ont pu changer : la session en cours n'a plus de sens.
    request.session.clear()
    return Response(status_code=204, headers={"HX-Redirect": "/login"})
