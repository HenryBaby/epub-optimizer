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
    assert "font-family: inherit" in css

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
    assert '<p class="eo-scene-break"/>' in chapter or '<p class="eo-scene-break"></p>' in chapter


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
    <item id="contents" href="OEBPS/contents.xhtml" media-type="application/xhtml+xml"/>
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
