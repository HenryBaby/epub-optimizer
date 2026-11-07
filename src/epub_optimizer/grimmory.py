"""Explicit, manual Grimmory file maintenance. No startup scans or remote mutations."""

from __future__ import annotations

import asyncio
import base64
import copy
import fcntl
import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from epub_optimizer.core import optimize_epub
from epub_optimizer.errors import EpubOptimizerError


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def _safe(path, *, exists=True):
    path = Path(os.path.abspath(path))
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise GrimmoryValidationError("Symlink paths are not permitted.")
    if exists and not path.exists():
        raise GrimmoryValidationError("Selected path does not exist.")
    return path


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _identities(root):
    return {
        p.relative_to(root).as_posix(): [p.lstat().st_dev, p.lstat().st_ino]
        for p in [root, *sorted(root.rglob("*"))]
    }


def _json_write(path, data):
    _safe(path, exists=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        _fsync_dir(path.parent)
        _fsync_dir(path.parent.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def _metadata(path):
    value = path.lstat()
    return dict(
        mode=stat.S_IMODE(value.st_mode),
        uid=value.st_uid,
        gid=value.st_gid,
        mtime_ns=value.st_mtime_ns,
        xattrs={
            name: base64.b64encode(os.getxattr(path, name)).decode() for name in os.listxattr(path)
        },
    )


def _preserve(path, item):
    current = path.stat()
    if (current.st_uid, current.st_gid) != (item["uid"], item["gid"]):
        os.chown(path, item["uid"], item["gid"])
    for name in os.listxattr(path):
        if name not in item.get("xattrs", {}):
            os.removexattr(path, name)
    for name, value in item.get("xattrs", {}).items():
        os.setxattr(path, name, base64.b64decode(value))
    os.chmod(path, item["mode"])
    os.utime(path, ns=(item["mtime_ns"], item["mtime_ns"]))
    if _metadata(path) != {key: item[key] for key in ("mode", "uid", "gid", "mtime_ns", "xattrs")}:
        raise GrimmoryValidationError("Filesystem metadata could not be preserved.")


def _manifest(root, *, hash_files=True):
    root = _safe(root)
    if not root.is_dir():
        raise GrimmoryValidationError("Library path must be a directory.")
    result = {}
    for path in [root, *sorted(root.rglob("*"))]:
        _safe(path)
        info = path.lstat()
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise GrimmoryValidationError("Special files are not permitted.")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise GrimmoryValidationError("Hardlinked files are not permitted.")
        item = _metadata(path)
        item.update(type="dir" if path.is_dir() else "file")
        if item["type"] == "file":
            item.update(size=info.st_size)
            if hash_files:
                item["sha256"] = _digest(path)
            after = path.lstat()
            if (info.st_ino, info.st_dev, info.st_mtime_ns, info.st_size) != (
                after.st_ino,
                after.st_dev,
                after.st_mtime_ns,
                after.st_size,
            ):
                raise GrimmoryValidationError("Library changed while scanning.")
        result[path.relative_to(root).as_posix()] = item
    return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GrimmoryValidationError("Grimmory redirects are not permitted.")


def _request_json(url, payload=None, token=None, *, method=None):
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with build_opener(_NoRedirect).open(request, timeout=15) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise GrimmoryValidationError("Response too large.")
        return json.loads(body) if body else None
    except HTTPError as exc:
        if exc.code == 403:
            raise GrimmoryValidationError(
                "Grimmory denied access; use an administrator or a user with library "
                "management permission and access to the selected library."
            ) from None
        raise GrimmoryValidationError("Grimmory request failed; check access and retry.") from None
    except Exception:
        raise GrimmoryValidationError(
            "Grimmory request failed; check the URL and credentials."
        ) from None


class GrimmoryValidationError(ValueError):
    """A known validation error safe to show in the manual maintenance UI."""


class GrimmoryConflictError(RuntimeError):
    """An explicit operation conflicts with an active operation."""


class GrimmoryManager:
    def __init__(self, *, state_dir=None, backup_dir=None, allowed_roots=None, excluded_paths=None):
        self.state_dir = Path(state_dir or "/data/grimmory")
        self.backup_dir = Path(
            backup_dir
            or os.environ.get("EPUB_OPTIMIZER_LIBRARY_BACKUP_DIR", "/data/library-backups")
        )
        self.allowed_roots = [
            Path(p).absolute()
            for p in (
                allowed_roots
                if allowed_roots is not None
                else filter(
                    None, os.environ.get("EPUB_OPTIMIZER_LIBRARY_ROOTS", "").split(os.pathsep)
                )
            )
        ]
        self.excluded_paths = [
            Path(p).absolute()
            for p in (
                excluded_paths
                if excluded_paths is not None
                else ["/watch", "/output", "/failed", "/unprocessed"]
            )
        ]
        self._state = dict(
            base_url="",
            libraries=[],
            mappings=[],
            plans={},
            snapshots={},
            jobs=[],
            watcher_maintenance=None,
        )
        state_path = self.state_dir / "state.json"
        self._state_digest = None
        if state_path.exists():
            _safe(state_path)
            state_bytes = state_path.read_bytes()
            self._state_digest = hashlib.sha256(state_bytes).hexdigest()
            self._state.update(json.loads(state_bytes))
        for job in self._state["jobs"]:
            if job["status"] in {"running", "backing_up", "restoring"}:
                job["status"] = "interrupted"
        self._token = None
        self._connected = False
        self._task = None
        self._cancel = threading.Event()
        self._lock = asyncio.Lock()
        self._process_lock = None
        self._status_lock = threading.RLock()
        self._public_state = self._capture_status()

    def _save(self):
        temporary_lock = self._process_lock is None
        if temporary_lock:
            self._acquire_process_lock()
        try:
            state_path = self.state_dir / "state.json"
            actual_digest = _digest(_safe(state_path)) if state_path.exists() else None
            if actual_digest != self._state_digest:
                raise GrimmoryConflictError(
                    "State changed in another worker; restart this worker before maintenance."
                )
            _json_write(state_path, self._state)
            self._state_digest = _digest(state_path)
            # Publish only detached snapshots; polling never traverses mutable worker state.
            public_state = self._capture_status()
            with self._status_lock:
                self._public_state = public_state
        finally:
            if temporary_lock:
                self._release_process_lock()

    @staticmethod
    def _public_plan(plan):
        return {k: copy.deepcopy(v) for k, v in plan.items() if k not in {"trees", "identities"}}

    def status(self):
        with self._status_lock:
            value = copy.deepcopy(self._public_state)
        value["running"] = bool(self._task and not self._task.done())
        return value

    def _capture_status(self):
        value = {
            k: copy.deepcopy(v) for k, v in self._state.items() if k not in {"plans", "snapshots"}
        }
        value["plans"] = {k: self._public_plan(p) for k, p in self._state["plans"].items()}
        value["snapshots"] = {
            k: {
                **{a: copy.deepcopy(b) for a, b in snap.items() if a != "plan"},
                "plan": self._public_plan(snap["plan"]),
            }
            for k, snap in self._state["snapshots"].items()
        }
        value.update(
            configured=bool(self.allowed_roots),
            connected=self._connected,
            running=bool(self._task and not self._task.done()),
            active_job=next(
                (
                    j
                    for j in reversed(value["jobs"])
                    if j["status"] in {"running", "backing_up", "restoring"}
                ),
                None,
            ),
            backup_scope="Files and folders only; Grimmory database is not backed up.",
        )
        value["preview"] = next(reversed(value["plans"].values()), None)
        value["job"] = value["jobs"][-1] if value["jobs"] else None
        value["history"] = value["jobs"]
        value["snapshots"] = list(value["snapshots"].values())
        value["plans"] = list(value["plans"].values())
        return value

    def _failure_message(self, exc, fallback):
        if isinstance(exc, (GrimmoryValidationError, EpubOptimizerError)):
            message = str(exc)
            return message.replace(self._token, "[redacted]") if self._token else message
        return fallback

    def _idle(self):
        if self._task and not self._task.done():
            raise GrimmoryConflictError("A library operation is already running.")

    async def connect(self, payload):
        async with self._lock:
            self._idle()
            url = str(payload.get("base_url", "")).rstrip("/")
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise GrimmoryValidationError(
                    "Provide an HTTP(S) URL without credentials, query or fragment."
                )
            auth = await asyncio.to_thread(
                _request_json,
                url + "/api/v1/auth/login",
                {"username": payload.get("username", ""), "password": payload.get("password", "")},
            )
            token = auth.get("accessToken") if isinstance(auth, dict) else None
            if not isinstance(token, str) or not token:
                raise GrimmoryValidationError("Grimmory did not return an access token.")
            libraries = await asyncio.to_thread(
                _request_json, url + "/api/v1/libraries", None, token
            )
            if not isinstance(libraries, list):
                raise GrimmoryValidationError("Unexpected Grimmory library response.")
            cleaned = []
            for library in libraries:
                if not isinstance(library, dict) or not isinstance(library.get("paths"), list):
                    raise GrimmoryValidationError("Unexpected Grimmory library response.")
                cleaned.append(
                    dict(
                        id=library.get("id"),
                        name=str(library.get("name", "")),
                        watch=library.get("watch") is not False,
                        paths=[
                            dict(id=p.get("id"), path=str(p.get("path", "")))
                            for p in library["paths"]
                            if isinstance(p, dict)
                        ],
                    )
                )
            self._state.update(base_url=url, libraries=cleaned)
            self._token = token
            self._connected = True
            self._save()
            return self.status()

    def _refresh(self):
        if not self._token:
            raise GrimmoryValidationError("Reconnect Grimmory before maintenance.")
        libraries = _request_json(self._state["base_url"] + "/api/v1/libraries", None, self._token)
        if not isinstance(libraries, list):
            raise GrimmoryValidationError("Unexpected Grimmory library response.")
        self._state["libraries"] = [
            dict(
                id=x["id"],
                name=x.get("name", ""),
                watch=x.get("watch") is not False,
                paths=x["paths"],
            )
            for x in libraries
        ]

    @staticmethod
    def _watch_body(library, library_id):
        """Whitelist the complete update DTO; never send discovery-only fields."""
        fields = (
            "name",
            "icon",
            "iconType",
            "paths",
            "watch",
            "formatPriority",
            "allowedFormats",
            "metadataSource",
            "organizationMode",
        )
        if not isinstance(library, dict) or str(library.get("id")) != str(library_id):
            raise GrimmoryValidationError("Unexpected Grimmory library identity.")
        if any(key not in library for key in ("name", "paths", "watch")):
            raise GrimmoryValidationError("Incomplete library settings; watching was not changed.")
        body = {key: copy.deepcopy(library.get(key)) for key in fields}
        if (
            not isinstance(body["name"], str)
            or not body["name"].strip()
            or type(body["watch"]) is not bool
        ):
            raise GrimmoryValidationError("Invalid library settings; watching was not changed.")
        for key in ("icon", "iconType", "metadataSource", "organizationMode"):
            if body[key] is not None and not isinstance(body[key], str):
                raise GrimmoryValidationError("Invalid library settings; watching was not changed.")
        for key in ("formatPriority", "allowedFormats"):
            if body[key] is not None and (
                not isinstance(body[key], list) or any(not isinstance(x, str) for x in body[key])
            ):
                raise GrimmoryValidationError("Invalid library formats; watching was not changed.")
        if not isinstance(body["paths"], list) or not body["paths"]:
            raise GrimmoryValidationError("Missing library paths; watching was not changed.")
        paths = []
        for path in body["paths"]:
            if (
                not isinstance(path, dict)
                or ("id" in path and (type(path["id"]) is not int or path["id"] <= 0))
                or (
                    "libraryId" in path
                    and (
                        type(path["libraryId"]) is not int
                        or str(path["libraryId"]) != str(library_id)
                    )
                )
                or not isinstance(path.get("path"), str)
                or not path["path"].strip()
            ):
                raise GrimmoryValidationError(
                    "Invalid library path identity; watching was not changed."
                )
            paths.append({key: path[key] for key in ("id", "libraryId", "path") if key in path})
        ids = [p["id"] for p in paths if "id" in p]
        if len(set(ids)) != len(ids) or len({p["path"] for p in paths}) != len(paths):
            raise GrimmoryValidationError("Duplicate library path identity.")
        body["paths"] = paths
        return body

    def _watch_read(self, library_id):
        url = self._state["base_url"] + f"/api/v1/libraries/{library_id}"
        return self._watch_body(_request_json(url, None, self._token), library_id)

    def _watch_update(self, item, body, target):
        item["status"] = "resume_pending" if target else "pause_pending"
        item.pop("error", None)
        # The receipt and its original value must be durable before a possibly ambiguous PUT.
        self._save()
        expected = {**body, "watch": target}
        _request_json(
            self._state["base_url"] + f"/api/v1/libraries/{item['library_id']}",
            expected,
            self._token,
            method="PUT",
        )
        actual = self._watch_read(item["library_id"])
        if actual != expected:
            raise GrimmoryValidationError(
                "Library settings changed or watching could not be verified; retry explicitly."
            )

    async def pause_watching(self, payload):
        return await self._watch_operation(payload, resume=False)

    async def resume_watching(self, payload):
        return await self._watch_operation(payload, resume=True)

    async def _watch_operation(self, payload, *, resume):
        async with self._lock:
            self._idle()
            if not self._connected or not self._token:
                raise GrimmoryValidationError("Reconnect Grimmory before changing watching.")
            session = self._state.get("watcher_maintenance")
            if resume:
                if not session or payload.get("session_id") != session["session_id"]:
                    raise GrimmoryValidationError("Select the saved watcher session to resume.")
            else:
                ids = payload.get("library_ids")
                if (
                    not isinstance(ids, list)
                    or not ids
                    or any(type(x) is not int or x <= 0 for x in ids)
                    or len(set(ids)) != len(ids)
                ):
                    raise GrimmoryValidationError("Select unique library IDs to pause.")
                known = {str(x["id"]) for x in self._state["libraries"]}
                if any(str(x) not in known for x in ids):
                    raise GrimmoryValidationError("Select discovered Grimmory libraries only.")
                if session and session["status"] != "resumed":
                    if set(ids) != {x["library_id"] for x in session["libraries"]}:
                        raise GrimmoryConflictError(
                            "Resume the saved watcher session before changing selection."
                        )
                else:
                    session = dict(
                        session_id=uuid.uuid4().hex,
                        base_url=self._state["base_url"],
                        status="partial",
                        libraries=[dict(library_id=x, status="pending") for x in ids],
                    )
            if session["base_url"] != self._state["base_url"]:
                raise GrimmoryConflictError(
                    "Reconnect to the saved Grimmory instance before watcher recovery."
                )
            if not resume and any(
                x["status"] in {"resume_pending", "restored"} for x in session["libraries"]
            ):
                raise GrimmoryConflictError("Finish resuming the saved watcher session first.")
            self._acquire_process_lock()
            try:
                self._state["watcher_maintenance"] = session
                session["status"] = "partial"
                self._save()
                worker = asyncio.create_task(
                    asyncio.to_thread(self._watch_libraries, session, resume)
                )
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    # Cancelling the coroutine cannot stop its HTTP thread. Keep both locks
                    # until it finishes, including when the caller cancels repeatedly.
                    while not worker.done():
                        try:
                            await asyncio.shield(worker)
                        except asyncio.CancelledError:
                            continue
                        except Exception:
                            break
                    if not worker.cancelled():
                        worker.exception()  # Retrieve failures even when cancellation wins.
                    raise
            finally:
                self._release_process_lock()
            return self.status()

    def _watch_libraries(self, session, resume):
        for item in session["libraries"]:
            try:
                body = self._watch_read(item["library_id"])
                if "original_watch" not in item:
                    if resume:
                        item["status"] = "restored"
                        item.pop("error", None)
                        continue
                    item.update(
                        original_watch=body["watch"],
                        paths=copy.deepcopy(body["paths"]),
                        name=body["name"],
                    )
                    self._save()
                if item["paths"] != body["paths"]:
                    raise GrimmoryValidationError(
                        "Library paths changed; watcher recovery requires the original paths."
                    )
                if resume:
                    if (
                        item["original_watch"]
                        and item["status"] in {"paused", "pause_pending", "resume_pending"}
                        and not body["watch"]
                    ):
                        self._watch_update(item, body, True)
                        body["watch"] = True
                    item["status"] = "restored"
                elif not item["original_watch"]:
                    if body["watch"]:
                        raise GrimmoryValidationError(
                            "Watching was enabled externally; resume this session first."
                        )
                    item["status"] = "unmodified"
                else:
                    if body["watch"]:
                        self._watch_update(item, body, False)
                        body["watch"] = False
                    item["status"] = "paused"
                item.pop("error", None)
                for library in self._state["libraries"]:
                    if str(library["id"]) == str(item["library_id"]):
                        library["watch"] = body["watch"]
            except Exception as exc:
                item["error"] = self._failure_message(
                    exc, "Watcher request failed; retry explicitly."
                )
            finally:
                self._save()
        complete = {"restored"} if resume else {"paused", "unmodified"}
        session["status"] = (
            ("resumed" if resume else "paused")
            if all(x["status"] in complete and "error" not in x for x in session["libraries"])
            else "partial"
        )
        self._save()

    def _mappings(self, mappings):
        if not self.allowed_roots or not mappings:
            raise GrimmoryValidationError(
                "Configure allowed library roots and select mappings first."
            )
        roots = []
        cleaned = []
        for mapping in mappings:
            session = self._state.get("watcher_maintenance")
            if session and session["status"] != "resumed":
                receipt = next(
                    (
                        x
                        for x in session["libraries"]
                        if str(x["library_id"]) == str(mapping.get("library_id"))
                    ),
                    None,
                )
                if receipt and (
                    receipt["status"] not in {"paused", "unmodified"} or "error" in receipt
                ):
                    raise GrimmoryValidationError(
                        "Watcher state is unverified; recover the saved session first."
                    )
            library = next(
                (
                    x
                    for x in self._state["libraries"]
                    if str(x["id"]) == str(mapping.get("library_id"))
                ),
                None,
            )
            if not library or mapping.get("remote_path") not in [
                p["path"] for p in library["paths"]
            ]:
                raise GrimmoryValidationError("Mapping does not match a discovered library path.")
            if library["watch"]:
                raise GrimmoryValidationError("Pause Grimmory watching before library maintenance.")
            root = _safe(Path(mapping.get("local_path", "")))
            if not any(root == _safe(p) or _safe(p) in root.parents for p in self.allowed_roots):
                raise GrimmoryValidationError(
                    "Library path is outside the configured allowed roots."
                )
            forbidden = [self.backup_dir, self.state_dir, *self.excluded_paths]
            if any(_overlap(root, _safe(p, exists=False)) for p in forbidden):
                raise GrimmoryValidationError("Library overlaps backup, state or automation paths.")
            if any(_overlap(root, other) for other in roots):
                raise GrimmoryValidationError("Selected library paths overlap.")
            roots.append(root)
            cleaned.append(
                dict(
                    library_id=library["id"],
                    remote_path=mapping["remote_path"],
                    local_path=str(root),
                )
            )
        return cleaned

    async def preview(self, payload):
        async with self._lock:
            self._idle()
            await asyncio.to_thread(self._refresh)
            mappings = self._mappings(payload.get("mappings", []))
            trees = await asyncio.to_thread(
                lambda: [_manifest(Path(m["local_path"])) for m in mappings]
            )
            identities = [_identities(Path(m["local_path"])) for m in mappings]
            body = dict(
                mappings=mappings,
                trees=trees,
                identities=identities,
                base_url=self._state["base_url"],
            )
            plan_id = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            files = [item for tree in trees for item in tree.values() if item["type"] == "file"]
            epub_count = sum(
                item["type"] == "file" and name.lower().endswith(".epub")
                for tree in trees
                for name, item in tree.items()
            )
            plan = dict(
                plan_id=plan_id,
                **body,
                files=len(files),
                epub_count=epub_count,
                bytes=sum(item["size"] for item in files),
                created_at=time.time(),
            )
            self._state["plans"][plan_id] = plan
            self._state["mappings"] = mappings
            self._save()
            return self._public_plan(plan)

    async def scan(self, payload):
        return await self.preview(payload)

    def _acquire_process_lock(self):
        _safe(self.state_dir, exists=False).mkdir(parents=True, exist_ok=True)
        path = _safe(self.state_dir / "operation.lock", exists=False)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise GrimmoryConflictError("Another library process is already running.") from None
        self._process_lock = fd

    def _release_process_lock(self):
        if self._process_lock is not None:
            os.close(self._process_lock)
            self._process_lock = None

    def _confirm(self, payload):
        self._idle()
        if payload.get("maintenance_confirmed") is not True:
            raise GrimmoryValidationError(
                "Confirm Grimmory maintenance mode before writing or restoring files."
            )

    async def start(self, payload):
        async with self._lock:
            self._confirm(payload)
            plan = self._state["plans"].get(payload.get("plan_id"))
            if not plan:
                raise GrimmoryValidationError("Unknown preview plan; preview the library first.")
            if plan["base_url"] != self._state["base_url"]:
                raise GrimmoryValidationError("Connection changed; preview again.")
            await asyncio.to_thread(self._refresh)
            self._mappings(plan["mappings"])
            self._acquire_process_lock()
            job = dict(
                id=uuid.uuid4().hex,
                plan_id=plan["plan_id"],
                status="backing_up",
                results=[],
                created_at=time.time(),
                kind="optimize",
            )
            self._state["jobs"].append(job)
            self._cancel.clear()
            try:
                self._save()
            except Exception:
                self._release_process_lock()
                raise
            self._task = asyncio.create_task(asyncio.to_thread(self._run, copy.deepcopy(plan), job))
            return copy.deepcopy(job)

    def _assert_tree(self, plan, expected=None, *, full=True):
        current = [_manifest(Path(m["local_path"]), hash_files=full) for m in plan["mappings"]]
        expected = expected if expected is not None else plan["trees"]
        if not full:
            expected = [
                {
                    name: {k: v for k, v in item.items() if k != "sha256"}
                    for name, item in tree.items()
                }
                for tree in expected
            ]
        identities = [_identities(Path(m["local_path"])) for m in plan["mappings"]]
        if current != expected or identities != plan["identities"]:
            raise GrimmoryValidationError(
                "Library changed; no further files were written. Preview again."
            )

    def _snapshot(self, plan, job):
        self._assert_tree(plan)
        _safe(self.backup_dir, exists=False).mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.backup_dir).free < plan["bytes"] * 2 + 1024 * 1024:
            raise GrimmoryValidationError(
                "Insufficient free space for a full independent snapshot and staging."
            )
        snapshot_id = job["id"]
        target = self.backup_dir / snapshot_id
        target.mkdir()
        for index, (mapping, tree) in enumerate(zip(plan["mappings"], plan["trees"], strict=True)):
            root = Path(mapping["local_path"])
            dest = target / str(index)
            dest.mkdir()
            for name, item in tree.items():
                if name == ".":
                    continue
                source, output = root / name, dest / name
                _safe(source)
                if item["type"] == "dir":
                    output.mkdir()
                else:
                    shutil.copy2(source, output)
                    _preserve(output, item)
                    with output.open("rb") as stream:
                        os.fsync(stream.fileno())
            self._directories(dest, tree)
            for directory in sorted(
                [dest, *[p for p in dest.rglob("*") if p.is_dir()]],
                key=lambda p: len(p.parts),
                reverse=True,
            ):
                _fsync_dir(directory)
            if _manifest(dest) != tree:
                raise GrimmoryValidationError("Snapshot verification failed; library untouched.")
        self._assert_tree(plan)
        snapshot = dict(
            snapshot_id=snapshot_id,
            plan=copy.deepcopy(plan),
            created_at=time.time(),
            status="ready",
            job_id=job["id"],
        )
        _json_write(target / "manifest.json", snapshot)
        _fsync_dir(target)
        _fsync_dir(self.backup_dir)
        _fsync_dir(self.backup_dir.parent)
        self._state["snapshots"][snapshot_id] = snapshot
        job["snapshot_id"] = snapshot_id
        self._save()
        return snapshot

    @staticmethod
    def _directories(root, tree):
        for name, item in sorted(tree.items(), key=lambda x: len(Path(x[0]).parts), reverse=True):
            if item["type"] == "dir":
                _preserve(root / name, item)

    def _replace(self, source, destination, original, before_hash, output_hash, journal):
        _safe(destination)
        info = destination.stat()
        identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if _digest(destination) != before_hash:
            raise GrimmoryValidationError("File changed before replacement.")
        parent_metadata = _metadata(destination.parent)
        temp = destination.parent / (".epub-library-" + uuid.uuid4().hex + ".part")
        journal["temp_path"] = (Path(journal["path"]).parent / temp.name).as_posix()
        journal["parent_metadata"] = parent_metadata
        self._save()
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                info = os.fstat(output.fileno())
                journal["temp_identity"] = [info.st_dev, info.st_ino]
                self._save()
                with _safe(source).open("rb") as stream:
                    shutil.copyfileobj(stream, output)
                output.flush()
                os.fsync(output.fileno())
            if _digest(temp) != output_hash:
                raise GrimmoryValidationError("Staged bytes changed; replacement refused.")
            _preserve(temp, original)
            with temp.open("rb") as stream:
                os.fsync(stream.fileno())
            journal["temp_sha256"] = output_hash
            self._save()
            _safe(destination)
            latest = destination.stat()
            if identity != (latest.st_dev, latest.st_ino, latest.st_size, latest.st_mtime_ns):
                raise GrimmoryValidationError("File identity changed before replacement.")
            if _digest(destination) != before_hash:
                raise GrimmoryValidationError("File changed before replacement.")
            staged = _safe(temp).stat()
            if [staged.st_dev, staged.st_ino] != journal["temp_identity"] or _digest(
                temp
            ) != journal["temp_sha256"]:
                raise GrimmoryValidationError("Staged temporary file changed before replacement.")
            os.replace(temp, destination)
            directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temp.exists():
                temp_info = _safe(temp).stat()
                if (
                    [temp_info.st_dev, temp_info.st_ino] == journal.get("temp_identity")
                    and journal.get("temp_sha256")
                    and _digest(temp) == journal["temp_sha256"]
                ):
                    temp.unlink()
            _preserve(destination.parent, parent_metadata)
            _fsync_dir(destination.parent)

    def _run(self, plan, job):
        try:
            snapshot = self._snapshot(plan, job)
            self._refresh()
            self._mappings(plan["mappings"])
            expected = copy.deepcopy(plan["trees"])
            job["status"] = "running"
            self._save()
            with tempfile.TemporaryDirectory(prefix="stage-", dir=self.state_dir) as staging:
                for index, (mapping, tree) in enumerate(
                    zip(plan["mappings"], plan["trees"], strict=True)
                ):
                    root = Path(mapping["local_path"])
                    for name, original in tree.items():
                        if original["type"] != "file" or not name.lower().endswith(".epub"):
                            continue
                        if self._cancel.is_set():
                            job["status"] = "cancelled"
                            return
                        self._assert_tree(plan, expected, full=False)
                        result = dict(root_index=index, path=name, status="failed")
                        job["results"].append(result)
                        try:
                            # Optimize the independent snapshot copy.
                            source = self.backup_dir / snapshot["snapshot_id"] / str(index) / name
                            if _digest(_safe(source)) != original["sha256"]:
                                raise GrimmoryValidationError(
                                    "Snapshot changed before optimization."
                                )
                            output_dir = Path(staging) / uuid.uuid4().hex
                            output_dir.mkdir()
                            optimized = optimize_epub(
                                source,
                                output_dir,
                                output_filename="result.epub",
                                preserve_metadata=True,
                            )
                            check = getattr(optimized, "epubcheck", None)
                            if check is None or not check.available or check.introduced:
                                raise GrimmoryValidationError(
                                    "EPUBCheck is unavailable or reports new findings."
                                )
                            output = output_dir / "result.epub"
                            after = _digest(output)
                            self._assert_tree(plan, expected, full=False)
                            result.update(
                                status="pending",
                                before_sha256=original["sha256"],
                                after_sha256=after,
                            )
                            # Persist replacement intent before touching the library.
                            self._save()
                            self._replace(
                                output, root / name, original, original["sha256"], after, result
                            )
                            plan["identities"][index][name] = _identities(root)[name]
                            expected[index][name] = dict(
                                original, sha256=after, size=output.stat().st_size
                            )
                            result["status"] = "optimized"
                        except Exception as exc:
                            result["status"] = "failed"
                            result["message"] = self._failure_message(
                                exc, "Optimization failed; inspect the original and preview again."
                            )
                        self._save()
            self._assert_tree(plan, expected)
            job["status"] = "completed"
        except Exception as exc:
            job["status"] = "failed"
            job["message"] = self._failure_message(
                exc, "Library operation stopped: backup, drift or filesystem safety check failed."
            )
        finally:
            job["finished_at"] = time.time()
            try:
                self._save()
            finally:
                self._release_process_lock()

    async def restore(self, payload):
        async with self._lock:
            self._confirm(payload)
            snapshot = self._state["snapshots"].get(payload.get("snapshot_id"))
            if not snapshot:
                raise GrimmoryValidationError("Unknown snapshot.")
            if snapshot["plan"]["base_url"] != self._state["base_url"]:
                raise GrimmoryValidationError(
                    "Connect to the snapshot Grimmory instance before restoring."
                )
            await asyncio.to_thread(self._refresh)
            self._mappings(snapshot["plan"]["mappings"])
            self._acquire_process_lock()
            job = dict(
                id=uuid.uuid4().hex,
                snapshot_id=snapshot["snapshot_id"],
                status="restoring",
                kind="restore",
                results=[],
                created_at=time.time(),
            )
            self._state["jobs"].append(job)
            self._cancel.clear()
            try:
                self._save()
            except Exception:
                self._release_process_lock()
                raise
            self._task = asyncio.create_task(
                asyncio.to_thread(self._restore, copy.deepcopy(snapshot), job)
            )
            return copy.deepcopy(job)

    def _restore(self, snapshot, job):
        try:
            plan = snapshot["plan"]
            self._refresh()
            self._mappings(plan["mappings"])
            snapshot_root = _safe(self.backup_dir / snapshot["snapshot_id"])
            saved = json.loads(_safe(snapshot_root / "manifest.json").read_text())
            if saved != snapshot:
                raise GrimmoryValidationError("Snapshot manifest changed.")
            for index, tree in enumerate(plan["trees"]):
                if _manifest(snapshot_root / str(index)) != tree:
                    raise GrimmoryValidationError("Snapshot bytes or metadata changed.")
            original_job = next(j for j in self._state["jobs"] if j["id"] == snapshot["job_id"])
            expected = copy.deepcopy(plan["trees"])
            current = [_manifest(Path(m["local_path"])) for m in plan["mappings"]]
            cleanup = []
            # Reconcile only exact temporary paths durably recorded before creation.
            for past_job in self._state["jobs"]:
                if past_job.get("snapshot_id") != snapshot["snapshot_id"]:
                    continue
                for pending in past_job["results"]:
                    if pending.get("status") != "pending" or "temp_path" not in pending:
                        continue
                    index, name = pending["root_index"], pending["path"]
                    relative = Path(pending["temp_path"])
                    if (
                        relative.is_absolute()
                        or ".." in relative.parts
                        or relative.parent != Path(name).parent
                        or not relative.name.startswith(".epub-library-")
                        or not relative.name.endswith(".part")
                    ):
                        raise GrimmoryValidationError("Invalid recovery journal path.")
                    root = Path(plan["mappings"][index]["local_path"])
                    parent_name = relative.parent.as_posix()
                    original_parent = plan["trees"][index][parent_name]
                    recorded_parent = pending["parent_metadata"]
                    if recorded_parent != {k: original_parent[k] for k in recorded_parent}:
                        raise GrimmoryValidationError("Recovery directory metadata mismatch.")
                    actual_parent = current[index][parent_name]
                    if any(
                        actual_parent[k] != original_parent[k]
                        for k in actual_parent
                        if k != "mtime_ns"
                    ):
                        raise GrimmoryValidationError("Recovery directory externally changed.")
                    identity = root.joinpath(parent_name).stat()
                    if [identity.st_dev, identity.st_ino] != plan["identities"][index][parent_name]:
                        raise GrimmoryValidationError("Recovery directory identity changed.")
                    temp_item = current[index].pop(relative.as_posix(), None)
                    if temp_item:
                        temp_info = _safe(root / relative).stat()
                        if (
                            temp_item["type"] != "file"
                            or [temp_info.st_dev, temp_info.st_ino] != pending.get("temp_identity")
                            or temp_item.get("sha256") != pending.get("temp_sha256")
                            or pending.get("temp_sha256") != pending.get("after_sha256")
                        ):
                            raise GrimmoryValidationError(
                                "Recovery temporary file changed or staging was incomplete; "
                                "manually inspect the recorded temporary file before retrying."
                            )
                    current[index][parent_name] = copy.deepcopy(original_parent)
                    cleanup.append(
                        (
                            root / relative,
                            root / parent_name,
                            original_parent,
                            pending if temp_item else None,
                        )
                    )
            for result in original_job["results"]:
                if "after_sha256" not in result:
                    continue
                index, name = result["root_index"], result["path"]
                actual = current[index].get(name)
                original = expected[index][name]
                if actual and actual.get("sha256") == result["after_sha256"]:
                    expected[index][name] = dict(
                        original, sha256=result["after_sha256"], size=actual["size"]
                    )
            if current != expected:
                raise GrimmoryValidationError("Library contains external changes; restore refused.")
            for temp, parent, metadata, pending in cleanup:
                if pending:
                    info = _safe(temp).stat()
                    if [info.st_dev, info.st_ino] != pending["temp_identity"] or _digest(
                        temp
                    ) != pending["temp_sha256"]:
                        raise GrimmoryValidationError("Recovery temporary file changed.")
                    temp.unlink()
                elif temp.exists():
                    raise GrimmoryValidationError("An unexpected recovery temporary file appeared.")
                _preserve(parent, metadata)
                _fsync_dir(parent)
            plan["identities"] = [_identities(Path(m["local_path"])) for m in plan["mappings"]]
            for index, (mapping, tree) in enumerate(
                zip(plan["mappings"], plan["trees"], strict=True)
            ):
                root = Path(mapping["local_path"])
                for name, item in tree.items():
                    if item["type"] != "file" or expected[index][name] == item:
                        continue
                    if self._cancel.is_set():
                        job["status"] = "cancelled"
                        return
                    self._assert_tree(plan, expected, full=False)
                    result = dict(
                        root_index=index,
                        path=name,
                        status="pending",
                        before_sha256=expected[index][name]["sha256"],
                        after_sha256=item["sha256"],
                    )
                    job["results"].append(result)
                    self._replace(
                        snapshot_root / str(index) / name,
                        root / name,
                        item,
                        expected[index][name]["sha256"],
                        item["sha256"],
                        result,
                    )
                    plan["identities"][index][name] = _identities(root)[name]
                    expected[index][name] = item
                    result["status"] = "restored"
                    self._save()
            self._assert_tree(plan)
            job["status"] = "completed"
        except Exception as exc:
            job["status"] = "failed"
            job["message"] = self._failure_message(
                exc, "Restore refused or stopped: snapshot verification or library conflict."
            )
        finally:
            job["finished_at"] = time.time()
            try:
                self._save()
            finally:
                self._release_process_lock()

    async def cancel(self):
        self._cancel.set()
        if self._task:
            await asyncio.shield(self._task)
        return self.status()

    async def close(self):
        await self.cancel()
