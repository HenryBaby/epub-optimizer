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
