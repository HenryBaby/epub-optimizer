from __future__ import annotations

import mimetypes
import posixpath
import re
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from lxml import etree

from epub_optimizer.epubcheck import EpubCheckFinding

OPF_NS = "http://www.idpf.org/2007/opf"


def repair_workspace(
    work_dir: Path,
    package_path: str,
    package_tree: etree._ElementTree,
    findings: list[EpubCheckFinding],
) -> list[str]:
    """Apply only deterministic, loss-minimizing EPUB repairs in-place."""
    codes = {finding.code.upper() for finding in findings}
    broken_reference_codes = {"RSC-007", "RSC-012"}
    repair_broken_references = bool(codes & broken_reference_codes)
    repair_missing_manifest_files = "OPF-003" in codes
    repair_missing_manifest_entries = "OPF-012" in codes
    structure_paths = {
        _normalized_package_path(unquote(finding.path))
        for finding in findings
        if finding.code.upper() == "RSC-005"
        and finding.path
        and "text not allowed here" in finding.message.lower()
        and "expected element" in finding.message.lower()
    }
    metadata_findings = [
        finding
        for finding in findings
        if finding.path and _normalized_package_path(unquote(finding.path))
        == _normalized_package_path(package_path)
    ]
    repair_metadata = _repair_opf_metadata(package_tree, metadata_findings)
    affected_paths = {
        _normalized_package_path(unquote(finding.path))
        for finding in findings
        if finding.code.upper() in broken_reference_codes and finding.path
    }
    root = package_tree.getroot()
    manifest = root.find(f"{{{OPF_NS}}}manifest")
    if manifest is None:
        manifest = root.find("manifest")
    if manifest is None:
        return repair_metadata
    package_dir = posixpath.dirname(package_path)
    actions: list[str] = list(repair_metadata)
    items = [e for e in manifest if isinstance(e.tag, str) and etree.QName(e).localname == "item"]
    ncx_paths = {
        _normalized_package_path(unquote(finding.path))
        for finding in findings
        if finding.code.upper() == "NCX-001" and finding.path
    }
    if ("OPF-030" in codes and repair_metadata) or ncx_paths:
        actions.extend(
            _synchronize_ncx_uid(
                work_dir,
                package_dir,
                package_tree,
                items,
                ncx_paths=ncx_paths or None,
            )
        )
    if not (
        repair_broken_references
        or repair_missing_manifest_files
        or repair_missing_manifest_entries
        or structure_paths
    ):
        return actions
    ids = {e.attrib.get("id", "") for e in items}
    missing_items = []
    spine_ids: set[str] = set()
    spine = root.find(f"{{{OPF_NS}}}spine")
    if spine is None:
        spine = root.find("spine")
    if spine is not None:
        spine_ids = {ref.attrib.get("idref", "") for ref in spine}
    for item in items:
        href = item.attrib.get("href")
        if not href:
            continue
        target = _safe_resolve(work_dir, package_dir, href)
        if target is None:
            continue
        if (
            repair_missing_manifest_files
            and not target.is_file()
            and item.attrib.get("id", "") not in spine_ids
        ):
            missing_items.append(item)
    if missing_items:
        missing_ids = {i.attrib.get("id", "") for i in missing_items}
        for item in missing_items:
            href = item.attrib.get("href", "")
            manifest.remove(item)
            actions.append(f"Removed missing manifest item: {href}")
        spine = root.find(f"{{{OPF_NS}}}spine")
        if spine is None:
            spine = root.find("spine")
        if spine is not None:
            for ref in list(spine):
                if ref.attrib.get("idref") in missing_ids:
                    spine.remove(ref)
                    actions.append(f"Removed stale spine reference: {ref.attrib.get('idref', '')}")
        items = [
            e for e in manifest if isinstance(e.tag, str) and etree.QName(e).localname == "item"
        ]
        ids = {e.attrib.get("id", "") for e in items}

    content_items = [
        i
        for i in items
        if i.attrib.get("media-type", "").lower()
        in {"application/xhtml+xml", "text/html", "application/x-dtbook+xml"}
    ]
    for item in content_items:
        href = item.attrib.get("href")
        if not href:
            continue
        rel_path = posixpath.normpath(posixpath.join(package_dir, unquote(href)))
        repair_document_references = (
            repair_broken_references
            and bool(affected_paths)
            and _normalized_package_path(rel_path) in affected_paths
        )
        repair_document_structure = _normalized_package_path(rel_path) in structure_paths
        if (
            not repair_document_references
            and not repair_missing_manifest_entries
            and not repair_document_structure
        ):
            continue
        content_file = _safe_resolve(work_dir, "", rel_path)
        if content_file is None:
            continue
        if not content_file.is_file():
            continue
        try:
            tree = etree.parse(
                str(content_file),
                etree.XMLParser(resolve_entities=False, no_network=True, recover=True),
            )
        except (OSError, etree.XMLSyntaxError):
            continue
        changed = False
        if repair_document_structure:
            structure_actions = _wrap_stray_block_text(tree.getroot(), rel_path)
            actions.extend(structure_actions)
            changed = bool(structure_actions)
        elements = tree.getroot().xpath("//*[@href or @src or @data or @*[local-name()='href']]")
        for element in list(elements):
            attrs = [a for a in ("href", "src", "data") if a in element.attrib]
            attrs.extend(
                a
                for a in element.attrib
                if etree.QName(a).localname == "href" and a not in attrs
            )
            for attr in attrs:
                value = element.attrib.get(attr)
                if not value:
                    continue
                parsed = urlsplit(value)
                if parsed.scheme or parsed.netloc:
                    continue
                if not parsed.path and parsed.fragment:
                    if not repair_document_references:
                        continue
                    if _fragment_exists(content_file, unquote(parsed.fragment)):
                        continue
                    _remove_reference(element, attr, actions, value)
                    changed = True
                    continue
                if not parsed.path:
                    continue
                target_rel = posixpath.normpath(
                    posixpath.join(posixpath.dirname(rel_path), unquote(parsed.path))
                )
                if target_rel.startswith("../") or target_rel.startswith("/"):
                    continue
                target = _safe_resolve(work_dir, "", target_rel)
                if target is None:
                    continue
                if parsed.fragment and (not target.is_file() or _is_html(target_rel)):
                    if target.is_file() and _fragment_exists(target, unquote(parsed.fragment)):
                        continue
                    if not target.is_file() and parsed.path:
                        if not repair_document_references:
                            continue
                        _remove_reference(element, attr, actions, value)
                        changed = True
                    else:
                        element.attrib[attr] = parsed.path or ""
                        actions.append(f"Removed broken fragment: {value}")
                        changed = True
                    continue
                if not target.is_file():
                    if not repair_document_references:
                        continue
                    _remove_reference(element, attr, actions, value)
                    changed = True
                    continue
                if repair_missing_manifest_entries and not _manifest_contains(
                    items, target_rel, package_dir
                ):
                    media = mimetypes.guess_type(target.name)[0]
                    if media:
                        new_id = _unique_id(ids, target.stem or "resource")
                        new_href = posixpath.relpath(target_rel, package_dir or ".")
                        new_item = etree.Element(
                            _qualified_like(manifest, "item"),
                            attrib={"id": new_id, "href": new_href, "media-type": media},
                        )
                        manifest.append(new_item)
                        items.append(new_item)
                        ids.add(new_id)
                        actions.append(f"Added manifest item for referenced resource: {new_href}")
                        changed = True

        if changed:
            tree.write(
                str(content_file), encoding="utf-8", xml_declaration=True, pretty_print=False
            )
    return actions


