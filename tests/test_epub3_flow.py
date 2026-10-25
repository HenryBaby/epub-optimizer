"""Regressions for EPUB 3 flow elements at paragraph-normalization boundaries."""

import zipfile
from pathlib import Path

import pytest
from lxml import etree

from epub_optimizer.core import (
    _normalize_direct_body_content,
    _process_content_document,
    optimize_epub,
)
from epub_optimizer.epubcheck import EpubCheckRunner

XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
EPUB3_BLOCK_ELEMENTS = (
    "article",
    "aside",
    "details",
    "dialog",
    "fieldset",
    "figure",
    "footer",
    "form",
    "header",
    "hgroup",
    "main",
    "menu",
    "nav",
    "search",
    "section",
)


def _document(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?><!DOCTYPE html>'
        f'<html xmlns="{XHTML_NS}" xmlns:epub="{EPUB_NS}" '
        'xml:lang="en" lang="en"><head><title>Flow regression</title></head>'
        f"<body>{body}</body></html>"
    ).encode()


def _nav_body() -> str:
    return (
        '<nav epub:type="toc" id="toc"><h1>Contents</h1>'
        '<ol><li><a href="chapter.xhtml">Chapter One</a></li></ol></nav>'
        '<nav epub:type="landmarks" id="landmarks"><h2>Landmarks</h2>'
        '<ol><li><a epub:type="bodymatter" href="chapter.xhtml">Start</a></li></ol></nav>'
        '<nav epub:type="page-list" id="pages"><h2>Pages</h2>'
        '<ol><li><a href="chapter.xhtml#page1">1</a></li></ol></nav>'
    )


def _chapter_body() -> str:
    return (
        '<main id="main"><article id="article"><header id="header">'
        '<h1>Chapter One</h1></header><section id="section">'
        '<h2>First section</h2><p id="page1">Chapter text.</p>'
        '<aside id="aside"><p>A note.</p></aside>'
        '<figure id="figure"><p>A textual figure.</p>'
        "<figcaption>A caption.</figcaption></figure></section>"
        '<footer id="footer"><p>End.</p></footer></article></main>'
    )


@pytest.mark.parametrize("container_name", ["body", "blockquote"])
@pytest.mark.parametrize("element_name", EPUB3_BLOCK_ELEMENTS)
def test_normalize_preserves_epub3_blocks_and_surrounding_inline_runs(
    container_name: str, element_name: str
) -> None:
    contents = (
        f'Before <em>emphasis</em> after<{element_name} id="structural">'
        f"<p>Block text</p></{element_name}>tail <strong>again</strong>"
    )
    root = etree.fromstring(
        _document(contents if container_name == "body" else f"<blockquote>{contents}</blockquote>")
    )
    container = root.find(f".//{{{XHTML_NS}}}{container_name}")
    assert container is not None
    structural = container.find(f"{{{XHTML_NS}}}{element_name}")

    _normalize_direct_body_content(root)

    assert [etree.QName(child).localname for child in container] == ["p", element_name, "p"]
    assert container[1] is structural
    assert ["".join(child.itertext()) for child in container] == [
        "Before emphasis after",
        "Block text",
        "tail again",
    ]
    normalized = etree.tostring(root)
    _normalize_direct_body_content(root)
    assert etree.tostring(root) == normalized


@pytest.mark.parametrize("wrapped", [False, True])
def test_process_content_document_preserves_all_three_navigation_types(
    tmp_path: Path, wrapped: bool
) -> None:
    nav_body = _nav_body()
    if wrapped:
        nav_body = f'<div id="wrapper">{nav_body}</div>'
    content = tmp_path / "nav.xhtml"
    content.write_bytes(_document(nav_body))

    _process_content_document(
        content, "nav.xhtml", "Styles/epub-optimizer.css", tmp_path, "toc", {}
    )

    root = etree.parse(str(content))
    navs = root.findall(f".//{{{XHTML_NS}}}nav")
    assert [nav.get(f"{{{EPUB_NS}}}type") for nav in navs] == ["toc", "landmarks", "page-list"]
    assert [nav.get("id") for nav in navs] == ["toc", "landmarks", "pages"]
    assert all(
        etree.QName(nav.getparent()).localname == ("div" if wrapped else "body") for nav in navs
    )
    assert [a.get("href") for nav in navs for a in nav.findall(f".//{{{XHTML_NS}}}a")] == [
        "chapter.xhtml",
        "chapter.xhtml",
        "chapter.xhtml#page1",
    ]


