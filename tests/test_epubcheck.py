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
    assert len(result.findings) == 1


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