def _wrap_stray_block_text(root: etree._Element, rel_path: str) -> list[str]:
    actions = []
    block_names = {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "dl",
        "fieldset",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "main",
        "nav",
        "noscript",
        "ol",
        "p",
        "pre",
        "script",
        "section",
        "svg",
        "table",
        "ul",
    }
    containers = root.xpath("//*[local-name()='body' or local-name()='blockquote']")
    for container in containers:
        current_paragraph = None
        if (container.text or "").strip():
            current_paragraph = etree.Element(_qualified_like(container, "p"))
            current_paragraph.text = container.text
            container.text = None
            container.insert(0, current_paragraph)
            actions.append(f"Wrapped stray block text in paragraph: {rel_path}")
        for child in [element for element in list(container) if element is not current_paragraph]:
            local = etree.QName(child).localname.lower()
            if local not in block_names:
                if current_paragraph is None:
                    current_paragraph = etree.Element(_qualified_like(container, "p"))
                    container.insert(container.index(child), current_paragraph)
                    actions.append(f"Wrapped stray inline content in paragraph: {rel_path}")
                container.remove(child)
                current_paragraph.append(child)
                continue
            current_paragraph = None
            if not (child.tail or "").strip():
                continue
            current_paragraph = etree.Element(_qualified_like(container, "p"))
            current_paragraph.text = child.tail
            child.tail = None
            container.insert(container.index(child) + 1, current_paragraph)
            actions.append(f"Wrapped stray block text in paragraph: {rel_path}")
    return actions


