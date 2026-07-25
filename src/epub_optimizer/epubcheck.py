"""Subprocess adapter for the official EPUBCheck CLI."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EpubCheckFinding:
    severity: str
    code: str
    message: str
    path: str | None = None
    line: int | None = None
    column: int | None = None

    @property
    def fingerprint(self) -> tuple[str, str, str]:
        return (self.code, " ".join(self.message.split()), self.path or "")


@dataclass(frozen=True)
class EpubCheckResult:
    available: bool
    status: str
    findings: list[EpubCheckFinding] = field(default_factory=list)
    returncode: int | None = None
    message: str | None = None
    occurrence_count: int = 0
    error_count: int = 0

    @property
    def errors(self) -> list[EpubCheckFinding]:
        return [f for f in self.findings if f.severity.lower() in {"error", "fatal"}]


@dataclass(frozen=True)
class EpubCheckComparison:
    input: EpubCheckResult
    output: EpubCheckResult
    persisting: list[EpubCheckFinding] = field(default_factory=list)
    resolved: list[EpubCheckFinding] = field(default_factory=list)
    introduced: list[EpubCheckFinding] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.input.available and self.output.available


class EpubCheckRunner:
    def __init__(
        self,
        executable: str | None = None,
        jar: str | Path | None = None,
        java: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.executable = executable or os.getenv("EPUBCHECK_EXECUTABLE")
        self.jar = (
            Path(jar or os.getenv("EPUBCHECK_JAR", ""))
            if (jar or os.getenv("EPUBCHECK_JAR"))
            else None
        )
        self.java = java or os.getenv("JAVA", "java")
        default_timeout = timeout if math.isfinite(timeout) and timeout > 0 else 120.0
        try:
            self.timeout = float(os.getenv("EPUBCHECK_TIMEOUT", default_timeout))
            if not math.isfinite(self.timeout) or self.timeout <= 0:
                self.timeout = default_timeout
        except (TypeError, ValueError):
            self.timeout = default_timeout

    def _command(self, epub: Path) -> list[str] | None:
        if self.executable:
            exe = shutil.which(self.executable) or self.executable
            if (
                not Path(exe).exists()
                and shutil.which(self.executable) is None
                and Path(self.executable).parent != Path(".")
            ):
                return None
            return [exe, str(epub), "--json", "-"]
        if self.jar and self.jar.is_file() and shutil.which(self.java):
            return [self.java, "-jar", str(self.jar), str(epub), "--json", "-"]
        return None

    def check(self, epub: Path) -> EpubCheckResult:
        command = self._command(epub)
        if command is None:
            return EpubCheckResult(
                False, "unavailable", message="EPUBCheck executable/JAR is unavailable."
            )
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            status = "timeout" if isinstance(exc, subprocess.TimeoutExpired) else "unavailable"
            return EpubCheckResult(False, status, message=str(exc))
        try:
            payload = json.loads(completed.stdout or completed.stderr or "{}")
        except json.JSONDecodeError:
            return EpubCheckResult(
                False,
                "error",
                returncode=completed.returncode,
                message="EPUBCheck returned invalid JSON.",
            )
        if completed.returncode not in {0, 1}:
            return EpubCheckResult(
                False,
                "error",
                returncode=completed.returncode,
                message="EPUBCheck failed to complete validation.",
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
            return EpubCheckResult(
                False,
                "error",
                returncode=completed.returncode,
                message="EPUBCheck returned an unexpected JSON report.",
            )
        raw = payload["messages"]
        findings = []
        occurrence_count = 0
        error_count = 0
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            raw_locations = item.get("locations")
            locations = raw_locations if isinstance(raw_locations, list) else [item]
            locations = [location for location in locations if isinstance(location, dict)]
            additional = item.get("additionalLocations", 0)
            additional_count = additional if isinstance(additional, int) else 0
            item_occurrences = len(locations) + max(additional_count, 0)
            occurrence_count += item_occurrences
            severity = str(item.get("severity", item.get("type", "error"))).lower()
            if severity in {"error", "fatal"}:
                error_count += item_occurrences
            for location in locations:
                findings.append(
                    EpubCheckFinding(
                        severity=severity,
                        code=str(item.get("ID", item.get("code", item.get("id", "unknown")))),
                        message=str(item.get("message", "")),
                        path=location.get("path") or location.get("file"),
                        line=location.get("line"),
                        column=location.get("column"),
                    )
                )
            if additional_count > 0 and locations:
                location = locations[0]
                findings.extend(
                    EpubCheckFinding(
                        severity=severity,
                        code=str(item.get("ID", item.get("code", item.get("id", "unknown")))),
                        message=str(item.get("message", "")),
                        path=location.get("path") or location.get("file"),
                        line=location.get("line"),
                        column=location.get("column"),
                    )
                    for _ in range(additional_count)
                )
        return EpubCheckResult(
            True,
            "ok",
            findings,
            completed.returncode,
            None,
            occurrence_count,
            error_count,
        )


def compare_epubcheck(
    input_result: EpubCheckResult, output_result: EpubCheckResult
) -> EpubCheckComparison:
    before: dict[tuple[str, str, str], list[EpubCheckFinding]] = defaultdict(list)
    after: dict[tuple[str, str, str], list[EpubCheckFinding]] = defaultdict(list)
    for finding in input_result.errors:
        before[finding.fingerprint].append(finding)
    for finding in output_result.errors:
        after[finding.fingerprint].append(finding)
    persisting = []
    resolved = []
    introduced = []
    for fingerprint in before.keys() | after.keys():
        before_findings = before[fingerprint]
        after_findings = after[fingerprint]
        common = min(len(before_findings), len(after_findings))
        persisting.extend(after_findings[:common])
        resolved.extend(before_findings[common:])
        introduced.extend(after_findings[common:])
    return EpubCheckComparison(
        input_result,
        output_result,
        persisting=persisting,
        resolved=resolved,
        introduced=introduced,
    )
