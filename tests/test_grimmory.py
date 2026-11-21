import asyncio
import errno
import hashlib
import json
import os
import threading
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from epub_optimizer import grimmory


@pytest.fixture
def setup_library(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    (root / "Author").mkdir()
    (root / "Author" / "Book.epub").write_bytes(b"original")
    (root / "Author" / "cover.jpg").write_bytes(b"cover")
    (root / "empty").mkdir()
    libraries = [dict(id=1, name="Books", watch=False, paths=[dict(id=2, path="/books")])]
    calls = []

    def request(url, payload=None, token=None):
        calls.append((url, payload, token))
        return {"accessToken": "secret-token"} if payload is not None else libraries

    monkeypatch.setattr(grimmory, "_request_json", request)

    def optimize(source, output, **kwargs):
        assert kwargs["preserve_metadata"] is True
        (output / kwargs["output_filename"]).write_bytes(b"optimized")
        return SimpleNamespace(epubcheck=SimpleNamespace(available=True, introduced=[]))

    monkeypatch.setattr(grimmory, "optimize_epub", optimize)
    manager = grimmory.GrimmoryManager(
        state_dir=tmp_path / "state",
        backup_dir=tmp_path / "backups",
        allowed_roots=[root],
        excluded_paths=[],
    )
    mapping = dict(library_id=1, remote_path="/books", local_path=str(root))
    return manager, root, mapping, libraries, calls


async def connect(manager):
    return await manager.connect(
        dict(base_url="http://grimmory:6060", username="u", password="secret-pass")
    )


async def optimize_all(manager, mapping):
    await connect(manager)
    plan = await manager.preview(dict(mappings=[mapping]))
    await manager.start(dict(plan_id=plan["plan_id"], maintenance_confirmed=True))
    await manager._task
    return plan


def test_full_snapshot_exact_names_metadata_restore(setup_library):
    manager, root, mapping, _, calls = setup_library
    before = grimmory._manifest(root)

    async def scenario():
        plan = await optimize_all(manager, mapping)
        assert plan["files"] == 2 and plan["epub_count"] == 1 and plan["bytes"] == 13
        assert manager.status()["job"]["status"] == "completed"
        assert (root / "Author/Book.epub").read_bytes() == b"optimized"
        assert (root / "Author/cover.jpg").read_bytes() == b"cover"
        assert sorted(p.name for p in (root / "Author").iterdir()) == ["Book.epub", "cover.jpg"]
        snapshot = manager.status()["snapshots"][0]
        backup = manager.backup_dir / snapshot["snapshot_id"] / "0"
        assert grimmory._manifest(backup) == before
        assert (backup / "Author/Book.epub").stat().st_ino != (
            root / "Author/Book.epub"
        ).stat().st_ino
        await manager.restore(dict(snapshot_id=snapshot["snapshot_id"], maintenance_confirmed=True))
        await manager._task
        assert manager.status()["job"]["status"] == "completed"
        assert grimmory._manifest(root) == before

    asyncio.run(scenario())
    stored = (manager.state_dir / "state.json").read_text()
    assert "secret-token" not in stored and "secret-pass" not in stored
    assert all("/api/v1/" in call[0] for call in calls)


@pytest.mark.parametrize("kind", ["extra", "edit", "backup"])
def test_restore_conflict_preflight_changes_nothing(setup_library, kind):
    manager, root, mapping, _, _ = setup_library

    async def scenario():
        await optimize_all(manager, mapping)
        snapshot = manager.status()["snapshots"][0]
        if kind == "extra":
            (root / "new.txt").write_text("external")
        elif kind == "edit":
            (root / "Author/cover.jpg").write_bytes(b"external")
        else:
            (manager.backup_dir / snapshot["snapshot_id"] / "0/Author/Book.epub").write_bytes(
                b"bad"
            )
        before = grimmory._manifest(root)
        await manager.restore(dict(snapshot_id=snapshot["snapshot_id"], maintenance_confirmed=True))
        await manager._task
        assert manager.status()["job"]["status"] == "failed"
        assert grimmory._manifest(root) == before

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "overlap", "outside", "watch"])
def test_unsafe_sources_rejected(setup_library, kind, tmp_path):
    manager, root, mapping, libraries, _ = setup_library
    if kind == "symlink":
        (root / "link").symlink_to(root / "Author/Book.epub")
    elif kind == "hardlink":
        os.link(root / "Author/Book.epub", root / "hard.epub")
    elif kind == "fifo":
        os.mkfifo(root / "pipe")
    elif kind == "overlap":
        manager.backup_dir = root / "backups"
    elif kind == "outside":
        mapping["local_path"] = str(tmp_path)
    else:
        libraries[0]["watch"] = True

    async def scenario():
        await connect(manager)
        with pytest.raises(ValueError):
            await manager.preview(dict(mappings=[mapping]))

    asyncio.run(scenario())


