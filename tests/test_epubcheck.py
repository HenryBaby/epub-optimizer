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


def test_compare_treats_opaque_growth_as_advisory_and_tracks_shrink():
    concrete = EpubCheckFinding("error", "RSC-005", "same error", "OPS/a.xhtml")
    opaque = EpubCheckFinding("error", "RSC-005", "same error")
    before = EpubCheckResult(True, "ok", [concrete, opaque, opaque], error_count=3)
    grown = EpubCheckResult(
        True, "ok", [concrete, opaque, opaque, opaque, opaque], error_count=5
    )

    growth = compare_epubcheck(before, grown)
    shrink = compare_epubcheck(grown, before)

    assert len(growth.persisting) == 5
    assert growth.introduced == []
    assert len(shrink.persisting) == 3
    assert shrink.resolved == [opaque, opaque]


def test_compare_matches_opaque_and_concrete_occurrences_of_same_error():
    path_a = EpubCheckFinding("error", "RSC-005", "same error", "OPS/a.xhtml")
    path_b = EpubCheckFinding("error", "RSC-005", "same error", "OPS/b.xhtml")
    opaque = EpubCheckFinding("error", "RSC-005", "same error")

    comparison = compare_epubcheck(
        EpubCheckResult(True, "ok", [path_a, path_b]),
        EpubCheckResult(True, "ok", [path_a, opaque]),
    )

    assert len(comparison.persisting) == 2
    assert comparison.resolved == []
    assert comparison.introduced == []


def test_compare_does_not_match_different_concrete_paths_or_diagnostics():
    before = EpubCheckFinding("error", "RSC-005", "same error", "OPS/a.xhtml")
    moved = EpubCheckFinding("error", "RSC-005", "same error", "OPS/b.xhtml")
    different = EpubCheckFinding("error", "RSC-006", "same error")

    comparison = compare_epubcheck(
        EpubCheckResult(True, "ok", [before]),
        EpubCheckResult(True, "ok", [moved, different]),
    )

    assert comparison.persisting == []
    assert comparison.resolved == [before]
    assert set(comparison.introduced) == {moved, different}


def test_compare_treats_growth_at_existing_resource_as_advisory():
    finding = EpubCheckFinding("error", "RSC-005", "same error", "OPS/a.xhtml")
    before = EpubCheckResult(True, "ok", [finding], error_count=1)
    after = EpubCheckResult(True, "ok", [finding, finding], error_count=2)

    comparison = compare_epubcheck(before, after)

    assert comparison.persisting == [finding, finding]
    assert comparison.introduced == []


def test_compare_detects_growth_at_new_concrete_resource():
    existing = EpubCheckFinding("error", "RSC-005", "same error", "OPS/a.xhtml")
    introduced = EpubCheckFinding("error", "RSC-005", "same error", "OPS/b.xhtml")

    comparison = compare_epubcheck(
        EpubCheckResult(True, "ok", [existing]),
        EpubCheckResult(True, "ok", [existing, introduced]),
    )

    assert comparison.persisting == [existing]
    assert comparison.introduced == [introduced]


def test_compare_detects_opaque_growth_without_opaque_baseline():
    existing = EpubCheckFinding("error", "RSC-005", "same error", "OPS/a.xhtml")
    opaque = EpubCheckFinding("error", "RSC-005", "same error")

    comparison = compare_epubcheck(
        EpubCheckResult(True, "ok", [existing]),
        EpubCheckResult(True, "ok", [existing, opaque]),
    )

    assert comparison.persisting == [existing]
    assert comparison.introduced == [opaque]


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
