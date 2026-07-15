import zipfile
from pathlib import Path

from epub_optimizer.core import optimize_epub, preview_epub_changes, validate_epub_details


def test_optimize_minimal_epub(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    output_dir = tmp_path / "out"
    _write_minimal_epub(source)

    result = optimize_epub(source, output_dir)

    assert result.content_documents_processed == 1
    assert result.stylesheets_replaced == 3
    assert result.output_path.is_file()

    with zipfile.ZipFile(result.output_path) as archive:
        names = archive.namelist()
        assert names[0] == "mimetype"
        assert archive.read("mimetype") == b"application/epub+zip"
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        chapter = archive.read("OEBPS/Text/chapter.xhtml").decode("utf-8")
        css = archive.read("OEBPS/Styles/epub-optimizer.css").decode("utf-8")

    assert "OEBPS/Styles/old.css" not in names
    assert "OEBPS/Fonts/publisher.woff2" not in names
    assert "OEBPS/Misc/page-template.xpgt" not in names
    assert "epub-optimizer.css" in opf
    assert 'name="epub-optimizer:version"' in opf
    assert "old.css" not in opf
    assert "publisher.woff2" not in opf
    assert "page-template.xpgt" not in opf
    assert "../Styles/epub-optimizer.css" in chapter
    assert '<h1 class="eo-chapter">Chapter One</h1>' in chapter
    assert 'class="eo-right">Chapter One' not in chapter
    assert 'class="eo-first"' in chapter
    assert 'class="eo-body"' in chapter
    assert 'class="eo-strike"' in chapter
    assert 'style="' not in chapter
    assert 'class="publisher"' not in chapter
    normalized_css = css.replace("\r\n", "\n")
    assert "font-family: inherit" in normalized_css
    assert "p {\n  margin: 0 0 0.75em;" in normalized_css
    assert "p.eo-body {\n  text-indent: 0;" in normalized_css
    assert "p.eo-first {\n  text-indent: 1em;" in normalized_css
    assert "h1.eo-chapter,\nh2.eo-chapter,\nh3.eo-chapter" in normalized_css
    assert "font-weight: bold;\n  text-align: center;" in normalized_css

    second_result = optimize_epub(result.output_path, tmp_path / "out-second")
    with zipfile.ZipFile(second_result.output_path) as archive:
        assert "OEBPS/Styles/epub-optimizer.css" in archive.namelist()
        second_opf = archive.read("OEBPS/content.opf").decode("utf-8")
        second_chapter = archive.read("OEBPS/Text/chapter.xhtml").decode("utf-8")

    assert second_opf.count("epub-optimizer.css") == 1
    assert second_opf.count('name="epub-optimizer:version"') == 1
    assert '<h1 class="eo-chapter">Chapter One</h1>' in second_chapter
    assert 'class="eo-first"' in second_chapter
    assert 'class="eo-body"' in second_chapter
    assert 'class="eo-strike"' in second_chapter


def test_preview_epub_changes_does_not_write_output(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    _write_minimal_epub(source)

    preview = preview_epub_changes(source)

    assert preview.input_filename == "book.epub"
    assert preview.epub_version == "3.0"
    assert preview.package_path == "OEBPS/content.opf"
    assert preview.content_documents == 1
    assert preview.stylesheets_and_fonts == 3
    assert preview.removable_files == 3
    assert preview.images_preserved == 0
    assert preview.would_write_canonical_css is True
    assert preview.change_summary == [
        "Would normalize 1 content document(s).",
        "Would replace 3 stylesheet/font manifest item(s).",
        "Would delete 3 old style/font file(s).",
        "Would preserve 0 image resource(s) without recompression.",
        "Would write the canonical EPUB Optimizer stylesheet.",
    ]
    assert not (tmp_path / "book-optimized.epub").exists()


def test_validate_epub_details_reports_structure_issues(tmp_path: Path) -> None:
    source = tmp_path / "broken-spine.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test</dc:identifier>
    <dc:title>Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="missing"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/Text/chapter.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Test</title></head>
  <body><p>Body.</p></body>
</html>
""",
        )

    report = validate_epub_details(source)

    assert report.valid is False
    assert any(issue.code == "missing-spine-target" for issue in report.issues)


def test_optimize_root_opf_anonymous_div_chapter(tmp_path: Path) -> None:
    source = tmp_path / "root-book.epub"
    _write_root_opf_div_chapter_epub(source)

    result = optimize_epub(source, tmp_path / "out-root")

    with zipfile.ZipFile(result.output_path) as archive:
        names = archive.namelist()
        opf = archive.read("content.opf").decode("utf-8")
        chapter = archive.read("OEBPS/chapter001.xhtml").decode("utf-8")

    assert "Styles/epub-optimizer.css" in names
    assert "Styles/old.css" not in names
    assert 'href="Styles/epub-optimizer.css"' in opf
    assert 'href="../Styles/epub-optimizer.css"' in chapter
    assert 'class="eo-chapter"' in chapter
    assert 'class="eo-smallcaps">ITIES</span>' in chapter
    assert '<p class="eo-first">L<span class="eo-smallcaps">EAVING THERE AND</span>' in chapter


def test_optimize_front_matter_nested_divs_and_empty_breaks(tmp_path: Path) -> None:
    source = tmp_path / "front.epub"
    _write_front_matter_div_epub(source)

    result = optimize_epub(source, tmp_path / "out-front")

    with zipfile.ZipFile(result.output_path) as archive:
        front = archive.read("OEBPS/alsoby.xhtml").decode("utf-8")
        chapter = archive.read("OEBPS/chapter.xhtml").decode("utf-8")

    assert 'class="eo-front-body"' in front
    assert '<h1 class="eo-front">ALSO BY WRITER</h1>' in front
    assert '<p class="eo-front-list-item"><i>First Book</i></p>' in front
    assert '<p class="eo-front-list-item"><i>Second Book</i></p>' in front
    assert '<span class="eo-smallcaps">ITIES</span>' in chapter
    assert "eo-scene-break" not in chapter
    assert '<p class="eo-first">First body paragraph.</p>' in chapter


def test_optimize_toc_entries(tmp_path: Path) -> None:
    source = tmp_path / "toc.epub"
    _write_toc_epub(source)

    result = optimize_epub(source, tmp_path / "out-toc")

    with zipfile.ZipFile(result.output_path) as archive:
        toc = archive.read("OEBPS/contents.xhtml").decode("utf-8")

    assert '<h1 class="eo-toc-heading">CONTENTS</h1>' in toc
    assert '<div class="eo-toc" id="toc">' in toc
    assert '<p class="eo-toc-entry"><a href="title.xhtml">Title Page</a></p>' in toc
    assert '<p class="eo-toc-part"><a href="part001.xhtml">PART ONE</a></p>' in toc
    assert '<p class="eo-toc-chapter"><a href="chapter001.xhtml">Chapter One</a></p>' in toc
    assert '<p class="eo-toc-chapter"><a href="chapter002.xhtml">Chapter Two</a></p>' in toc
    assert '<p class="eo-toc"' not in toc


def test_optimize_opaque_front_matter_and_blockquote_alignment(tmp_path: Path) -> None:
    source = tmp_path / "opaque-front.epub"
    _write_opaque_front_matter_epub(source)

    result = optimize_epub(source, tmp_path / "out-opaque-front")

    with zipfile.ZipFile(result.output_path) as archive:
        contents = archive.read("OEBPS/split003.xhtml").decode("utf-8")
        dedication = archive.read("OEBPS/split002.xhtml").decode("utf-8")
        chapter = archive.read("OEBPS/split009.xhtml").decode("utf-8")
        css = archive.read("OEBPS/Styles/epub-optimizer.css").decode("utf-8")

    assert '<h1 class="eo-toc-heading">Contents</h1>' in contents
    assert '<p class="eo-toc-entry"><a href="split002.xhtml">Dedication</a></p>' in contents
    assert '<p class="eo-toc-part"><a href="split008.xhtml">Part One</a></p>' in contents
    assert '<p class="eo-toc-chapter"><a href="split009.xhtml">Chapter One</a></p>' in contents
    assert 'class="eo-first">Contents' not in contents

    assert '<h1 class="eo-front"><a href="split003.xhtml">Dedication</a></h1>' in dedication
    assert dedication.count('class="eo-dedication"') == 2
    assert (
        '<blockquote class="eo-dedication"><strong>FOR A FRIEND</strong></blockquote>'
        in dedication
    )

    assert chapter.count('class="eo-blockquote"') == 1
    assert '<blockquote class="eo-right">- SOURCE</blockquote>' in chapter
    assert "blockquote.eo-right" in css


def test_optimize_title_page_layout_roles(tmp_path: Path) -> None:
    source = tmp_path / "title.epub"
    _write_title_page_epub(source)

    result = optimize_epub(source, tmp_path / "out-title")

    with zipfile.ZipFile(result.output_path) as archive:
        title = archive.read("OEBPS/title.xhtml").decode("utf-8")
        css = archive.read("Styles/epub-optimizer.css").decode("utf-8")

    assert '<div class="eo-title-page">' in title
    assert '<h1 class="eo-title-main">BOOK TITLE</h1>' in title
    assert '<p class="eo-title-credit-label">TRANSLATED FROM THE ORIGINAL BY</p>' in title
    assert '<p class="eo-title-credit">Translator Name</p>' in title
    assert '<p class="eo-title-author">Author Name</p>' in title
    assert '<p class="eo-title-publisher">PUBLISHER BOOKS<br/>City</p>' in title
    assert "eo-title-main" in css


def test_optimize_opaque_also_by_works_list(tmp_path: Path) -> None:
    source = tmp_path / "works.epub"
    _write_opaque_works_list_epub(source)

    result = optimize_epub(source, tmp_path / "out-works")

    with zipfile.ZipFile(result.output_path) as archive:
        works = archive.read("OEBPS/adc.xhtml").decode("utf-8")
        css = archive.read("Styles/epub-optimizer.css").decode("utf-8")

    assert '<h1 class="eo-front">ALSO BY WRITER</h1>' in works
    assert '<p class="eo-front-section">FICTION</p>' in works
    assert '<p class="eo-front-list-item"><em>First Book</em></p>' in works
    assert '<p class="eo-front-list-item"><em>Second Book</em></p>' in works
    assert "eo-chapter" not in works
    assert "eo-front-section" in css


def test_optimize_opening_epigraph_resets_first_body_paragraph(tmp_path: Path) -> None:
    source = tmp_path / "epigraph.epub"
    _write_opening_epigraph_epub(source)

    result = optimize_epub(source, tmp_path / "out-epigraph")

    with zipfile.ZipFile(result.output_path) as archive:
        chapter = archive.read("OEBPS/chapter.xhtml").decode("utf-8")

    assert '<p class="eo-extract"><i>This is a long opening epigraph' in chapter
    assert '<p class="eo-extract"><b>--The Stolen Journals</b></p>' in chapter
    assert '<p class="eo-first">The first narrative paragraph starts here.</p>' in chapter
    assert '<p class="eo-body">The following paragraph continues the same scene.</p>' in chapter

    second_result = optimize_epub(result.output_path, tmp_path / "out-epigraph-second")
    with zipfile.ZipFile(second_result.output_path) as archive:
        second_chapter = archive.read("OEBPS/chapter.xhtml").decode("utf-8")

    assert '<p class="eo-extract"><i>This is a long opening epigraph' in second_chapter
    assert '<p class="eo-extract"><b>--The Stolen Journals</b></p>' in second_chapter
    assert '<p class="eo-first">The first narrative paragraph starts here.</p>' in second_chapter
    assert (
        '<p class="eo-body">The following paragraph continues the same scene.</p>'
        in second_chapter
    )


def test_optimize_narrative_prologue_uses_body_flow(tmp_path: Path) -> None:
    source = tmp_path / "prologue.epub"
    _write_narrative_prologue_epub(source)

    result = optimize_epub(source, tmp_path / "out-prologue")

    with zipfile.ZipFile(result.output_path) as archive:
        prologue = archive.read("OEBPS/prologue.xhtml").decode("utf-8")

    assert '<h1 class="eo-chapter">PROLOGUE</h1>' in prologue
    assert '<p class="eo-extract"><i>Excerpt from an archival speech:</i></p>' in prologue
    assert '<p class="eo-first">This is the first prose paragraph' in prologue
    assert '<p class="eo-body">This is the second prose paragraph' in prologue
    assert "eo-front-body" not in prologue


def test_optimize_prologue_preserves_letter_inset(tmp_path: Path) -> None:
    source = tmp_path / "prologue-letter.epub"
    _write_prologue_letter_epub(source)

    result = optimize_epub(source, tmp_path / "out-prologue-letter")

    with zipfile.ZipFile(result.output_path) as archive:
        prologue = archive.read("OEBPS/prologue.xhtml").decode("utf-8")
        css = archive.read("Styles/epub-optimizer.css").decode("utf-8")

    assert '<div class="eo-letter">' in prologue
    assert '<p class="eo-letter-opener">My dear correspondent,</p>' in prologue
    assert '<p class="eo-letter-first">This is the first line of the letter' in prologue
    assert '<p class="eo-letter-body">This is the following line of the letter' in prologue
    assert '<p class="eo-letter-attribution">Missive from A to B</p>' in prologue
    assert '<p class="eo-first">This is the first narrative paragraph' in prologue
    assert "eo-letter" in css


def test_optimize_narrative_introduction_uses_body_flow(tmp_path: Path) -> None:
    source = tmp_path / "introduction.epub"
    _write_narrative_introduction_epub(source)

    result = optimize_epub(source, tmp_path / "out-introduction")

    with zipfile.ZipFile(result.output_path) as archive:
        introduction = archive.read("OEBPS/introduction.xhtml").decode("utf-8")

    assert '<h1 class="eo-chapter">INTRODUCTION</h1>' in introduction
    assert '<p class="eo-first">This is the first long introduction paragraph' in introduction
    assert '<p class="eo-body">This is the second long introduction paragraph' in introduction
    assert "eo-front-body" not in introduction


def test_optimize_metadata_pages_do_not_use_body_flow(tmp_path: Path) -> None:
    source = tmp_path / "metadata.epub"
    _write_metadata_page_epub(source)

    result = optimize_epub(source, tmp_path / "out-metadata")

    with zipfile.ZipFile(result.output_path) as archive:
        info = archive.read("OEBPS/info.xhtml").decode("utf-8")
        css = archive.read("Styles/epub-optimizer.css").decode("utf-8")

    assert '<p class="eo-metadata-line">Original title: <cite>Example</cite></p>' in info
    assert '<p class="eo-metadata-line">Digital editor: Example Editor</p>' in info
    assert '<p class="eo-metadata-line">ePub base r2.1</p>' in info
    assert "eo-first" not in info
    assert "eo-body" not in info
    assert "eo-metadata-line" in css


def test_optimize_narrative_chapter_with_metadata_like_words(tmp_path: Path) -> None:
    source = tmp_path / "metadata-like-chapter.epub"
    _write_metadata_like_chapter_epub(source)

    result = optimize_epub(source, tmp_path / "out-metadata-like")

    with zipfile.ZipFile(result.output_path) as archive:
        chapter = archive.read("OEBPS/chapter.xhtml").decode("utf-8")

    assert '<h1 class="eo-chapter">Cities &amp; The Sky 2</h1>' in chapter
    assert '<p class="eo-first">This belief is handed down in Beersheba:' in chapter
    assert '<p class="eo-body">They also believe, these inhabitants,' in chapter
    assert "eo-metadata" not in chapter


def test_optimize_preserves_existing_semantic_heading_roles(tmp_path: Path) -> None:
    source = tmp_path / "semantic-heading-roles.epub"
    _write_semantic_heading_roles_epub(source)

    result = optimize_epub(source, tmp_path / "out-semantic-heading-roles")

    with zipfile.ZipFile(result.output_path) as archive:
        toc = archive.read("OEBPS/toc.xhtml").decode("utf-8")
        front = archive.read("OEBPS/ack.xhtml").decode("utf-8")
        metadata = archive.read("OEBPS/info.xhtml").decode("utf-8")
        image = archive.read("OEBPS/image-title.xhtml").decode("utf-8")
        chapter = archive.read("OEBPS/chapter.xhtml").decode("utf-8")

    assert '<h1 class="eo-centered">Contents</h1>' in toc
    assert '<h1 class="eo-metadata-title">Acknowledgements</h1>' in front
    assert '<h1 class="eo-metadata-title">Edition Information</h1>' in metadata
    assert '<h1 class="eo-image">Illustrated Title</h1>' in image
    assert '<h1 class="eo-chapter">Chapter One</h1>' in chapter
    assert '<h1 class="eo-right">Chapter One</h1>' not in chapter


def test_optimize_swedish_filename_does_not_trigger_front_matter_hint(tmp_path: Path) -> None:
    source = tmp_path / "swedish.epub"
    _write_swedish_filename_epub(source)

    result = optimize_epub(source, tmp_path / "out-swedish")

    with zipfile.ZipFile(result.output_path) as archive:
        chapter = archive.read("Man_som_hatar_kvinnor_split_1.html").decode("utf-8")

    assert '<p class="eo-first">Första stycket i kapitlet.</p>' in chapter
    assert '<p class="eo-body">Andra stycket i samma sammanhang.</p>' in chapter
    assert "eo-front-body" not in chapter


def test_optimize_part_pages_images_empty_blocks_and_ncx(tmp_path: Path) -> None:
    source = tmp_path / "structure.epub"
    _write_structure_cleanup_epub(source)

    result = optimize_epub(source, tmp_path / "out-structure")

    with zipfile.ZipFile(result.output_path) as archive:
        part = archive.read("OEBPS/part001.xhtml").decode("utf-8")
        ncx = archive.read("toc.ncx").decode("utf-8")

    assert '<h1 class="eo-part">PART ONE</h1>' in part
    assert "missing.jpg" not in part
    assert "<p/>" not in part
    assert "<div/>" not in part
    assert "  Part One  " not in ncx
    assert ">Part One<" in ncx
    assert "missing.xhtml" not in ncx
    assert "javascript:" not in ncx
    assert ncx.count("<navPoint") == 1
    assert 'playOrder="1"' in ncx


def test_optimize_preserves_svg_cover_sizing(tmp_path: Path) -> None:
    source = tmp_path / "svg-cover.epub"
    _write_svg_cover_epub(source)

    result = optimize_epub(source, tmp_path / "out-svg-cover")

    with zipfile.ZipFile(result.output_path) as archive:
        titlepage = archive.read("OEBPS/xhtml/titlepage.xhtml").decode("utf-8")
        css = archive.read("OEBPS/Styles/epub-optimizer.css").decode("utf-8")

    assert '<div class="eo-image">' in titlepage
    assert 'class="eo-scene-break"' not in titlepage
    assert 'width="100%"' in titlepage
    assert 'height="100%"' in titlepage
    assert 'width="1246"' in titlepage
    assert 'height="2200"' in titlepage
    assert ".eo-image svg" in css


def test_optimize_ignores_comment_nodes_inside_blocks(tmp_path: Path) -> None:
    source = tmp_path / "comment-nodes.epub"
    _write_comment_node_epub(source)

    result = optimize_epub(source, tmp_path / "out-comments")

    with zipfile.ZipFile(result.output_path) as archive:
        chapter = archive.read("OEBPS/Text/chapter.xhtml").decode("utf-8")

    assert "publisher marker" in chapter
    assert "inline marker" in chapter
    assert 'class="eo-body"' in chapter


def _write_minimal_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test</dc:identifier>
    <dc:title>Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
    <item id="old-css" href="Styles/old.css" media-type="text/css"/>
    <item id="font" href="Fonts/publisher.woff2" media-type="font/woff2"/>
    <item id="page-template"
          href="Misc/page-template.xpgt"
          media-type="application/vnd.adobe-page-template+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/Styles/old.css",
            "body { font-family: PublisherFont; margin: 2em; }",
        )
        archive.writestr("OEBPS/Fonts/publisher.woff2", b"fake-font")
        archive.writestr("OEBPS/Misc/page-template.xpgt", "page-template")
        archive.writestr(
            "OEBPS/Text/chapter.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>Test</title>
    <link href="../Styles/old.css" rel="stylesheet" type="text/css"/>
  </head>
  <body>
    <h1 class="chapter" style="text-align: right;">Chapter One</h1>
    <p class="nonindent" style="margin: 2em;">First paragraph with <em>emphasis</em>.</p>
    <p class="indent"><span class="publisher">Second</span> paragraph with
    <span class="strike">struck text</span>.</p>
  </body>
</html>
""",
        )


def _write_comment_node_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-comments</dc:identifier>
    <dc:title>Comment Nodes</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/Text/chapter.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Comment Nodes</title></head>
  <body>
    <p><!-- publisher marker -->Chapter One</p>
    <p>Body text.<!-- inline marker --></p>
  </body>
</html>
""",
        )


def _write_svg_cover_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-svg-cover</dc:identifier>
    <dc:title>SVG Cover</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item
      id="titlepage1"
      href="xhtml/titlepage.xhtml"
      media-type="application/xhtml+xml"
      properties="svg calibre:title-page"
    />
    <item id="cover" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
  </manifest>
  <spine>
    <itemref idref="titlepage1"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/xhtml/titlepage.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
  <head>
    <title>Cover</title>
    <style type="text/css">
      body { text-align: center; padding: 0; margin: 0; }
    </style>
  </head>
  <body>
    <div>
      <svg version="1.1" xmlns="http://www.w3.org/2000/svg"
        xmlns:xlink="http://www.w3.org/1999/xlink"
        width="100%" height="100%" viewBox="0 0 1246 2200"
        preserveAspectRatio="none">
        <image width="1246" height="2200" xlink:href="../images/cover.jpg"/>
      </svg>
    </div>
  </body>
</html>
""",
        )
        archive.writestr("OEBPS/images/cover.jpg", b"fake-cover")


