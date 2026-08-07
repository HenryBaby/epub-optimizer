import asyncio
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from epub_optimizer.automation import AutomationJob, AutomationManager


def test_automation_processes_stable_epub(monkeypatch, tmp_path: Path) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
        unprocessed_dir=tmp_path / "unprocessed",
        config_path=tmp_path / "automation-config.json",
        history_path=tmp_path / "automation-history.json",
    )
    manager.config.enabled = True
    manager.config.stable_seconds = 3
    manager._ensure_directories()

    source = manager.watch_dir / "Book.epub"
    source.write_bytes(b"epub")
    stat = source.stat()
    manager._candidates[source] = (stat.st_size, stat.st_mtime, time.time() - 10)

    def fake_optimize(input_path, output_dir, *, output_filename, progress):
        assert input_path == source
        progress("Validated EPUB archive.")
        output_path = output_dir / output_filename
        output_path.write_bytes(b"optimized")
        return SimpleNamespace(output_filename=output_filename)

    monkeypatch.setattr("epub_optimizer.automation.optimize_epub", fake_optimize)

    manager._scan_once()

    assert not source.exists()
    assert (manager.output_dir / "Book-optimized.epub").read_bytes() == b"optimized"
    assert (manager.unprocessed_dir / "Book.epub").read_bytes() == b"epub"
    assert manager.history[0].status == "success"
    assert manager.history[0].output_filename == "Book-optimized.epub"


def test_automation_moves_failed_epub_and_writes_report(monkeypatch, tmp_path: Path) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
        unprocessed_dir=tmp_path / "unprocessed",
        config_path=tmp_path / "automation-config.json",
        history_path=tmp_path / "automation-history.json",
    )
    manager.config.enabled = True
    manager.config.stable_seconds = 3
    manager._ensure_directories()

    source = manager.watch_dir / "Broken.epub"
    source.write_bytes(b"epub")
    stat = source.stat()
    manager._candidates[source] = (stat.st_size, stat.st_mtime, time.time() - 10)

    def fake_optimize(_input_path, _output_dir, *, output_filename, progress):
        progress("Resolved OPF package document: content.opf")
        raise ValueError(f"cannot optimize {output_filename}")

    monkeypatch.setattr("epub_optimizer.automation.optimize_epub", fake_optimize)

    manager._scan_once()

    failed_epub = manager.failed_dir / "Broken.epub"
    report = manager.failed_dir / "Broken.epub.error.json"
    assert not source.exists()
    assert failed_epub.read_bytes() == b"epub"
    assert "ValueError" in report.read_text(encoding="utf-8")
    assert manager.history[0].status == "failed"
    assert "cannot optimize" in manager.history[0].message
    assert manager.history[0].diagnostic is not None
    assert manager.history[0].diagnostic.stage == "Resolving package document"


def test_automation_cleans_old_unprocessed_sources(tmp_path: Path) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
        unprocessed_dir=tmp_path / "unprocessed",
        config_path=tmp_path / "automation-config.json",
        history_path=tmp_path / "automation-history.json",
        unprocessed_retention_seconds=60,
    )
    manager._ensure_directories()
    old_source = manager.unprocessed_dir / "Old.epub"
    new_source = manager.unprocessed_dir / "New.epub"
    old_source.write_bytes(b"old")
    new_source.write_bytes(b"new")
    old_time = time.time() - 120
    current_time = time.time()
    os.utime(old_source, (old_time, old_time))
    os.utime(new_source, (current_time, current_time))

    manager._cleanup_unprocessed()

    assert not old_source.exists()
    assert new_source.read_bytes() == b"new"


def test_automation_cleans_old_failed_sources_and_reports(tmp_path: Path) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
        unprocessed_dir=tmp_path / "unprocessed",
        config_path=tmp_path / "automation-config.json",
        history_path=tmp_path / "automation-history.json",
        unprocessed_retention_seconds=60,
    )
    manager._ensure_directories()
    failed_source = manager.failed_dir / "Old.epub"
    failed_report = manager.failed_dir / "Old.epub.error.json"
    failed_source.write_bytes(b"old")
    failed_report.write_text("{}", encoding="utf-8")
    old_time = time.time() - 120
    os.utime(failed_source, (old_time, old_time))
    os.utime(failed_report, (old_time, old_time))

    manager._cleanup_retained_files()

    assert not failed_source.exists()
    assert not failed_report.exists()


def test_automation_reprocess_failed_moves_file_to_watch(tmp_path: Path) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
        unprocessed_dir=tmp_path / "unprocessed",
        config_path=tmp_path / "automation-config.json",
        history_path=tmp_path / "automation-history.json",
    )
    manager._ensure_directories()
    failed_source = manager.failed_dir / "Retry.epub"
    failed_report = manager.failed_dir / "Retry.epub.error.json"
    failed_source.write_bytes(b"epub")
    failed_report.write_text("{}", encoding="utf-8")
    manager._record(
        AutomationJob(
            filename="Retry.epub",
            status="failed",
            message="Previous failure.",
            output_filename=None,
            elapsed_seconds=1.0,
            updated_at=time.time(),
        )
    )

    result = asyncio.run(manager.reprocess_failed("Retry.epub"))

    assert result["filename"] == "Retry.epub"
    assert not failed_source.exists()
    assert not failed_report.exists()
    assert (manager.watch_dir / "Retry.epub").read_bytes() == b"epub"
    assert manager.history[0].status == "requeued"
    assert "Queued for reprocessing" in manager.history[0].message
    reloaded = AutomationManager(
        watch_dir=manager.watch_dir,
        output_dir=manager.output_dir,
        failed_dir=manager.failed_dir,
        unprocessed_dir=manager.unprocessed_dir,
        config_path=manager.config_path,
        history_path=manager.history_path,
    )
    assert reloaded.history[0].status == "requeued"


