from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from epub_optimizer import __version__
from epub_optimizer.core import optimize_epub, optimized_filename
from epub_optimizer.errors import EpubOptimizerError

BASE_DIR = Path(__file__).resolve().parent
MAX_UPLOAD_MB = int(os.getenv("EPUB_OPTIMIZER_MAX_UPLOAD_MB", "100"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

app = FastAPI(title="EPUB Optimizer")
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


@app.post("/optimize", response_class=HTMLResponse)
async def optimize(request: Request, file: Annotated[UploadFile, File()]) -> HTMLResponse:
    original_name = Path(file.filename or "").name
    if not original_name.lower().endswith(".epub"):
        return _render_error(request, "Please upload a file with the .epub extension.")

    with tempfile.TemporaryDirectory(prefix="epub-optimizer-web-") as temp_name:
        temp_dir = Path(temp_name)
        upload_path = temp_dir / original_name
        output_dir = temp_dir / "output"
        output_dir.mkdir()

        try:
            await _save_upload(file, upload_path)
            result = optimize_epub(
                upload_path,
                output_dir,
                output_filename=optimized_filename(original_name),
                max_size_bytes=MAX_UPLOAD_BYTES,
            )
            download_token = result.output_filename
            persistent_output = _persistent_output_dir()
            persistent_output.mkdir(parents=True, exist_ok=True)
            final_output = persistent_output / download_token
            final_output.write_bytes(result.output_path.read_bytes())
        except EpubOptimizerError as exc:
            return _render_error(request, str(exc))
        except Exception:
            return _render_error(request, "Optimization failed unexpectedly.")

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_version": __version__,
            "max_upload_mb": MAX_UPLOAD_MB,
            "result": result,
            "download_name": download_token,
            "error": None,
        },
    )


@app.get("/download/{filename}")
def download(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    path = _persistent_output_dir() / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Optimized EPUB is no longer available.")
    return FileResponse(path, filename=safe_name, media_type="application/epub+zip")


async def _save_upload(file: UploadFile, target: Path) -> None:
    total = 0
    with target.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise EpubOptimizerError(f"Upload exceeds the {MAX_UPLOAD_MB} MB limit.")
            output.write(chunk)


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
    return Path(os.getenv("EPUB_OPTIMIZER_OUTPUT_DIR", tempfile.gettempdir())) / "epub-optimizer"