def test_start_drift_and_watch_refresh_leave_original(setup_library):
    manager, root, mapping, libraries, _ = setup_library

    async def scenario():
        await connect(manager)
        plan = await manager.preview(dict(mappings=[mapping]))
        libraries[0]["watch"] = True
        with pytest.raises(ValueError):
            await manager.start(dict(plan_id=plan["plan_id"], maintenance_confirmed=True))
        libraries[0]["watch"] = False
        (root / "Author/cover.jpg").write_bytes(b"new")
        await manager.start(dict(plan_id=plan["plan_id"], maintenance_confirmed=True))
        await manager._task
        assert manager.status()["job"]["status"] == "failed"
        assert (root / "Author/Book.epub").read_bytes() == b"original"

    asyncio.run(scenario())


@pytest.mark.parametrize("available,introduced", [(False, []), (True, ["new finding"])])
def test_validation_guard_leaves_original(setup_library, monkeypatch, available, introduced):
    manager, root, mapping, _, _ = setup_library

    def optimize(source, output, **kwargs):
        (output / "result.epub").write_bytes(b"bad")
        return SimpleNamespace(
            epubcheck=SimpleNamespace(available=available, introduced=introduced)
        )

    monkeypatch.setattr(grimmory, "optimize_epub", optimize)
    asyncio.run(optimize_all(manager, mapping))
    assert manager.status()["job"]["results"][0]["status"] == "failed"
    assert (root / "Author/Book.epub").read_bytes() == b"original"


