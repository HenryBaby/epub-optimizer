from __future__ import annotations

import posixpath
import tempfile
import time
from pathlib import Path, PurePosixPath

from lxml import etree

from epub_optimizer.epub import (
    extract_epub,
    find_package_document,
    make_relative_href,
    validate_epub_archive,
    write_epub,
)
from epub_optimizer.errors import InvalidEpubError
from epub_optimizer.models import OptimizationResult
from epub_optimizer.style import CANONICAL_CSS

OPF_NS = "http://www.idpf.org/2007/opf"
XHTML_NS = "http://www.w3.org/1999/xhtml"
DANGEROUS_URI_SCHEMES = {"javascript", "data", "vbscript", "file"}
CANONICAL_CSS_ID = "epub-optimizer-css"
CANONICAL_CSS_HREF = "Styles/epub-optimizer.css"


def optimize_epub(
    input_path: Path,
    output_dir: Path,
    *,
    output_filename: str | None = None,
    max_size_bytes: int | None = None,
) -> OptimizationResult:
    started = time.perf_counter()
    log: list[str] = []
    warnings: list[str] = []

    input_path = input_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_filename = output_filename or optimized_filename(input_path.name)
    output_path = output_dir / output_filename

    log.append("Validated EPUB archive.")
    validate_epub_archive(input_path, max_size_bytes=max_size_bytes)

    with tempfile.TemporaryDirectory(prefix="epub-optimizer-") as temp_name:
        work_dir = Path(temp_name)
        extract_epub(input_path, work_dir)
        log.append("Extracted EPUB into a temporary workspace.")

        package_path = find_package_document(work_dir)
        package_file = work_dir / Path(*PurePosixPath(package_path).parts)
        package_dir = posixpath.dirname(package_path)
        package_dir_path = package_file.parent
        log.append(f"Resolved OPF package document: {package_path}")

        package_tree = _parse_xml(package_file)
        package_root = package_tree.getroot()
        epub_version = package_root.attrib.get("version")

        manifest = _find_child(package_root, "manifest")
        if manifest is None:
            raise InvalidEpubError("OPF package document is missing a manifest.")

        items = _manifest_items(manifest)
        css_hrefs = [
            item.attrib["href"]
            for item in items
            if item.attrib.get("media-type", "").lower() == "text/css" and item.attrib.get("href")
        ]
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

        canonical_css_package_href = _ensure_canonical_css(package_dir_path)
        canonical_item_href = _relative_from_package_dir(package_dir, canonical_css_package_href)
        stylesheets_replaced = _replace_stylesheet_manifest_items(
            manifest, css_hrefs, canonical_item_href
        )
        log.append(f"Replaced {stylesheets_replaced} stylesheet manifest item(s).")

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
            ):
                processed_docs += 1

        log.append(f"Processed {processed_docs} content document(s).")
        _write_xml(package_tree, package_file)
        write_epub(work_dir, output_path)
        log.append("Repackaged optimized EPUB.")

    elapsed = time.perf_counter() - started
    log.append(f"Finished in {elapsed:.2f} seconds.")

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


def optimized_filename(filename: str) -> str:
    path = Path(filename)
    stem = path.stem or "optimized"
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


def _manifest_items(manifest: etree._Element) -> list[etree._Element]:
    return [
        child
        for child in manifest
        if isinstance(child.tag, str) and etree.QName(child).localname == "item"
    ]


def _ensure_canonical_css(package_dir_path: Path) -> str:
    css_path = package_dir_path / CANONICAL_CSS_HREF
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(CANONICAL_CSS, encoding="utf-8")
    return css_path.relative_to(package_dir_path.parent).as_posix()


def _relative_from_package_dir(package_dir: str, package_relative_path: str) -> str:
    if not package_dir:
        return package_relative_path
    prefix = package_dir.rstrip("/") + "/"
    if package_relative_path.startswith(prefix):
        return package_relative_path[len(prefix) :]
    return posixpath.relpath(package_relative_path, package_dir)


