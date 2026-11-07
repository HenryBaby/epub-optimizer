"""Watcher changes use mocked HTTP exclusively; no Grimmory instance is contacted."""

import asyncio
import copy
import json
from urllib.error import HTTPError

import pytest

from epub_optimizer import grimmory


def library(identifier, watch=True):
    return dict(
        id=identifier,
        name=f"Books {identifier}",
        icon="book",
        iconType="FONT_AWESOME",
        paths=[dict(id=identifier * 10, libraryId=identifier, path=f"/books/{identifier}")],
        watch=watch,
        formatPriority=["EPUB", "PDF"],
        allowedFormats=["EPUB"],
        metadataSource="EMBEDDED",
        organizationMode="BOOK_TITLE",
        sort="ignored",
        fileNamingPattern="never-send",
    )


@pytest.fixture
def remote(tmp_path, monkeypatch):
    libraries = {1: library(1), 2: library(2, False), 3: library(3)}
    puts = []
    fault = {}

    def request(url, payload=None, token=None, *, method=None):
        if url.endswith("/auth/login"):
            return {"accessToken": "secret-token"}
        if url.endswith("/libraries"):
            return copy.deepcopy(list(libraries.values()))
        identifier = int(url.rsplit("/", 1)[1])
        if method == "PUT":
            # The receipt is durable before any remote mutation.
            saved = json.loads((tmp_path / "state/state.json").read_text())
            assert saved["watcher_maintenance"]["libraries"]
            puts.append((identifier, copy.deepcopy(payload)))
            if fault.get("deny") == identifier:
                raise grimmory.GrimmoryValidationError(
                    "Grimmory denied access; library management permission required."
                )
            libraries[identifier].update(copy.deepcopy(payload))
            if fault.get("timeout") == identifier:
                raise TimeoutError("secret-token")
            if fault.get("drift") == identifier:
                libraries[identifier]["name"] = "Changed externally"
            return None
        return copy.deepcopy(libraries[identifier])

    monkeypatch.setattr(grimmory, "_request_json", request)
    manager = grimmory.GrimmoryManager(state_dir=tmp_path / "state", allowed_roots=[tmp_path])
    return manager, libraries, puts, fault


async def connect(manager, url="http://grimmory:6060"):
    await manager.connect(dict(base_url=url, username="user", password="password"))


def test_preserves_complete_settings_and_restores_only_owned(remote):
    manager, libraries, puts, _ = remote
    before = copy.deepcopy(libraries)

    async def scenario():
        await connect(manager)
        result = await manager.pause_watching(dict(library_ids=[1, 2]))
        session = result["watcher_maintenance"]
        assert session["status"] == "paused"
        assert [x["original_watch"] for x in session["libraries"]] == [True, False]
        await manager.pause_watching(dict(library_ids=[2, 1]))
        assert len(puts) == 1
        await manager.resume_watching(dict(session_id=session["session_id"]))
        assert manager.status()["watcher_maintenance"]["status"] == "resumed"

    asyncio.run(scenario())
    assert libraries == before
    assert [identifier for identifier, _ in puts] == [1, 1]
    for _, payload in puts:
        assert payload["paths"] == before[1]["paths"]
        assert "id" not in payload and "sort" not in payload and "fileNamingPattern" not in payload
        assert {k: v for k, v in payload.items() if k != "watch"} == {
            k: before[1][k] for k in payload if k != "watch"
        }


@pytest.mark.parametrize("retry", ["pause", "resume"])
def test_timeout_after_apply_retains_original_and_recovers(remote, retry):
    manager, libraries, puts, fault = remote

    async def scenario():
        await connect(manager)
        fault["timeout"] = 1
        result = await manager.pause_watching(dict(library_ids=[1, 3]))
        receipt = result["watcher_maintenance"]
        assert receipt["status"] == "partial"
        assert receipt["libraries"][0]["status"] == "pause_pending"
        assert "secret-token" not in json.dumps(result)
        assert libraries[1]["watch"] is False and libraries[3]["watch"] is False
        with pytest.raises(grimmory.GrimmoryValidationError, match="unverified"):
            manager._mappings([dict(library_id=1)])
        fault.clear()
        if retry == "pause":
            await manager.pause_watching(dict(library_ids=[1, 3]))
            assert manager.status()["watcher_maintenance"]["status"] == "paused"
            assert len(puts) == 2
        await manager.resume_watching(dict(session_id=receipt["session_id"]))
        assert all(libraries[x]["watch"] for x in (1, 3))

    asyncio.run(scenario())


