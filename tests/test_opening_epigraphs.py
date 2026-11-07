"""Opening quotations must keep their paragraph boundaries and narrative flow."""

import pytest
from lxml import etree

from epub_optimizer.core import XHTML_NS, _classify_blocks, _opening_epigraph_paragraphs


def _document(body: str) -> etree._Element:
    return etree.fromstring(f'<html xmlns="{XHTML_NS}"><body>{body}</body></html>')


def _roles(root: etree._Element) -> list[str | None]:
    return [element.get("class") for element in root.xpath("//*[local-name()='p']")]


@pytest.mark.parametrize("wrapped", [False, True])
def test_multiple_quote_paragraphs_with_short_interior_line(wrapped: bool) -> None:
    quote = (
        '<p id="quote"><em>A quotation begins with a substantial opening sentence.</em></p>'
        '<p id="short"><i>Remember.</i></p>'
        '<p><em>A final quoted paragraph completes the thought.</em></p>'
        '<p><b>—Collected Correspondence</b></p>'
    )
    if wrapped:
        quote = f'<div id="quotation">{quote}</div>'
    root = _document(
        f'<h1>Chapter</h1>{quote}<p><i>I have arrived.</i></p>'
        '<p>The next paragraph continues the story.</p>'
    )
    before_text = list(root.itertext())
    before_structure = [(element.tag, element.get("id")) for element in root.iter()]

    _classify_blocks(root, "body")

    assert _roles(root) == ["eo-extract"] * 4 + ["eo-first", "eo-body"]
    assert list(root.itertext()) == before_text
    assert [(element.tag, element.get("id")) for element in root.iter()] == before_structure
    first_pass = etree.tostring(root)
    _classify_blocks(root, "body")
    assert etree.tostring(root) == first_pass


def test_stale_optimizer_roles_are_repaired_as_a_complete_group() -> None:
    root = _document(
        '<h1 class="eo-chapter">Chapter</h1><div>'
        '<p class="eo-extract"><i>An opening quotation.</i></p>'
        '<p class="eo-first"><i>A short line.</i></p>'
        '<p class="eo-body"><i>The quotation continues in another paragraph.</i></p>'
        '<p class="eo-right"><b>—An Anonymous Archive</b></p></div>'
        '<p class="eo-body">The first narrative paragraph.</p>'
        '<p class="eo-body">The story continues.</p>'
    )

    _classify_blocks(root, "body")

    assert _roles(root) == ["eo-extract"] * 4 + ["eo-first", "eo-body"]
    first_pass = etree.tostring(root)
    _classify_blocks(root, "body")
    assert etree.tostring(root) == first_pass


@pytest.mark.parametrize("narrative", ["I have arrived.", "A longer italic narrative opening."])
def test_italic_narrative_outside_confirmed_wrapper_stays_prose(narrative: str) -> None:
    root = _document(
        '<h1 class="eo-chapter">Chapter</h1><div>'
        '<p class="eo-extract"><i>A remembered sentence from an earlier era.</i></p>'
        '<p class="eo-extract"><b>Collected Sayings</b></p></div>'
        f'<p class="eo-first"><i>{narrative}</i></p>'
        '<p>The story moves forward.</p>'
        '<p><i>Later emphasis should also remain narrative prose.</i></p>'
    )

    _classify_blocks(root, "body")

    assert _roles(root) == ["eo-extract", "eo-extract", "eo-first", "eo-body", "eo-body"]


def test_unattributed_italic_run_is_ambiguous_narrative() -> None:
    root = _document(
        '<h1>Chapter</h1><p><i>The first italic narrative paragraph begins here.</i></p>'
        '<p><i>The second italic narrative paragraph follows immediately.</i></p>'
        '<p>The narrative continues without an attribution.</p>'
    )

    _classify_blocks(root, "body")

    assert _roles(root) == ["eo-first", "eo-body", "eo-body"]


@pytest.mark.parametrize(
    "body",
    [
        '<h1>Chapter</h1><div><p><i>One.</i></p><p><i>Two.</i></p></div>'
        '<p><b>—Outside the wrapper</b></p>',
        '<h1>Chapter</h1><p><i>One.</i></p><p>* * *</p><p><b>—Archive</b></p>',
        '<h1>Chapter</h1><p><i>One.</i></p><h2>Section</h2><p><b>—Archive</b></p>',
        '<h1>Chapter</h1><p>The narrative has already begun.</p>'
        '<p><i>A later emphasized paragraph.</i></p><p><b>—Archive</b></p>',
        '<h1>Chapter</h1><div class="letter"><p class="ltg"><i>Dear friend,</i></p>'
        '<p class="lt"><i>A letter continues.</i></p><p><b>—Writer</b></p></div>',
        '<h1>Chapter</h1><p class="poetry"><i>A verse line.</i></p>'
        '<p><b>—Poet</b></p>',
    ],
)
def test_attribution_cannot_cross_structural_or_semantic_barriers(body: str) -> None:
    assert not _opening_epigraph_paragraphs(_document(body), "body")


@pytest.mark.parametrize(
    "paragraphs",
    [
        ["Short line."] * 9,
        ["x" * 901, "Short line."],
        ["x" * 800] * 5,
    ],
)
def test_quote_scan_has_paragraph_and_character_bounds(paragraphs: list[str]) -> None:
    quote = "".join(f'<p><i>{text}</i></p>' for text in paragraphs)
    root = _document(f'<h1>Chapter</h1>{quote}<p><b>—Archive</b></p>')

    assert not _opening_epigraph_paragraphs(root, "body")


def test_single_unattributed_opening_retains_existing_prologue_behavior() -> None:
    root = _document(
        '<h1>PROLOGUE</h1><p><i>Excerpt from an archival speech:</i></p>'
        '<p>The narrative begins in this paragraph.</p>'
    )

    _classify_blocks(root, "body")

    assert _roles(root) == ["eo-extract", "eo-first"]