def _replace_stylesheet_manifest_items(
    manifest: etree._Element,
    old_css_hrefs: list[str],
    canonical_href: str,
) -> int:
    replaced = 0
    for item in _manifest_items(manifest):
        if item.attrib.get("media-type", "").lower() == "text/css":
            manifest.remove(item)
            replaced += 1

    attrib = {"id": CANONICAL_CSS_ID, "href": canonical_href, "media-type": "text/css"}
    manifest.append(etree.Element(f"{{{OPF_NS}}}item", attrib=attrib))
    return max(replaced, len(old_css_hrefs))


def _join_package_path(package_dir: str, href: str) -> str:
    joined = posixpath.normpath(posixpath.join(package_dir, href))
    if joined.startswith("../") or joined == ".." or joined.startswith("/"):
        raise InvalidEpubError(f"Manifest href escapes the EPUB root: {href}")
    return joined


def _process_content_document(
    content_file: Path,
    content_package_path: str,
    canonical_css_package_href: str,
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
    _classify_blocks(root)
    _write_xml(tree, content_file)
    return True


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


def _sanitize_links(root: etree._Element) -> None:
    for element in root.xpath("//*[@href or @src]"):
        for attr in ("href", "src"):
            value = element.attrib.get(attr)
            if not value:
                continue
            scheme = value.split(":", 1)[0].lower() if ":" in value else ""
            if scheme in DANGEROUS_URI_SCHEMES:
                del element.attrib[attr]


def _classify_blocks(root: etree._Element) -> None:
    after_boundary = True
    for element in root.xpath("//*[local-name()='body']//*[self::*]"):
        local = etree.QName(element).localname.lower()
        source_classes = set(element.attrib.get("class", "").lower().split())

        if local in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            _replace_classes(element, _heading_role(local, source_classes))
            after_boundary = True
            continue

        if local == "p":
            role = _paragraph_role(source_classes, after_boundary)
            _replace_classes(element, role)
            after_boundary = False
            continue

        if local in {"div", "figure"}:
            role = _container_role(source_classes)
            if role:
                _replace_classes(element, role)
                after_boundary = role in {"eo-image", "eo-extract"}

        if local == "img":
            parent = element.getparent()
            parent_name = etree.QName(parent).localname.lower() if parent is not None else ""
            if parent_name in {"div", "figure", "p"}:
                _add_class(parent, "eo-image")
            after_boundary = True


def _heading_role(local: str, classes: set[str]) -> str:
    if any(cls.startswith("chapter") for cls in classes):
        return "eo-chapter"
    if "part" in classes:
        return "eo-part"
    if "section" in classes or local not in {"h1"}:
        return "eo-section"
    if classes & {
        "acknowledgments",
        "authorsnote",
        "foreword",
        "preface",
        "introduction",
        "prologue",
        "epilogue",
        "afterward",
        "glossary",
        "appendix",
        "notes",
        "bibliography",
        "abouttheauthor",
        "contents",
        "toc",
    }:
        return "eo-front"
    return "eo-chapter"


def _paragraph_role(classes: set[str], after_boundary: bool) -> str:
    if classes & {"caption"}:
        return "eo-caption"
    if classes & {"center", "center0", "bl_center"}:
        return "eo-centered"
    if classes & {"right", "bl_right", "attribution"}:
        return "eo-right"
    if classes & {"extract", "extract1", "bl_extract", "bl_nonindent", "bl_indent"}:
        return "eo-extract"
    if classes & {"nonindent", "nonindent1"} or after_boundary:
        return "eo-first"
    return "eo-body"


def _container_role(classes: set[str]) -> str | None:
    if classes & {"cover", "titlepage", "dis_img"}:
        return "eo-image"
    if classes & {"block", "textbox", "abstract"}:
        return "eo-extract"
    if classes & {"dedication", "copyright", "toc", "toc_fm", "toc_bm", "toc_chap", "toc_part"}:
        return "eo-centered"
    return None


def _replace_classes(element: etree._Element, class_name: str) -> None:
    element.attrib["class"] = class_name


def _add_class(element: etree._Element, class_name: str) -> None:
    classes = element.attrib.get("class", "").split()
    if class_name not in classes:
        classes.append(class_name)
    element.attrib["class"] = " ".join(classes)
