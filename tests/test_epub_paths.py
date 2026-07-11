import pytest

from epub_optimizer.epub import validate_archive_entry_name
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
