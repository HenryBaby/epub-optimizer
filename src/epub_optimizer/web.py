from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from epub_optimizer import __version__
from epub_optimizer.automation import AutomationManager
from epub_optimizer.core import (
    optimize_epub,
    optimized_filename,
    preview_epub_changes,
    validate_epub_details,
)
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
        manager = getattr(app.state, "grimmory_manager", None)
        if manager is not None:
            await manager.close()


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


def _grimmory_manager():
    # Construction is lazy; neither startup nor the home page connects or scans.
    manager = getattr(app.state, "grimmory_manager", None)
    if manager is None:
        from epub_optimizer.grimmory import GrimmoryManager

        manager = GrimmoryManager()
        app.state.grimmory_manager = manager
    return manager


@app.get("/grimmory")
def grimmory_status() -> JSONResponse:
    return JSONResponse(_grimmory_manager().status(), headers={"Cache-Control": "no-store"})


def _normalized_origin(value: str) -> tuple[str, str, int]:
    # urlsplit strips some controls, so reject them before parsing untrusted input.
    if not value or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Invalid origin")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or not re.fullmatch(r"[a-z0-9.:-]+", parsed.hostname)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
        or parsed.path not in ("", "/")
        or "?" in value
        or "#" in value
    ):
        raise ValueError("Invalid origin")
    host = parsed.hostname
    authority = f"[{host}]" if ":" in host else host
    if not re.fullmatch(re.escape(authority) + r"(?::[0-9]+)?", parsed.netloc.lower()):
        raise ValueError("Invalid origin")
    port = parsed.port  # Also rejects malformed and out-of-range ports.
    return (
        parsed.scheme,
        host,
        port if port is not None else (443 if parsed.scheme == "https" else 80),
    )


async def _grimmory_action(request: Request, action: str) -> JSONResponse:
    public_origin = os.getenv("EPUB_OPTIMIZER_PUBLIC_ORIGIN")
    expected = None
    if public_origin is not None:
        try:
            expected = _normalized_origin(public_origin)
        except ValueError as exc:
            raise HTTPException(
                status_code=503, detail="Invalid EPUB_OPTIMIZER_PUBLIC_ORIGIN configuration."
            ) from exc
    origins = request.headers.getlist("origin")
    if origins:
        try:
            if len(origins) != 1:
                raise ValueError("Multiple origins")
            origin = _normalized_origin(origins[0])
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Invalid request origin.") from exc
        try:
            # Never infer the browser origin from client-supplied forwarding headers.
            # A mounted application's base URL can contain a root path.
            base = urlsplit(str(request.base_url))
            if expected is None:
                expected = _normalized_origin(f"{base.scheme}://{base.netloc}")
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail="Invalid request origin configuration.",
            ) from exc
        if origin != expected:
            raise HTTPException(
                status_code=403,
                detail="Same-origin requests are required. Behind a reverse proxy, configure "
                "EPUB_OPTIMIZER_PUBLIC_ORIGIN with the optimizer's public browser origin.",
            )
    try:
        body = await request.body()
        if len(body) > 64 * 1024:
            raise HTTPException(status_code=413, detail="Grimmory request is too large.")
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Grimmory request must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Grimmory request must be an object.")
    try:
        manager = _grimmory_manager()
        operation = getattr(manager, action)
        result = await operation() if action == "cancel" else await operation(payload)
    except ValueError as exc:
        from epub_optimizer.grimmory import GrimmoryValidationError

        # Only explicitly safe manager messages may reach the browser.
        detail = (
            str(exc)
            if isinstance(exc, GrimmoryValidationError)
            else "Grimmory request rejected. Check inputs and maintenance state."
        )
        raise HTTPException(status_code=400, detail=detail) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=409, detail="Grimmory operation conflicts with the current state."
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Grimmory operation failed. Check the connection and try again."
        ) from exc
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/grimmory/connect")
async def grimmory_connect(request: Request) -> JSONResponse:
    return await _grimmory_action(request, "connect")


@app.post("/grimmory/preview")
async def grimmory_preview(request: Request) -> JSONResponse:
    return await _grimmory_action(request, "preview")


@app.post("/grimmory/start")
async def grimmory_start(request: Request) -> JSONResponse:
    return await _grimmory_action(request, "start")


@app.post("/grimmory/cancel")
async def grimmory_cancel(request: Request) -> JSONResponse:
    return await _grimmory_action(request, "cancel")


@app.post("/grimmory/restore")
async def grimmory_restore(request: Request) -> JSONResponse:
    return await _grimmory_action(request, "restore")


@app.get("/health")
def health() -> JSONResponse:
    automation = _automation_manager().status()
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "automation_running": automation["running"],
            "automation_enabled": automation["config"]["enabled"],
        }
    )


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