def test_constructor_no_library_io_interrupted_no_resume(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    (state / "state.json").write_text(json.dumps({"jobs": [dict(id="x", status="running")]}))
    monkeypatch.setattr(grimmory, "_manifest", lambda _: pytest.fail("implicit scan"))
    manager = grimmory.GrimmoryManager(state_dir=state, allowed_roots=[])
    assert manager.status()["job"]["status"] == "interrupted"
    assert manager._task is None and not manager.status()["configured"]


def test_explicit_confirmation_and_cancel(setup_library, monkeypatch):
    manager, root, mapping, _, _ = setup_library
    entered, release = threading.Event(), threading.Event()
    original = grimmory.optimize_epub

    def optimize(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(grimmory, "optimize_epub", optimize)
    (root / "Author/Second.epub").write_bytes(b"second")

    async def scenario():
        await connect(manager)
        plan = await manager.preview(dict(mappings=[mapping]))
        with pytest.raises(ValueError):
            await manager.start(dict(plan_id=plan["plan_id"]))
        await manager.start(dict(plan_id=plan["plan_id"], maintenance_confirmed=True))
        assert await asyncio.to_thread(entered.wait, 5)
        with pytest.raises(grimmory.GrimmoryConflictError):
            await manager.preview(dict(mappings=[mapping]))
        manager._cancel.set()
        release.set()
        await manager.cancel()
        assert manager.status()["job"]["status"] == "cancelled"
        assert (root / "Author/Second.epub").read_bytes() == b"second"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "url", ["file:///books", "http://user:pass@server", "http://server?q=x", "http://server/#token"]
)
def test_url_credentials_query_and_scheme_rejected(setup_library, url):
    manager, _, _, _, _ = setup_library

    async def scenario():
        with pytest.raises(ValueError):
            await manager.connect(dict(base_url=url, username="u", password="pass"))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "phase",
    [
        "temp",
        "renamed",
        "restore_temp",
        "external_dir",
        "external_extra",
        "external_temp_edit",
        "external_temp_replace",
        "incomplete_temp",
    ],
)
def test_interrupted_replacement_recovery_is_specific(setup_library, phase):
    manager, root, mapping, _, _ = setup_library

    async def scenario():
        await optimize_all(manager, mapping)
        snapshot_id = manager.status()["snapshots"][0]["snapshot_id"]
        snapshot = manager._state["snapshots"][snapshot_id]
        original = snapshot["plan"]["trees"][0]["Author"]
        original_job = manager._state["jobs"][-1]
        pending = original_job["results"][0]
        pending.update(
            status="pending",
            temp_path="Author/.epub-library-crash.part",
            parent_metadata={k: original[k] for k in ("mode", "uid", "gid", "mtime_ns", "xattrs")},
        )
        if phase == "restore_temp":
            original_job["results"][0] = dict(pending, status="optimized")
            manager._state["jobs"].append(
                dict(
                    id="interrupted-restore",
                    kind="restore",
                    status="interrupted",
                    snapshot_id=snapshot_id,
                    results=[pending],
                )
            )
        if phase in {
            "temp",
            "restore_temp",
            "external_extra",
            "external_temp_edit",
            "external_temp_replace",
            "incomplete_temp",
        }:
            temp = root / pending["temp_path"]
            content = b"original" if phase == "restore_temp" else b"optimized"
            if phase == "restore_temp":
                pending["after_sha256"] = hashlib.sha256(content).hexdigest()
            temp.write_bytes(content)
            info = temp.stat()
            pending["temp_identity"] = [info.st_dev, info.st_ino]
            pending["temp_sha256"] = grimmory._digest(temp)
            if phase == "external_temp_edit":
                temp.write_bytes(b"external writer bytes")
            elif phase == "external_temp_replace":
                replacement = root / "Author/replacement"
                replacement.write_bytes(content)
                replacement.replace(temp)
            elif phase == "incomplete_temp":
                pending.pop("temp_sha256")
        else:
            info = (root / "Author").stat()
            os.utime(root / "Author", ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
        if phase == "external_dir":
            os.chmod(root / "Author", 0o700 if original["mode"] != 0o700 else 0o755)
        if phase == "external_extra":
            (root / "Author/unknown.txt").write_text("external")
        manager._save()
        before = grimmory._manifest(root)
        await manager.restore(dict(snapshot_id=snapshot_id, maintenance_confirmed=True))
        await manager._task
        if phase in {
            "external_dir",
            "external_extra",
            "external_temp_edit",
            "external_temp_replace",
            "incomplete_temp",
        }:
            assert manager.status()["job"]["status"] == "failed"
            assert grimmory._manifest(root) == before
            if phase in {"external_temp_edit", "external_temp_replace", "incomplete_temp"}:
                assert (
                    "manually inspect the recorded temporary file"
                    in manager.status()["job"]["message"]
                )
        else:
            assert manager.status()["job"]["status"] == "completed"
            assert grimmory._manifest(root) == snapshot["plan"]["trees"][0]

    asyncio.run(scenario())


def test_status_and_preview_do_not_publish_tree_manifests(setup_library):
    manager, _, mapping, _, _ = setup_library

    async def scenario():
        plan = await optimize_all(manager, mapping)
        assert "trees" not in plan and "identities" not in plan
        assert "trees" not in json.dumps(manager.status())
        assert "identities" not in json.dumps(manager.status())

    asyncio.run(scenario())


def test_stale_manager_cannot_overwrite_registry_or_start_job(setup_library):
    manager, root, mapping, _, _ = setup_library

    async def scenario():
        await connect(manager)
        plan = await manager.preview(dict(mappings=[mapping]))
        stale = grimmory.GrimmoryManager(
            state_dir=manager.state_dir,
            backup_dir=manager.backup_dir,
            allowed_roots=[root],
            excluded_paths=[],
        )
        stale._token = "secret-token"
        await manager.start(dict(plan_id=plan["plan_id"], maintenance_confirmed=True))
        await manager._task
        stored = (manager.state_dir / "state.json").read_bytes()
        with pytest.raises(grimmory.GrimmoryConflictError, match="another worker"):
            await stale.start(dict(plan_id=plan["plan_id"], maintenance_confirmed=True))
        assert stale._task is None
        assert (manager.state_dir / "state.json").read_bytes() == stored
        assert len(json.loads(stored)["snapshots"]) == 1
        assert (root / "Author/Book.epub").read_bytes() == b"optimized"
        await stale.close()

    asyncio.run(scenario())


def test_status_polling_reads_detached_snapshots_during_worker_updates(setup_library):
    manager, root, mapping, _, _ = setup_library
    for index in range(8):
        (root / "Author" / f"Book{index}.epub").write_bytes(b"original")

    async def scenario():
        await connect(manager)
        plan = await manager.preview(dict(mappings=[mapping]))
        await manager.start(dict(plan_id=plan["plan_id"], maintenance_confirmed=True))
        count = 0
        while not manager._task.done():
            state = manager.status()
            for job in state["jobs"]:
                assert isinstance(job["results"], list)
            state["jobs"].clear()
            assert manager.status()["jobs"]
            count += 1
            await asyncio.sleep(0.001)
        await manager._task
        assert count > 0
        assert manager.status()["job"]["status"] == "completed"
        assert len(manager.status()["job"]["results"]) == 9

    asyncio.run(scenario())


@pytest.mark.parametrize("expected_failure", [True, False])
def test_optimizer_diagnostics_preserve_known_failures_only(
    setup_library, monkeypatch, expected_failure
):
    manager, root, mapping, _, _ = setup_library
    from epub_optimizer.errors import InvalidEpubError

    def optimize(*args, **kwargs):
        if expected_failure:
            raise InvalidEpubError("OPF metadata mismatch: dc:title differs from the source.")
        raise RuntimeError("unexpected secret-token and private remote response")

    monkeypatch.setattr(grimmory, "optimize_epub", optimize)
    asyncio.run(optimize_all(manager, mapping))
    result = manager.status()["job"]["results"][0]
    assert result["status"] == "failed"
    assert result["path"] == "Author/Book.epub"
    if expected_failure:
        assert result["message"] == "OPF metadata mismatch: dc:title differs from the source."
    else:
        assert result["message"] == "Optimization failed; inspect the original and preview again."
        assert "private remote response" not in json.dumps(manager.status())
        assert "secret-token" not in json.dumps(manager.status())
    assert (root / "Author/Book.epub").read_bytes() == b"original"


def test_restore_diagnostics_explain_known_snapshot_conflict(setup_library):
    manager, root, mapping, _, _ = setup_library

    async def scenario():
        await optimize_all(manager, mapping)
        snapshot_id = manager.status()["snapshots"][0]["snapshot_id"]
        backup = manager.backup_dir / snapshot_id / "0/Author/Book.epub"
        backup.write_bytes(b"corrupted snapshot")
        before = grimmory._manifest(root)
        await manager.restore(dict(snapshot_id=snapshot_id, maintenance_confirmed=True))
        await manager._task
        assert manager.status()["job"]["status"] == "failed"
        assert manager.status()["job"]["message"] == "Snapshot bytes or metadata changed."
        assert grimmory._manifest(root) == before

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure, expected",
    [
        ("mkdir", "creating backup directory (EACCES)"),
        ("ownership", "preserving ownership (EPERM)"),
        ("space", "copying file and copy metadata (ENOSPC)"),
        ("readonly", "copying file and copy metadata (EROFS)"),
        ("unsupported", f"syncing backup directories ({errno.errorcode[errno.EOPNOTSUPP]})"),
        ("missing", "copying file and copy metadata (ENOENT)"),
        ("manifest", "persisting snapshot manifest (ENOSPC)"),
        ("unexpected", None),
        ("http", None),
    ],
)
def test_backup_filesystem_diagnostics_leave_library_untouched(
    setup_library, monkeypatch, caplog, failure, expected
):
    manager, root, mapping, _, _ = setup_library
    before = grimmory._manifest(root)
    identities = grimmory._identities(root)
    private = "secret-token secret-pass https://private.example/?credential=private-value"

    def fail(code):
        raise OSError(code, private, private)

    def no_optimizer(*args, **kwargs):
        pytest.fail("optimizer must not run without a ready snapshot")

    monkeypatch.setattr(grimmory, "optimize_epub", no_optimizer)
    if failure in {"mkdir", "unexpected"}:
        original = grimmory.Path.mkdir

        def mkdir(path, *args, **kwargs):
            if path == manager.backup_dir:
                if failure == "unexpected":
                    raise RuntimeError(private)
                fail(errno.EACCES)
            return original(path, *args, **kwargs)

        monkeypatch.setattr(grimmory.Path, "mkdir", mkdir)
    elif failure == "ownership":
        original = grimmory._preserve

        def preserve(path, item, **kwargs):
            # Force an owner mismatch without requiring root or changing real ownership.
            if manager.backup_dir in path.parents:
                item = dict(item, uid=path.stat().st_uid + 1)
            return original(path, item, **kwargs)

        monkeypatch.setattr(grimmory, "_preserve", preserve)
        monkeypatch.setattr(grimmory.os, "chown", lambda *args: fail(errno.EPERM))
    elif failure == "unsupported":
        original = grimmory._fsync_dir

        def fsync_dir(path):
            if manager.backup_dir in path.parents:
                fail(errno.EOPNOTSUPP)
            return original(path)

        monkeypatch.setattr(grimmory, "_fsync_dir", fsync_dir)
    elif failure == "manifest":
        original = grimmory._json_write

        def json_write(path, data):
            if path.name == "manifest.json":
                fail(errno.ENOSPC)
            return original(path, data)

        monkeypatch.setattr(grimmory, "_json_write", json_write)
    else:
        def copy(*args, **kwargs):
            if failure == "http":
                raise HTTPError(private, 403, private, {}, None)
            fail({"space": errno.ENOSPC, "readonly": errno.EROFS, "missing": errno.ENOENT}[failure])

        monkeypatch.setattr(grimmory.shutil, "copy2", copy)

    asyncio.run(optimize_all(manager, mapping))
    status = manager.status()
    job = status["job"]
    assert job["status"] == "failed"
    assert job["results"] == []
    assert status["snapshots"] == []
    assert "snapshot_id" not in job
    if expected:
        assert job["message"].startswith("Backup failed while ")
        assert expected in job["message"]
        if failure == "ownership":
            assert "source owner/group" in job["message"]
        elif failure == "mkdir":
            assert "backup write access" in job["message"]
    else:
        assert job["message"] == (
            "Library operation stopped: backup, drift or filesystem safety check failed."
        )
    assert grimmory._manifest(root) == before
    assert grimmory._identities(root) == identities
    published = json.dumps(status) + (manager.state_dir / "state.json").read_text() + caplog.text
    for secret in ("secret-token", "secret-pass", "private.example", "private-value"):
        assert secret not in published