def _write_root_opf_div_chapter_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-root</dc:identifier>
    <dc:title>Root Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter001" href="OEBPS/chapter001.xhtml" media-type="application/xhtml+xml"/>
    <item id="old-css" href="Styles/old.css" media-type="text/css"/>
  </manifest>
  <spine>
    <itemref idref="chapter001"/>
  </spine>
</package>
""",
        )
        archive.writestr("Styles/old.css", "div { font-family: PublisherFont; }")
        archive.writestr(
            "OEBPS/chapter001.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>Root Test</title>
    <link href="../Styles/old.css" rel="stylesheet" type="text/css"/>
  </head>
  <body>
    <div class="calibre-heading">C<span>ITIES</span> &amp; M<span>EMORY</span> • 1</div>
    <div class="calibre-body">L<span>EAVING THERE AND</span> proceeding east.</div>
  </body>
</html>
""",
        )


def _write_front_matter_div_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-front</dc:identifier>
    <dc:title>Front Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="alsoby" href="OEBPS/alsoby.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter" href="OEBPS/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="alsoby"/>
    <itemref idref="chapter"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/alsoby.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Front Test</title></head>
  <body>
    <div>
      <div>ALSO BY WRITER</div>
      <div><i>First Book</i></div>
      <div><i>Second Book</i></div>
    </div>
  </body>
