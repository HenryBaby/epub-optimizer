import asyncio
import hashlib
import json
import os
import threading
from types import SimpleNamespace

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
