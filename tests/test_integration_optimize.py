import zipfile
from pathlib import Path

from epub_optimizer.core import optimize_epub


def test_optimize_minimal_epub(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    output_dir = tmp_path / "out"
    _write_minimal_epub(source)

    result = optimize_epub(source, output_dir)

    assert result.content_documents_processed == 1
    assert result.stylesheets_replaced == 1
    assert result.output_path.is_file()

    with zipfile.ZipFile(result.output_path) as archive:
        assert archive.namelist()[0] == "mimetype"
        assert archive.read("mimetype") == b"application/epub+zip"
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        chapter = archive.read("OEBPS/Text/chapter.xhtml").decode("utf-8")
        css = archive.read("OEBPS/Styles/epub-optimizer.css").decode("utf-8")

    assert "epub-optimizer.css" in opf
    assert "old.css" not in opf
    assert "../Styles/epub-optimizer.css" in chapter
    assert 'class="eo-chapter"' in chapter
    assert 'class="eo-first"' in chapter
    assert 'class="eo-body"' in chapter
    assert "font-family: inherit" in css


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
    <p class="nonindent">First paragraph with <em>emphasis</em>.</p>
    <p class="indent">Second paragraph.</p>
  </body>
</html>
""",
        )