def test_known_failure_diagnostics_redact_token(setup_library):
    manager, _, _, _, _ = setup_library
    manager._token = "secret-token"
    assert manager._failure_message(
        grimmory.GrimmoryValidationError("Cannot continue: secret-token"), "fallback"
    ) == "Cannot continue: [redacted]"


@pytest.fixture
def saved_snapshot(setup_library):
    manager, root, mapping, _, calls = setup_library
    asyncio.run(optimize_all(manager, mapping))
    snapshot_id = manager.status()["snapshots"][0]["snapshot_id"]
    return manager, root, snapshot_id, calls


def test_delete_snapshot_offline_removes_only_selected_backup(saved_snapshot):
    manager, root, snapshot_id, calls = saved_snapshot
    before = grimmory._manifest(root)
    other = manager.backup_dir / ("f" * 32)
    other.mkdir()
    (other / "keep").write_bytes(b"unrelated backup")
    fresh = grimmory.GrimmoryManager(
        state_dir=manager.state_dir, backup_dir=manager.backup_dir, allowed_roots=[]
    )
    calls.clear()
    result = asyncio.run(fresh.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert result["snapshots"] == []
    assert not (manager.backup_dir / snapshot_id).exists()
    assert (other / "keep").read_bytes() == b"unrelated backup"
    assert grimmory._manifest(root) == before
    assert calls == []
    assert json.loads((manager.state_dir / "state.json").read_text())["snapshots"] == {}
    assert fresh._process_lock is None


@pytest.mark.parametrize("confirmed", [None, False, 1, "true"])
def test_delete_snapshot_requires_explicit_confirmation(saved_snapshot, confirmed):
    manager, _, snapshot_id, _ = saved_snapshot
    with pytest.raises(grimmory.GrimmoryValidationError, match="Confirm"):
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=confirmed)))
    assert (manager.backup_dir / snapshot_id / "manifest.json").exists()
    assert manager.status()["snapshots"][0]["status"] == "ready"