</html>
""",
        )
        archive.writestr(
            "OEBPS/chapter.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Front Test</title></head>
  <body>
    <div>C<span>ITIES</span> • 1</div>
    <div/>
    <div>First body paragraph.</div>
  </body>
</html>
""",
        )


def _write_toc_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-toc</dc:identifier>
    <dc:title>TOC Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="contents"
          href="OEBPS/contents.xhtml"
          media-type="application/xhtml+xml"
          properties="nav"/>
    <item id="chapter001" href="OEBPS/chapter001.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="contents"/>
    <itemref idref="chapter001"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/contents.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>TOC Test</title></head>
  <body>
    <div class="toc" id="toc">
      <h1 class="toc">CONTENTS</h1>
      <div class="toc_fm">
        <p class="center0"><a href="title.xhtml">Title Page</a></p>
      </div>
      <div class="toc_part"><a href="part001.xhtml">PART ONE</a></div>
      <div class="toc_chap"><a href="chapter001.xhtml">Chapter One</a></div>
      <p class="toc"><a href="chapter002.xhtml">Chapter Two</a></p>
    </div>
  </body>
</html>
""",
        )
        archive.writestr(
            "OEBPS/chapter001.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>TOC Test</title></head>
  <body><p>Body.</p></body>
</html>
""",
        )


