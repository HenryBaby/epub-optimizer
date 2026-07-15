from __future__ import annotations

import posixpath
import re
import tempfile
import time
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from lxml import etree

from epub_optimizer.epub import (
    extract_epub,
    find_package_document,
    make_relative_href,
    validate_epub_archive,
    write_epub,
)
from epub_optimizer.errors import InvalidEpubError
from epub_optimizer.models import (
    OptimizationPreview,
    OptimizationResult,
    ValidationIssue,
    ValidationReport,
)
from epub_optimizer.style import CANONICAL_CSS

OPF_NS = "http://www.idpf.org/2007/opf"
XHTML_NS = "http://www.w3.org/1999/xhtml"
DANGEROUS_URI_SCHEMES = {"javascript", "data", "vbscript", "file"}
CANONICAL_CSS_ID = "epub-optimizer-css"
CANONICAL_CSS_HREF = "Styles/epub-optimizer.css"
OPTIMIZER_META_NAME = "epub-optimizer:version"
REMOVABLE_MEDIA_TYPES = {
    "application/font-woff",
    "application/font-woff2",
    "application/vnd.adobe-page-template+xml",
    "application/vnd.ms-opentype",
    "application/x-font-opentype",
    "application/x-font-otf",
    "application/x-font-ttf",
    "application/x-font-truetype",
    "application/x-font-woff",
    "font/otf",
    "font/sfnt",
    "font/ttf",
    "font/woff",
    "font/woff2",
}
REMOVABLE_SUFFIXES = {".css", ".xpgt", ".otf", ".ttf", ".woff", ".woff2"}
PRESENTATION_ATTRS = {
    "align",
    "alink",
    "background",
    "bgcolor",
    "border",
    "cellpadding",
    "cellspacing",
    "clear",
    "color",
    "face",
    "height",
    "hspace",
    "link",
    "marginheight",
    "marginwidth",
    "size",
    "style",
    "text",
    "valign",
    "vlink",
    "vspace",
    "width",
}
FRONT_MATTER_HINTS = {
    "ack",
    "acknowledg",
    "afterword",
    "alsoby",
    "appendix",
    "ata",
    "author",
    "authorsnote",
    "bibliography",
    "colophon",
    "contents",
    "cop",
    "copyright",
    "ded",
    "dedication",
    "epigraph",
    "foreword",
    "glossary",
    "intro",
    "introduction",
    "notes",
    "preface",
    "prologue",
    "source",
    "toc",
    "title",
}
EO_BLOCK_ROLES = {
    "eo-blockquote",
    "eo-body",
    "eo-caption",
    "eo-centered",
    "eo-chapter",
    "eo-dedication",
    "eo-extract",
    "eo-first",
    "eo-footnote",
    "eo-front",
    "eo-front-body",
    "eo-front-list-item",
    "eo-front-section",
    "eo-hanging",
    "eo-image",
    "eo-letter",
    "eo-letter-attribution",
    "eo-letter-body",
    "eo-letter-first",
    "eo-letter-opener",
    "eo-list",
    "eo-metadata-line",
    "eo-metadata-page",
    "eo-metadata-title",
    "eo-part",
    "eo-poetry",
    "eo-right",
    "eo-scene-break",
    "eo-section",
    "eo-title-author",
    "eo-title-credit",
    "eo-title-credit-label",
    "eo-title-main",
    "eo-title-page",
    "eo-title-publisher",
    "eo-toc",
    "eo-toc-chapter",
    "eo-toc-entry",
    "eo-toc-heading",
    "eo-toc-part",
}
EO_INLINE_ROLES = {
    "eo-overline",
    "eo-smallcaps",
    "eo-strike",
    "eo-underline",
}


def optimize_epub(
    input_path: Path,
    output_dir: Path,
    *,
    output_filename: str | None = None,
    max_size_bytes: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> OptimizationResult:
    started = time.perf_counter()
    log: list[str] = []
    warnings: list[str] = []

    input_path = input_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_filename = output_filename or optimized_filename(input_path.name)
    output_path = output_dir / output_filename

    _append_log(log, "Validated EPUB archive.", progress)
    validate_epub_archive(input_path, max_size_bytes=max_size_bytes)

    with tempfile.TemporaryDirectory(prefix="epub-optimizer-") as temp_name:
        work_dir = Path(temp_name)
        extract_epub(input_path, work_dir)
        _append_log(log, "Extracted EPUB into a temporary workspace.", progress)

        package_path = find_package_document(work_dir)
        package_file = work_dir / Path(*PurePosixPath(package_path).parts)
        package_dir = posixpath.dirname(package_path)
        package_dir_path = package_file.parent
        _append_log(log, f"Resolved OPF package document: {package_path}", progress)

        package_tree = _parse_xml(package_file)
        package_root = package_tree.getroot()
        epub_version = package_root.attrib.get("version")

        manifest = _find_child(package_root, "manifest")
        if manifest is None:
            raise InvalidEpubError("OPF package document is missing a manifest.")

        items = _manifest_items(manifest)
        removable_hrefs = _removable_manifest_hrefs(items)
        stylesheet_class_roles = _stylesheet_class_roles(work_dir, package_dir, removable_hrefs)
        content_items = [
            item
            for item in items
            if item.attrib.get("media-type", "").lower()
            in {"application/xhtml+xml", "text/html", "application/x-dtbook+xml"}
            and item.attrib.get("href")
        ]
        image_count = sum(
            1 for item in items if item.attrib.get("media-type", "").lower().startswith("image/")
        )

        canonical_css_package_href = _ensure_canonical_css(work_dir, package_dir_path)
        canonical_item_href = _relative_from_package_dir(package_dir, canonical_css_package_href)
        stylesheets_replaced = _replace_removable_manifest_items(
            manifest,
            removable_hrefs,
            canonical_item_href,
        )
        removed_files = _delete_package_files(work_dir, package_dir, removable_hrefs)
        _append_log(
            log,
            f"Removed {stylesheets_replaced} old style/font manifest item(s).",
            progress,
        )
        if removed_files:
            _append_log(log, f"Deleted {removed_files} old style/font file(s).", progress)

        processed_docs = 0
        for item in content_items:
            href = item.attrib["href"]
            content_package_path = _join_package_path(package_dir, href)
            content_file = work_dir / Path(*PurePosixPath(content_package_path).parts)
            if not content_file.is_file():
                warnings.append(f"Manifest content document is missing: {href}")
                continue
            if _process_content_document(
                content_file,
                content_package_path,
                canonical_css_package_href,
                work_dir,
                _document_role(item),
                stylesheet_class_roles,
            ):
                processed_docs += 1

        normalized_nav = _normalize_navigation_documents(work_dir, package_dir, items)
        if normalized_nav:
            _append_log(log, f"Normalized {normalized_nav} navigation document(s).", progress)

        _append_log(log, f"Processed {processed_docs} content document(s).", progress)
        _ensure_optimizer_marker(package_root)
        _write_xml(package_tree, package_file)
        write_epub(work_dir, output_path)
        _append_log(log, "Repackaged optimized EPUB.", progress)

    elapsed = time.perf_counter() - started
    _append_log(log, f"Finished in {elapsed:.2f} seconds.", progress)

    return OptimizationResult(
        input_filename=input_path.name,
        output_path=output_path,
        output_filename=output_filename,
        epub_version=epub_version,
        package_path=package_path,
        elapsed_seconds=elapsed,
        content_documents_processed=processed_docs,
        stylesheets_replaced=stylesheets_replaced,
        images_preserved=image_count,
        warnings=warnings,
        log=log,
    )


def preview_epub_changes(
    input_path: Path,
    *,
    max_size_bytes: int | None = None,
) -> OptimizationPreview:
    input_path = input_path.resolve()
    validate_epub_archive(input_path, max_size_bytes=max_size_bytes)

    with tempfile.TemporaryDirectory(prefix="epub-optimizer-preview-") as temp_name:
        work_dir = Path(temp_name)
        extract_epub(input_path, work_dir)

        package_path = find_package_document(work_dir)
        package_file = work_dir / Path(*PurePosixPath(package_path).parts)
        package_dir = posixpath.dirname(package_path)
        package_tree = _parse_xml(package_file)
        package_root = package_tree.getroot()
        epub_version = package_root.attrib.get("version")

        manifest = _find_child(package_root, "manifest")
        if manifest is None:
            raise InvalidEpubError("OPF package document is missing a manifest.")

        items = _manifest_items(manifest)
        removable_hrefs = _removable_manifest_hrefs(items)
        content_items = [
            item
            for item in items
            if item.attrib.get("media-type", "").lower()
            in {"application/xhtml+xml", "text/html", "application/x-dtbook+xml"}
            and item.attrib.get("href")
        ]
        image_count = sum(
            1 for item in items if item.attrib.get("media-type", "").lower().startswith("image/")
        )
        warnings = []
        for item in content_items:
            href = item.attrib["href"]
            if not _package_file_exists(work_dir, package_dir, href):
                warnings.append(f"Manifest content document is missing: {href}")

        return OptimizationPreview(
            input_filename=input_path.name,
            epub_version=epub_version,
            package_path=package_path,
            content_documents=len(content_items),
            stylesheets_and_fonts=len(removable_hrefs),
            removable_files=_existing_package_file_count(work_dir, package_dir, removable_hrefs),
            images_preserved=image_count,
            would_write_canonical_css=True,
            warnings=warnings,
        )


def validate_epub_details(
    input_path: Path,
    *,
    max_size_bytes: int | None = None,
) -> ValidationReport:
    input_path = input_path.resolve()
    validate_epub_archive(input_path, max_size_bytes=max_size_bytes)
    issues: list[ValidationIssue] = []

    with tempfile.TemporaryDirectory(prefix="epub-optimizer-validate-") as temp_name:
        work_dir = Path(temp_name)
        extract_epub(input_path, work_dir)

        package_path = find_package_document(work_dir)
        package_file = work_dir / Path(*PurePosixPath(package_path).parts)
        package_dir = posixpath.dirname(package_path)
        package_tree = _parse_xml(package_file)
        package_root = package_tree.getroot()
        epub_version = package_root.attrib.get("version")

        manifest = _find_child(package_root, "manifest")
        if manifest is None:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="missing-manifest",
                    message="OPF package document is missing a manifest.",
                )
            )
            return ValidationReport(
                input_filename=input_path.name,
                valid=False,
                epub_version=epub_version,
                package_path=package_path,
                issues=issues,
            )

        items = _manifest_items(manifest)
        item_ids = {item.attrib.get("id", "") for item in items}
        for item in items:
            href = item.attrib.get("href")
            if href and not _package_file_exists(work_dir, package_dir, href):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="missing-manifest-file",
                        message=f"Manifest file is missing: {href}",
                    )
                )

        spine = _find_child(package_root, "spine")
        if spine is None:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="missing-spine",
                    message="OPF package document is missing a spine.",
                )
            )
        else:
            for itemref in spine:
                if not isinstance(itemref.tag, str) or etree.QName(itemref).localname != "itemref":
                    continue
                idref = itemref.attrib.get("idref", "")
                if idref not in item_ids:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="missing-spine-target",
                            message=f"Spine references missing manifest item: {idref}",
                        )
                    )

        return ValidationReport(
            input_filename=input_path.name,
            valid=not any(issue.severity == "error" for issue in issues),
            epub_version=epub_version,
            package_path=package_path,
            issues=issues,
        )