@pytest.mark.parametrize(
    "snapshot_id", [None, [], {}, "", ".", "..", "../library", "/tmp", "a" * 32]
)
def test_delete_snapshot_rejects_invalid_or_unknown_ids(saved_snapshot, snapshot_id):
    manager, root, valid_id, _ = saved_snapshot
    before = grimmory._manifest(root)
    with pytest.raises(grimmory.GrimmoryValidationError):
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert (manager.backup_dir / valid_id / "manifest.json").exists()
    assert grimmory._manifest(root) == before


@pytest.mark.parametrize("kind", ["identity", "manifest", "directory", "descendant", "parent"])
def test_delete_snapshot_rejects_tampering_and_symlinks(saved_snapshot, kind):
    manager, root, snapshot_id, _ = saved_snapshot
    target = manager.backup_dir / snapshot_id
    if kind == "identity":
        manager._state["snapshots"][snapshot_id]["snapshot_id"] = "../library"
        manager._save()
    elif kind == "manifest":
        (target / "manifest.json").write_text("{}")
    elif kind == "descendant":
        (target / "escape").symlink_to(root, target_is_directory=True)
    elif kind == "directory":
        target.rename(target.with_name("saved"))
        target.symlink_to(root, target_is_directory=True)
    else:
        manager.backup_dir.rename(manager.backup_dir.with_name("saved-backups"))
        manager.backup_dir.symlink_to(root, target_is_directory=True)
    before = grimmory._manifest(root)
    with pytest.raises(grimmory.GrimmoryValidationError):
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert grimmory._manifest(root) == before
    assert manager.status()["snapshots"][0]["status"] == "ready"


