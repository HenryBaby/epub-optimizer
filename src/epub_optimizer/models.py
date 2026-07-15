from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class OptimizationResult:
    input_filename: str
    output_path: Path
    output_filename: str
    epub_version: str | None
    package_path: str
    elapsed_seconds: float
    content_documents_processed: int
    stylesheets_replaced: int
    images_preserved: int
    warnings: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OptimizationPreview:
    input_filename: str
    epub_version: str | None
    package_path: str
    content_documents: int
    stylesheets_and_fonts: int
    removable_files: int
    images_preserved: int
    would_write_canonical_css: bool
    warnings: list[str] = field(default_factory=list)
