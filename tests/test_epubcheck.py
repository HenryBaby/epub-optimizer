from epub_optimizer.epubcheck import EpubCheckFinding, EpubCheckResult, compare_epubcheck


def test_compare_ignores_line_and_column_and_normalizes_message():
    before = EpubCheckResult(
        True, "ok", [EpubCheckFinding("error", "RSC-005", "bad   link", "OPS/a.xhtml", 1, 2)]
    )
    after = EpubCheckResult(
        True, "ok", [EpubCheckFinding("error", "RSC-005", "bad link", "OPS/a.xhtml", 9, 8)]
    )
    comparison = compare_epubcheck(before, after)
    assert len(comparison.persisting) == 1
    assert not comparison.introduced


def test_unavailable_runner_status(tmp_path, monkeypatch):
    from epub_optimizer.epubcheck import EpubCheckRunner

    monkeypatch.delenv("EPUBCHECK_EXECUTABLE", raising=False)
    monkeypatch.delenv("EPUBCHECK_JAR", raising=False)
    result = EpubCheckRunner().check(tmp_path / "book.epub")
    assert result.available is False
    assert result.status == "unavailable"


def test_json_command_uses_epub_input_then_stdout(tmp_path):
    from epub_optimizer.epubcheck import EpubCheckRunner

    runner = EpubCheckRunner(executable="epubcheck")
    assert runner._command(tmp_path / "book.epub") == [
        "epubcheck", str(tmp_path / "book.epub"), "--json", "-"
    ]


def test_nested_locations_expand_findings(monkeypatch, tmp_path):
    import subprocess

    from epub_optimizer.epubcheck import EpubCheckRunner

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1,
            stdout=(
                '{"messages":[{"ID":"RSC-005","message":"bad link",'
                '"locations":[{"path":"a.xhtml","line":2,"column":3},'
                '{"path":"b.xhtml"}]}]}'
            ),
            stderr="",
        ),
    )
    result = EpubCheckRunner(executable="python").check(tmp_path / "book.epub")
    assert len(result.findings) == 2
    assert {f.path for f in result.findings} == {"a.xhtml", "b.xhtml"}


def test_additional_locations_count_as_occurrences(monkeypatch, tmp_path):
    import subprocess

    from epub_optimizer.epubcheck import EpubCheckRunner

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1,
            stdout='{"messages":[{"ID":"X","severity":"ERROR","message":"m","locations":[{"path":"a"}],"additionalLocations":2}]}',
            stderr="",
        ),
    )
    result = EpubCheckRunner(executable="python").check(tmp_path / "book.epub")
    assert result.occurrence_count == 3
    assert result.error_count == 3
    assert len(result.findings) == 3
    assert [finding.path for finding in result.findings] == ["a", None, None]


def test_compare_tracks_opaque_additional_location_growth_and_shrink():
    concrete = EpubCheckFinding("error", "RSC-005", "same error", "OPS/a.xhtml")
    opaque = EpubCheckFinding("error", "RSC-005", "same error")
    before = EpubCheckResult(True, "ok", [concrete, opaque, opaque], error_count=3)
    grown = EpubCheckResult(
        True, "ok", [concrete, opaque, opaque, opaque, opaque], error_count=5
    )

    growth = compare_epubcheck(before, grown)
    shrink = compare_epubcheck(grown, before)

    assert len(growth.persisting) == 3
    assert growth.introduced == [opaque, opaque]
    assert len(shrink.persisting) == 3
    assert shrink.resolved == [opaque, opaque]


def test_compare_detects_growth_in_identical_error_occurrences():
    finding = EpubCheckFinding("error", "RSC-005", "same error", "OPS/a.xhtml")
    before = EpubCheckResult(True, "ok", [finding], error_count=1)
    after = EpubCheckResult(True, "ok", [finding, finding], error_count=2)

    comparison = compare_epubcheck(before, after)

    assert comparison.persisting == [finding]
    assert comparison.introduced == [finding]


def test_compare_treats_fatal_finding_as_blocking():
    before = EpubCheckResult(True, "ok")
    fatal = EpubCheckFinding("fatal", "PKG-001", "Cannot read package", "content.opf")

    comparison = compare_epubcheck(before, EpubCheckResult(True, "ok", [fatal], 1))

    assert comparison.introduced == [fatal]


def test_runner_rejects_unexpected_report_shape(monkeypatch, tmp_path):
    import subprocess

    from epub_optimizer.epubcheck import EpubCheckRunner

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="{}", stderr=""),
    )

    result = EpubCheckRunner(executable="python").check(tmp_path / "book.epub")

    assert result.available is False
    assert result.status == "error"


def test_runner_rejects_unexpected_return_code(monkeypatch, tmp_path):
    import subprocess

    from epub_optimizer.epubcheck import EpubCheckRunner

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 2, stdout='{"messages":[]}', stderr="failure"
        ),
    )

    result = EpubCheckRunner(executable="python").check(tmp_path / "book.epub")

    assert result.available is False
    assert result.status == "error"
