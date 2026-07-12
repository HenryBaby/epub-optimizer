import re
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

from epub_optimizer.web import app


def test_homepage_renders() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "EPUB Optimizer" in response.text
    assert "v0.1.14" in response.text


def test_download_link_handles_url_significant_filename_chars(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EPUB_OPTIMIZER_OUTPUT_DIR", str(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/optimize",
        files={
            "file": (
                "Book #01.epub",
                _minimal_epub_bytes(),
                "application/epub+zip",
            )
        },
    )

    assert response.status_code == 200
    match = re.search(r'href="(/download/[^"]+)"', response.text)
    assert match is not None
    assert "%23" in match.group(1)

    download = client.get(match.group(1))

    assert download.status_code == 200
    assert download.headers["content-type"] == "application/epub+zip"


def _minimal_epub_bytes() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
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
    <dc:identifier id="id">urn:test</dc:identifier>
    <dc:title>Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter"/>
  </spine>
</package>
""",
        )
        archive.writestr(
            "chapter.xhtml",
            """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Test</title></head>
  <body><h1>Chapter One</h1><p>Body.</p></body>
</html>
""",
        )
    return output.getvalue()