@app.post("/automation/reprocess")
async def reprocess_failed_job(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Reprocess request must be an object.")
    filename = str(payload.get("filename", ""))
    if not filename:
        raise HTTPException(status_code=400, detail="Reprocess request requires a filename.")
    try:
        reprocessed = await _automation_manager().reprocess_failed(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Failed EPUB is no longer available.") from exc
    return JSONResponse({"reprocessed": reprocessed, "status": _automation_manager().status()})


@app.delete("/automation/retained/{kind}")
async def clear_retained_automation_files(kind: str) -> JSONResponse:
    try:
        result = await _automation_manager().clear_retained_files(kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"cleanup": result, "status": _automation_manager().status()})


@app.delete("/downloads")
def clear_manual_downloads() -> JSONResponse:
    output_dir = _persistent_output_dir()
    removed = 0
    for pattern in ("*.epub", "*.zip", "*.zip.json"):
        for path in output_dir.glob(pattern):
            if not path.is_file():
                continue
            with suppress(FileNotFoundError):
                path.unlink()
                removed += 1
    return JSONResponse({"removed": removed})


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


@app.post("/api/optimize")
async def api_optimize(
    file: Annotated[UploadFile, File()],
    append_suffix: Annotated[bool, Form()] = True,
) -> FileResponse:
    original_name = Path(file.filename or "").name
    if not original_name.lower().endswith(".epub"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a file with the .epub extension.",
        )

    temp_dir = Path(tempfile.mkdtemp(prefix="epub-optimizer-api-"))
    upload_path = temp_dir / "input.epub"
    output_dir = temp_dir / "output"
    output_dir.mkdir()
    try:
        await _save_upload(file, upload_path)
        result = await asyncio.to_thread(
            optimize_epub,
            upload_path,
            output_dir,
            output_filename=_output_filename(original_name, append_suffix=append_suffix),
            max_size_bytes=MAX_UPLOAD_BYTES,
        )
    except EpubOptimizerError as exc:
        _remove_tree(temp_dir)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Unexpected API optimization failure for %s", original_name)
        _remove_tree(temp_dir)
        raise HTTPException(status_code=500, detail="Optimization failed unexpectedly.") from exc

    return FileResponse(
        result.output_path,
        filename=result.output_filename,
        media_type="application/epub+zip",
        background=BackgroundTask(_remove_tree, temp_dir),
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


@app.post("/validate")
async def validate(files: Annotated[list[UploadFile], File()]) -> JSONResponse:
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one EPUB file.")

    reports = []
    with tempfile.TemporaryDirectory(prefix="epub-optimizer-validate-web-") as temp_name:
        temp_dir = Path(temp_name)
        upload_dir = temp_dir / "uploads"
        upload_dir.mkdir()
        for index, file in enumerate(files, start=1):
            original_name = Path(file.filename or "").name
            if not original_name.lower().endswith(".epub"):
                reports.append(
                    {
                        "filename": original_name or "Unknown file",
                        "valid": False,
                        "issues": [
                            {
                                "severity": "error",
                                "code": "invalid-extension",
                                "message": "Please upload a file with the .epub extension.",
                            }
                        ],
                    }
                )
                continue

            upload_path = upload_dir / f"{index}-{uuid.uuid4().hex}.epub"
            try:
                await _save_upload(file, upload_path)
                report = validate_epub_details(upload_path, max_size_bytes=MAX_UPLOAD_BYTES)
            except EpubOptimizerError as exc:
                reports.append(
                    {
                        "filename": original_name,
                        "valid": False,
                        "issues": [
                            {
                                "severity": "error",
                                "code": "validation-failed",
                                "message": str(exc),
                            }
                        ],
                    }
                )
                continue

            data = asdict(report)
            data["filename"] = original_name
            reports.append(data)

    return JSONResponse({"reports": reports})


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
                    image_diagnostics=result.image_diagnostics,
                    repair_actions=result.repair_actions,
                    validation_outcome=result.validation_outcome,
                    validation_remaining=result.validation_remaining,
                    validation_persisting=result.validation_persisting,
                    warnings=result.warnings,
                    epubcheck=_epubcheck_payload(result.epubcheck),
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


def _epubcheck_payload(comparison: object | None) -> dict[str, object]:
    if comparison is None:
        return {"available": False, "status": "unavailable"}
    from dataclasses import asdict

    data = asdict(comparison)
    data["available"] = bool(getattr(comparison, "available", False))
    for key in ("input", "output"):
        value = data.get(key, {})
        if isinstance(value, dict):
            value["occurrence_count"] = value.get(
                "occurrence_count", len(value.get("findings", []))
            )
            value["errors"] = value.get("error_count", 0)
    data["counts"] = {
        key: len(data.get(key, [])) for key in ("persisting", "resolved", "introduced")
    }
    output = data.get("output", {})
    remaining = int(output.get("errors", 0)) if isinstance(output, dict) else 0
    data["validation_outcome"] = (
        "unavailable" if not data["available"] else "clean" if remaining == 0 else "legacy_issues"
    )
    data["remaining"] = remaining
    data["persisting_count"] = data["counts"]["persisting"]
    return data


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


def _remove_tree(path: Path) -> None:
    with suppress(FileNotFoundError):
        shutil.rmtree(path)


def _archive_manifest_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.json")
