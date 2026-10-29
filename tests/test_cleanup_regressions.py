"""Cleanup must preserve fragment targets and legacy diagnostic contexts."""

import base64
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from epub_optimizer.core import (
    XHTML_NS,
    _collapse_nested_blockquotes,
    _normalize_direct_body_content,
    _process_content_document,
    _remove_broken_images,
    _remove_empty_blocks,
    _strip_publisher_presentation,
    _unwrap_font_elements,
    optimize_epub,
)
from epub_optimizer.epubcheck import EpubCheckRunner


def _document(body: str) -> str:
    return (
        f'<html xmlns="{XHTML_NS}"><head><title>Cleanup regression</title></head>'
        f"<body>{body}</body></html>"
    )


def _write_epub2(path: Path, body: str, targets: tuple[str, ...] = ()) -> None:
    guide = "".join(
        f'<reference type="text" title="Target {i}" href="chapter.xhtml#{target}"/>'
        for i, target in enumerate(targets)
    )
    guide = f"<guide>{guide}</guide>" if targets else ""
    files = {
        "META-INF/container.xml": (
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>'
        ),
        "OPS/content.opf": (
            '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
            'unique-identifier="book-id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="book-id">cleanup-regression</dc:identifier>'
            "<dc:title>Cleanup regression</dc:title><dc:language>en</dc:language></metadata>"
            '<manifest><item id="chapter" href="chapter.xhtml" '
            'media-type="application/xhtml+xml"/>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            '<item id="cover" href="cover.png" media-type="image/png"/></manifest>'
            '<spine toc="ncx"><itemref idref="chapter"/></spine>'
            f"{guide}</package>"
        ),
        "OPS/toc.ncx": (
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            '<head><meta name="dtb:uid" content="cleanup-regression"/></head>'
            "<docTitle><text>Cleanup regression</text></docTitle><navMap>"
            '<navPoint id="chapter" playOrder="1"><navLabel><text>Chapter</text></navLabel>'
            '<content src="chapter.xhtml"/></navPoint></navMap></ncx>'
        ),
        "OPS/chapter.xhtml": _document(body),
        "OPS/cover.png": base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII="
        ),
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, content in files.items():
            archive.writestr(name, content)


def _runner(source: Path) -> EpubCheckRunner:
    runner = EpubCheckRunner()
    if runner._command(source) is None:
        pytest.skip("Official EPUBCheck executable/JAR is unavailable")
    return runner


def test_empty_fragment_blocks_survive_official_epubcheck_and_repeated_optimization(
    tmp_path: Path,
) -> None:
    source = tmp_path / "anchors.epub"
    targets = ("empty-div", "nested-anchor", "image-anchor", "quote")
    _write_epub2(
        source,
        '<div id="empty-div"/><p><a id="nested-anchor"/></p>'
        '<div class="image"><a id="image-anchor"/></div>'
        '<blockquote id="quote"><blockquote><p>Quotation.</p></blockquote></blockquote>'
        "<p>Chapter text.</p>",
        targets,
    )
    runner = _runner(source)
    before = runner.check(source)
    assert before.available, before.message
    assert before.errors == [], before.findings
    for pass_number in range(2):
        result = optimize_epub(source, tmp_path / f"anchors-{pass_number}", epubcheck=runner)
        assert result.epubcheck is not None
        assert result.epubcheck.output.errors == [], result.epubcheck.output.findings
        assert result.epubcheck.introduced == []
        with zipfile.ZipFile(result.output_path) as archive:
            root = etree.fromstring(archive.read("OPS/chapter.xhtml"))
            assert set(targets) <= set(root.xpath("//@id"))
            package = etree.fromstring(archive.read("OPS/content.opf"))
            assert set(package.xpath("//*[local-name()='reference']/@href")) == {
                f"chapter.xhtml#{target}" for target in targets
            }
        source = result.output_path


@pytest.mark.parametrize("legacy", ["center", "amazon"])
def test_legacy_markup_does_not_introduce_official_epubcheck_errors(
    tmp_path: Path, legacy: str
) -> None:
    source = tmp_path / f"{legacy}.epub"
    image = '<img src="cover.png" alt="Cover"/>'
    body = (
        f"<center>{image}</center><p>Chapter text.</p>"
        if legacy == "center"
        else '<p><img src="cover.png" alt="Cover" width="1" style="height:1px" '
        'data-AmznRemoved="1" data-AmznRemoved-M8="2"/></p><p>Chapter text.</p>'
    )
    _write_epub2(source, body)
    runner = _runner(source)
    before = runner.check(source)
    assert before.available, before.message
    assert any(f.code == "RSC-005" for f in before.errors), before.findings
    if legacy == "center":
        assert any('"center"' in f.message for f in before.errors), before.findings
    else:
        assert any("data-AmznRemoved" in f.message for f in before.errors), before.findings
    for pass_number in range(2):
        result = optimize_epub(source, tmp_path / f"{legacy}-{pass_number}", epubcheck=runner)
        assert result.epubcheck is not None
        assert result.epubcheck.introduced == []
        if legacy == "amazon":
            assert result.epubcheck.output.errors == [], result.epubcheck.output.findings
        with zipfile.ZipFile(result.output_path) as archive:
            root = etree.fromstring(archive.read("OPS/chapter.xhtml"))
            images = root.xpath("//*[local-name()='img']")
            assert len(images) == 1
            assert images[0].get("src") == "cover.png"
            assert images[0].get("alt") == "Cover"
            if legacy == "center":
                assert root.xpath("//*[local-name()='body']/*[local-name()='center']")
                assert not root.xpath("//*[local-name()='p']/*[local-name()='center']")
            else:
                assert not any("amznremoved" in key.lower() for key in images[0].attrib)
        source = result.output_path