def test_delete_snapshot_rejects_backup_path_overlapping_source(saved_snapshot):
    manager, root, snapshot_id, _ = saved_snapshot
    manager.backup_dir = root
    (root / snapshot_id).mkdir()
    before = grimmory._manifest(root)
    with pytest.raises(grimmory.GrimmoryValidationError):
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert grimmory._manifest(root) == before


@pytest.mark.parametrize("kind", ["active", "journal", "watching"])
def test_delete_snapshot_blocks_unfinished_recovery(saved_snapshot, kind):
    manager, _, snapshot_id, _ = saved_snapshot
    job = manager._state["jobs"][-1]
    if kind == "active":
        job["status"] = "restoring"
    elif kind == "journal":
        job["status"] = "interrupted"
        job["results"][0]["status"] = "pending"
    else:
        job["watching_recovery"] = dict(status="pending", base_url="http://grimmory:6060")
    manager._save()
    with pytest.raises(grimmory.GrimmoryConflictError):
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert (manager.backup_dir / snapshot_id / "manifest.json").exists()


def test_delete_snapshot_blocks_active_task(saved_snapshot):
    manager, _, snapshot_id, _ = saved_snapshot

    async def scenario():
        manager._task = asyncio.create_task(asyncio.sleep(30))
        try:
            with pytest.raises(grimmory.GrimmoryConflictError):
                await manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True))
        finally:
            manager._task.cancel()
            await asyncio.gather(manager._task, return_exceptions=True)

    asyncio.run(scenario())
    assert (manager.backup_dir / snapshot_id / "manifest.json").exists()


@pytest.mark.parametrize("kind", ["locked", "stale"])
def test_delete_snapshot_checks_process_lock_and_digest_before_removal(saved_snapshot, kind):
    manager, root, snapshot_id, _ = saved_snapshot
    other = grimmory.GrimmoryManager(
        state_dir=manager.state_dir, backup_dir=manager.backup_dir, allowed_roots=[root]
    )
    if kind == "locked":
        other._acquire_process_lock()
    else:
        other._state["base_url"] = "http://changed:6060"
        other._save()
    stored = (manager.state_dir / "state.json").read_bytes()
    try:
        with pytest.raises(grimmory.GrimmoryConflictError):
            asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    finally:
        other._release_process_lock()
    assert (manager.state_dir / "state.json").read_bytes() == stored
    assert (manager.backup_dir / snapshot_id / "manifest.json").exists()


