"""Import CSV tolérant + export round-trip."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import PlainTextResponse

from app.deps import CurrentUser, ManagerUser, SessionDep, csrf_protect
from app.i18n import gettext as _
from app.services import audit, csv_io
from app.templating import render

router = APIRouter(dependencies=[Depends(csrf_protect)])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


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