def _synchronize_ncx_uid(
    work_dir: Path,
    package_dir: str,
    package_tree: etree._ElementTree,
    items: list[etree._Element],
    *,
    ncx_paths: set[str] | None,
) -> list[str]:
    root = package_tree.getroot()
    identifier_id = root.attrib.get("unique-identifier", "")
    identifiers = root.xpath(
        "//*[local-name()='metadata']/*[local-name()='identifier' and @id=$identifier_id]",
        identifier_id=identifier_id,
    )
    if not identifiers or not (identifiers[0].text or "").strip():
        return []
    identifier = (identifiers[0].text or "").strip()
    actions = []
    for item in items:
        if item.attrib.get("media-type", "").lower() != "application/x-dtbncx+xml":
            continue
        href = item.attrib.get("href", "")
        decoded_href = unquote(href)
        package_path = _normalized_package_path(posixpath.join(package_dir, decoded_href))
        if ncx_paths is not None and package_path not in ncx_paths:
            continue
        ncx_path = _safe_resolve(work_dir, package_dir, decoded_href)
        if ncx_path is None or not ncx_path.is_file():
            continue
        try:
            tree = etree.parse(
                str(ncx_path),
                etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
            )
        except (OSError, etree.XMLSyntaxError):
            continue
        uid_nodes = tree.getroot().xpath(
            "//*[local-name()='meta' and translate(@name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
            "'abcdefghijklmnopqrstuvwxyz')='dtb:uid']"
        )
        if not uid_nodes or uid_nodes[0].attrib.get("content") == identifier:
            continue
        uid_nodes[0].attrib["content"] = identifier
        tree.write(str(ncx_path), encoding="utf-8", xml_declaration=True, pretty_print=False)
        actions.append(f"Synchronized NCX identifier with OPF identifier: {href}")
    return actions


def _repair_opf_metadata(
    package_tree: etree._ElementTree, findings: list[EpubCheckFinding]
) -> list[str]:
    """Conservative, finding-gated repairs for common OPF metadata errors."""
    actions: list[str] = []
    root = package_tree.getroot()
    codes = {f.code.upper() for f in findings}
    metadata = root.find(f"{{{OPF_NS}}}metadata")
    if metadata is None:
        metadata = root.find("metadata")
    if metadata is None:
        return actions
    if "OPF-030" in codes:
        identifiers = [
            e
            for e in metadata
            if etree.QName(e).localname == "identifier" and (e.text or "").strip()
        ]
        if identifiers:
            chosen = next((e for e in identifiers if e.attrib.get("id")), identifiers[0])
            ident = chosen.attrib.get("id")
            if not ident:
                ident = "bookid"
                used = {e.attrib.get("id") for e in metadata if e.attrib.get("id")}
                i = 2
                while ident in used:
                    ident = f"bookid-{i}"
                    i += 1
                chosen.set("id", ident)
                actions.append(f"Assigned stable id to dc:identifier: {ident}")
            root.set("unique-identifier", ident)
            actions.append(f"Pointed package unique-identifier to dc:identifier: {ident}")
    if "OPF-028" in codes:
        prefix_attr = root.attrib.get("prefix", "")
        declared_prefixes = {
            token.rstrip(":") for token in prefix_attr.split()[::2] if token.endswith(":")
        }
        # Calibre's known vocabulary can be declared losslessly. Unknown
        # vendor metadata is preserved and remains a reported legacy issue.
        for finding in findings:
            if finding.code.upper() != "OPF-028":
                continue
            match = re.search(r'prefix:\s*"([A-Za-z][\w-]*)"', finding.message, re.I)
            if not match:
                continue
            prefix = match.group(1)
            if prefix.lower() == "calibre" and prefix not in declared_prefixes:
                declaration = "calibre: https://calibre-ebook.com"
                root.set("prefix", f"{prefix_attr} {declaration}".strip())
                prefix_attr = root.attrib["prefix"]
                declared_prefixes.add(prefix)
                actions.append("Declared known calibre metadata vocabulary")
                continue
    if "RSC-005" in codes:
        invalid_properties = {
            match.group(1)
            for finding in findings
            for match in [re.search(r'Property "([^"]+)" must refine', finding.message)]
            if match
        }
        valid_refinement_targets = {
            "role": {"creator", "contributor", "publisher"},
            "file-as": {"creator", "contributor"},
            "title-type": {"title"},
        }
        for elem in list(metadata):
            if etree.QName(elem).localname != "meta" or "refines" not in elem.attrib:
                continue
            # Only discard malformed refinement metadata; primary dc:* remains intact.
            ref = elem.attrib.get("refines", "")
            prop = elem.attrib.get("property", "")
            target = next((e for e in metadata if e.attrib.get("id") == ref[1:]), None)
            target_is_invalid = False
            allowed_targets = valid_refinement_targets.get(prop)
            if prop in invalid_properties and target is not None and allowed_targets is not None:
                target_is_invalid = etree.QName(target).localname not in allowed_targets
            if (
                not ref.startswith("#")
                or not prop
                or target is None
                or target_is_invalid
            ):
                metadata.remove(elem)
                actions.append("Removed invalid metadata refinement")
    return actions