def test_automation_status_marks_older_failure_resolved_after_success(tmp_path: Path) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
        unprocessed_dir=tmp_path / "unprocessed",
        config_path=tmp_path / "automation-config.json",
        history_path=tmp_path / "automation-history.json",
    )
    manager.history = [
        AutomationJob(
            filename="Retry.epub",
            status="success",
            message="Done.",
            output_filename="Retry-optimized.epub",
            elapsed_seconds=2.0,
            updated_at=2.0,
        ),
        AutomationJob(
            filename="Retry.epub",
            status="failed",
            message="Old failure.",
            output_filename=None,
            elapsed_seconds=1.0,
            updated_at=1.0,
        ),
    ]

    history = manager.status()["history"]

    assert history[0]["display_status"] == "success"
    assert history[1]["status"] == "failed"
    assert history[1]["display_status"] == "resolved"
    assert history[1]["reprocessable"] is False


def test_reprocess_uses_unique_retained_filename_for_duplicate_books(tmp_path: Path) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
        unprocessed_dir=tmp_path / "unprocessed",
        config_path=tmp_path / "automation-config.json",
        history_path=tmp_path / "automation-history.json",
    )
    manager._ensure_directories()
    for retained_name, updated_at in (("Book.epub", 1.0), ("Book-2.epub", 2.0)):
        (manager.failed_dir / retained_name).write_bytes(retained_name.encode())
        manager._record(
            AutomationJob(
                filename="Book.epub",
                status="failed",
                message="Failed.",
                output_filename=None,
                elapsed_seconds=1.0,
                updated_at=updated_at,
                failed_filename=retained_name,
            )
        )

    status = manager.status()["history"]
    assert [job["failed_filename"] for job in status] == ["Book-2.epub", "Book.epub"]
    assert all(job["reprocessable"] for job in status)

    asyncio.run(manager.reprocess_failed("Book-2.epub"))

    assert (manager.failed_dir / "Book.epub").is_file()
    assert not (manager.failed_dir / "Book-2.epub").exists()
    assert (manager.watch_dir / "Book-2.epub").read_bytes() == b"Book-2.epub"
    assert manager.history[0].failed_filename == "Book-2.epub"
    assert manager.history[0].status == "requeued"
    assert manager.history[1].status == "failed"


def test_reprocess_rolls_back_file_when_history_update_fails(monkeypatch, tmp_path: Path) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
        unprocessed_dir=tmp_path / "unprocessed",
        config_path=tmp_path / "automation-config.json",
        history_path=tmp_path / "automation-history.json",
    )
    manager._ensure_directories()
    failed_source = manager.failed_dir / "Retry.epub"
    failed_report = manager.failed_dir / "Retry.epub.error.json"
    failed_source.write_bytes(b"epub")
    failed_report.write_text("{}", encoding="utf-8")

    def fail_history_update(_filename: str, _watch_path: Path) -> None:
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(manager, "_mark_failed_history_requeued", fail_history_update)

    try:
        asyncio.run(manager.reprocess_failed("Retry.epub"))
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("Expected history persistence failure")

    assert failed_source.read_bytes() == b"epub"
    assert failed_report.is_file()
    assert not (manager.watch_dir / "Retry.epub").exists()


def test_duplicate_failure_resolution_uses_retained_filename(tmp_path: Path) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
        unprocessed_dir=tmp_path / "unprocessed",
        config_path=tmp_path / "automation-config.json",
        history_path=tmp_path / "automation-history.json",
    )
    manager._ensure_directories()
    (manager.failed_dir / "Book-2.epub").write_bytes(b"failed duplicate")
    manager.history = [
        AutomationJob(
            filename="Book.epub",
            status="success",
            message="Done.",
            output_filename="Book-optimized.epub",
            elapsed_seconds=1.0,
            updated_at=3.0,
        ),
        AutomationJob(
            filename="Book.epub",
            status="requeued",
            message="Queued.",
            output_filename=None,
            elapsed_seconds=1.0,
            updated_at=2.0,
            failed_filename="Book.epub",
        ),
        AutomationJob(
            filename="Book.epub",
            status="failed",
            message="Separate duplicate failed.",
            output_filename=None,
            elapsed_seconds=1.0,
            updated_at=1.0,
            failed_filename="Book-2.epub",
        ),
    ]

    history = manager.status()["history"]

    assert history[1]["display_status"] == "resolved"
    assert history[2]["display_status"] == "failed"
    assert history[2]["reprocessable"] is True


def test_reprocess_does_not_reload_history_after_database_commit(
    monkeypatch, tmp_path: Path
) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
        unprocessed_dir=tmp_path / "unprocessed",
        config_path=tmp_path / "automation-config.json",
        history_path=tmp_path / "automation-history.json",
    )
    manager._ensure_directories()
    failed_source = manager.failed_dir / "Retry.epub"
    failed_source.write_bytes(b"epub")
    manager._record(
        AutomationJob(
            filename="Retry.epub",
            status="failed",
            message="Failed.",
            output_filename=None,
            elapsed_seconds=1.0,
            updated_at=1.0,
            failed_filename="Retry.epub",
        )
    )

    def fail_reload() -> list[AutomationJob]:
        raise sqlite3.OperationalError("reload unavailable")

    monkeypatch.setattr(manager, "_load_history", fail_reload)

    asyncio.run(manager.reprocess_failed("Retry.epub"))

    assert not failed_source.exists()
    assert (manager.watch_dir / "Retry.epub").is_file()
    assert manager.history[0].status == "requeued"