@pytest.mark.parametrize("stage", ["intent", "removal", "partial", "registry"])
def test_delete_snapshot_failure_is_safe_and_retryable(saved_snapshot, monkeypatch, stage):
    manager, root, snapshot_id, calls = saved_snapshot
    before = grimmory._manifest(root)
    target = manager.backup_dir / snapshot_id
    real_save, real_remove = manager._save, grimmory.shutil.rmtree
    saves = 0

    def save():
        nonlocal saves
        saves += 1
        if saves == (2 if stage == "registry" else 1):
            raise OSError(errno.ENOSPC, "private filesystem path")
        real_save()

    def remove(path):
        if stage == "partial":
            (path / "0/Author/Book.epub").unlink()
        raise OSError(errno.EACCES, "private filesystem path")

    if stage in {"intent", "registry"}:
        monkeypatch.setattr(manager, "_save", save)
    else:
        monkeypatch.setattr(grimmory.shutil, "rmtree", remove)
        remove.avoids_symlink_attacks = True
    with pytest.raises(OSError):
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert grimmory._manifest(root) == before
    assert snapshot_id in manager._state["snapshots"]
    assert manager._process_lock is None
    stored = json.loads((manager.state_dir / "state.json").read_text())["snapshots"][snapshot_id]
    assert stored["status"] == ("ready" if stage == "intent" else "deleting")
    if stage != "intent":
        with pytest.raises(grimmory.GrimmoryValidationError, match="deletion is pending"):
            asyncio.run(manager.restore(dict(snapshot_id=snapshot_id, maintenance_confirmed=True)))
    else:
        assert (target / "manifest.json").exists()
    monkeypatch.setattr(grimmory.shutil, "rmtree", real_remove)
    recovered = grimmory.GrimmoryManager(
        state_dir=manager.state_dir, backup_dir=manager.backup_dir, allowed_roots=[]
    )
    calls.clear()
    asyncio.run(recovered.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert not target.exists()
    assert recovered.status()["snapshots"] == []
    assert calls == []


def test_delete_snapshot_serializes_requests_and_holds_process_lock(saved_snapshot, monkeypatch):
    manager, root, snapshot_id, _ = saved_snapshot
    other = grimmory.GrimmoryManager(
        state_dir=manager.state_dir, backup_dir=manager.backup_dir, allowed_roots=[root]
    )
    entered, release = threading.Event(), threading.Event()
    real_remove = grimmory.shutil.rmtree

    def remove(path):
        entered.set()
        assert release.wait(5)
        real_remove(path)

    remove.avoids_symlink_attacks = True
    monkeypatch.setattr(grimmory.shutil, "rmtree", remove)

    async def scenario():
        first = asyncio.create_task(
            manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True))
        )
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            with pytest.raises(grimmory.GrimmoryConflictError, match="process"):
                await other.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True))
            second = asyncio.create_task(
                manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True))
            )
            await asyncio.sleep(0)
            assert not second.done()
        finally:
            release.set()
        await first
        with pytest.raises(grimmory.GrimmoryValidationError, match="Unknown snapshot"):
            await second

    asyncio.run(scenario())
    assert manager.status()["snapshots"] == []


def test_delete_snapshot_allows_interrupted_job_without_pending_recovery(saved_snapshot):
    manager, _, snapshot_id, _ = saved_snapshot
    manager._state["jobs"][-1]["status"] = "interrupted"
    manager._save()
    asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert manager.status()["snapshots"] == []


def test_delete_snapshot_retry_rejects_replaced_directory(saved_snapshot, monkeypatch):
    manager, _, snapshot_id, _ = saved_snapshot
    target = manager.backup_dir / snapshot_id
    real_remove = grimmory.shutil.rmtree

    def remove(path):
        raise OSError(errno.EACCES, "denied")

    remove.avoids_symlink_attacks = True
    monkeypatch.setattr(grimmory.shutil, "rmtree", remove)
    with pytest.raises(OSError):
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    target.rename(target.with_name("retained-original"))
    target.mkdir()
    (target / "keep").write_bytes(b"replacement data")
    monkeypatch.setattr(grimmory.shutil, "rmtree", real_remove)
    with pytest.raises(grimmory.GrimmoryValidationError, match="directory changed"):
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert (target / "keep").read_bytes() == b"replacement data"


