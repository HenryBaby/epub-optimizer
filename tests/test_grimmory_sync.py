"""Read-only native KOSync and guarded same-byte event publication."""

import asyncio
import copy
import hashlib
import io
import json
import os
import threading
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from epub_optimizer import grimmory


@pytest.fixture
def sync_library(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    book = root / "Book.epub"
    book.write_bytes(b"original book fixture")
    library = dict(id=1, name="Books", watch=False, paths=[dict(id=2, path="/books")])
    indexed = [
        dict(
            id=10,
            libraryId=1,
            libraryPath=dict(id=2),
            primaryFile=dict(
                id=20,
                bookId=10,
                fileSubPath="",
                fileName="Book.epub",
                book=True,
                bookType="EPUB",
                filePath="/books/Book.epub",
            ),
            alternativeFormats=[],
        )
    ]
    calls = []
    native = dict(current=False, auth=True)

    def request(url, payload=None, token=None, *, method=None):
        calls.append((url, copy.deepcopy(payload), method))
        if url.endswith("/auth/login"):
            return dict(accessToken="admin-token")
        if url.endswith("/libraries"):
            return [copy.deepcopy(library)]
        if url.endswith("/book"):
            return copy.deepcopy(indexed)
        if url.endswith("/libraries/1"):
            if method == "PUT":
                library.update(copy.deepcopy(payload))
            return copy.deepcopy(library)
        raise AssertionError(url)

    def native_get(base, route, username, password):
        assert (username, password) == ("reader", "private-password")
        if route == "users/auth":
            if not native["auth"]:
                raise grimmory.GrimmoryValidationError("KOSync authentication or request failed.")
            return True
        if native.get("failure"):
            raise grimmory.GrimmoryValidationError("Unexpected KOSync response.")
        return native["current"]

    def optimize(source, output, **kwargs):
        (output / kwargs["output_filename"]).write_bytes(b"optimized book fixture")
        return SimpleNamespace(epubcheck=SimpleNamespace(available=True, introduced=[]))

    monkeypatch.setattr(grimmory, "_request_json", request)
    monkeypatch.setattr(grimmory, "_kosync_get", native_get)
    monkeypatch.setattr(grimmory, "optimize_epub", optimize)
    manager = grimmory.GrimmoryManager(
        state_dir=tmp_path / "state",
        backup_dir=tmp_path / "backup",
        allowed_roots=[root],
        excluded_paths=[],
    )
    manager.SYNC_REFRESH_TIMEOUT = 0
    mapping = dict(library_id=1, remote_path="/books", local_path=str(root))

    async def prepare():
        await manager.connect(dict(base_url="http://grimmory", username="admin", password="admin"))
        plan = await manager.preview(dict(mappings=[mapping]))
        source = await manager.start(dict(plan_id=plan["plan_id"], maintenance_confirmed=True))
        await manager._task
        return source["id"]

    source_id = asyncio.run(prepare())
    calls.clear()
    original_replace = manager._replace

    def publish(*args):
        original_replace(*args)
        native["current"] = not native.get("timeout", False)

    monkeypatch.setattr(manager, "_replace", publish)
    return manager, book, library, indexed, native, calls, source_id


def refresh(manager, source_id):
    return manager.refresh_sync(
        dict(
            job_id=source_id,
            kosync_username="reader",
            kosync_password="private-password",
            maintenance_confirmed=True,
        )
    )


def run_refresh(manager, source_id):
    async def scenario():
        await refresh(manager, source_id)
        await manager._task

    asyncio.run(scenario())
    return manager.status()["job"]


@pytest.mark.parametrize("watch", [False, True])
def test_refresh_same_bytes_new_inode_preserves_metadata_and_watch(sync_library, watch):
    manager, book, library, _, _, calls, source_id = sync_library
    library["watch"] = watch
    manager._state["watcher_maintenance"] = dict(
        session_id="keep-original", status="paused", libraries=[]
    )
    receipt = copy.deepcopy(manager._state["watcher_maintenance"])
    before, inode = grimmory._metadata(book), book.stat().st_ino
    body = book.read_bytes()
    os.utime(book, ns=(1_000_000, book.stat().st_mtime_ns))
    os.utime(book.parent, ns=(2_000_000, book.parent.stat().st_mtime_ns))
    job = run_refresh(manager, source_id)
    assert job["status"] == "completed", job
    assert job["results"][0]["status"] == "verified", job
    assert job["results"][0]["book_id"] == 10
    assert book.stat().st_atime_ns == 1_000_000
    assert book.parent.stat().st_atime_ns == 2_000_000
    assert book.read_bytes() == body and book.stat().st_ino != inode
    assert grimmory._metadata(book) == before
    assert library["watch"] is watch
    assert job["watching_recovery"]["status"] == "restored", job
    assert manager._state["watcher_maintenance"] == receipt
    assert manager.status()["sync_watching_recovery"] is None
    assert [payload["watch"] for _, payload, method in calls if method == "PUT"] == (
        [True, False] if not watch else []
    )
    stored = (manager.state_dir / "state.json").read_text()
    for secret in [
        "reader",
        "private-password",
        "admin-token",
        hashlib.md5(b"private-password").hexdigest(),
    ]:
        assert secret not in stored


def test_already_current_does_not_publish_or_change_watching(sync_library):
    manager, book, _, _, native, calls, source_id = sync_library
    native["current"] = True
    inode = book.stat().st_ino
    job = run_refresh(manager, source_id)
    assert job["status"] == "completed", job
    assert book.stat().st_ino == inode
    assert not any(method == "PUT" for _, _, method in calls)
    assert "watching_recovery" not in job


def test_actual_v350_id_only_library_path_and_full_file_path(sync_library):
    manager, _, _, indexed, _, _, _ = sync_library
    assert indexed[0]["libraryPath"] == {"id": 2}
    assert indexed[0]["primaryFile"]["book"] is True
    assert "isBook" not in indexed[0]["primaryFile"]
    assert manager._indexed_book(manager._state["mappings"][0], "Book.epub") == (10, 20)


@pytest.mark.parametrize(
    "drift", ["unindexed", "ambiguous", "bookid", "filehash", "path", "filepath", "notbook"]
)
def test_preflight_rejects_unindexed_or_drifted_targets(sync_library, drift):
    manager, book, _, indexed, _, calls, source_id = sync_library
    if drift == "unindexed":
        indexed.clear()
    elif drift == "ambiguous":
        indexed.append(copy.deepcopy(indexed[0]))
    elif drift == "bookid":
        indexed[0]["primaryFile"]["bookId"] = 99
    elif drift == "filehash":
        book.write_bytes(b"external change")
    elif drift == "path":
        indexed[0]["libraryPath"]["id"] = 999
    elif drift == "filepath":
        indexed[0]["primaryFile"]["filePath"] = "/different/Book.epub"
    else:
        indexed[0]["primaryFile"]["book"] = False
    inode = book.stat().st_ino
    job = run_refresh(manager, source_id)
    assert job["status"] == "failed", job
    assert job["results"][0]["status"] == "skipped", job
    assert book.stat().st_ino == inode
    assert not any(method == "PUT" for _, _, method in calls)


def test_auth_fails_before_library_write(sync_library):
    manager, book, _, _, native, calls, source_id = sync_library
    native["auth"] = False
    inode = book.stat().st_ino
    job = run_refresh(manager, source_id)
    assert job["status"] == "failed" and book.stat().st_ino == inode, job
    assert calls == []


def test_timeout_restores_watch_and_reports_failure(sync_library):
    manager, _, library, _, native, _, source_id = sync_library
    native["timeout"] = True
    job = run_refresh(manager, source_id)
    assert job["status"] == "failed", job
    assert job["results"][0]["status"] == "failed", job
    assert library["watch"] is False
    assert manager.status()["sync_watching_recovery"] is None


def test_restore_failure_survives_restart_and_explicit_recovery(sync_library, monkeypatch):
    manager, _, library, _, _, _, source_id = sync_library
    update = manager._watch_update

    def fail_restore(item, body, target):
        if not target:
            raise RuntimeError("network down")
        return update(item, body, target)

    monkeypatch.setattr(manager, "_watch_update", fail_restore)
    job = run_refresh(manager, source_id)
    assert job["status"] == "failed", job
    assert library["watch"] is True
    restarted = grimmory.GrimmoryManager(
        state_dir=manager.state_dir,
        backup_dir=manager.backup_dir,
        allowed_roots=manager.allowed_roots,
        excluded_paths=[],
    )
    assert restarted.status()["sync_watching_recovery"]["job_id"] == job["id"]

    async def recover():
        with pytest.raises(grimmory.GrimmoryConflictError):
            await restarted.connect(dict(base_url="http://other", username="a", password="b"))
        await restarted.connect(dict(base_url="http://grimmory", username="a", password="b"))
        with pytest.raises(grimmory.GrimmoryConflictError):
            await restarted.pause_watching(dict(library_ids=[1]))
        await restarted.restore_sync_watching(dict(job_id=job["id"]))

    asyncio.run(recover())
    assert library["watch"] is False
    assert restarted.status()["sync_watching_recovery"] is None


def test_restored_recovery_receipt_cannot_revert_later_watching_change(sync_library):
    manager, _, library, _, _, calls, source_id = sync_library
    job = run_refresh(manager, source_id)
    assert job["watching_recovery"]["status"] == "restored", job
    library["watch"] = True  # A subsequent user action, after refresh finished.
    calls.clear()

    async def replay():
        with pytest.raises(grimmory.GrimmoryValidationError, match="current unresolved"):
            await manager.restore_sync_watching(dict(job_id=job["id"]))

    asyncio.run(replay())
    assert library["watch"] is True
    assert calls == []
    assert manager.status()["sync_watching_recovery"] is None


def test_old_recovery_job_is_rejected_when_newer_receipt_is_pending(sync_library):
    manager, _, library, _, _, calls, source_id = sync_library
    old_job = run_refresh(manager, source_id)
    # Model persisted interrupted receipts, including one superseded by a newer job.
    old_state = manager._state["jobs"][-1]
    old_state["watching_recovery"]["status"] = "pending"
    newer = copy.deepcopy(old_state)
    newer["id"] = "newer-sync-job"
    newer["watching_recovery"]["job_id"] = newer["id"]
    manager._state["jobs"].append(newer)
    manager._save()
    library["watch"] = True
    calls.clear()

    async def stale_recovery():
        with pytest.raises(grimmory.GrimmoryValidationError, match="current unresolved"):
            await manager.restore_sync_watching(dict(job_id=old_job["id"]))

    asyncio.run(stale_recovery())
    assert library["watch"] is True
    assert calls == []
    assert manager.status()["sync_watching_recovery"]["job_id"] == newer["id"]


def test_cancel_keeps_process_lock_through_restoration(sync_library, monkeypatch):
    manager, _, library, _, native, _, source_id = sync_library
    entered, release, published = threading.Event(), threading.Event(), threading.Event()
    manager.SYNC_REFRESH_TIMEOUT = 30
    native["timeout"] = True
    update = manager._watch_update
    replace = manager._replace

    def published_replace(*args):
        replace(*args)
        published.set()

    def blocked_restore(item, body, target):
        if not target:
            entered.set()
            assert release.wait(5)
        return update(item, body, target)

    monkeypatch.setattr(manager, "_watch_update", blocked_restore)
    monkeypatch.setattr(manager, "_replace", published_replace)

    async def scenario():
        await refresh(manager, source_id)
        assert await asyncio.to_thread(published.wait, 5)
        cancellation = asyncio.create_task(manager.cancel())
        assert await asyncio.to_thread(entered.wait, 5)
        assert manager._process_lock is not None and not cancellation.done()
        with pytest.raises(grimmory.GrimmoryConflictError):
            await manager.pause_watching(dict(library_ids=[1]))
        release.set()
        await cancellation

    asyncio.run(scenario())
    assert library["watch"] is False
    assert manager._process_lock is None
    assert manager.status()["job"]["status"] == "cancelled"


def test_partial_md5_offsets(tmp_path):
    path = tmp_path / "sample.epub"
    data = bytes(range(256)) * 100
    path.write_bytes(data)
    expected = hashlib.md5()
    for offset in [0, *(1024 << (2 * i) for i in range(11))]:
        if offset >= len(data):
            break
        expected.update(data[offset : offset + 1024])
    assert grimmory._partial_md5(path) == expected.hexdigest()


@pytest.mark.parametrize(
    "code,payload,expected",
    [
        (200, {"document": "abc", "progress": None}, True),
        (404, {"message": "No progress found for user and book"}, True),
        (404, {"message": "Book not found for hash abc"}, False),
        (404, {"message": "something else"}, None),
        (200, {"document": "wrong"}, None),
        (401, {"message": "unauthorized"}, None),
    ],
)
def test_native_requests_only_get_and_exact_ack(monkeypatch, code, payload, expected):
    captured = []

    class Response(io.BytesIO):
        status = code

    class Opener:
        def open(self, request, timeout):
            captured.append(request)
            assert timeout == 10
            body = json.dumps(payload).encode()
            if code != 200:
                raise HTTPError(request.full_url, code, "failure", {}, io.BytesIO(body))
            return Response(body)

    monkeypatch.setattr(grimmory, "build_opener", lambda *args: Opener())
    if expected is None:
        with pytest.raises(grimmory.GrimmoryValidationError):
            grimmory._kosync_get("http://grimmory", "syncs/progress/abc", "reader", "password")
    else:
        assert (
            grimmory._kosync_get("http://grimmory", "syncs/progress/abc", "reader", "password")
            is expected
        )
    request = captured[0]
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") is None
    assert request.get_header("X-auth-user") == "reader"
    assert request.get_header("X-auth-key") == hashlib.md5(b"password").hexdigest()
