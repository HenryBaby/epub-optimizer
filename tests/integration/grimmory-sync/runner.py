"""Real Grimmory 3.5.0 regression; execute only through the isolated compose file."""

import asyncio
import hashlib
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lxml import etree

from epub_optimizer.grimmory import GrimmoryManager, _partial_md5


BASE = os.environ["GRIMMORY_URL"]
ADMIN = "integration-admin"
KOSYNC = "integration-koreader"
PASSWORD = os.environ["TEST_ADMIN_PASSWORD"]
KO_PASSWORD = os.environ["TEST_KOSYNC_PASSWORD"]
BOOK = Path("/books/Author/Fixture.epub")
TOKEN = None


def api(route, payload=None, *, method=None, native=False, expected=200):
    headers = {"Accept": "application/json"}
    if native:
        headers.update({"x-auth-user": KOSYNC,
                        "x-auth-key": hashlib.md5(KO_PASSWORD.encode()).hexdigest()})
    elif TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = Request(BASE + route, data=json.dumps(payload).encode() if payload is not None else None,
                      headers=headers, method=method or ("POST" if payload is not None else "GET"))
    try:
        response = urlopen(request, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read()
        value = json.loads(raw) if raw else None
        assert response.code == expected, (route, response.code, value)
        return value


def wait_for(check, label, seconds=180):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (URLError, AssertionError, ConnectionError) as error:
            last = str(error)
        time.sleep(1)
    raise AssertionError(f"Timed out waiting for {label}: {last}")


def fixture(path, title="Fingerprint Fixture"):
    path.parent.mkdir(parents=True, exist_ok=True)
    quote = ("The patient reader follows a remembered path through the quiet archive. " * 20)[:920]
    quote = "“" + quote + "”"
    assert len(quote) == 922
    files = {
        "META-INF/container.xml": '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        "OEBPS/package.opf": f'''<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">urn:uuid:bbab46ab-f8f7-4b3b-8e52-929be3b8984f</dc:identifier><dc:title>{title}</dc:title><dc:creator>Test Author</dc:creator><dc:language>en</dc:language><meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="style" href="style.css" media-type="text/css"/></manifest><spine><itemref idref="chapter"/></spine></package>''',
        "OEBPS/chapter.xhtml": f'''<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en"><head><title>Chapter One</title><link rel="stylesheet" href="style.css"/></head><body><h1 id="chapter-one">Chapter One</h1><div id="opening-quote"><p id="quote"><i>{quote}</i></p><p id="attribution"><b>—The Archive</b></p></div><p id="narrative">The first reader entered the archive and opened the waiting volume.</p><p id="continuation">Every page preserved a trail back to the beginning.</p></body></html>''',
        "OEBPS/nav.xhtml": '''<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en"><head><title>Contents</title></head><body><nav epub:type="toc"><h1>Contents</h1><ol><li><a href="chapter.xhtml">Chapter One</a></li></ol></nav></body></html>''',
        "OEBPS/style.css": "body { margin: 0; } p { text-indent: 1em; }",
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, content in files.items():
            archive.writestr(name, content, compress_type=zipfile.ZIP_DEFLATED)


def content_identity(path):
    with zipfile.ZipFile(path) as archive:
        chapter = etree.fromstring(archive.read("OEBPS/chapter.xhtml"))
        package = etree.fromstring(archive.read("OEBPS/package.opf"))
        metadata = package.xpath("//*[local-name()='metadata']")[0]
        return (etree.tostring(metadata, method="c14n"),
                "".join(chapter.itertext()), sorted(chapter.xpath("//@id")))


def bootstrap():
    global TOKEN
    wait_for(lambda: api("/api/v1/setup/status"), "fresh server setup", 240)
    api("/api/v1/setup", {"username": ADMIN, "password": PASSWORD,
                          "email": "integration@example.invalid", "name": "Integration Admin"})
    TOKEN = api("/api/v1/auth/login", {"username": ADMIN, "password": PASSWORD})["accessToken"]
    api("/api/v1/koreader-users/me", {"username": KOSYNC, "password": KO_PASSWORD}, method="PUT")
    api("/api/v1/koreader-users/me/sync?enabled=true", method="PATCH", expected=204)
    api("/api/koreader/users/auth", native=True)
    library = api("/api/v1/libraries", {
        "name": "Isolated integration", "icon": "book", "iconType": "LUCIDE",
        "paths": [{"path": "/books"}], "watch": False, "allowedFormats": ["EPUB"],
        "formatPriority": ["EPUB"], "metadataSource": "EMBEDDED", "organizationMode": "BOOK_PER_FILE",
    })
    route = f"/api/v1/libraries/{library['id']}"
    books = wait_for(lambda: api(route + "/book"), "initial book import")
    assert len(books) == 1, books
    Path("/state/indexed-book-dto.json").write_text(json.dumps(books, indent=2))
    old = _partial_md5(BOOK)
    progress = {"document": old, "progress": "/body/DocFragment[1]/body/p[1]/text().0",
                "percentage": 0.375, "device": "isolated-integration", "device_id": "fixture-reader"}
    api("/api/koreader/syncs/progress", progress, method="PUT", native=True)
    saved = api("/api/koreader/syncs/progress/" + old, native=True)
    assert saved["progress"] == progress["progress"] and saved["percentage"] == progress["percentage"], saved
    return route, books[0]["id"], old, saved


async def verify(route, book_id, old, saved):
    manager = GrimmoryManager(state_dir=Path("/state/optimizer"), backup_dir=Path("/backups"),
                              allowed_roots=[Path("/books")], excluded_paths=[])
    await manager.connect({"base_url": BASE, "username": ADMIN, "password": PASSWORD})
    library = api(route)
    library["watch"] = True
    api(route, library, method="PUT")
    await manager.pause_watching({"library_ids": [library["id"]]})
    receipt = json.loads(json.dumps(manager._state["watcher_maintenance"]))
    original_identity = content_identity(BOOK)
    mapping = {"library_id": library["id"], "remote_path": "/books", "local_path": "/books"}
    plan = await manager.preview({"mappings": [mapping]})
    await manager.start({"plan_id": plan["plan_id"], "maintenance_confirmed": True})
    await manager._task
    source = manager.status()["job"]
    assert source["status"] == "completed" and source["results"][0]["status"] == "optimized", source
    assert content_identity(BOOK) == original_identity
    new = _partial_md5(BOOK)
    assert new != old, "Fixture must exercise a changed partial MD5"
    unknown = api("/api/koreader/syncs/progress/" + new, native=True, expected=404)
    assert unknown["message"] == f"Book not found for hash {new}", unknown
    assert api("/api/koreader/syncs/progress/" + old, native=True)["progress"] == saved["progress"]
    # A pre-existing unindexed file must not be imported when watching is enabled.
    unindexed = Path("/books/Unindexed/Untouched.epub")
    fixture(unindexed, "Must Remain Unindexed")
    sidecar = BOOK.parent / "notes.txt"
    sidecar.write_text("Sidecar must survive byte-for-byte.\n")
    before = BOOK.read_bytes()
    inode = BOOK.stat().st_ino
    await manager.refresh_sync({"job_id": source["id"], "kosync_username": KOSYNC,
                                "kosync_password": KO_PASSWORD, "maintenance_confirmed": True})
    await manager._task
    refreshed = manager.status()["job"]
    assert refreshed["status"] == "completed", refreshed
    assert BOOK.read_bytes() == before and BOOK.stat().st_ino != inode
    assert api(route)["watch"] is False
    assert manager._state["watcher_maintenance"] == receipt
    books = api(route + "/book")
    assert len(books) == 1 and books[0]["id"] == book_id, books
    current = api("/api/koreader/syncs/progress/" + new, native=True)
    assert current["progress"] == saved["progress"] and current["percentage"] == saved["percentage"], current
    assert sidecar.read_text() == "Sidecar must survive byte-for-byte.\n"
    assert content_identity(BOOK) == original_identity
    assert sorted(p.relative_to(Path("/books")).as_posix() for p in Path("/books").rglob("*.epub")) == [
        "Author/Fixture.epub", "Unindexed/Untouched.epub"]
    assert not list(Path("/books").rglob("*.part"))
    # Already-current documents are verified without replay, preserving watch=True.
    library = api(route)
    library["watch"] = True
    api(route, library, method="PUT")
    inode = BOOK.stat().st_ino
    await manager.refresh_sync({"job_id": source["id"], "kosync_username": KOSYNC,
                                "kosync_password": KO_PASSWORD, "maintenance_confirmed": True})
    await manager._task
    assert manager.status()["job"]["status"] == "completed", manager.status()["job"]
    assert BOOK.stat().st_ino == inode and BOOK.read_bytes() == before
    assert api(route)["watch"] is True
    assert manager._state["watcher_maintenance"] == receipt
    assert len(api(route + "/book")) == 1
    for path in Path("/state").rglob("*.json"):
        data = path.read_text()
        assert KO_PASSWORD not in data and PASSWORD not in data and TOKEN not in data
    Path("/state/result.json").write_text(json.dumps({"status": "passed", "book_id": book_id,
        "old_document": old, "new_document": new, "progress": current,
        "checks": ["official EPUBCheck optimization", "same book ID", "native progress preserved",
                   "identical bytes republished", "new inode", "watch restored false",
                   "watch true already-current no replay", "original pause receipt preserved",
                   "unindexed EPUB not imported", "metadata text IDs and sidecar preserved",
                   "credentials absent from persistent state"]}, indent=2))
    print("PASS: real Grimmory native KOSync fingerprint refresh and progress preservation", flush=True)
    await manager.close()


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "prepare":
        fixture(BOOK)
    else:
        setup = bootstrap()
        print("Bootstrap API contract proven; DTO saved to /state/indexed-book-dto.json", flush=True)
        if mode == "verify":
            asyncio.run(verify(*setup))
        elif mode != "bootstrap":
            raise SystemExit("Expected prepare, bootstrap, or verify")
