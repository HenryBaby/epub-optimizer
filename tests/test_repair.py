from lxml import etree

from epub_optimizer.epubcheck import EpubCheckFinding
from epub_optimizer.repair import repair_workspace


def test_repair_workspace_persists_missing_cross_document_fragment(tmp_path) -> None:
    work = tmp_path / "work"
    chapter = work / "OEBPS" / "Text" / "chapter.xhtml"
    chapter.parent.mkdir(parents=True)
    chapter.write_text(
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p><a href="missing.xhtml#section">Text stays</a></p>'
        "</body></html>",
        encoding="utf-8",
    )
    package_tree = _package_tree("Text/chapter.xhtml")

    actions = repair_workspace(
        work,
        "OEBPS/package.opf",
        package_tree,
        [EpubCheckFinding("error", "RSC-007", "Missing", "OEBPS/Text/chapter.xhtml")],
    )

    repaired = chapter.read_text(encoding="utf-8")
    assert 'href="missing.xhtml#section"' not in repaired
    assert "Text stays" in repaired
    assert actions == [
        "Removed broken link target (text preserved): missing.xhtml#section"
    ]


def test_repair_workspace_rejects_manifest_path_outside_workspace(tmp_path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    victim = tmp_path / "victim.xhtml"
    victim.write_text("untouched", encoding="utf-8")
    package_tree = _package_tree("../../victim.xhtml")

    actions = repair_workspace(
        work,
        "OEBPS/package.opf",
        package_tree,
        [EpubCheckFinding("error", "OPF-003", "Missing manifest resource", "package.opf")],
    )

    assert actions == []
    assert victim.read_text(encoding="utf-8") == "untouched"


def test_pathless_finding_does_not_authorize_document_repairs(tmp_path) -> None:
    work = tmp_path / "work"
    chapter = work / "OEBPS" / "Text" / "chapter.xhtml"
    chapter.parent.mkdir(parents=True)
    original = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p><a href="missing.xhtml">Text stays linked</a></p>'
        "</body></html>"
    )
    chapter.write_text(original, encoding="utf-8")

    actions = repair_workspace(
        work,
        "OEBPS/package.opf",
        _package_tree("Text/chapter.xhtml"),
        [EpubCheckFinding("error", "RSC-007", "Missing")],
    )

    assert actions == []
    assert chapter.read_text(encoding="utf-8") == original


def test_rsc005_wraps_stray_blockquote_text_without_losing_content(tmp_path) -> None:
    work = tmp_path / "work"
    chapter = work / "OEBPS" / "Text" / "chapter.xhtml"
    chapter.parent.mkdir(parents=True)
    chapter.write_text(
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><blockquote>'
        'Quoted text<strong>bold</strong><code>code</code>tail text'
        "</blockquote></body></html>",
        encoding="utf-8",
    )

    actions = repair_workspace(
        work,
        "OEBPS/package.opf",
        _package_tree("Text/chapter.xhtml"),
        [
            EpubCheckFinding(
                "error",
                "RSC-005",
                "text not allowed here; expected element p",
                "OEBPS/Text/chapter.xhtml",
            )
        ],
    )

    root = etree.parse(str(chapter)).getroot()
    blockquote = root.xpath("//*[local-name()='blockquote']")[0]
    assert not (blockquote.text or "").strip()
    paragraphs = blockquote.xpath("./*[local-name()='p']")
    assert ["".join(p.itertext()) for p in paragraphs] == ["Quoted textboldcodetail text"]
    assert paragraphs[0].xpath("./*[local-name()='strong']")
    assert paragraphs[0].xpath("./*[local-name()='code']")
    assert "bold" in "".join(blockquote.itertext())
    assert len(actions) == 1


def test_broken_resources_preserve_alt_and_fallback_content(tmp_path) -> None:
    work = tmp_path / "work"
    chapter = work / "OEBPS" / "Text" / "chapter.xhtml"
    chapter.parent.mkdir(parents=True)
    chapter.write_text(
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p><img src="missing.jpg" alt="Map of the city"/></p>'
        '<object data="missing.bin"><p>Download description</p></object>'
        "</body></html>",
        encoding="utf-8",
    )

    actions = repair_workspace(
        work,
        "OEBPS/package.opf",
        _package_tree("Text/chapter.xhtml"),
        [EpubCheckFinding("error", "RSC-007", "Missing", "OEBPS/Text/chapter.xhtml")],
    )

    repaired = chapter.read_text(encoding="utf-8")
    assert "Map of the city" in repaired
    assert "Download description" in repaired
    assert 'src="missing.jpg"' not in repaired
    assert 'data="missing.bin"' not in repaired
    assert len(actions) == 2