def test_partial_failure_does_not_forget_success(remote):
    manager, libraries, _, fault = remote

    async def scenario():
        await connect(manager)
        fault["deny"] = 3
        session = (await manager.pause_watching(dict(library_ids=[1, 3])))["watcher_maintenance"]
        assert session["status"] == "partial"
        assert session["libraries"][0]["status"] == "paused"
        assert "permission" in session["libraries"][1]["error"]
        fault.clear()
        await manager.resume_watching(dict(session_id=session["session_id"]))
        assert libraries[1]["watch"] and libraries[3]["watch"]

    asyncio.run(scenario())


def test_restart_requires_reconnect_to_same_instance(remote):
    manager, libraries, puts, _ = remote

    async def scenario():
        await connect(manager)
        session = (await manager.pause_watching(dict(library_ids=[1])))["watcher_maintenance"]
        restarted = grimmory.GrimmoryManager(state_dir=manager.state_dir)
        assert len(puts) == 1
        with pytest.raises(grimmory.GrimmoryValidationError, match="Reconnect"):
            await restarted.resume_watching(dict(session_id=session["session_id"]))
        await connect(restarted, "http://other:6060")
        with pytest.raises(grimmory.GrimmoryConflictError, match="instance"):
            await restarted.resume_watching(dict(session_id=session["session_id"]))
        assert len(puts) == 1
        await connect(restarted)
        await restarted.resume_watching(dict(session_id=session["session_id"]))
        assert libraries[1]["watch"]

    asyncio.run(scenario())
    assert "secret-token" not in (manager.state_dir / "state.json").read_text()


def test_path_conflict_refuses_overwrite_but_current_settings_are_preserved(remote):
    manager, libraries, puts, _ = remote

    async def scenario():
        await connect(manager)
        session = (await manager.pause_watching(dict(library_ids=[1])))["watcher_maintenance"]
        libraries[1]["name"] = "New name"
        libraries[1]["paths"][0]["path"] = "/changed"
        await manager.resume_watching(dict(session_id=session["session_id"]))
        assert len(puts) == 1
        assert "paths changed" in manager.status()["watcher_maintenance"]["libraries"][0]["error"]
        libraries[1]["paths"][0]["path"] = "/books/1"
        await manager.resume_watching(dict(session_id=session["session_id"]))
        assert libraries[1]["name"] == "New name"
        assert libraries[1]["watch"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field,value",
    [
        ("paths", []),
        ("allowedFormats", 42),
        ("watch", "true"),
        ("name", ""),
        ("paths", [{"id": True, "path": "/new"}]),
        ("metadataSource", 42),
    ],
)
def test_malformed_library_fails_closed(remote, field, value):
    manager, libraries, puts, _ = remote

    async def scenario():
        await connect(manager)
        libraries[1][field] = value
        result = await manager.pause_watching(dict(library_ids=[1]))
        assert result["watcher_maintenance"]["status"] == "partial"
        assert puts == []

    asyncio.run(scenario())


def test_unverified_post_update_and_selection_conflicts(remote):
    manager, _, puts, fault = remote

    async def scenario():
        await connect(manager)
        fault["drift"] = 1
        session = (await manager.pause_watching(dict(library_ids=[1])))["watcher_maintenance"]
        assert session["status"] == "partial"
        with pytest.raises(grimmory.GrimmoryConflictError, match="selection"):
            await manager.pause_watching(dict(library_ids=[3]))
        with pytest.raises(grimmory.GrimmoryValidationError, match="saved"):
            await manager.resume_watching(dict(session_id="wrong"))
        assert len(puts) == 1

    asyncio.run(scenario())


