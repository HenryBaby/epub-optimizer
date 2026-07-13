from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from epub_optimizer.core import optimize_epub, optimized_filename
from epub_optimizer.errors import FailureDiagnostic, failure_diagnostic

WATCH_DIR = Path("/watch")
AUTOMATION_OUTPUT_DIR = Path("/output")
FAILED_DIR = Path("/data/failed")
AUTOMATION_CONFIG_PATH = Path("/data/automation-config.json")
AUTOMATION_HISTORY_PATH = Path("/data/automation-history.json")
DEFAULT_POLL_SECONDS = 10
DEFAULT_STABLE_SECONDS = 15
MAX_HISTORY_ITEMS = 25

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AutomationConfig:
    enabled: bool = False
    append_suffix: bool = True
    poll_seconds: int = DEFAULT_POLL_SECONDS
    stable_seconds: int = DEFAULT_STABLE_SECONDS


@dataclass(slots=True)
class AutomationJob:
    filename: str
    status: str
    message: str
    output_filename: str | None
    elapsed_seconds: float | None
    updated_at: float
    diagnostic: FailureDiagnostic | None = None


class AutomationManager:
    def __init__(
        self,
        *,
        watch_dir: Path = WATCH_DIR,
        output_dir: Path = AUTOMATION_OUTPUT_DIR,
        failed_dir: Path = FAILED_DIR,
        config_path: Path = AUTOMATION_CONFIG_PATH,
        history_path: Path = AUTOMATION_HISTORY_PATH,
    ) -> None:
        self.watch_dir = watch_dir
        self.output_dir = output_dir
        self.failed_dir = failed_dir
        self.config_path = config_path
        self.history_path = history_path
        self.config = self._load_config()
        self.history = self._load_history()
        self.current_job: AutomationJob | None = None
        self.last_scan_at: float | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._candidates: dict[Path, tuple[int, float, float]] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._ensure_directories()
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="epub-optimizer-automation")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def update_config(self, values: dict[str, Any]) -> AutomationConfig:
        async with self._lock:
            self.config = AutomationConfig(
                enabled=bool(values.get("enabled", self.config.enabled)),
                append_suffix=bool(values.get("append_suffix", self.config.append_suffix)),
                poll_seconds=_bounded_int(
                    values.get("poll_seconds", self.config.poll_seconds),
                    minimum=3,
                    maximum=3600,
                    fallback=self.config.poll_seconds,
                ),
                stable_seconds=_bounded_int(
                    values.get("stable_seconds", self.config.stable_seconds),
                    minimum=3,
                    maximum=3600,
                    fallback=self.config.stable_seconds,
                ),
            )
            self._write_json(self.config_path, asdict(self.config))
            return self.config

    async def clear_history(self) -> None:
        async with self._lock:
            self.history = []
            self._write_json(self.history_path, [])

    def status(self) -> dict[str, Any]:
        return {
            "config": asdict(self.config),
            "paths": {
                "watch_dir": self.watch_dir.as_posix(),
                "output_dir": self.output_dir.as_posix(),
                "failed_dir": self.failed_dir.as_posix(),
            },
            "current_job": asdict(self.current_job) if self.current_job else None,
            "history": [asdict(job) for job in self.history],
            "last_scan_at": self.last_scan_at,
            "running": self._task is not None and not self._task.done(),
        }

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self.config.enabled:
                    await asyncio.to_thread(self._scan_once)
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=max(self.config.poll_seconds, 1),
                )
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Automation watcher failed during scan.")
                await asyncio.sleep(max(self.config.poll_seconds, 1))

    def _scan_once(self) -> None:
        self._ensure_directories()
        self.last_scan_at = time.time()
        for path in sorted(self.watch_dir.glob("*.epub")):
            if not path.is_file():
                continue
            if self._is_stable(path):
                self._process(path)
                self._candidates.pop(path, None)

    def _is_stable(self, path: Path) -> bool:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return False

        now = time.time()
        snapshot = (stat.st_size, stat.st_mtime)
        previous = self._candidates.get(path)
        if previous is None or previous[:2] != snapshot:
            self._candidates[path] = (stat.st_size, stat.st_mtime, now)
            return False
        return now - previous[2] >= self.config.stable_seconds

    def _process(self, path: Path) -> None:
        started = time.perf_counter()
        self.current_job = AutomationJob(
            filename=path.name,
            status="running",
            message="Optimizing watched EPUB.",
            output_filename=None,
            elapsed_seconds=None,
            updated_at=time.time(),
        )
        stage = {"label": "Optimizing watched EPUB"}

        def report(message: str) -> None:
            stage["label"] = _stage_label_for_message(message)

        try:
            output_filename = (
                optimized_filename(path.name)
                if self.config.append_suffix
                else _original_epub_name(path.name)
            )
            target_name = _unique_name(self.output_dir, output_filename)
            result = optimize_epub(
                path,
                self.output_dir,
                output_filename=target_name,
                progress=report,
            )
            path.unlink()
            self._record(
                AutomationJob(
                    filename=path.name,
                    status="success",
                    message="Optimized EPUB moved to output folder.",
                    output_filename=result.output_filename,
                    elapsed_seconds=round(time.perf_counter() - started, 2),
                    updated_at=time.time(),
                )
            )
        except Exception as exc:
            LOGGER.exception("Automation failed for %s", path)
            failed_path = _unique_path(self.failed_dir, path.name)
            with suppress(FileNotFoundError):
                shutil.move(str(path), failed_path)
            message = _friendly_failure_message(exc)
            report_path = _failure_report_path(failed_path)
            diagnostic = failure_diagnostic(
                exc,
                stage=stage["label"],
                message=message,
                failed_path=failed_path.as_posix(),
                report_path=report_path.as_posix(),
            )
            self._record(
                AutomationJob(
                    filename=path.name,
                    status="failed",
                    message=message,
                    output_filename=None,
                    elapsed_seconds=round(time.perf_counter() - started, 2),
                    updated_at=time.time(),
                    diagnostic=diagnostic,
                )
            )
            _write_failure_report(failed_path, diagnostic)
        finally:
            self.current_job = None

    def _record(self, job: AutomationJob) -> None:
        self.history.insert(0, job)
        self.history = self.history[:MAX_HISTORY_ITEMS]
        self._write_json(self.history_path, [asdict(item) for item in self.history])

    def _ensure_directories(self) -> None:
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> AutomationConfig:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return AutomationConfig()
        return AutomationConfig(
            enabled=bool(data.get("enabled", False)),
            append_suffix=bool(data.get("append_suffix", True)),
            poll_seconds=_bounded_int(
                data.get("poll_seconds", DEFAULT_POLL_SECONDS),
                minimum=3,
                maximum=3600,
                fallback=DEFAULT_POLL_SECONDS,
            ),
            stable_seconds=_bounded_int(
                data.get("stable_seconds", DEFAULT_STABLE_SECONDS),
                minimum=3,
                maximum=3600,
                fallback=DEFAULT_STABLE_SECONDS,
            ),
        )

    def _load_history(self) -> list[AutomationJob]:
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        jobs = []
        for item in data[:MAX_HISTORY_ITEMS]:
            if isinstance(item, dict):
                jobs.append(
                    AutomationJob(
                        filename=str(item.get("filename", "")),
                        status=str(item.get("status", "unknown")),
                        message=str(item.get("message", "")),
                        output_filename=item.get("output_filename"),
                        elapsed_seconds=item.get("elapsed_seconds"),
                        updated_at=float(item.get("updated_at", time.time())),
                        diagnostic=_load_diagnostic(item.get("diagnostic")),
                    )
                )
        return jobs

    @staticmethod
    def _write_json(path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _bounded_int(value: object, *, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(parsed, minimum), maximum)


def _original_epub_name(filename: str) -> str:
    path = Path(filename)
    stem = path.stem or "optimized"
    suffix = path.suffix if path.suffix.lower() == ".epub" else ".epub"
    return f"{stem}{suffix}"


def _unique_name(directory: Path, filename: str) -> str:
    return _unique_path(directory, filename).name


def _unique_path(directory: Path, filename: str) -> Path:
    safe_name = Path(filename).name
    candidate = directory / safe_name
    suffix = Path(safe_name).suffix
    stem = Path(safe_name).stem
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def _failure_report_path(failed_path: Path) -> Path:
    return failed_path.with_name(f"{failed_path.name}.error.json")


def _write_failure_report(failed_path: Path, diagnostic: FailureDiagnostic) -> None:
    report_path = _failure_report_path(failed_path)
    report_path.write_text(
        json.dumps(
            {
                "filename": failed_path.name,
                "diagnostic": diagnostic.to_dict(),
                "updated_at": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _load_diagnostic(value: object) -> FailureDiagnostic | None:
    if not isinstance(value, dict):
        return None
    return FailureDiagnostic(
        stage=str(value.get("stage", "Unknown stage")),
        message=str(value.get("message", "Optimization failed.")),
        exception_type=str(value.get("exception_type", "Exception")),
        detail=str(value.get("detail", "")),
        internal_path=_optional_str(value.get("internal_path")),
        failed_path=_optional_str(value.get("failed_path")),
        report_path=_optional_str(value.get("report_path")),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


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


def _friendly_failure_message(exc: BaseException) -> str:
    message = str(exc)
    return message if message else "Optimization failed unexpectedly."