@pytest.mark.parametrize("anchor", ["id", "name", "xml:id"])
def test_empty_cleanup_preserves_self_and_descendant_fragment_targets(anchor: str) -> None:
    root = etree.fromstring(
        _document(
            f'<div {anchor}="div-target"/><p><a {anchor}="p-target"/></p>'
            f'<section><span {anchor}="section-target"/></section>'
            "<div/><p>Chapter.</p>"
        ).encode()
    )
    _remove_empty_blocks(root)
    body = root.find(f"{{{XHTML_NS}}}body")
    assert body is not None
    assert [etree.QName(child).localname for child in body] == ["div", "p", "section", "p"]


def test_missing_image_cleanup_keeps_container_fragment_target(tmp_path: Path) -> None:
    root = etree.fromstring(
        _document(
            '<div class="image"><a id="target"/><img src="missing.png" alt="Missing"/></div>'
            '<div class="image"><img src="also-missing.png" alt="Missing"/></div><p>Text.</p>'
        ).encode()
    )
    _remove_broken_images(root, tmp_path / "chapter.xhtml", tmp_path)
    _remove_empty_blocks(root)
    assert root.xpath("//*[@id='target']")
    assert len(root.xpath("//*[local-name()='div']")) == 1
    assert not root.xpath("//*[local-name()='img']")


def test_wrapper_normalization_keeps_fragment_targets_and_text() -> None:
    root = etree.fromstring(
        _document(
            '<font id="font-target">Before <em>emphasis</em> after</font>tail'
            '<blockquote id="outer"><blockquote id="inner"><p>Quote.</p></blockquote></blockquote>'
        ).encode()
    )
    before = "".join(root.itertext())
    _unwrap_font_elements(root)
    _normalize_direct_body_content(root)
    _collapse_nested_blockquotes(root)
    assert set(root.xpath("//@id")) == {"font-target", "outer", "inner"}
    assert root.xpath("//*[local-name()='span' and @id='font-target']")
    assert "".join(root.itertext()) == before


@pytest.mark.parametrize(
    ("contents", "expected_wrapper"),
    [
        ('Before <em id="emphasis">emphasis</em> after', "span"),
        ('Before <div id="block"><p>A paragraph in a block.</p></div> after', "div"),
    ],
)
def test_process_anchored_font_preserves_flow_context(
    tmp_path: Path, contents: str, expected_wrapper: str
) -> None:
    content = tmp_path / "chapter.xhtml"
    content.write_text(
        _document(f'<p>Chapter text.</p><font id="target">{contents}</font>tail'),
        encoding="utf-8",
    )
    before = etree.parse(str(content))
    body_text = "".join(before.find(f"{{{XHTML_NS}}}body").itertext())
    targets = set(before.xpath("//@id"))

    _process_content_document(
        content, "chapter.xhtml", "Styles/epub-optimizer.css", tmp_path, "chapter", {}
    )

    root = etree.parse(str(content))
    target = root.xpath("//*[@id='target']")[0]
    assert etree.QName(target).localname == expected_wrapper
    assert set(root.xpath("//@id")) == targets
    assert "".join(root.find(f"{{{XHTML_NS}}}body").itertext()) == body_text
    assert not root.xpath("//*[local-name()='p']//*[local-name()='div']")
    if expected_wrapper == "div":
        assert etree.QName(target.getparent()).localname == "body"


def test_amazon_cleanup_preserves_other_epub3_data_and_foreign_attributes() -> None:
    root = etree.fromstring(
        _document(
            '<p data-custom="keep" aria-label="Keep" data-AmznRemoved="1">Text.</p>'
            '<svg xmlns="http://www.w3.org/2000/svg" data-AmznRemoved="keep"/>'
            '<p xmlns:vendor="urn:vendor" vendor:data-AmznRemoved="keep">More.</p>'
        ).encode()
    )
    _strip_publisher_presentation(root)
    paragraph = root.find(f".//{{{XHTML_NS}}}p")
    assert paragraph is not None
    assert paragraph.attrib == {"data-custom": "keep", "aria-label": "Keep"}
    assert root.find(".//{http://www.w3.org/2000/svg}svg").get("data-AmznRemoved") == "keep"
    assert root.xpath("//*[@*[namespace-uri()='urn:vendor']]")