def _append_log(
    log: list[str],
    message: str,
    progress: Callable[[str], None] | None,
) -> None:
    log.append(message)
    if progress is not None:
        progress(message)


def optimized_filename(filename: str) -> str:
    path = Path(filename)
    stem = path.stem or "optimized"
    if stem.lower().endswith("-optimized"):
        stem = stem[: -len("-optimized")] or "optimized"
    suffix = path.suffix if path.suffix.lower() == ".epub" else ".epub"
    return f"{stem}-optimized{suffix}"


def _parse_xml(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
    try:
        return etree.parse(str(path), parser)
    except etree.XMLSyntaxError as exc:
        raise InvalidEpubError(f"Could not parse XML file: {path.name}") from exc


def _write_xml(tree: etree._ElementTree, path: Path) -> None:
    tree.write(
        str(path),
        encoding="utf-8",
        xml_declaration=True,
        pretty_print=False,
    )


def _find_child(parent: etree._Element, local_name: str) -> etree._Element | None:
    found = parent.find(f"{{{OPF_NS}}}{local_name}")
    if found is not None:
        return found
    return parent.find(local_name)


def _ensure_optimizer_marker(package_root: etree._Element) -> None:
    metadata = _find_child(package_root, "metadata")
    if metadata is None:
        metadata = etree.Element(_qualified_like(package_root, "metadata"))
        package_root.insert(0, metadata)

    for child in metadata:
        if not isinstance(child.tag, str) or etree.QName(child).localname != "meta":
            continue
        if child.attrib.get("name") == OPTIMIZER_META_NAME:
            child.attrib["content"] = _optimizer_version()
            return

    metadata.append(
        etree.Element(
            _qualified_like(metadata, "meta"),
            attrib={"name": OPTIMIZER_META_NAME, "content": _optimizer_version()},
        )
    )


def _qualified_like(element: etree._Element, local_name: str) -> str:
    namespace = etree.QName(element).namespace
    if namespace:
        return f"{{{namespace}}}{local_name}"
    return local_name


def _optimizer_version() -> str:
    try:
        return version("epub-optimizer")
    except PackageNotFoundError:
        return "unknown"


def _manifest_items(manifest: etree._Element) -> list[etree._Element]:
    return [
        child
        for child in manifest
        if isinstance(child.tag, str) and etree.QName(child).localname == "item"
    ]


def _ensure_canonical_css(work_dir: Path, package_dir_path: Path) -> str:
    css_path = package_dir_path / CANONICAL_CSS_HREF
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(CANONICAL_CSS, encoding="utf-8")
    return css_path.relative_to(work_dir).as_posix()


def _relative_from_package_dir(package_dir: str, package_relative_path: str) -> str:
    if not package_dir:
        return package_relative_path
    prefix = package_dir.rstrip("/") + "/"
    if package_relative_path.startswith(prefix):
        return package_relative_path[len(prefix) :]
    return posixpath.relpath(package_relative_path, package_dir)


def _removable_manifest_hrefs(items: list[etree._Element]) -> list[str]:
    hrefs: list[str] = []
    for item in items:
        href = item.attrib.get("href")
        if not href:
            continue
        if item.attrib.get("id") == CANONICAL_CSS_ID or href == CANONICAL_CSS_HREF:
            continue
        media_type = item.attrib.get("media-type", "").lower()
        suffix = PurePosixPath(href).suffix.lower()
        if (
            media_type == "text/css"
            or media_type in REMOVABLE_MEDIA_TYPES
            or suffix in REMOVABLE_SUFFIXES
        ):
            hrefs.append(href)
    return hrefs


def _replace_removable_manifest_items(
    manifest: etree._Element,
    removable_hrefs: list[str],
    canonical_href: str,
) -> int:
    replaced = 0
    canonical_exists = False
    for item in _manifest_items(manifest):
        href = item.attrib.get("href")
        media_type = item.attrib.get("media-type", "").lower()
        suffix = PurePosixPath(href or "").suffix.lower()
        if item.attrib.get("id") == CANONICAL_CSS_ID or href == CANONICAL_CSS_HREF:
            item.attrib["id"] = CANONICAL_CSS_ID
            item.attrib["href"] = canonical_href
            item.attrib["media-type"] = "text/css"
            canonical_exists = True
            continue
        if (
            media_type == "text/css"
            or media_type in REMOVABLE_MEDIA_TYPES
            or suffix in REMOVABLE_SUFFIXES
        ):
            manifest.remove(item)
            replaced += 1

    if not canonical_exists:
        attrib = {"id": CANONICAL_CSS_ID, "href": canonical_href, "media-type": "text/css"}
        manifest.append(etree.Element(f"{{{OPF_NS}}}item", attrib=attrib))
    return max(replaced, len(removable_hrefs))


def _delete_package_files(work_dir: Path, package_dir: str, hrefs: list[str]) -> int:
    deleted = 0
    for href in hrefs:
        package_path = _join_package_path(package_dir, href)
        file_path = work_dir / Path(*PurePosixPath(package_path).parts)
        if file_path.is_file():
            file_path.unlink()
            deleted += 1
    return deleted


def _existing_package_file_count(work_dir: Path, package_dir: str, hrefs: list[str]) -> int:
    count = 0
    for href in hrefs:
        package_path = _join_package_path(package_dir, href)
        file_path = work_dir / Path(*PurePosixPath(package_path).parts)
        if file_path.is_file():
            count += 1
    return count


def _package_file_exists(work_dir: Path, package_dir: str, href: str) -> bool:
    package_path = _join_package_path(package_dir, href)
    file_path = work_dir / Path(*PurePosixPath(package_path).parts)
    return file_path.is_file()


def _stylesheet_class_roles(
    work_dir: Path,
    package_dir: str,
    hrefs: list[str],
) -> dict[str, str]:
    roles: dict[str, str] = {}
    for href in hrefs:
        if not href.lower().split("#", 1)[0].endswith(".css"):
            continue
        package_path = _join_package_path(package_dir, href)
        file_path = work_dir / Path(*PurePosixPath(package_path).parts)
        if not file_path.is_file():
            continue
        css = file_path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", css):
            class_name = match.group(1).lower()
            declarations = match.group(2).lower()
            if re.search(r"text-align\s*:\s*right\b", declarations):
                roles[class_name] = "eo-right"
            elif re.search(r"text-align\s*:\s*center\b", declarations):
                roles[class_name] = "eo-centered"
    return roles


def _join_package_path(package_dir: str, href: str) -> str:
    joined = posixpath.normpath(posixpath.join(package_dir, href))
    if joined.startswith("../") or joined == ".." or joined.startswith("/"):
        raise InvalidEpubError(f"Manifest href escapes the EPUB root: {href}")
    return joined


def _process_content_document(
    content_file: Path,
    content_package_path: str,
    canonical_css_package_href: str,
    work_dir: Path,
    document_role: str,
    stylesheet_class_roles: dict[str, str],
) -> bool:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    tree = etree.parse(str(content_file), parser)
    root = tree.getroot()

    head = _first_xpath(root, "//*[local-name()='head']")
    if head is not None:
        _remove_stylesheet_links(head)
        css_href = make_relative_href(content_package_path, canonical_css_package_href)
        _append_stylesheet_link(head, css_href)

    _sanitize_links(root)
    _apply_presentation_role_hints(root, stylesheet_class_roles)
    _strip_publisher_presentation(root)
    _remove_broken_images(root, content_file, work_dir)
    _unwrap_font_elements(root)
    _normalize_inline_spans(root)
    _collapse_nested_blockquotes(root)
    _remove_empty_blocks(root)
    document_role = _refine_document_role(root, document_role)
    _classify_blocks(root, document_role)
    _strip_unclassified_classes(root)
    _write_xml(tree, content_file)
    return True


def _normalize_navigation_documents(
    work_dir: Path,
    package_dir: str,
    items: list[etree._Element],
) -> int:
    normalized = 0
    for item in items:
        href = item.attrib.get("href")
        if not href:
            continue
        media_type = item.attrib.get("media-type", "").lower()
        if media_type != "application/x-dtbncx+xml":
            continue
        nav_package_path = _join_package_path(package_dir, href)
        nav_file = work_dir / Path(*PurePosixPath(nav_package_path).parts)
        if not nav_file.is_file():
            continue
        if _normalize_ncx_document(nav_file, work_dir, posixpath.dirname(nav_package_path)):
            normalized += 1
    return normalized


def _normalize_ncx_document(nav_file: Path, work_dir: Path, nav_dir: str) -> bool:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    tree = etree.parse(str(nav_file), parser)
    root = tree.getroot()
    changed = False

    for nav_point in list(root.xpath("//*[local-name()='navPoint']")):
        label = _first_xpath(nav_point, "./*[local-name()='navLabel']/*[local-name()='text']")
        content = _first_xpath(nav_point, "./*[local-name()='content']")
        src = content.attrib.get("src") if content is not None else ""
        if not src or _is_dangerous_or_missing_nav_target(src, work_dir, nav_dir):
            parent = nav_point.getparent()
            if parent is not None:
                parent.remove(nav_point)
                changed = True
            continue

        if label is not None:
            normalized = _normalized_text(label)
            if label.text != normalized:
                label.text = normalized
                changed = True

    for index, nav_point in enumerate(root.xpath("//*[local-name()='navPoint']"), start=1):
        new_order = str(index)
        if nav_point.attrib.get("playOrder") != new_order:
            nav_point.attrib["playOrder"] = new_order
            changed = True

    if changed:
        _write_xml(tree, nav_file)
    return changed


def _is_dangerous_or_missing_nav_target(src: str, work_dir: Path, nav_dir: str) -> bool:
    parsed = urlsplit(src)
    if parsed.scheme in DANGEROUS_URI_SCHEMES:
        return True
    if parsed.scheme or parsed.netloc:
        return False
    path = unquote(parsed.path)
    if not path:
        return True
    normalized = posixpath.normpath(posixpath.join(nav_dir, path))
    if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        return True
    target = work_dir / Path(*PurePosixPath(normalized).parts)
    return not target.is_file()


def _first_xpath(root: etree._Element, query: str) -> etree._Element | None:
    matches = root.xpath(query)
    return matches[0] if matches else None


def _remove_stylesheet_links(head: etree._Element) -> None:
    for link in list(head.xpath("./*[local-name()='link']")):
        rel = link.attrib.get("rel", "").lower()
        link_type = link.attrib.get("type", "").lower()
        if "stylesheet" in rel or rel == "xpgt" or "page-template" in link_type:
            head.remove(link)


def _append_stylesheet_link(head: etree._Element, href: str) -> None:
    tag = _namespaced_tag(head, "link")
    link = etree.Element(tag)
    link.attrib["href"] = href
    link.attrib["rel"] = "stylesheet"
    link.attrib["type"] = "text/css"
    head.append(link)


def _namespaced_tag(element: etree._Element, local_name: str) -> str:
    qname = etree.QName(element)
    if qname.namespace:
        return f"{{{qname.namespace}}}{local_name}"
    return local_name


def _local_name(element: etree._Element) -> str | None:
    if not isinstance(element.tag, str):
        return None
    return etree.QName(element).localname.lower()


def _refine_document_role(root: etree._Element, document_role: str) -> str:
    if document_role in {"part", "title", "toc", "works"}:
        return document_role
    if document_role == "metadata":
        return "metadata"
    if _looks_like_toc_document(root):
        return "toc"
    if _looks_like_dedication_document(root):
        return "dedication"
    if _looks_like_metadata_page(root):
        return "metadata"
    if document_role == "prologue" and _looks_like_narrative_prologue(root):
        return "body"
    if document_role == "introduction" and _looks_like_narrative_introduction(root):
        return "body"
    if document_role in {"introduction", "prologue"}:
        return "front"
    if _looks_like_works_list_document(root):
        return "works"
    return document_role


def _looks_like_toc_document(root: etree._Element) -> bool:
    blocks = [
        element
        for element in _meaningful_body_blocks(root)
        if not _has_block_children(element)
    ]
    if len(blocks) < 5:
        return False

    first_text = _normalized_text(blocks[0]).lower()
    if first_text not in {"contents", "table of contents"}:
        return False

    texts = [_normalized_text(element) for element in blocks[:80]]
    short_count = sum(1 for text in texts if _is_short_list_text(text))
    link_count = sum(1 for element in blocks[:80] if _contains_link(element))
    chapterish_count = sum(1 for text in texts if _looks_like_chapterish_label(text))
    return short_count / len(texts) >= 0.8 and (link_count >= 3 or chapterish_count >= 3)


def _looks_like_dedication_document(root: etree._Element) -> bool:
    blocks = [
        element
        for element in root.xpath("//*[local-name()='body']//*[self::*]")
        if etree.QName(element).localname.lower() in {"blockquote", "div", "h1", "h2", "h3", "p"}
        and _normalized_text(element)
    ]
    if not 2 <= len(blocks) <= 12:
        return False

    first_text = _normalized_text(blocks[0]).lower()
    if first_text not in {"dedication", "dedicated to"}:
        return False

    texts = [_normalized_text(element) for element in blocks]
    short_count = sum(1 for text in texts if len(text) <= 120 and len(text.split()) <= 16)
    return short_count / len(texts) >= 0.75


def _looks_like_narrative_prologue(root: etree._Element) -> bool:
    return _looks_like_narrative_named_section(root, {"prologue"})


def _looks_like_narrative_introduction(root: etree._Element) -> bool:
    return _looks_like_narrative_named_section(root, {"introduction", "intro"})


def _looks_like_narrative_named_section(root: etree._Element, heading_names: set[str]) -> bool:
    body_blocks = _meaningful_body_blocks(root)
    if len(body_blocks) < 3:
        return False

    heading_text = _normalized_text(body_blocks[0]).lower()
    if not any(name in heading_text for name in heading_names):
        return False

    paragraph_texts = [
        _normalized_text(element)
        for element in body_blocks[1:]
        if etree.QName(element).localname.lower() in {"div", "p"}
    ]
    if len(paragraph_texts) < 2:
        return False

    long_paragraphs = sum(1 for text in paragraph_texts if len(text) > 140)
    short_paragraphs = sum(1 for text in paragraph_texts if _is_short_list_text(text))
    return long_paragraphs >= 2 and long_paragraphs > short_paragraphs


def _looks_like_metadata_page(root: etree._Element) -> bool:
    blocks = [
        element
        for element in _meaningful_body_blocks(root)
        if not _has_block_children(element)
    ]
    if not 2 <= len(blocks) <= 14:
        return False

    texts = [_normalized_text(element) for element in blocks]
    combined = " ".join(texts).lower()
    metadata_hits = sum(1 for text in texts if _is_metadata_line_text(text))
    short_count = sum(1 for text in texts if len(text) <= 90)
    short_ratio = short_count / len(texts)
    return (
        (metadata_hits >= 2 and short_ratio >= 0.5)
        or (
            metadata_hits >= 1
            and short_ratio >= 0.75
            and any(token in combined for token in {"epub", "isbn", "copyright", "editor"})
        )
    )


def _looks_like_works_list_document(root: etree._Element) -> bool:
    blocks = [
        element
        for element in _meaningful_body_blocks(root)
        if etree.QName(element).localname.lower() in {"div", "h1", "h2", "h3", "p"}
        and not _has_block_children(element)
    ]
    if len(blocks) < 4:
        return False

    early_text = " ".join(_normalized_text(element).lower() for element in blocks[:4])
    if not _has_works_list_heading(early_text):
        return False

    texts = [_normalized_text(element) for element in blocks[:80]]
    short_count = sum(1 for text in texts if _is_short_list_text(text))
    emphasized_count = sum(1 for element in blocks[:80] if _contains_emphasis(element))
    category_count = sum(1 for text in texts if _is_works_category_text(text))
    return short_count / len(texts) >= 0.65 and (emphasized_count >= 3 or category_count >= 1)


def _meaningful_body_blocks(root: etree._Element) -> list[etree._Element]:
    return [
        element
        for element in root.xpath("//*[local-name()='body']//*[self::*]")
        if etree.QName(element).localname.lower() in {"div", "h1", "h2", "h3", "p"}
        and _normalized_text(element)
    ]


def _has_works_list_heading(text: str) -> bool:
    return any(
        phrase in text
        for phrase in {
            "also by",
            "also from",
            "by the same author",
            "other books by",
            "other works by",
            "works by",
        }
    )


def _sanitize_links(root: etree._Element) -> None:
    for element in root.xpath("//*[@href or @src]"):
        for attr in ("href", "src"):
            value = element.attrib.get(attr)
            if not value:
                continue
            scheme = value.split(":", 1)[0].lower() if ":" in value else ""
            if scheme in DANGEROUS_URI_SCHEMES:
                del element.attrib[attr]


def _remove_broken_images(root: etree._Element, content_file: Path, work_dir: Path) -> None:
    for image in list(root.xpath("//*[local-name()='img']")):
        src = image.attrib.get("src")
        if not src:
            _remove_element_preserving_tail(image)
            continue
        asset_path = _resolve_content_asset_path(content_file, work_dir, src)
        if asset_path is not None and not asset_path.is_file():
            _remove_element_preserving_tail(image)

    image_containers = "//*[local-name()='p' or local-name()='div' or local-name()='figure']"
    for element in list(root.xpath(image_containers)):
        classes = set(element.attrib.get("class", "").lower().split())
        if classes & {"eo-image", "image", "img", "dis_img", "cover"} and _is_empty_block(element):
            _remove_element_preserving_tail(element)


def _resolve_content_asset_path(content_file: Path, work_dir: Path, href: str) -> Path | None:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    if not path:
        return None
    normalized = posixpath.normpath(posixpath.join(content_file.parent.as_posix(), path))
    candidate = Path(normalized).resolve()
    try:
        candidate.relative_to(work_dir.resolve())
    except ValueError:
        return None
    return candidate


def _remove_empty_blocks(root: etree._Element) -> None:
    removable_names = {"div", "p", "section"}
    empty_blocks = "//*[local-name()='div' or local-name()='p' or local-name()='section']"
    for element in list(root.xpath(empty_blocks)):
        if etree.QName(element).localname.lower() not in removable_names:
            continue
        if not _is_empty_block(element):
            continue
        classes = set(element.attrib.get("class", "").lower().split())
        if classes & {"scene-break", "scenebreak", "separator", "ornament", "space-break"}:
            continue
        _remove_element_preserving_tail(element)


def _remove_element_preserving_tail(element: etree._Element) -> None:
    parent = element.getparent()
    if parent is None:
        return
    tail = element.tail
    previous = element.getprevious()
    if tail:
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(element)


def _strip_publisher_presentation(root: etree._Element) -> None:
    for element in root.xpath("//*"):
        local_element = _local_name(element)
        for attr in list(element.attrib):
            local_attr = attr.rsplit("}", 1)[-1].lower()
            if local_element in {"svg", "image"} and local_attr in {"height", "width"}:
                continue
            if local_attr in PRESENTATION_ATTRS:
                del element.attrib[attr]


def _apply_presentation_role_hints(
    root: etree._Element,
    stylesheet_class_roles: dict[str, str],
) -> None:
    for element in root.xpath("//*"):
        roles: set[str] = set()
        align = element.attrib.get("align", "").lower()
        style = element.attrib.get("style", "").lower()
        classes = set(element.attrib.get("class", "").lower().split())

        if align == "right" or re.search(r"text-align\s*:\s*right\b", style):
            roles.add("eo-right")
        elif align == "center" or re.search(r"text-align\s*:\s*center\b", style):
            roles.add("eo-centered")

        for class_name in classes:
            role = stylesheet_class_roles.get(class_name)
            if role:
                roles.add(role)

        if "eo-right" in roles:
            _add_class(element, "eo-right")
        elif "eo-centered" in roles:
            _add_class(element, "eo-centered")


def _collapse_nested_blockquotes(root: etree._Element) -> None:
    changed = True
    while changed:
        changed = False
        for element in list(root.xpath("//*[local-name()='blockquote']")):
            children = [child for child in element if isinstance(child.tag, str)]
            if len(children) != 1:
                continue
            child = children[0]
            if etree.QName(child).localname.lower() != "blockquote":
                continue
            if (element.text or "").strip() or (child.tail or "").strip():
                continue
            parent = element.getparent()
            if parent is None:
                continue
            index = parent.index(element)
            element.remove(child)
            child.tail = element.tail
            parent.remove(element)
            parent.insert(index, child)
            changed = True


def _unwrap_font_elements(root: etree._Element) -> None:
    for element in list(root.xpath("//*[local-name()='font']")):
        parent = element.getparent()
        if parent is None:
            continue
        index = parent.index(element)
        if element.text:
            if index == 0:
                parent.text = (parent.text or "") + element.text
            else:
                previous = parent[index - 1]
                previous.tail = (previous.tail or "") + element.text
        for child in list(element):
            element.remove(child)
            parent.insert(index, child)
            index += 1
        if element.tail:
            if index == 0:
                parent.text = (parent.text or "") + element.tail
            elif index <= len(parent):
                parent[index - 1].tail = (parent[index - 1].tail or "") + element.tail
        parent.remove(element)


def _normalize_inline_spans(root: etree._Element) -> None:
    for span in root.xpath("//*[local-name()='span']"):
        classes = set(span.attrib.get("class", "").lower().split())
        existing_role = _existing_optimizer_inline_role(classes)
        if existing_role:
            _replace_classes(span, existing_role)
        elif classes & {"bold"}:
            _rename_element(span, "strong")
            span.attrib.pop("class", None)
        elif classes & {"italic", "ital"}:
            _rename_element(span, "em")
            span.attrib.pop("class", None)
        elif classes & {"underline"}:
            _replace_classes(span, "eo-underline")
        elif classes & {"strike"}:
            _replace_classes(span, "eo-strike")
        elif classes & {"overline"}:
            _replace_classes(span, "eo-overline")
        elif classes & {"smallcaps", "small-cap", "small-caps"} or _is_probable_smallcaps_span(
            span
        ):
            _replace_classes(span, "eo-smallcaps")
        else:
            span.attrib.pop("class", None)


def _rename_element(element: etree._Element, local_name: str) -> None:
    namespace = etree.QName(element).namespace
    element.tag = f"{{{namespace}}}{local_name}" if namespace else local_name


def _classify_blocks(root: etree._Element, document_role: str) -> None:
    after_boundary = True
    is_front_matter = document_role in {"dedication", "front", "title", "works"}
    title_line_index = 0
    metadata_line_index = 0
    opening_epigraph = False
    for element in root.xpath("//*[local-name()='body']//*[self::*]"):
        local = etree.QName(element).localname.lower()
        source_classes = set(element.attrib.get("class", "").lower().split())
        if local in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            existing_role = _existing_optimizer_block_role(source_classes)
            if existing_role and not _should_reclassify_heading_role(
                existing_role,
                document_role,
                local,
                source_classes,
            ):
                _replace_classes(element, existing_role)
                after_boundary = _role_creates_boundary(existing_role)
                opening_epigraph = False
                continue
            if document_role == "toc":
                _replace_classes(element, "eo-toc-heading")
                after_boundary = True
                continue
            if document_role == "title":
                role = _title_page_line_role(element, title_line_index)
                title_line_index += 1
                _replace_classes(element, role)
                after_boundary = role in {"eo-title-main", "eo-title-author"}
                continue
            if document_role == "works":
                _replace_classes(element, "eo-front")
                after_boundary = True
                opening_epigraph = False
                continue
            if document_role == "metadata":
                role = _metadata_line_role(element, metadata_line_index)
                metadata_line_index += 1
                _replace_classes(element, role)
                after_boundary = True
                opening_epigraph = False
                continue
            _replace_classes(element, _heading_role(local, source_classes, is_front_matter))
            after_boundary = True
            opening_epigraph = False
            continue

        existing_role = _existing_optimizer_block_role(source_classes)
        if existing_role and local in {
            "aside",
            "blockquote",
            "div",
            "figcaption",
            "figure",
            "ol",
            "p",
            "section",
            "ul",
        }:
            _replace_classes(element, existing_role)
            after_boundary = _role_creates_boundary(existing_role)
            opening_epigraph = existing_role in {"eo-extract", "eo-scene-break"}
            continue

        if local in {"ol", "ul"}:
            _replace_classes(element, "eo-list")
            after_boundary = True
            continue

        if local == "blockquote":
            role = _blockquote_role(source_classes, document_role)
            _replace_classes(element, role)
            after_boundary = True
            continue

        if local in {"figcaption"}:
            _replace_classes(element, "eo-caption")
            after_boundary = True
            continue

        if local in {"aside"}:
            _replace_classes(element, "eo-footnote")
            after_boundary = True
            continue

        if local == "p":
            letter_role = _letter_paragraph_role(source_classes)
            if letter_role or _has_ancestor_class(element, "eo-letter"):
                _replace_classes(element, letter_role or "eo-letter-body")
                after_boundary = False
                continue
            if _is_letter_attribution(source_classes):
                _replace_classes(element, "eo-letter-attribution")
                after_boundary = True
                continue
            if document_role == "toc":
                role = _toc_entry_role(element, source_classes, after_boundary)
                if role == "eo-toc-heading":
                    _rename_element(element, "h1")
                _replace_classes(element, role)
                after_boundary = role in {"eo-image", "eo-toc-heading", "eo-toc-part"}
                continue
            if document_role == "part":
                role = _part_paragraph_role(element, after_boundary)
                if role == "eo-part":
                    _rename_element(element, "h1")
                _replace_classes(element, role)
                after_boundary = role in {"eo-image", "eo-part", "eo-scene-break"}
                continue
            if document_role == "title":
                role = _title_page_line_role(element, title_line_index)
                title_line_index += 1
                if role == "eo-title-main":
                    _rename_element(element, "h1")
                _replace_classes(element, role)
                after_boundary = role in {"eo-image", "eo-title-main", "eo-title-author"}
                continue
            if document_role == "works":
                role = _works_list_item_role(element, after_boundary)
                if role == "eo-front":
                    _rename_element(element, "h1")
                _replace_classes(element, role)
                after_boundary = role in {"eo-front", "eo-front-section", "eo-image"}
                continue
            if document_role == "metadata":
                role = _metadata_line_role(element, metadata_line_index)
                metadata_line_index += 1
                _replace_classes(element, role)
                after_boundary = True
                continue
            if document_role == "dedication":
                role = _dedication_line_role(element, after_boundary)
                if role == "eo-front":
                    _rename_element(element, "h1")
                _replace_classes(element, role)
                after_boundary = True
                continue
            if (
                after_boundary
                and not is_front_matter
                and _is_opening_epigraph_paragraph(element)
            ):
                _replace_classes(element, "eo-extract")
                after_boundary = True
                opening_epigraph = True
                continue
            if opening_epigraph and _is_opening_epigraph_attribution(element):
                _replace_classes(element, "eo-extract")
                after_boundary = True
                opening_epigraph = False
                continue
            role = _paragraph_role(element, source_classes, after_boundary, is_front_matter)
            _replace_classes(element, role)
            after_boundary = role in {
                "eo-caption",
                "eo-centered",
                "eo-extract",
                "eo-footnote",
                "eo-front-list-item",
                "eo-image",
                "eo-letter-attribution",
                "eo-poetry",
                "eo-scene-break",
            }
            opening_epigraph = role in {"eo-extract", "eo-scene-break"}
            continue

        if local == "div" and _is_direct_body_child(element):
            if document_role == "toc":
                role = _toc_block_role(element, source_classes, after_boundary)
            elif document_role == "title":
                role = _title_div_role(element, title_line_index)
                if role != "eo-title-page":
                    title_line_index += 1
            elif document_role == "works":
                role = _works_list_div_role(element, after_boundary)
            elif document_role == "metadata":
                role = _metadata_div_role(element, metadata_line_index)
                if role != "eo-metadata-page":
                    metadata_line_index += 1
            elif document_role == "dedication":
                role = _dedication_line_role(element, after_boundary)
            else:
                container_role = _container_role(source_classes)
                role = container_role or _anonymous_div_role(element, after_boundary, document_role)
            if role:
                if role in {
                    "eo-chapter",
                    "eo-front",
                    "eo-part",
                    "eo-section",
                    "eo-title-main",
                    "eo-toc-heading",
                }:
                    _rename_element(element, "h1")
                    _replace_classes(element, role)
                    after_boundary = True
                    opening_epigraph = False
                else:
                    if role == "eo-image" or _has_block_children(element):
                        _replace_classes(element, role)
                        after_boundary = True
                        opening_epigraph = False
                        continue
                    _rename_element(element, "p")
                    _replace_classes(element, role)
                    after_boundary = role in {
                        "eo-caption",
                        "eo-centered",
                        "eo-extract",
                    "eo-footnote",
                    "eo-front-list-item",
                    "eo-front-section",
                    "eo-image",
                    "eo-metadata-line",
                    "eo-metadata-title",
                        "eo-poetry",
                        "eo-scene-break",
                        "eo-title-author",
                        "eo-title-credit",
                        "eo-title-credit-label",
                        "eo-title-publisher",
                        "eo-toc-entry",
                        "eo-toc-chapter",
                        "eo-toc-part",
                    }
                    opening_epigraph = role in {"eo-extract", "eo-scene-break"}
                continue

        if local == "div" and document_role == "front":
            role = _container_role(source_classes) or _front_nested_div_role(
                element,
                after_boundary,
            )
            if role:
                if role == "eo-front":
                    _rename_element(element, "h1")
                    _replace_classes(element, role)
                    after_boundary = True
                else:
                    if _has_block_children(element):
                        _replace_classes(element, role)
                        after_boundary = True
                        continue
                    _rename_element(element, "p")
                    _replace_classes(element, role)
                    after_boundary = role in {"eo-front-list-item", "eo-scene-break", "eo-image"}
                continue

        if local == "div" and document_role == "works":
            role = _works_list_div_role(element, after_boundary)
            if role:
                if role == "eo-front":
                    _rename_element(element, "h1")
                    _replace_classes(element, role)
                    after_boundary = True
                    continue
                if _has_block_children(element):
                    _replace_classes(element, role)
                    after_boundary = True
                    continue
                _rename_element(element, "p")
                _replace_classes(element, role)
                after_boundary = role in {
                    "eo-front",
                    "eo-front-section",
                    "eo-image",
                    "eo-scene-break",
                }
                continue

        if local == "div" and document_role == "metadata":
            role = _metadata_div_role(element, metadata_line_index)
            if role == "eo-metadata-page":
                _replace_classes(element, role)
                after_boundary = True
                continue
            metadata_line_index += 1
            if role:
                if _has_block_children(element):
                    _replace_classes(element, role)
                    after_boundary = True
                    continue
                _rename_element(element, "p")
                _replace_classes(element, role)
                after_boundary = True
                continue

        if local == "div" and document_role == "title":
            role = _title_div_role(element, title_line_index)
            if role == "eo-title-page":
                _replace_classes(element, role)
                after_boundary = True
                continue
            title_line_index += 1
            if role == "eo-title-main":
                _rename_element(element, "h1")
                _replace_classes(element, role)
                after_boundary = True
                continue
            if role:
                if _has_block_children(element):
                    _replace_classes(element, role)
                    after_boundary = True
                    continue
                _rename_element(element, "p")
                _replace_classes(element, role)
                after_boundary = role in {
                    "eo-image",
                    "eo-title-author",
                    "eo-title-main",
                    "eo-title-publisher",
                    "eo-scene-break",
                }
                continue

        if local == "div" and document_role == "toc":
            role = _toc_block_role(element, source_classes, after_boundary)
            if role == "eo-toc":
                _replace_classes(element, role)
                after_boundary = True
                continue

            if role:
                if role == "eo-toc-heading":
                    _rename_element(element, "h1")
                    _replace_classes(element, role)
                    after_boundary = True
                    continue
                if _has_block_children(element):
                    _replace_classes(element, role)
                    after_boundary = True
                    continue
                _rename_element(element, "p")
                _replace_classes(element, role)
                after_boundary = role in {
                    "eo-scene-break",
                    "eo-toc-chapter",
                    "eo-toc-entry",
                    "eo-toc-part",
                }
                continue

        if local in {"div", "figure", "section"}:
            role = _container_role(source_classes)
            if role:
                _replace_classes(element, role)
                after_boundary = role in {
                    "eo-dedication",
                    "eo-extract",
                    "eo-footnote",
                    "eo-image",
                    "eo-poetry",
                    "eo-toc",
                }

        if local == "img":
            parent = element.getparent()
            parent_name = etree.QName(parent).localname.lower() if parent is not None else ""
            if parent_name in {"div", "figure", "p"}:
                _add_class(parent, "eo-image")
            after_boundary = True


def _heading_role(local: str, classes: set[str], is_front_matter: bool) -> str:
    if "eo-part" in classes or "part" in classes:
        return "eo-part"
    if "eo-front" in classes or is_front_matter or classes & FRONT_MATTER_HINTS:
        return "eo-front"
    if "eo-section" in classes:
        return "eo-section"
    if "eo-chapter" in classes or any(cls.startswith("chapter") for cls in classes):
        return "eo-chapter"
    if "section" in classes or local not in {"h1"}:
        return "eo-section"
    return "eo-chapter"


def _should_reclassify_heading_role(
    existing_role: str,
    document_role: str,
    local: str,
    classes: set[str],
) -> bool:
    if existing_role not in {"eo-centered", "eo-right"}:
        return False
    if document_role in {"dedication", "front", "metadata", "title", "toc", "works"}:
        return False
    return bool(
        local == "h1"
        or "eo-chapter" in classes
        or any(cls.startswith("chapter") for cls in classes)
    )


def _existing_optimizer_block_role(classes: set[str]) -> str | None:
    for role in sorted(classes):
        if role in EO_BLOCK_ROLES:
            return role
    return None


def _existing_optimizer_inline_role(classes: set[str]) -> str | None:
    for role in sorted(classes):
        if role in EO_INLINE_ROLES:
            return role
    return None


def _role_creates_boundary(role: str) -> bool:
    return role in {
        "eo-caption",
        "eo-centered",
        "eo-chapter",
        "eo-dedication",
        "eo-extract",
        "eo-footnote",
        "eo-front",
        "eo-front-list-item",
        "eo-front-section",
        "eo-image",
        "eo-letter-attribution",
        "eo-metadata-line",
        "eo-metadata-title",
        "eo-part",
        "eo-poetry",
        "eo-right",
        "eo-scene-break",
        "eo-section",
        "eo-title-author",
        "eo-title-main",
        "eo-title-publisher",
        "eo-toc-chapter",
        "eo-toc-entry",
        "eo-toc-heading",
        "eo-toc-part",
    }


def _paragraph_role(
    element: etree._Element,
    classes: set[str],
    after_boundary: bool,
    is_front_matter: bool,
) -> str:
    if _contains_direct_image(element):
        return "eo-image"
    if _is_scene_break(element):
        return "eo-scene-break"
    letter_role = _letter_paragraph_role(classes)
    if letter_role:
        return letter_role
    if _is_letter_attribution(classes):
        return "eo-letter-attribution"
    if classes & {"caption", "figcaption"}:
        return "eo-caption"
    if classes & {"center", "center0", "bl_center", "eo-centered"}:
        return "eo-centered"
    if classes & {"right", "bl_right", "attribution", "eo-right"}:
        return "eo-right"
    if classes & {"poem", "poetry", "verse", "line", "stanza"}:
        return "eo-poetry"
    if classes & {"footnote", "note", "endnote"}:
        return "eo-footnote"
    if classes & {"hanging", "reference", "bl_hanging", "d_hanging"}:
        return "eo-hanging"
    if classes & {"extract", "extract1", "bl_extract", "bl_nonindent", "bl_indent", "stanga"}:
        return "eo-extract"
    if classes & {"nonindent", "nonindent1"} or after_boundary:
        return "eo-first"
    if is_front_matter:
        return "eo-front-body"
    return "eo-body"


def _letter_paragraph_role(classes: set[str]) -> str | None:
    if classes & {"ltg", "letter-greeting", "salutation"}:
        return "eo-letter-opener"
    if classes & {"ltf", "letter-first"}:
        return "eo-letter-first"
    if classes & {"lt", "ltl", "letter", "letter-body", "letter-last"}:
        return "eo-letter-body"
    return None


def _is_letter_attribution(classes: set[str]) -> bool:
    return bool(classes & {"ept", "letter-source", "letter-credit", "missive-source"})


def _blockquote_role(classes: set[str], document_role: str) -> str:
    if document_role == "dedication":
        return "eo-dedication"
    if "eo-right" in classes:
        return "eo-right"
    if "eo-centered" in classes:
        return "eo-centered"
    return "eo-blockquote"


def _dedication_line_role(element: etree._Element, after_boundary: bool) -> str:
    if _contains_direct_image(element):
        return "eo-image"
    if _is_scene_break(element):
        return "eo-scene-break"
    text = _normalized_text(element)
    if after_boundary and text.lower() in {"dedication", "dedicated to"}:
        return "eo-front"
    return "eo-dedication"


def _is_opening_epigraph_paragraph(element: etree._Element) -> bool:
    text = _normalized_text(element)
    if not 20 <= len(text) <= 900:
        return False
    if _contains_direct_image(element):
        return False
    return _emphasized_text_ratio(element) >= 0.65


def _is_opening_epigraph_attribution(element: etree._Element) -> bool:
    text = _normalized_text(element)
    if not text or len(text) > 140:
        return False
    if text.startswith(("-", "--", "—", "–")):
        return True
    classes = set(element.attrib.get("class", "").lower().split())
    if classes & {"attribution", "source", "credit"}:
        return True
    return _bold_text_ratio(element) >= 0.6 and len(text.split()) <= 12


def _emphasized_text_ratio(element: etree._Element) -> float:
    return _tagged_text_ratio(element, {"em", "i"})


def _bold_text_ratio(element: etree._Element) -> float:
    return _tagged_text_ratio(element, {"strong", "b"})


def _tagged_text_ratio(element: etree._Element, local_names: set[str]) -> float:
    total = len(_normalized_text(element))
    if total == 0:
        return 0.0
    tagged = 0
    for child in element.xpath(".//*"):
        if etree.QName(child).localname.lower() in local_names:
            tagged += len(_normalized_text(child))
    return min(tagged / total, 1.0)


def _part_paragraph_role(element: etree._Element, after_boundary: bool) -> str:
    if _contains_direct_image(element):
        return "eo-image"
    if _is_scene_break(element):
        return "eo-scene-break"
    text = _normalized_text(element)
    if after_boundary and _is_short_heading_text(text):
        return "eo-part"
    return "eo-first" if after_boundary else "eo-body"


def _title_div_role(element: etree._Element, line_index: int) -> str:
    if _has_block_children(element):
        return "eo-title-page"
    return _title_page_line_role(element, line_index)


def _metadata_div_role(element: etree._Element, line_index: int) -> str:
    if _has_block_children(element):
        return "eo-metadata-page"
    return _metadata_line_role(element, line_index)


def _metadata_line_role(element: etree._Element, line_index: int) -> str:
    if _contains_direct_image(element):
        return "eo-image"
    if _is_scene_break(element) or _is_empty_block(element):
        return "eo-scene-break"

    text = _normalized_text(element)
    if line_index == 0 and not _is_metadata_line_text(text):
        return "eo-metadata-title"
    if etree.QName(element).localname.lower() in {"h1", "h2", "h3"}:
        return "eo-metadata-title"
    return "eo-metadata-line"


def _title_page_line_role(element: etree._Element, line_index: int) -> str:
    if _contains_direct_image(element):
        return "eo-image"
    if _is_scene_break(element):
        return "eo-scene-break"

    text = _normalized_text(element)
    if not text:
        return "eo-scene-break"
    lower_text = text.lower()
    if line_index == 0:
        return "eo-title-main"
    if _is_title_credit_label(lower_text):
        return "eo-title-credit-label"
    if _contains_credit_label_before(element) and line_index <= 2:
        return "eo-title-credit"
    if _is_title_publisher_line(text, lower_text, line_index):
        return "eo-title-publisher"
    if _looks_like_person_credit(text):
        return "eo-title-author"
    return "eo-title-credit" if line_index <= 2 else "eo-title-author"


def _is_title_credit_label(lower_text: str) -> bool:
    if len(lower_text) > 80:
        return False
    if " by" in lower_text or "by " in lower_text or " from " in lower_text:
        return True
    return lower_text.startswith(
        (
            "adapted ",
            "afterword ",
            "edited ",
            "illustrated ",
            "introduction ",
            "translated ",
            "with ",
        )
    )


def _is_title_publisher_line(text: str, lower_text: str, line_index: int) -> bool:
    publisher_tokens = {
        "books",
        "classics",
        "edition",
        "editions",
        "house",
        "imprint",
        "press",
        "publishers",
        "publishing",
    }
    if any(token in lower_text for token in publisher_tokens):
        return True
    words = text.replace("/", " ").split()
    return (
        line_index >= 4
        and 1 <= len(words) <= 4
        and bool(words)
        and all(word[:1].isupper() for word in words)
    )


def _looks_like_person_credit(text: str) -> bool:
    words = [word.strip(".,;:") for word in text.split()]
    if not 1 <= len(words) <= 5:
        return False
    alpha_words = [word for word in words if any(char.isalpha() for char in word)]
    return bool(alpha_words) and all(word[:1].isupper() for word in alpha_words)


def _contains_credit_label_before(element: etree._Element) -> bool:
    parent = element.getparent()
    if parent is None:
        return False
    for sibling in parent:
        if sibling is element:
            return False
        if not isinstance(sibling.tag, str):
            continue
        text = _normalized_text(sibling).lower()
        if text and _is_title_credit_label(text):
            return True
    return False


def _has_ancestor_class(element: etree._Element, class_name: str) -> bool:
    parent = element.getparent()
    while parent is not None:
        if class_name in parent.attrib.get("class", "").split():
            return True
        parent = parent.getparent()
    return False


def _container_role(classes: set[str]) -> str | None:
    if classes & {"part"}:
        return "eo-part"
    if "eo-right" in classes:
        return "eo-right"
    if "eo-centered" in classes:
        return "eo-centered"
    if classes & {"cover", "titlepage", "dis_img"}:
        return "eo-image"
    if classes & {"letter", "missive", "diary", "journal"}:
        return "eo-letter"
    if classes & {"block", "textbox", "abstract", "epigraph"}:
        return "eo-extract"
    if classes & {"poem", "poetry", "verse", "stanza"}:
        return "eo-poetry"
    if classes & {"hanging", "dialogue"}:
        return "eo-hanging"
    if classes & {"footnote", "note", "endnote"}:
        return "eo-footnote"
    if classes & {"dedication"}:
        return "eo-dedication"
    if classes & {"copyright", "otherbooks", "titlepage"}:
        return "eo-centered"
    return None


def _contains_direct_image(element: etree._Element) -> bool:
    return any(_local_name(child) in {"img", "svg"} for child in element)


def _is_direct_body_child(element: etree._Element) -> bool:
    parent = element.getparent()
    return parent is not None and etree.QName(parent).localname.lower() == "body"


def _anonymous_div_role(
    element: etree._Element,
    after_boundary: bool,
    document_role: str,
) -> str | None:
    if _contains_direct_image(element):
        return "eo-image"
    if _is_scene_break(element):
        return "eo-scene-break"
    if _is_empty_block(element):
        return "eo-scene-break"
    if _has_block_children(element):
        return "eo-front-body" if document_role == "front" else None

    text = _normalized_text(element)
    if not text:
        return None
    if document_role == "front":
        if (
            after_boundary
            and _is_first_meaningful_body_child(element)
            and _is_short_heading_text(text)
        ):
            return "eo-front"
        if _is_front_list_item(element):
            return "eo-front-list-item"
        return "eo-front-body"
    if document_role == "part":
        if (
            after_boundary
            and _is_first_meaningful_body_child(element)
            and _is_short_heading_text(text)
        ):
            return "eo-part"
        return "eo-first"
    if after_boundary and _is_first_meaningful_body_child(element) and _is_short_heading_text(text):
        return "eo-chapter"
    return "eo-first" if after_boundary else "eo-body"


def _front_nested_div_role(element: etree._Element, after_boundary: bool) -> str | None:
    if _contains_direct_image(element):
        return "eo-image"
    if _is_scene_break(element) or _is_empty_block(element):
        return "eo-scene-break"
    if _has_block_children(element):
        return "eo-front-body"

    text = _normalized_text(element)
    if not text:
        return None
    if after_boundary and _is_first_meaningful_sibling(element) and _is_short_heading_text(text):
        return "eo-front"
    if _is_front_list_item(element):
        return "eo-front-list-item"
    return "eo-front-body"


def _works_list_div_role(element: etree._Element, after_boundary: bool) -> str | None:
    if _has_block_children(element):
        return "eo-front-body"
    return _works_list_item_role(element, after_boundary)


def _works_list_item_role(element: etree._Element, after_boundary: bool) -> str:
    if _contains_direct_image(element):
        return "eo-image"
    if _is_scene_break(element) or _is_empty_block(element):
        return "eo-scene-break"

    text = _normalized_text(element)
    if after_boundary and _has_works_list_heading(text.lower()):
        return "eo-front"
    if _is_works_category_text(text):
        return "eo-front-section"
    return "eo-front-list-item"


def _has_block_children(element: etree._Element) -> bool:
    block_names = {
        "blockquote",
        "div",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ol",
        "p",
        "section",
        "table",
        "ul",
    }
    return any(_local_name(child) in block_names for child in element)


def _contains_emphasis(element: etree._Element) -> bool:
    return bool(element.xpath(".//*[local-name()='em' or local-name()='i']"))


def _is_front_list_item(element: etree._Element) -> bool:
    parent = element.getparent()
    if parent is None or _is_first_meaningful_sibling(element):
        return False

    siblings = [
        child
        for child in parent
        if isinstance(child.tag, str) and (_normalized_text(child) or _contains_direct_image(child))
    ]
    if len(siblings) < 3:
        return False

    short_leaf_count = 0
    text_count = 0
    for sibling in siblings:
        text = _normalized_text(sibling)
        if not text:
            continue
        text_count += 1
        if not _has_block_children(sibling) and _is_short_list_text(text):
            short_leaf_count += 1

    return text_count >= 3 and short_leaf_count / text_count >= 0.75


def _toc_block_role(
    element: etree._Element,
    classes: set[str],
    after_boundary: bool,
) -> str:
    if classes & {"toc", "toc_fm", "toc_bm", "eo-toc"} and _has_block_children(element):
        return "eo-toc"
    return _toc_entry_role(element, classes, after_boundary)


def _toc_entry_role(
    element: etree._Element,
    classes: set[str],
    after_boundary: bool,
) -> str:
    text = _normalized_text(element)
    if _contains_direct_image(element):
        return "eo-image"
    if not text:
        return "eo-scene-break"
    if _is_toc_separator(text):
        return "eo-toc-entry"
    if after_boundary and _is_short_heading_text(text) and not _contains_link(element):
        return "eo-toc-heading"
    if classes & {"toc_part", "eo-toc-part"} or _looks_like_toc_part(element, text):
        return "eo-toc-part"
    if (
        classes & {"toc_chap", "toc_sub", "eo-toc-chapter"}
        or _contains_chapterish_link(element)
        or _looks_like_chapterish_label(text)
    ):
        return "eo-toc-chapter"
    return "eo-toc-entry"


def _contains_link(element: etree._Element) -> bool:
    return bool(element.xpath(".//*[local-name()='a']"))


def _is_toc_separator(text: str) -> bool:
    punctuation = {".", "*", "-", "_", "•", "·", "…"}
    return bool(text) and all(char.isspace() or char in punctuation for char in text)


def _looks_like_toc_part(element: etree._Element, text: str) -> bool:
    if not _contains_link(element):
        return False
    if text.lower().startswith("part "):
        return True
    words = text.split()
    letters = [char for char in text if char.isalpha()]
    return len(words) <= 4 and (not letters or all(char.upper() == char for char in letters))


def _contains_chapterish_link(element: etree._Element) -> bool:
    for link in element.xpath(".//*[local-name()='a']"):
        href_name = posixpath.basename(link.attrib.get("href", "").split("#", 1)[0]).lower()
        if (
            "chap" in href_name
            or "chapter" in href_name
            or _has_numbered_content_token(href_name, "c")
        ):
            return True
    return False


def _looks_like_chapterish_label(text: str) -> bool:
    lower_text = text.lower()
    return (
        lower_text.startswith("chapter ")
        or lower_text.startswith("part ")
        or lower_text in {"prologue", "epilogue", "introduction", "preface"}
    )


def _has_numbered_content_token(value: str, prefix: str) -> bool:
    for separator in {"_", "-", "."}:
        marker = f"{separator}{prefix}"
        start = value.find(marker)
        while start != -1:
            suffix = value[start + len(marker) :]
            if suffix and suffix[0].isdigit():
                return True
            start = value.find(marker, start + 1)
    return value.startswith(prefix) and len(value) > 1 and value[1].isdigit()


def _is_first_meaningful_body_child(element: etree._Element) -> bool:
    parent = element.getparent()
    if parent is None:
        return False
    for child in parent:
        if not isinstance(child.tag, str):
            continue
        if etree.QName(child).localname.lower() in {"script", "style"}:
            continue
        if _normalized_text(child) or _contains_direct_image(child):
            return child is element
    return False


def _is_first_meaningful_sibling(element: etree._Element) -> bool:
    parent = element.getparent()
    if parent is None:
        return False
    for child in parent:
        if not isinstance(child.tag, str):
            continue
        if etree.QName(child).localname.lower() in {"script", "style"}:
            continue
        if _normalized_text(child) or _contains_direct_image(child):
            return child is element
    return False


def _normalized_text(element: etree._Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _is_empty_block(element: etree._Element) -> bool:
    return not _normalized_text(element) and not len(element)


def _is_probable_smallcaps_span(element: etree._Element) -> bool:
    text = _normalized_text(element)
    if len(text) < 2:
        return False
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and all(char.upper() == char for char in letters)


def _is_short_heading_text(text: str) -> bool:
    words = text.split()
    return len(text) <= 120 and len(words) <= 14


def _is_short_list_text(text: str) -> bool:
    words = text.split()
    return len(text) <= 90 and len(words) <= 12


def _is_works_category_text(text: str) -> bool:
    words = text.split()
    letters = [char for char in text if char.isalpha()]
    return (
        1 <= len(words) <= 4
        and len(text) <= 60
        and bool(letters)
        and all(char.upper() == char for char in letters)
    )


def _is_metadata_line_text(text: str) -> bool:
    lower_text = text.lower()
    metadata_tokens = {
        "base",
        "book design",
        "cover art",
        "copyright",
        "digital",
        "edited",
        "editor",
        "edition",
        "epub",
        "isbn",
        "original title",
        "published",
        "publisher",
        "release",
        "rights",
        "title:",
        "version",
    }
    if any(token in lower_text for token in metadata_tokens):
        return True
    if ":" in text and len(text) <= 100:
        return True
    return _looks_like_short_date_or_version(text)


def _looks_like_short_date_or_version(text: str) -> bool:
    if len(text) > 40:
        return False
    has_digit = any(char.isdigit() for char in text)
    if not has_digit:
        return False
    separators = sum(text.count(separator) for separator in {"-", "/", ".", ":"})
    return separators >= 1


def _is_scene_break(element: etree._Element) -> bool:
    text = _normalized_text(element)
    return text in {"*", "* * *", "***", "****", "*****"}


def _document_role(item: etree._Element) -> str:
    properties = item.attrib.get("properties", "").lower().split()
    if "nav" in properties:
        return "toc"
    values = " ".join(
        [
            item.attrib.get("id", ""),
            item.attrib.get("href", ""),
            " ".join(properties),
        ]
    ).lower()
    tokens = set(_identifier_tokens(values))
    if tokens & {"titlepage", "title-page", "title_page"}:
        return "title"
    if "title" in tokens and not (tokens & {"subtitle", "entitle"}):
        return "title"
    if tokens & {"colophon", "credits", "creditos", "info"}:
        return "metadata"
    if "prologue" in tokens:
        return "prologue"
    if tokens & {"introduction", "intro"}:
        return "introduction"
    if tokens & {"toc", "contents"}:
        return "toc"
    if _has_front_matter_hint(tokens):
        return "front"
    if "part" in tokens or any(_has_numbered_prefix(token, "part") for token in tokens):
        return "part"
    if (
        "chapter" in tokens
        or "chap" in tokens
        or any(_has_numbered_prefix(token, "chapter") for token in tokens)
        or any(_has_numbered_prefix(token, "chap") for token in tokens)
        or "/chap" in values
        or "/ch" in values
    ):
        return "chapter"
    return "body"


def _identifier_tokens(value: str) -> list[str]:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in value)
    return normalized.split()


def _has_front_matter_hint(tokens: set[str]) -> bool:
    if tokens & FRONT_MATTER_HINTS:
        return True
    return any(token.startswith("acknowledg") for token in tokens)


def _has_numbered_prefix(token: str, prefix: str) -> bool:
    suffix = token.removeprefix(prefix)
    return suffix != token and bool(suffix) and suffix[0].isdigit()


def _strip_unclassified_classes(root: etree._Element) -> None:
    for element in root.xpath("//*[@class]"):
        classes = [cls for cls in element.attrib["class"].split() if cls.startswith("eo-")]
        if classes:
            element.attrib["class"] = " ".join(classes)
        else:
            del element.attrib["class"]


def _replace_classes(element: etree._Element, class_name: str) -> None:
    element.attrib["class"] = class_name


def _add_class(element: etree._Element, class_name: str) -> None:
    classes = element.attrib.get("class", "").split()
    if class_name not in classes:
        classes.append(class_name)
    element.attrib["class"] = " ".join(classes)