def _write_opaque_front_matter_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-opaque-front</dc:identifier>
    <dc:title>Opaque Front Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="style" href="stylesheet.css" media-type="text/css"/>
    <item id="id2" href="split002.xhtml" media-type="application/xhtml+xml"/>
    <item id="id3" href="split003.xhtml" media-type="application/xhtml+xml"/>
    <item id="id9" href="split009.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="id2"/>
    <itemref idref="id3"/>
    <itemref idref="id9"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/stylesheet.css",
            """.heading { text-align: justify; text-indent: 0; }
.tocentry { text-align: justify; text-indent: 0; }
.quoteouter { margin-left: 2em; }
.quoteinner { margin-left: 2em; }
.source { text-align: right; text-indent: 0; }
""",
        )
        archive.writestr(
            "OEBPS/split002.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>Opaque Test</title>
    <link href="stylesheet.css" rel="stylesheet" type="text/css"/>
  </head>
  <body>
    <p class="heading"><a href="split003.xhtml">Dedication</a></p>
    <blockquote class="quoteouter">
      <blockquote class="quoteinner"><strong>FOR A FRIEND</strong></blockquote>
    </blockquote>
    <blockquote class="quoteouter">
      <blockquote class="quoteinner"><em>and everyone else</em></blockquote>
    </blockquote>
  </body>
</html>
""",
        )
        archive.writestr(
            "OEBPS/split003.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>Opaque Test</title>
    <link href="stylesheet.css" rel="stylesheet" type="text/css"/>
  </head>
  <body>
    <p class="heading">Contents</p>
    <p class="tocentry"><a href="split002.xhtml">Dedication</a></p>
    <p class="tocentry"><a href="intro.xhtml">Introduction</a></p>
    <p class="tocentry"><a href="note.xhtml">A Note on the Text</a></p>
    <p class="tocentry"><a href="split008.xhtml">Part One</a></p>
    <p class="tocentry"><a href="split009.xhtml">Chapter One</a></p>
  </body>
</html>
""",
        )
        archive.writestr(
            "OEBPS/split009.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>Opaque Test</title>
    <link href="stylesheet.css" rel="stylesheet" type="text/css"/>
  </head>
  <body>
    <p class="heading">CHAPTER ONE</p>
    <blockquote class="quoteouter">
      <blockquote class="quoteinner"><em>A chapter opening quotation.</em></blockquote>
    </blockquote>
    <blockquote class="quoteouter">
      <blockquote class="source">- SOURCE</blockquote>
    </blockquote>
    <p>First narrative paragraph.</p>
    <p>Second narrative paragraph.</p>
  </body>
</html>
""",
        )


def _write_title_page_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-title</dc:identifier>
    <dc:title>Title Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="titlepage" href="OEBPS/title.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="titlepage"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/title.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Title Test</title></head>
  <body>
    <div>
      <p>BOOK TITLE</p>
      <p>TRANSLATED FROM THE ORIGINAL BY</p>
      <p>Translator Name</p>
      <p>Author Name</p>
      <p>PUBLISHER BOOKS<br/>City</p>
    </div>
  </body>
</html>
""",
        )


