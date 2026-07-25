import zipfile

import pytest

from epub_optimizer.epub import extract_epub, validate_archive_entry_name
from epub_optimizer.errors import InvalidEpubError


@pytest.mark.parametrize(
    "name",
    [
        "mimetype",
        "META-INF/container.xml",
        "OEBPS/Text/chapter.xhtml",
    ],
)
def test_validate_archive_entry_name_accepts_safe_paths(name: str) -> None:
    assert str(validate_archive_entry_name(name)) == name


@pytest.mark.parametrize(
    "name",
    [
        "../outside.txt",
        "OEBPS/../outside.txt",
        "/absolute/path.txt",
        "C:/absolute/path.txt",
        "OEBPS\\..\\outside.txt",
    ],
)
def test_validate_archive_entry_name_rejects_unsafe_paths(name: str) -> None:
    with pytest.raises(InvalidEpubError):
        validate_archive_entry_name(name)


def test_extract_epub_collapses_case_and_unicode_equivalent_entries(tmp_path) -> None:
    source = tmp_path / "duplicates.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Book/Styles/epub-optimizer.css", "old")
        archive.writestr("Book/styles/epub-optimizer.css", "canonical")
        archive.writestr("Book/Text/Cafe\u0301.xhtml", "first")
        archive.writestr("Book/Text/Caf\u00e9.xhtml", "second")

    output = tmp_path / "output"
    extract_epub(source, output)

    files = sorted(
        path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()
    )
    assert files == ["Book/Styles/epub-optimizer.css", "Book/Text/Cafe\u0301.xhtml"]
    assert (output / "Book/Styles/epub-optimizer.css").read_text() == "canonical"
    assert (output / "Book/Text/Cafe\u0301.xhtml").read_text() == "second"
