import re
from pathlib import Path
from zipfile import ZipFile

import pytest
from lxml import etree

from epub_optimizer import core
from epub_optimizer.epubcheck import EpubCheckFinding, EpubCheckResult
from epub_optimizer.errors import InvalidEpubError
from epub_optimizer.repair import repair_workspace

OPF = "http://www.idpf.org/2007/opf"
PACKAGE_PATH = "OEBPS/book.opf"


class _SequentialEpubCheck:
    def __init__(self, *results):
        self.results = iter(results)

    def check(self, _path):
        return next(self.results)


def _clean_runner():
    return _SequentialEpubCheck(*[EpubCheckResult(True, "passed")] * 3)


def _write_book(path: Path, *, marker=True, invalid=False, default_namespace=True):
    root = etree.fromstring(
        f'''<package xmlns="{OPF}" xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:custom="https://example.org/custom/" version="2.0"
            unique-identifier="{'missing' if invalid else 'book-id'}"
            prefix="custom: https://example.org/custom/">
          <metadata xml:lang="sv">
            <!-- Keep publisher fields, spacing, and namespace context. -->
            <dc:title id="title">  A title &amp; subtitle  </dc:title>
            <dc:creator custom:sort="Author, The">The Author</dc:creator>
            <dc:identifier id="book-id">urn:isbn:12345</dc:identifier>
            <dc:identifier custom:scheme="vendor">Other identifier</dc:identifier>
            <dc:language>sv</dc:language>
            <meta property="custom:series" custom:key="custom:field">Series 7</meta>
            <custom:field custom:kind="custom:special">Before<custom:value/>After</custom:field>
          </metadata>
          <manifest>
            <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
            <item id="style" href="old.css" media-type="text/css"/>
            <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
          </manifest>
          <spine toc="ncx"><itemref idref="chapter"/></spine>
        </package>'''.encode()
    )
    if marker:
        etree.SubElement(
            root.find(f"{{{OPF}}}metadata"),
            f"{{{OPF}}}meta",
            name=core.OPTIMIZER_META_NAME,
            content="old-version",
        )
    raw = etree.tostring(root)
    if not default_namespace:
        # Exercise an explicitly prefixed OPF namespace as well as the default.
        raw = raw.replace(f'xmlns="{OPF}"'.encode(), f'xmlns:opf="{OPF}"'.encode())
        for name in ("package", "metadata", "manifest", "item", "spine", "itemref", "meta"):
            raw = re.sub(rb"(<\/?)(" + name.encode() + rb")(?=[\s/>])", rb"\1opf:\2", raw)
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
            f'<rootfiles><rootfile full-path="{PACKAGE_PATH}" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr(PACKAGE_PATH, raw)
        archive.writestr("OEBPS/old.css", "p {color: red}")
        archive.writestr(
            "OEBPS/chapter.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter</title>'
            '<link rel="stylesheet" href="old.css"/></head><body><p>Story text.</p></body></html>',
        )
        archive.writestr(
            "OEBPS/toc.ncx",
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            '<head><meta name="dtb:uid" content="original-ncx-uid"/></head>'
            '<docTitle><text>Title</text></docTitle><navMap><navPoint id="ch" playOrder="1">'
            '<navLabel><text>Chapter</text></navLabel><content src="chapter.xhtml"/>'
            '</navPoint></navMap></ncx>',
        )


def _package(path):
    with ZipFile(path) as archive:
        return etree.fromstring(archive.read(PACKAGE_PATH))


@pytest.mark.parametrize("marker", [False, True])
@pytest.mark.parametrize("default_namespace", [False, True])
def test_strict_mode_preserves_all_metadata_while_optimizing(
    tmp_path, marker, default_namespace
):
    source = tmp_path / "source.epub"
    _write_book(source, marker=marker, default_namespace=default_namespace)
    before = core._protected_metadata(_package(source))

    result = core.optimize_epub(
        source, tmp_path / "output", preserve_metadata=True, epubcheck=_clean_runner()
    )

    assert core._protected_metadata(_package(result.output_path)) == before
    assert result.content_documents_processed == 1
    assert result.stylesheets_replaced == 1
    with ZipFile(result.output_path) as archive:
        assert "OEBPS/old.css" not in archive.namelist()
        assert "OEBPS/Styles/epub-optimizer.css" in archive.namelist()
        assert b'content="original-ncx-uid"' in archive.read("OEBPS/toc.ncx")