def _write_opaque_works_list_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-works</dc:identifier>
    <dc:title>Works Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="adc" href="OEBPS/adc.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="adc"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/adc.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Works Test</title></head>
  <body>
    <h1>ALSO BY WRITER</h1>
    <p>FICTION</p>
    <p><em>First Book</em></p>
    <p><em>Second Book</em></p>
    <p>POETRY</p>
    <p><em>Collected Poems</em></p>
  </body>
</html>
""",
        )


def _write_opening_epigraph_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-epigraph</dc:identifier>
    <dc:title>Epigraph Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="OEBPS/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/chapter.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Epigraph Test</title></head>
  <body>
    <h1>Chapter One</h1>
    <p><i>This is a long opening epigraph that belongs before the narrative
    and should not consume the first body paragraph indentation.</i></p>
    <p><b>--The Stolen Journals</b></p>
    <p>The first narrative paragraph starts here.</p>
    <p>The following paragraph continues the same scene.</p>
  </body>
</html>
""",
        )


def _write_narrative_prologue_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-prologue</dc:identifier>
    <dc:title>Prologue Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="prologue" href="OEBPS/prologue.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="prologue"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/prologue.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Prologue Test</title></head>
  <body>
    <h1>PROLOGUE</h1>
    <p><i>Excerpt from an archival speech:</i></p>
    <p>This is the first prose paragraph in a narrative prologue. It is long enough
    to look like body text rather than a short front-matter note, and it should use
    the same paragraph flow rules as a chapter opening after the epigraph.</p>
    <p>This is the second prose paragraph in that same prologue. It should continue
    the same context as body text and should not be classified as front matter.</p>
  </body>