def test_repairs_common_opf_metadata_errors_without_removing_primary_metadata(tmp_path) -> None:
    package_tree = etree.ElementTree(
        etree.fromstring(
            b'''<package xmlns="http://www.idpf.org/2007/opf" version="3.0"
                unique-identifier="missing">
              <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                <dc:identifier>urn:isbn:123</dc:identifier>
                <dc:title id="title">Title stays</dc:title>
                <dc:creator id="author">Author stays</dc:creator>
                <meta property="calibre:timestamp">2020-01-01</meta>
                <meta property="vendor:accessibility">Preserve this</meta>
                <meta refines="#missing" property="title-type">main</meta>
                <meta refines="#title" property="role">aut</meta>
                <meta refines="#author" property="role">aut</meta>
              </metadata>
              <manifest>
                <item id="ncx" href="toc%20file.ncx" media-type="application/x-dtbncx+xml"/>
              </manifest>
              <spine/>
            </package>'''
        )
    )
    findings = [
        EpubCheckFinding("error", "OPF-028", 'Undeclared prefix: "calibre".', "OEBPS/book.opf"),
        EpubCheckFinding("error", "OPF-028", 'Undeclared prefix: "vendor".', "OEBPS/book.opf"),
        EpubCheckFinding(
            "error", "OPF-030", 'The unique-identifier "missing" was not found.', "OEBPS/book.opf"
        ),
        EpubCheckFinding(
            "error", "RSC-005", '@refines missing target id: "missing"', "OEBPS/book.opf"
        ),
        EpubCheckFinding(
            "error",
            "RSC-005",
            'Property "role" must refine a "creator", "contributor", or "publisher" property.',
            "OEBPS/book.opf",
        ),
    ]
    ncx = tmp_path / "OEBPS" / "toc file.ncx"
    ncx.parent.mkdir(parents=True)
    ncx.write_text(
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">'
        '<head><meta name="dtb:uid" content="old-id"/></head></ncx>',
        encoding="utf-8",
    )

    actions = repair_workspace(tmp_path, "OEBPS/book.opf", package_tree, findings)

    root = package_tree.getroot()
    metadata = root.find("{http://www.idpf.org/2007/opf}metadata")
    assert metadata is not None
    identifier = metadata.find("{http://purl.org/dc/elements/1.1/}identifier")
    title = metadata.find("{http://purl.org/dc/elements/1.1/}title")
    assert identifier is not None and identifier.text == "urn:isbn:123"
    assert title is not None and title.text == "Title stays"
    assert root.attrib["unique-identifier"] == identifier.attrib["id"]
    assert "calibre:" in root.attrib["prefix"]
    refinements = metadata.xpath("*[@refines]")
    assert len(refinements) == 1
    assert refinements[0].attrib["refines"] == "#author"
    assert metadata.xpath('*[@property="vendor:accessibility"]')[0].text == "Preserve this"
    assert "Declared known calibre metadata vocabulary" in actions
    assert f'content="{identifier.text}"' in ncx.read_text(encoding="utf-8")
    assert any(action.startswith("Synchronized NCX identifier") for action in actions)


def test_ncx001_synchronizes_uid_when_opf_identifier_is_already_valid(tmp_path) -> None:
    package_tree = etree.ElementTree(
        etree.fromstring(
            b'''<package xmlns="http://www.idpf.org/2007/opf" version="2.0"
                unique-identifier="bookid">
              <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                <dc:identifier id="bookid">urn:isbn:123</dc:identifier>
              </metadata>
              <manifest>
                <item id="ncx" href="toc%20file.ncx" media-type="application/x-dtbncx+xml"/>
              </manifest>
              <spine toc="ncx"/>
            </package>'''
        )
    )
    ncx = tmp_path / "OEBPS" / "toc file.ncx"
    ncx.parent.mkdir(parents=True)
    ncx.write_text(
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">'
        '<head><meta name="dtb:uid" content="old-id"/></head></ncx>',
        encoding="utf-8",
    )

    actions = repair_workspace(
        tmp_path,
        "OEBPS/book.opf",
        package_tree,
        [
            EpubCheckFinding(
                "error",
                "NCX-001",
                "NCX identifier does not match OPF identifier",
                "OEBPS/toc file.ncx",
            )
        ],
    )

    assert 'content="urn:isbn:123"' in ncx.read_text(encoding="utf-8")
    assert actions == ["Synchronized NCX identifier with OPF identifier: toc%20file.ncx"]


def _package_tree(content_href: str) -> etree._ElementTree:
    root = etree.fromstring(
        f'''<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
          <manifest>
            <item id="chapter" href="{content_href}" media-type="application/xhtml+xml"/>
          </manifest>
          <spine><itemref idref="chapter"/></spine>
        </package>'''.encode()
    )
    return etree.ElementTree(root)
