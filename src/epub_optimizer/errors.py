from __future__ import annotations

from dataclasses import asdict, dataclass


class EpubOptimizerError(Exception):
    """Base exception for expected optimizer failures."""


class InvalidEpubError(EpubOptimizerError):
    """Raised when an input file is not a usable EPUB."""


@dataclass(frozen=True, slots=True)
class FailureDiagnostic:
    stage: str
    message: str
    exception_type: str
    detail: str
    internal_path: str | None = None
    failed_path: str | None = None
    report_path: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def failure_diagnostic(
    exc: BaseException,
    *,
    stage: str,
    message: str | None = None,
    internal_path: str | None = None,
    failed_path: str | None = None,
    report_path: str | None = None,
) -> FailureDiagnostic:
    return FailureDiagnostic(
        stage=stage,
        message=message or _friendly_message(exc),
        exception_type=type(exc).__name__,
        detail=f"{type(exc).__name__}: {exc}",
        internal_path=internal_path,
        failed_path=failed_path,
        report_path=report_path,
    )


def _friendly_message(exc: BaseException) -> str:
    if isinstance(exc, InvalidEpubError):
        return str(exc)
    if isinstance(exc, EpubOptimizerError):
        return str(exc)
    return "Optimization failed unexpectedly."