</html>
""",
        )


def _write_prologue_letter_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-prologue-letter</dc:identifier>
    <dc:title>Prologue Letter Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="prologue" href="OEBPS/prologue.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="prologue"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/prologue.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Prologue Letter Test</title></head>
  <body>
    <div class="chapter1">
      <p class="cn">Prologue</p>
      <div class="letter">
        <p class="ltg">My dear correspondent,</p>
        <p class="ltf">This is the first line of the letter and should remain inset.</p>
        <p class="lt">This is the following line of the letter and should be compact.</p>
      </div>
      <div class="epigraph">
        <p class="ept">Missive from A to B</p>
      </div>
      <p class="pf">This is the first narrative paragraph after the letter.</p>
      <p class="calibre4">This is the second narrative paragraph after the letter.</p>
    </div>
  </body>
</html>
""",
        )


def _write_narrative_introduction_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-introduction</dc:identifier>
    <dc:title>Introduction Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="introduction" href="OEBPS/introduction.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="introduction"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/introduction.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Introduction Test</title></head>
  <body>
    <h1>INTRODUCTION</h1>
    <p>This is the first long introduction paragraph, with enough prose to be
    classified as narrative material rather than compact front matter. It should
    use the same body flow rules as chapters.</p>
    <p>This is the second long introduction paragraph, also prose-heavy enough
    to prove that this document is not a short title, credit, or metadata page.
    It should continue the introduction body flow.</p>
  </body>