def test_delete_snapshot_cancellation_holds_lock_until_removal_stops(saved_snapshot, monkeypatch):
    manager, _, snapshot_id, _ = saved_snapshot
    entered, release = threading.Event(), threading.Event()
    real_remove = grimmory.shutil.rmtree

    def remove(path):
        entered.set()
        assert release.wait(5)
        real_remove(path)

    remove.avoids_symlink_attacks = True
    monkeypatch.setattr(grimmory.shutil, "rmtree", remove)

    async def scenario():
        deletion = asyncio.create_task(
            manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True))
        )
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            deletion.cancel()
            await asyncio.sleep(0)
            assert manager._process_lock is not None
            assert manager._lock.locked()
            deletion.cancel()
            await asyncio.sleep(0)
            assert manager._process_lock is not None
            assert manager._lock.locked()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await deletion
        assert manager._process_lock is None
        assert manager.status()["snapshots"][0]["status"] == "deleting"
        await manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True))

    asyncio.run(scenario())
    assert manager.status()["snapshots"] == []


@pytest.mark.parametrize("stage", ["intent", "registry"])
def test_delete_snapshot_reconciles_state_after_replacement_failure(
    saved_snapshot, monkeypatch, stage
):
    manager, root, snapshot_id, _ = saved_snapshot
    before = grimmory._manifest(root)
    real_write = grimmory._json_write
    writes = 0

    def write(path, data):
        nonlocal writes
        writes += 1
        real_write(path, data)
        if writes == (1 if stage == "intent" else 2):
            raise OSError(errno.EIO, "sync failure after replacement")

    monkeypatch.setattr(grimmory, "_json_write", write)
    with pytest.raises(OSError):
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    persisted = json.loads((manager.state_dir / "state.json").read_text())
    assert manager._state == persisted
    assert manager._state_digest == grimmory._digest(manager.state_dir / "state.json")
    assert grimmory._manifest(root) == before
    if stage == "intent":
        assert manager.status()["snapshots"][0]["status"] == "deleting"
        assert (manager.backup_dir / snapshot_id / "manifest.json").exists()
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert manager.status()["snapshots"] == []
    assert not (manager.backup_dir / snapshot_id).exists()


def test_delete_snapshot_missing_directory_retry_syncs_backup_before_registry(
    saved_snapshot, monkeypatch
):
    manager, _, snapshot_id, _ = saved_snapshot
    target = manager.backup_dir / snapshot_id
    snapshot = manager._state["snapshots"][snapshot_id]
    info = target.stat()
    snapshot.update(status="deleting", deletion_identity=[info.st_dev, info.st_ino])
    manager._save()
    grimmory.shutil.rmtree(target)
    events = []
    real_sync, real_save = grimmory._fsync_dir, manager._save

    def sync(path):
        if path == manager.backup_dir:
            events.append("sync backup")
        real_sync(path)

    def save():
        events.append("save registry")
        real_save()

    monkeypatch.setattr(grimmory, "_fsync_dir", sync)
    monkeypatch.setattr(manager, "_save", save)
    asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert events[:2] == ["sync backup", "save registry"]


def test_delete_snapshot_unreadable_failed_save_requires_restart(saved_snapshot, monkeypatch):
    manager, _, snapshot_id, _ = saved_snapshot
    real_safe = grimmory._safe

    def unreadable(path, **kwargs):
        if path == manager.state_dir / "state.json":
            raise OSError(errno.EACCES, "state temporarily unreadable")
        return real_safe(path, **kwargs)

    def save():
        monkeypatch.setattr(grimmory, "_safe", unreadable)
        raise OSError(errno.EIO, "write failed")

    monkeypatch.setattr(manager, "_save", save)
    with pytest.raises(OSError):
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    assert manager.status()["snapshots"][0]["status"] == "deleting"
    assert (manager.backup_dir / snapshot_id / "manifest.json").exists()
    monkeypatch.setattr(grimmory, "_safe", real_safe)
    with pytest.raises(grimmory.GrimmoryConflictError, match="restart"):
        asyncio.run(manager.delete_snapshot(dict(snapshot_id=snapshot_id, confirmed=True)))
    with pytest.raises(grimmory.GrimmoryValidationError, match="deletion is pending"):
        asyncio.run(manager.restore(dict(snapshot_id=snapshot_id, maintenance_confirmed=True)))