@pytest.mark.parametrize("marker", [False, True])
def test_default_mode_still_adds_or_updates_optimizer_marker(tmp_path, marker, monkeypatch):
    source = tmp_path / "source.epub"
    _write_book(source, marker=marker)
    monkeypatch.setattr(core, "_optimizer_version", lambda: "test-version")

    result = core.optimize_epub(source, tmp_path / "output", epubcheck=_clean_runner())

    markers = _package(result.output_path).xpath(
        "//*[local-name()='meta' and @name=$name]", name=core.OPTIMIZER_META_NAME
    )
    assert len(markers) == 1
    assert markers[0].get("content") == "test-version"


def test_strict_mode_keeps_invalid_metadata_as_legacy_issues(tmp_path):
    source = tmp_path / "source.epub"
    _write_book(source, invalid=True)
    findings = [
        EpubCheckFinding("error", "OPF-030", "Missing unique identifier", PACKAGE_PATH),
        EpubCheckFinding("error", "NCX-001", "UID mismatch", "OEBPS/toc.ncx"),
    ]
    legacy = EpubCheckResult(True, "failed", findings, error_count=2)
    runner = _SequentialEpubCheck(legacy, legacy, legacy)

    result = core.optimize_epub(
        source, tmp_path / "output", preserve_metadata=True, epubcheck=runner
    )

    assert result.validation_outcome == "legacy_issues"
    assert result.validation_remaining == 2
    assert result.validation_persisting == 2
    assert result.repair_actions == []
    assert core._protected_metadata(_package(result.output_path)) == core._protected_metadata(
        _package(source)
    )


@pytest.mark.parametrize(
    "mutation", ["title", "unique-identifier", "prefix", "namespace", "xml:lang", "xml:base"]
)
def test_final_archive_guard_rejects_mutation_before_overwriting_output(
    tmp_path, monkeypatch, mutation
):
    source = tmp_path / "source.epub"
    _write_book(source)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    destination = output_dir / "exact-name.epub"
    destination.write_bytes(b"previous output must survive")
    real_write = core.write_epub

    def malicious_packager(work, staged):
        real_write(work, staged)
        with ZipFile(staged) as archive:
            entries = [(entry, archive.read(entry.filename)) for entry in archive.infolist()]
        with ZipFile(staged, "w") as archive:
            for entry, data in entries:
                if entry.filename == PACKAGE_PATH:
                    root = etree.fromstring(data)
                    if mutation == "title":
                        root.xpath("//*[local-name()='title']")[0].text = "Changed"
                    elif mutation == "namespace":
                        data = data.replace(b"https://example.org/custom/", b"https://evil.test/")
                    elif mutation.startswith("xml:"):
                        root.set(
                            "{http://www.w3.org/XML/1998/namespace}" + mutation.split(":")[1],
                            "changed",
                        )
                    else:
                        root.set(mutation, "changed")
                    if mutation != "namespace":
                        data = etree.tostring(root)
                archive.writestr(entry, data)

    monkeypatch.setattr(core, "write_epub", malicious_packager)
    with pytest.raises(InvalidEpubError, match="Protected EPUB metadata changed"):
        core.optimize_epub(
            source, output_dir, output_filename=destination.name,
            preserve_metadata=True, epubcheck=_clean_runner(),
        )

    assert destination.read_bytes() == b"previous output must survive"


def test_strict_repairs_allow_resource_repairs_but_preserve_metadata_and_ncx(tmp_path):
    source = tmp_path / "source.epub"
    _write_book(source, invalid=True)
    work = tmp_path / "work"
    with ZipFile(source) as archive:
        archive.extractall(work)
    tree = etree.ElementTree(_package(source))
    before = core._protected_metadata(tree.getroot())
    ncx = work / "OEBPS/toc.ncx"
    original_ncx = ncx.read_bytes()
    chapter = work / "OEBPS/chapter.xhtml"
    chapter.write_text(
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p><a href="missing.xhtml">Keep text</a></p></body></html>'
    )

    actions = repair_workspace(
        work, PACKAGE_PATH, tree,
        [
            EpubCheckFinding("error", "OPF-030", "Missing ID", PACKAGE_PATH),
            EpubCheckFinding("error", "NCX-001", "UID mismatch", "OEBPS/toc.ncx"),
            EpubCheckFinding("error", "RSC-007", "Missing", "OEBPS/chapter.xhtml"),
        ],
        preserve_metadata=True,
    )

    assert actions == ["Removed broken link target (text preserved): missing.xhtml"]
    assert core._protected_metadata(tree.getroot()) == before
    assert ncx.read_bytes() == original_ncx
    assert "Keep text" in chapter.read_text()
    assert "missing.xhtml" not in chapter.read_text()
