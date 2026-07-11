from epub_optimizer.core import optimized_filename


def test_optimized_filename_appends_suffix_before_extension() -> None:
    assert optimized_filename("Example Book.epub") == "Example Book-optimized.epub"


def test_optimized_filename_normalizes_missing_extension() -> None:
    assert optimized_filename("Example Book") == "Example Book-optimized.epub"
