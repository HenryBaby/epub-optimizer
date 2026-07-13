import time
from pathlib import Path
from types import SimpleNamespace

from epub_optimizer.automation import AutomationManager


def test_automation_processes_stable_epub(monkeypatch, tmp_path: Path) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
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
    assert manager.history[0].status == "success"
    assert manager.history[0].output_filename == "Book-optimized.epub"


def test_automation_moves_failed_epub_and_writes_report(monkeypatch, tmp_path: Path) -> None:
    manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "output",
        failed_dir=tmp_path / "failed",
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
