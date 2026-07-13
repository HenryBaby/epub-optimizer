import json
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from epub_optimizer.automation import AutomationJob, AutomationManager
from epub_optimizer.web import app


@pytest.fixture(autouse=True)
def output_base_dir(tmp_path):
    app.state.output_base_dir = tmp_path
    app.state.automation_manager = AutomationManager(
        watch_dir=tmp_path / "watch",
        output_dir=tmp_path / "automation-output",
        failed_dir=tmp_path / "failed",
        config_path=tmp_path / "automation-config.json",
        history_path=tmp_path / "automation-history.json",
    )
    yield
    if hasattr(app.state, "output_base_dir"):
        del app.state.output_base_dir
    if hasattr(app.state, "automation_manager"):
        del app.state.automation_manager


def test_homepage_renders() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "EPUB Optimizer" in response.text
    assert "v1.1.0" in response.text
    assert 'href="/static/favicon.png?v=1.1.0"' in response.text
    assert 'href="/static/styles.css?v=1.1.0"' in response.text
    assert 'id="optimizer-form"' in response.text
    assert 'name="files"' in response.text
    assert 'id="source-picker"' in response.text
    assert 'id="choose-folder"' in response.text
    assert 'id="append-suffix"' in response.text
    assert "multiple" in response.text
    assert 'id="theme-toggle"' in response.text
    assert 'id="file-summary"' in response.text
    assert 'id="progress-meter"' in response.text
    assert 'id="download-all"' in response.text
    assert 'id="automation-form"' in response.text
    assert 'id="automation-clear-history"' in response.text
    assert 'src="/static/app.js?v=1.1.0"' in response.text


def test_automation_status_and_configuration() -> None:
    client = TestClient(app)

    response = client.get("/automation")

    assert response.status_code == 200
    status = response.json()
    assert status["config"]["enabled"] is False
    assert status["config"]["append_suffix"] is True
    assert status["paths"]["watch_dir"].endswith("watch")

    update = client.post(
        "/automation",
        json={
            "enabled": True,
            "append_suffix": False,
            "poll_seconds": 4,
            "stable_seconds": 5,
        },
    )

    assert update.status_code == 200
    updated = update.json()["config"]
    assert updated == {
        "enabled": True,
        "append_suffix": False,
        "poll_seconds": 4,
        "stable_seconds": 5,
    }


def test_automation_history_can_be_cleared() -> None:
    client = TestClient(app)
    manager = app.state.automation_manager
    manager.history = [
        AutomationJob(
            filename="Book.epub",
            status="success",
            message="Done.",
            output_filename="Book-optimized.epub",
            elapsed_seconds=0.1,
            updated_at=1.0,
        )
    ]

    response = client.delete("/automation/history")

    assert response.status_code == 200
    assert response.json()["history"] == []
    assert manager.history == []


def test_streaming_optimize_handles_url_significant_filename_chars() -> None:
    client = TestClient(app)

    response = client.post(
        "/optimize",
        files={
            "files": (
                "Book #01.epub",
                _minimal_epub_bytes(),
                "application/epub+zip",
            )
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    complete = next(event for event in events if event["type"] == "file_complete")
    assert "%23" in complete["download_url"]
    assert any(event["type"] == "log" for event in events)
    assert events[-1]["type"] == "complete"
    assert events[-1]["successful"] == 1
    assert events[-1]["failed"] == 0
    assert events[-1]["batch_download_url"].startswith("/download-archive/")

    download = client.get(complete["download_url"])

    assert download.status_code == 200
    assert download.headers["content-type"] == "application/epub+zip"

    expired_download = client.get(complete["download_url"])

    assert expired_download.status_code == 404


def test_streaming_optimize_can_preserve_original_filename() -> None:
    client = TestClient(app)

    response = client.post(
        "/optimize",
        data={"append_suffix": "false"},
        files={
            "files": (
                "Original Name.epub",
                _minimal_epub_bytes(),
                "application/epub+zip",
            )
        },
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    complete = next(event for event in events if event["type"] == "file_complete")

    assert complete["output_filename"] == "Original Name.epub"
    assert complete["download_url"] == "/download/Original%20Name.epub"


def test_streaming_optimize_ignores_stale_output_name_collisions(tmp_path) -> None:
    output_dir = tmp_path / "epub-optimizer"
    output_dir.mkdir()
    (output_dir / "Original Name.epub").write_bytes(b"stale")
    client = TestClient(app)

    response = client.post(
        "/optimize",
        data={"append_suffix": "false"},
        files={
            "files": (
                "Original Name.epub",
                _minimal_epub_bytes(),
                "application/epub+zip",
            )
        },
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    complete = next(event for event in events if event["type"] == "file_complete")

    assert complete["download_name"] == "Original Name.epub"
    assert complete["download_url"] == "/download/Original%20Name.epub"
    assert (output_dir / "Original Name.epub").read_bytes() != b"stale"


def test_streaming_optimize_disambiguates_duplicate_batch_names() -> None:
    client = TestClient(app)

    response = client.post(
        "/optimize",
        data={"append_suffix": "false"},
        files=[
            (
                "files",
                (
                    "Same.epub",
                    _minimal_epub_bytes(),
                    "application/epub+zip",
                ),
            ),
            (
                "files",
                (
                    "Same.epub",
                    _minimal_epub_bytes(),
                    "application/epub+zip",
                ),
            ),
        ],
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    completed = [event for event in events if event["type"] == "file_complete"]

    assert [event["download_name"] for event in completed] == ["Same.epub", "Same-2.epub"]


def test_streaming_optimize_reports_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_optimization(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("epub_optimizer.web.optimize_epub", fail_optimization)
    client = TestClient(app)

    response = client.post(
        "/optimize",
        files={
            "files": (
                "Broken.epub",
                _minimal_epub_bytes(),
                "application/epub+zip",
            )
        },
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    error = next(event for event in events if event["type"] == "file_error")

    assert error["filename"] == "Broken.epub"
    assert error["message"] == "Optimization failed unexpectedly: RuntimeError: boom"


def test_streaming_optimize_accepts_multiple_files() -> None:
    client = TestClient(app)

    response = client.post(
        "/optimize",
        files=[
            (
                "files",
                (
                    "First.epub",
                    _minimal_epub_bytes(),
                    "application/epub+zip",
                ),
            ),
            (
                "files",
                (
                    "Second.epub",
                    _minimal_epub_bytes(),
                    "application/epub+zip",
                ),
            ),
        ],
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    completed = [event for event in events if event["type"] == "file_complete"]

    assert [event["filename"] for event in completed] == ["First.epub", "Second.epub"]
    assert events[-1]["type"] == "complete"
    assert events[-1]["successful"] == 2
    assert events[-1]["failed"] == 0
    assert events[-1]["batch_download_url"].startswith("/download-archive/")

    archive_response = client.get(events[-1]["batch_download_url"])

    assert archive_response.status_code == 200
    assert archive_response.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(BytesIO(archive_response.content)) as archive:
        names = archive.namelist()

    assert names == ["First-optimized.epub", "Second-optimized.epub"]

    expired_archive = client.get(events[-1]["batch_download_url"])

    assert expired_archive.status_code == 404

    for event in completed:
        expired_download = client.get(event["download_url"])

        assert expired_download.status_code == 404


def _minimal_epub_bytes() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test</dc:identifier>
    <dc:title>Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "chapter.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Test</title></head>
  <body><h1>Chapter One</h1><p>Body.</p></body>
</html>
""",
        )
    return output.getvalue()
