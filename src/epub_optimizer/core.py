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

        canonical_css_package_href = _ensure_canonical_css(work_dir, package_dir_path)
        canonical_item_href = _relative_from_package_dir(package_dir, canonical_css_package_href)
        stylesheets_replaced = _replace_removable_manifest_items(
            manifest,
            removable_hrefs,
            canonical_item_href,
        )
        removed_files = _delete_package_files(work_dir, package_dir, removable_hrefs)
        log.append(f"Removed {stylesheets_replaced} old style/font manifest item(s).")
        if removed_files:
            log.append(f"Deleted {removed_files} old style/font file(s).")

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
                _document_role(item),
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


def _join_package_path(package_dir: str, href: str) -> str:
    joined = posixpath.normpath(posixpath.join(package_dir, href))
    if joined.startswith("../") or joined == ".." or joined.startswith("/"):
        raise InvalidEpubError(f"Manifest href escapes the EPUB root: {href}")
    return joined


def _process_content_document(
    content_file: Path,
    content_package_path: str,
    canonical_css_package_href: str,
    document_role: str,
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
    _strip_publisher_presentation(root)
    _unwrap_font_elements(root)
    _normalize_inline_spans(root)
    _classify_blocks(root, document_role)
    _strip_unclassified_classes(root)
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


def _strip_publisher_presentation(root: etree._Element) -> None:
    for element in root.xpath("//*"):
        for attr in list(element.attrib):
            local_attr = attr.rsplit("}", 1)[-1].lower()
            if local_attr in PRESENTATION_ATTRS:
                del element.attrib[attr]


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
        if classes & {"bold"}:
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
        elif classes & {"smallcaps", "small-cap", "small-caps"}:
            _replace_classes(span, "eo-smallcaps")
        else:
            span.attrib.pop("class", None)


def _rename_element(element: etree._Element, local_name: str) -> None:
    namespace = etree.QName(element).namespace
    element.tag = f"{{{namespace}}}{local_name}" if namespace else local_name


def _classify_blocks(root: etree._Element, document_role: str) -> None:
    after_boundary = True
    is_front_matter = document_role == "front"
    for element in root.xpath("//*[local-name()='body']//*[self::*]"):
        local = etree.QName(element).localname.lower()
        source_classes = set(element.attrib.get("class", "").lower().split())

        if local in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            _replace_classes(element, _heading_role(local, source_classes, is_front_matter))
            after_boundary = True
            continue

        if local in {"ol", "ul"}:
            _replace_classes(element, "eo-list")
            after_boundary = True
            continue

        if local == "blockquote":
            _replace_classes(element, "eo-blockquote")
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
            role = _paragraph_role(element, source_classes, after_boundary, is_front_matter)
            _replace_classes(element, role)
            after_boundary = role in {
                "eo-caption",
                "eo-centered",
                "eo-extract",
                "eo-footnote",
                "eo-image",
                "eo-poetry",
                "eo-scene-break",
            }
            continue

        if local == "div" and _is_direct_body_child(element):
            container_role = _container_role(source_classes)
            role = container_role or _anonymous_div_role(element, after_boundary, document_role)
            if role:
                if role in {"eo-chapter", "eo-part", "eo-front", "eo-section"}:
                    _rename_element(element, "h1")
                    _replace_classes(element, role)
                    after_boundary = True
                else:
                    _rename_element(element, "p")
                    _replace_classes(element, role)
                    after_boundary = role in {
                        "eo-caption",
                        "eo-centered",
                        "eo-extract",
                        "eo-footnote",
                        "eo-image",
                        "eo-poetry",
                        "eo-scene-break",
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
    if "part" in classes:
        return "eo-part"
    if is_front_matter or classes & FRONT_MATTER_HINTS:
        return "eo-front"
    if any(cls.startswith("chapter") for cls in classes):
        return "eo-chapter"
    if "section" in classes or local not in {"h1"}:
        return "eo-section"
    return "eo-chapter"


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
    if classes & {"caption", "figcaption"}:
        return "eo-caption"
    if classes & {"center", "center0", "bl_center"}:
        return "eo-centered"
    if classes & {"right", "bl_right", "attribution"}:
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


def _container_role(classes: set[str]) -> str | None:
    if classes & {"part"}:
        return "eo-part"
    if classes & {"cover", "titlepage", "dis_img"}:
        return "eo-image"
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
    if classes & {"toc", "toc_fm", "toc_bm", "toc_chap", "toc_part", "toc_sub"}:
        return "eo-toc"
    if classes & {"copyright", "otherbooks", "titlepage"}:
        return "eo-centered"
    return None


def _contains_direct_image(element: etree._Element) -> bool:
    return any(etree.QName(child).localname.lower() == "img" for child in element)


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
    if _has_block_children(element):
        return None

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
    return any(etree.QName(child).localname.lower() in block_names for child in element)


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


def _normalized_text(element: etree._Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _is_short_heading_text(text: str) -> bool:
    words = text.split()
    return len(text) <= 120 and len(words) <= 14


def _is_scene_break(element: etree._Element) -> bool:
    text = _normalized_text(element)
    return text in {"*", "* * *", "***", "****", "*****"}


def _document_role(item: etree._Element) -> str:
    values = " ".join(
        [
            item.attrib.get("id", ""),
            item.attrib.get("href", ""),
            item.attrib.get("properties", ""),
        ]
    ).lower()
    if any(hint in values for hint in FRONT_MATTER_HINTS):
        return "front"
    if "part" in values:
        return "part"
    if "chapter" in values or "/chap" in values or "/ch" in values:
        return "chapter"
    return "body"


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
