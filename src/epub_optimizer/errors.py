class EpubOptimizerError(Exception):
    """Base exception for expected optimizer failures."""


class InvalidEpubError(EpubOptimizerError):
    """Raised when an input file is not a usable EPUB."""