def _normalized_package_path(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/").lstrip("/"))


def _remove_reference(element, attr, actions, value):
    local = etree.QName(element).localname.lower()
    if local in {"a", "area"} and attr == "href":
        element.attrib.pop(attr, None)
        actions.append(f"Removed broken link target (text preserved): {value}")
    elif local == "img":
        parent = element.getparent()
        if parent is not None:
            alt = element.attrib.get("alt", "").strip()
            if alt:
                replacement = etree.Element(_qualified_like(element, "span"))
                replacement.text = alt
                replacement.tail = element.tail
                parent.replace(element, replacement)
                actions.append(f"Replaced broken image with alt text: {value}")
            else:
                parent.remove(element)
                actions.append(f"Removed broken image without alt text: {value}")
    elif local in {"object", "audio", "video"}:
        element.attrib.pop(attr, None)
        actions.append(f"Removed broken resource attribute; fallback preserved: {value}")
    elif local in {"link", "script", "image", "source"}:
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
            actions.append(f"Removed broken resource element: {value}")
    else:
        element.attrib.pop(attr, None)
        actions.append(f"Removed broken reference: {value}")


def _resolve(work_dir: Path, package_dir: str, href: str) -> Path:
    raw = posixpath.join(package_dir, href)
    if raw.startswith("/") or PurePosixPath(href).is_absolute():
        raise ValueError("absolute EPUB path")
    candidate = (work_dir / Path(*PurePosixPath(posixpath.normpath(raw)).parts)).resolve()
    root = work_dir.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("EPUB path escapes workspace")
    return candidate


def _safe_resolve(work_dir: Path, package_dir: str, href: str) -> Path | None:
    try:
        return _resolve(work_dir, package_dir, href)
    except ValueError:
        return None


def _is_html(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in {".xhtml", ".html", ".htm"}


def _fragment_exists(path: Path, fragment: str) -> bool:
    try:
        root = etree.parse(
            str(path), etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
        ).getroot()
        return bool(root.xpath("//*[@id=$id or @name=$id]", id=fragment))
    except (OSError, etree.XMLSyntaxError):
        return False


def _manifest_contains(items, target_rel: str, package_dir: str) -> bool:
    target = posixpath.normpath(target_rel)
    for item in items:
        href = item.attrib.get("href", "")
        if posixpath.normpath(posixpath.join(package_dir, href)) == target:
            return True
    return False


def _unique_id(ids: set[str], stem: str) -> str:
    base = "optimizer-" + "".join(c if c.isalnum() else "-" for c in stem).strip("-") or "resource"
    candidate = base
    index = 2
    while candidate in ids:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _qualified_like(element, local_name):
    namespace = etree.QName(element).namespace
    return f"{{{namespace}}}{local_name}" if namespace else local_name
