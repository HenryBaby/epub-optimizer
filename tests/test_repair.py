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