def test_active_job_blocks_both_operations(remote):
    manager, _, puts, _ = remote

    async def scenario():
        await connect(manager)
        manager._task = asyncio.create_task(asyncio.Event().wait())
        try:
            for operation, payload in [
                (manager.pause_watching, dict(library_ids=[1])),
                (manager.resume_watching, dict(session_id="any")),
            ]:
                with pytest.raises(grimmory.GrimmoryConflictError, match="running"):
                    await operation(payload)
        finally:
            manager._task.cancel()
        assert puts == []

    asyncio.run(scenario())


def test_request_forbidden_has_safe_permission_message(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            assert request.method == "PUT"
            raise HTTPError(request.full_url, 403, "secret-token", {}, None)

    monkeypatch.setattr(grimmory, "build_opener", lambda *args: Opener())
    with pytest.raises(grimmory.GrimmoryValidationError, match="management permission") as error:
        grimmory._request_json("http://mock/api/v1/libraries/1", {}, "secret-token", method="PUT")
    assert "secret-token" not in str(error.value)


@pytest.mark.parametrize("omit", [False, True])
def test_nullable_optional_settings_round_trip(remote, omit):
    manager, libraries, puts, _ = remote
    optional = (
        "icon",
        "iconType",
        "formatPriority",
        "allowedFormats",
        "metadataSource",
        "organizationMode",
    )
    for key in optional:
        if omit:
            libraries[1].pop(key)
        else:
            libraries[1][key] = None

    async def scenario():
        await connect(manager)
        receipt = (await manager.pause_watching(dict(library_ids=[1])))["watcher_maintenance"]
        assert receipt["status"] == "paused"
        await manager.resume_watching(dict(session_id=receipt["session_id"]))
        assert libraries[1]["watch"]
        assert all(payload[key] is None for _, payload in puts for key in optional)

    asyncio.run(scenario())


def test_stale_worker_revision_prevents_remote_writes(remote):
    manager, _, puts, _ = remote

    async def scenario():
        await connect(manager)
        other = grimmory.GrimmoryManager(state_dir=manager.state_dir)
        await connect(other)
        other._state["mappings"] = [{"changed": True}]
        other._save()
        with pytest.raises(grimmory.GrimmoryConflictError, match="State changed"):
            await manager.pause_watching(dict(library_ids=[1]))
        assert puts == []

    asyncio.run(scenario())


def test_cancelled_http_worker_retains_both_locks_until_finished(remote, monkeypatch):
    import threading

    manager, _, _, _ = remote
    entered, release = threading.Event(), threading.Event()
    original_request = grimmory._request_json
    updates = []

    def request(url, payload=None, token=None, *, method=None):
        if method == "PUT":
            updates.append((url, token))
            if not entered.is_set():
                entered.set()
                if not release.wait(10):
                    raise AssertionError("Blocked mock PUT was not released")
        return original_request(url, payload, token, method=method)

    monkeypatch.setattr(grimmory, "_request_json", request)

    async def scenario():
        await connect(manager)
        pause = asyncio.create_task(manager.pause_watching(dict(library_ids=[1, 3])))
        reconnect = None
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            pause.cancel()
            await asyncio.sleep(0)
            pause.cancel()
            await asyncio.sleep(0)
            reconnect = asyncio.create_task(connect(manager, "http://other:6060"))
            await asyncio.sleep(0)
            assert not pause.done() and not reconnect.done()
            assert manager._lock.locked() and manager._process_lock is not None
            assert manager._state["base_url"] == "http://grimmory:6060"
            assert manager._token == "secret-token"
            competing = grimmory.GrimmoryManager(state_dir=manager.state_dir)
            with pytest.raises(grimmory.GrimmoryConflictError, match="process"):
                competing._acquire_process_lock()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await pause
            if reconnect is not None:
                await reconnect
        assert updates == [
            (f"http://grimmory:6060/api/v1/libraries/{identifier}", "secret-token")
            for identifier in (1, 3)
        ]
        assert manager._process_lock is None
        assert not manager._lock.locked()
        assert manager._state["base_url"] == "http://other:6060"
        assert manager.status()["watcher_maintenance"]["status"] == "paused"

    asyncio.run(scenario())