</html>
""",
        )


def _write_metadata_page_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-metadata</dc:identifier>
    <dc:title>Metadata Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="info" href="OEBPS/info.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="info"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/info.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Metadata Test</title></head>
  <body>
    <p>Original title: <cite>Example</cite></p>
    <p>Digital editor: Example Editor</p>
    <p>ePub base r2.1</p>
  </body>
</html>
""",
        )


def _write_metadata_like_chapter_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-metadata-like-chapter</dc:identifier>
    <dc:title>Metadata-like Chapter Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="OEBPS/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/chapter.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Metadata-like Chapter Test</title></head>
  <body>
    <h1 style="text-align: right;">Cities &amp; The Sky 2</h1>
    <p>This belief is handed down in Beersheba: that, suspended in the heavens,
    there exists another Beersheba, where the city’s most elevated virtues and
    sentiments are poised, and that the earthly city takes its shape from those
    ideals.</p>
    <p>They also believe, these inhabitants, that another Beersheba exists
    underground, the receptacle of everything base and unworthy that happens to
    them, and it is their constant care to erase every version of that city from
    their minds.</p>
    <p>Intent on piling up its carats of perfection, Beersheba takes for virtue
    what is now a grim mania to fill the empty vessel of itself.</p>
  </body>
</html>
""",
        )


def _write_semantic_heading_roles_epub(path: Path) -> None:
    docs = {
        "OEBPS/toc.xhtml": '<h1 class="eo-centered">Contents</h1><p>Chapter One</p>',
        "OEBPS/ack.xhtml": '<h1 class="eo-metadata-title">Acknowledgements</h1><p>Thanks.</p>',
        "OEBPS/info.xhtml": (
            '<h1 class="eo-metadata-title">Edition Information</h1>'
            '<p>Original title: Example</p><p>ePub base r2.1</p>'
        ),
        "OEBPS/image-title.xhtml": '<h1 class="eo-image">Illustrated Title</h1><p>Caption.</p>',
        "OEBPS/chapter.xhtml": (
            '<h1 class="eo-right">Chapter One</h1>'
            '<p>First narrative paragraph.</p><p>Second narrative paragraph.</p>'
        ),
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-semantic-heading-roles</dc:identifier>
    <dc:title>Semantic Heading Roles Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="css" href="Styles/epub-optimizer.css" media-type="text/css"/>
    <item id="toc" href="OEBPS/toc.xhtml" media-type="application/xhtml+xml"/>
    <item id="ack" href="OEBPS/ack.xhtml" media-type="application/xhtml+xml"/>
    <item id="info" href="OEBPS/info.xhtml" media-type="application/xhtml+xml"/>
    <item id="image-title" href="OEBPS/image-title.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter" href="OEBPS/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="toc"/>
    <itemref idref="ack"/>
    <itemref idref="info"/>
    <itemref idref="image-title"/>
    <itemref idref="chapter"/>
  </spine>
</package>
""",
        )
        archive.writestr("Styles/epub-optimizer.css", "body { font-family: inherit; }")
        for name, body in docs.items():
            archive.writestr(
                name,
                f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>Semantic Heading Roles Test</title>
    <link href="../Styles/epub-optimizer.css" rel="stylesheet" type="text/css"/>
  </head>
  <body>{body}</body>
</html>
""",
            )


def _write_swedish_filename_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-swedish</dc:identifier>
    <dc:title>Svenskt test</dc:title>
    <dc:language>sv</dc:language>
  </metadata>
  <manifest>
    <item id="id1"
          href="Man_som_hatar_kvinnor_split_1.html"
          media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="id1"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "Man_som_hatar_kvinnor_split_1.html",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Svenskt test</title></head>
  <body>
    <p>Första stycket i kapitlet.</p>
    <p>Andra stycket i samma sammanhang.</p>
  </body>
</html>
""",
        )


def _write_structure_cleanup_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr(
            "content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="id" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:test-structure</dc:identifier>
    <dc:title>Structure Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="part001" href="OEBPS/part001.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="part001"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "OEBPS/part001.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Structure Test</title></head>
  <body>
    <p><img alt="image.missing" src="missing.jpg"/></p>
    <p/>
    <div/>
    <p>PART ONE</p>
  </body>
</html>
""",
        )
        archive.writestr(
            "toc.ncx",
            """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head/>
  <docTitle><text>Structure Test</text></docTitle>
  <navMap>
    <navPoint id="nav1" playOrder="9">
      <navLabel><text>  Part One  </text></navLabel>
      <content src="OEBPS/part001.xhtml"/>
    </navPoint>
    <navPoint id="nav2" playOrder="10">
      <navLabel><text>Missing</text></navLabel>
      <content src="OEBPS/missing.xhtml"/>
    </navPoint>
    <navPoint id="nav3" playOrder="11">
      <navLabel><text>Unsafe</text></navLabel>
      <content src="javascript:alert(1)"/>
    </navPoint>
  </navMap>
</ncx>
""",
        )
