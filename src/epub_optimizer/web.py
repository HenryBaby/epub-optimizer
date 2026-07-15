from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from epub_optimizer import __version__
from epub_optimizer.automation import AutomationManager
from epub_optimizer.core import optimize_epub, optimized_filename, preview_epub_changes
from epub_optimizer.errors import EpubOptimizerError, failure_diagnostic

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_BASE_DIR = Path("/data")
MAX_UPLOAD_MB = int(os.getenv("EPUB_OPTIMIZER_MAX_UPLOAD_MB", "100"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
LOGGER = logging.getLogger(__name__)
AUTOMATION_MANAGER = AutomationManager()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await _automation_manager().start()
    try:
        yield
    finally:
        await _automation_manager().stop()


app = FastAPI(title="EPUB Optimizer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_version": __version__,
            "max_upload_mb": MAX_UPLOAD_MB,
            "result": None,
            "error": None,
        },
    )


@app.get("/automation")
def automation_status() -> JSONResponse:
    return JSONResponse(_automation_manager().status())


@app.post("/automation")
async def configure_automation(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Automation configuration must be an object.")
    config = await _automation_manager().update_config(payload)
    return JSONResponse({"config": asdict(config), "status": _automation_manager().status()})


@app.delete("/automation/history")
async def clear_automation_history() -> JSONResponse:
    await _automation_manager().clear_history()
    return JSONResponse(_automation_manager().status())


@app.post("/optimize")
async def optimize(
    files: Annotated[list[UploadFile], File()],
    append_suffix: Annotated[bool, Form()] = True,
) -> StreamingResponse:
    return StreamingResponse(
        _optimization_events(files, append_suffix=append_suffix),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/dry-run")
async def dry_run(files: Annotated[list[UploadFile], File()]) -> JSONResponse:
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one EPUB file.")

    previews = []
    with tempfile.TemporaryDirectory(prefix="epub-optimizer-preview-web-") as temp_name:
        temp_dir = Path(temp_name)
        upload_dir = temp_dir / "uploads"
        upload_dir.mkdir()
        for index, file in enumerate(files, start=1):
            original_name = Path(file.filename or "").name
            if not original_name.lower().endswith(".epub"):
                previews.append(
                    {
                        "filename": original_name or "Unknown file",
                        "status": "failed",
                        "message": "Please upload a file with the .epub extension.",
                    }
                )
                continue

            upload_path = upload_dir / f"{index}-{uuid.uuid4().hex}.epub"
            try:
                await _save_upload(file, upload_path)
                preview = preview_epub_changes(upload_path, max_size_bytes=MAX_UPLOAD_BYTES)
            except EpubOptimizerError as exc:
                previews.append(
                    {
                        "filename": original_name,
                        "status": "failed",
                        "message": str(exc),
                    }
                )
                continue
            except Exception as exc:
                LOGGER.exception("Unexpected dry-run failure for %s", original_name)
                previews.append(
                    {
                        "filename": original_name,
                        "status": "failed",
                        "message": "Dry run failed unexpectedly.",
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue

            data = asdict(preview)
            data["filename"] = original_name
            data["status"] = "ok"
            previews.append(data)

    return JSONResponse({"previews": previews})


@app.get("/download/{filename}")
def download(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    path = _persistent_output_dir() / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Optimized EPUB is no longer available.")
    return FileResponse(
        path,
        filename=safe_name,
        media_type="application/epub+zip",
        background=BackgroundTask(_remove_download, path),
    )


@app.get("/download-archive/{filename}")
def download_archive(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    path = _persistent_output_dir() / safe_name
    if not path.is_file() or path.suffix.lower() != ".zip":
        raise HTTPException(
            status_code=404,
            detail="Optimized EPUB archive is no longer available.",
        )
    return FileResponse(
        path,
        filename=safe_name,
        media_type="application/zip",
        background=BackgroundTask(_remove_archive_downloads, path),
    )


async def _save_upload(file: UploadFile, target: Path) -> None:
    total = 0
    with target.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise EpubOptimizerError(f"Upload exceeds the {MAX_UPLOAD_MB} MB limit.")
            output.write(chunk)


async def _optimization_events(
    files: list[UploadFile],
    *,
    append_suffix: bool,
) -> AsyncIterator[str]:
    if not files:
        yield _json_event("error", message="Please upload at least one EPUB file.")
        return

    with tempfile.TemporaryDirectory(prefix="epub-optimizer-web-") as temp_name:
        temp_dir = Path(temp_name)
        upload_dir = temp_dir / "uploads"
        output_dir = temp_dir / "output"
        upload_dir.mkdir()
        output_dir.mkdir()

        uploads: list[tuple[str, Path]] = []
        for index, file in enumerate(files, start=1):
            original_name = Path(file.filename or "").name
            if not original_name.lower().endswith(".epub"):
                yield _json_event(
                    "file_error",
                    index=index,
                    total=len(files),
                    filename=original_name or "Unknown file",
                    message="Please upload a file with the .epub extension.",
                    **_diagnostic_event_fields(
                        ValueError("File does not use the .epub extension."),
                        stage="Preparing EPUB file",
                        message="Please upload a file with the .epub extension.",
                    ),
                )
                continue

            upload_path = upload_dir / f"{index}-{uuid.uuid4().hex}.epub"
            try:
                await _save_upload(file, upload_path)
            except EpubOptimizerError as exc:
                yield _json_event(
                    "file_error",
                    index=index,
                    total=len(files),
                    filename=original_name,
                    message=str(exc),
                    **_diagnostic_event_fields(
                        exc,
                        stage="Saving uploaded EPUB",
                        message=str(exc),
                    ),
                )
                continue
            uploads.append((original_name, upload_path))

        if not uploads:
            yield _json_event("complete", successful=0, failed=len(files))
            return

        failed = len(files) - len(uploads)
        successful = 0
        completed_downloads: list[str] = []
        reserved_download_names: set[str] = set()
        persistent_output = _persistent_output_dir()
        persistent_output.mkdir(parents=True, exist_ok=True)

        for index, (original_name, upload_path) in enumerate(uploads, start=1):
            yield _json_event("file_start", index=index, total=len(uploads), filename=original_name)
            queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
            loop = asyncio.get_running_loop()
            stage = {"label": "Preparing EPUB file"}

            def report(
                message: str,
                *,
                event_loop: asyncio.AbstractEventLoop = loop,
                progress_queue: asyncio.Queue[dict[str, object]] = queue,
                file_index: int = index,
                file_total: int = len(uploads),
                file_name: str = original_name,
                stage_ref: dict[str, str] = stage,
            ) -> None:
                stage_ref["label"] = _stage_label_for_message(message)
                event_loop.call_soon_threadsafe(
                    progress_queue.put_nowait,
                    {
                        "type": "log",
                        "index": file_index,
                        "total": file_total,
                        "filename": file_name,
                        "message": message,
                    },
                )

            task = asyncio.create_task(
                asyncio.to_thread(
                    optimize_epub,
                    upload_path,
                    output_dir,
                    output_filename=_output_filename(original_name, append_suffix=append_suffix),
                    max_size_bytes=MAX_UPLOAD_BYTES,
                    progress=report,
                )
            )

            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                except TimeoutError:
                    continue
                yield _json_line(event)

            try:
                result = await task
                download_name = _batch_download_name(
                    result.output_filename,
                    reserved_download_names,
                )
                final_output = persistent_output / download_name
                final_output.write_bytes(result.output_path.read_bytes())
                yield _json_event(
                    "file_complete",
                    index=index,
                    total=len(uploads),
                    filename=original_name,
                    output_filename=result.output_filename,
                    download_name=download_name,
                    download_url=f"/download/{quote(download_name)}",
                    elapsed_seconds=round(result.elapsed_seconds, 2),
                    epub_version=result.epub_version,
                    package_path=result.package_path,
                    content_documents_processed=result.content_documents_processed,
                    stylesheets_replaced=result.stylesheets_replaced,
                    images_preserved=result.images_preserved,
                    warnings=result.warnings,
                )
                successful += 1
                completed_downloads.append(download_name)
            except EpubOptimizerError as exc:
                failed += 1
                yield _json_event(
                    "file_error",
                    index=index,
                    total=len(uploads),
                    filename=original_name,
                    message=str(exc),
                    **_diagnostic_event_fields(
                        exc,
                        stage=stage["label"],
                        message=str(exc),
                    ),
                )
            except Exception as exc:
                LOGGER.exception("Unexpected optimization failure for %s", original_name)
                failed += 1
                yield _json_event(
                    "file_error",
                    index=index,
                    total=len(uploads),
                    filename=original_name,
                    message="Optimization failed unexpectedly.",
                    **_diagnostic_event_fields(
                        exc,
                        stage=stage["label"],
                        message="Optimization failed unexpectedly.",
                    ),
                )

        if completed_downloads:
            archive_name = _unique_download_name(persistent_output, "optimized-epubs.zip")
            _write_download_archive(persistent_output, archive_name, completed_downloads)
            _write_archive_manifest(persistent_output, archive_name, completed_downloads)
            yield _json_event(
                "complete",
                successful=successful,
                failed=failed,
                batch_download_url=f"/download-archive/{quote(archive_name)}",
            )
        else:
            yield _json_event("complete", successful=successful, failed=failed)


def _write_download_archive(output_dir: Path, archive_name: str, filenames: list[str]) -> None:
    archive_path = output_dir / archive_name
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in filenames:
            safe_name = Path(filename).name
            file_path = output_dir / safe_name
            if file_path.is_file():
                archive.write(file_path, arcname=safe_name)


def _write_archive_manifest(output_dir: Path, archive_name: str, filenames: list[str]) -> None:
    manifest_path = _archive_manifest_path(output_dir / archive_name)
    safe_names = [Path(filename).name for filename in filenames]
    manifest_path.write_text(json.dumps(safe_names), encoding="utf-8")


def _unique_download_name(output_dir: Path, filename: str) -> str:
    safe_name = Path(filename).name
    candidate = safe_name
    path = output_dir / candidate
    suffix = Path(safe_name).suffix
    stem = Path(safe_name).stem
    counter = 2
    while path.exists():
        candidate = f"{stem}-{counter}{suffix}"
        path = output_dir / candidate
        counter += 1
    return candidate


def _batch_download_name(filename: str, reserved_names: set[str]) -> str:
    safe_name = Path(filename).name
    candidate = safe_name
    suffix = Path(safe_name).suffix
    stem = Path(safe_name).stem
    counter = 2
    while candidate.lower() in reserved_names:
        candidate = f"{stem}-{counter}{suffix}"
        counter += 1
    reserved_names.add(candidate.lower())
    return candidate


def _output_filename(filename: str, *, append_suffix: bool) -> str:
    if append_suffix:
        return optimized_filename(filename)
    path = Path(filename)
    stem = path.stem or "optimized"
    suffix = path.suffix if path.suffix.lower() == ".epub" else ".epub"
    return f"{stem}{suffix}"


def _json_event(event_type: str, **payload: object) -> str:
    payload["type"] = event_type
    return _json_line(payload)


def _json_line(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _diagnostic_event_fields(
    exc: BaseException,
    *,
    stage: str,
    message: str,
) -> dict[str, object]:
    diagnostic = failure_diagnostic(exc, stage=stage, message=message)
    return {
        "stage": diagnostic.stage,
        "exception_type": diagnostic.exception_type,
        "detail": diagnostic.detail,
        "diagnostic": diagnostic.to_dict(),
    }


def _stage_label_for_message(message: str) -> str:
    normalized = message.lower()
    if "validated epub archive" in normalized:
        return "Validating EPUB archive"
    if "extracted epub" in normalized:
        return "Extracting EPUB workspace"
    if "resolved opf package" in normalized:
        return "Resolving package document"
    if "removed" in normalized and "manifest" in normalized:
        return "Cleaning old manifest entries"
    if "deleted" in normalized and "style/font file" in normalized:
        return "Deleting old style and font files"
    if "processed" in normalized and "content document" in normalized:
        return "Normalizing content documents"
    if "repackaged optimized epub" in normalized:
        return "Repackaging optimized EPUB"
    return message


def _render_error(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_version": __version__,
            "max_upload_mb": MAX_UPLOAD_MB,
            "result": None,
            "error": message,
        },
        status_code=400,
    )


def _persistent_output_dir() -> Path:
    output_base = getattr(app.state, "output_base_dir", OUTPUT_BASE_DIR)
    return Path(output_base) / "epub-optimizer"


def _automation_manager() -> AutomationManager:
    return getattr(app.state, "automation_manager", AUTOMATION_MANAGER)


def _remove_download(path: Path) -> None:
    with suppress(FileNotFoundError):
        path.unlink()


def _remove_archive_downloads(path: Path) -> None:
    output_dir = path.parent
    manifest_path = _archive_manifest_path(path)
    with suppress(FileNotFoundError):
        filenames = json.loads(manifest_path.read_text(encoding="utf-8"))
        for filename in filenames:
            _remove_download(output_dir / Path(filename).name)
        manifest_path.unlink()
    _remove_download(path)


def _archive_manifest_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.json")