@pytest.mark.parametrize("document_role", ["chapter", "front", "title", "works", "metadata", "toc"])
@pytest.mark.parametrize("element_name", EPUB3_BLOCK_ELEMENTS)
def test_process_keeps_div_containing_epub3_block_as_a_container(
    tmp_path: Path, document_role: str, element_name: str
) -> None:
    content = tmp_path / "chapter.xhtml"
    # A heading-like source class must not force the container into h1 either.
    content.write_bytes(
        _document(
            f'<div id="wrapper" class="part"><{element_name} id="structural">'
            f"<p>Short text</p></{element_name}></div>"
        )
    )

    _process_content_document(
        content, "chapter.xhtml", "Styles/epub-optimizer.css", tmp_path, document_role, {}
    )

    root = etree.parse(str(content))
    wrapper = root.xpath('//*[@id="wrapper"]')[0]
    assert etree.QName(wrapper).localname == "div"
    assert wrapper[0].tag == f"{{{XHTML_NS}}}{element_name}"
    assert wrapper[0].get("id") == "structural"


def _write_clean_epub3(path: Path, *, wrapped: bool) -> None:
    nav_body = _nav_body()
    if wrapped:
        nav_body = f'<div id="wrapper">{nav_body}</div>'
    files = {
        "META-INF/container.xml": (
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>"
        ),
        "EPUB/package.opf": (
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="3.0" unique-identifier="book-id"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="book-id">'
            'urn:uuid:a09bc84a-cb12-4825-a443-9953f560fdd1</dc:identifier>'
            "<dc:title>EPUB 3 flow regression</dc:title><dc:language>en</dc:language>"
            '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata>'
            '<manifest><item id="nav" href="nav.xhtml" '
            'media-type="application/xhtml+xml" properties="nav"/>'
            '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
            '</manifest><spine><itemref idref="chapter"/></spine></package>'
        ),
        "EPUB/nav.xhtml": _document(nav_body),
        "EPUB/chapter.xhtml": _document(_chapter_body()),
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, content in files.items():
            archive.writestr(name, content, compress_type=zipfile.ZIP_DEFLATED)


@pytest.mark.parametrize("wrapped", [False, True])
def test_optimize_clean_epub3_has_no_official_epubcheck_errors(
    tmp_path: Path, wrapped: bool
) -> None:
    source = tmp_path / "clean.epub"
    runner = EpubCheckRunner()
    if runner._command(source) is None:
        pytest.skip("Official EPUBCheck executable/JAR is unavailable")
    _write_clean_epub3(source, wrapped=wrapped)
    before = runner.check(source)
    assert before.available, before.message
    assert before.errors == [], before.findings
    assert before.error_count == 0

    result = optimize_epub(source, tmp_path / "out", epubcheck=runner)

    assert result.epubcheck is not None
    assert result.epubcheck.available
    assert result.epubcheck.input.errors == []
    assert result.epubcheck.output.errors == [], result.epubcheck.output.findings
    assert result.epubcheck.output.error_count == 0
    assert result.epubcheck.introduced == []
    repeated = optimize_epub(result.output_path, tmp_path / "repeated", epubcheck=runner)
    assert repeated.epubcheck is not None
    assert repeated.epubcheck.available
    assert repeated.epubcheck.input.error_count == 0
    assert repeated.epubcheck.output.errors == [], repeated.epubcheck.output.findings
    assert repeated.epubcheck.output.error_count == 0
    assert repeated.epubcheck.introduced == []
    with zipfile.ZipFile(result.output_path) as archive:
        nav_root = etree.fromstring(archive.read("EPUB/nav.xhtml"))
        assert len(nav_root.findall(f".//{{{XHTML_NS}}}nav")) == 3
        assert not nav_root.xpath(
            "//*[local-name()='p' or local-name()='h1']/*[local-name()='nav']"
        )
        chapter_root = etree.fromstring(archive.read("EPUB/chapter.xhtml"))
        for element_name in ("main", "article", "header", "section", "aside", "figure", "footer"):
            assert chapter_root.find(f".//{{{XHTML_NS}}}{element_name}") is not None
