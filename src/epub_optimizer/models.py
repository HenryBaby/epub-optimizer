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
    image_diagnostics: list[str] = field(default_factory=list)
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
    image_diagnostics: list[str] = field(default_factory=list)
    change_summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    input_filename: str
    valid: bool
    epub_version: str | None
    package_path: str | None
    issues: list[ValidationIssue] = field(default_factory=list)
