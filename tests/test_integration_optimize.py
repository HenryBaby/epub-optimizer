import zipfile
from pathlib import Path

from epub_optimizer.core import optimize_epub


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
    assert "old.css" not in opf
    assert "publisher.woff2" not in opf
    assert "page-template.xpgt" not in opf
    assert "../Styles/epub-optimizer.css" in chapter
    assert 'class="eo-chapter"' in chapter
    assert 'class="eo-first"' in chapter
    assert 'class="eo-body"' in chapter
    assert 'style="' not in chapter
    assert 'class="publisher"' not in chapter
    normalized_css = css.replace("\r\n", "\n")
    assert "font-family: inherit" in normalized_css
    assert "p {\n  margin: 0 0 0.75em;" in normalized_css
    assert "p.eo-body {\n  text-indent: 0;" in normalized_css
    assert "p.eo-first {\n  text-indent: 1em;" in normalized_css

    second_result = optimize_epub(result.output_path, tmp_path / "out-second")
    with zipfile.ZipFile(second_result.output_path) as archive:
        assert "OEBPS/Styles/epub-optimizer.css" in archive.namelist()
        second_opf = archive.read("OEBPS/content.opf").decode("utf-8")

    assert second_opf.count("epub-optimizer.css") == 1


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
    <h1 class="chapter">Chapter One</h1>
    <p class="nonindent" style="margin: 2em;">First paragraph with <em>emphasis</em>.</p>
    <p class="indent"><span class="publisher">Second</span> paragraph.</p>
  </body>
</html>
""",
        )


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
