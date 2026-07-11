from __future__ import annotations

import posixpath
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from defusedxml import ElementTree

from epub_optimizer.errors import InvalidEpubError

CONTAINER_PATH = "META-INF/container.xml"
EPUB_MIMETYPE = b"application/epub+zip"


def validate_archive_entry_name(name: str) -> PurePosixPath:
    if not name or name.endswith("/"):
        return PurePosixPath(name)

    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)

    if path.is_absolute() or normalized.startswith("/"):
        raise InvalidEpubError(f"Archive entry uses an absolute path: {name}")
    if ":" in path.parts[0]:
        raise InvalidEpubError(f"Archive entry uses a drive-qualified path: {name}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise InvalidEpubError(f"Archive entry contains an unsafe path segment: {name}")

    return path


def validate_epub_archive(input_path: Path, max_size_bytes: int | None = None) -> None:
    if not input_path.is_file():
        raise InvalidEpubError("Input file does not exist.")
    if input_path.suffix.lower() != ".epub":
        raise InvalidEpubError("Input file must use the .epub extension.")
    if max_size_bytes is not None and input_path.stat().st_size > max_size_bytes:
        raise InvalidEpubError("Input file exceeds the configured maximum upload size.")
    if not zipfile.is_zipfile(input_path):
        raise InvalidEpubError("Input file is not a valid ZIP archive.")

    with zipfile.ZipFile(input_path) as archive:
        names = archive.namelist()
        if "mimetype" not in names:
            raise InvalidEpubError("EPUB archive is missing the mimetype file.")
        if archive.read("mimetype").strip() != EPUB_MIMETYPE:
            raise InvalidEpubError("EPUB mimetype is invalid.")
        if CONTAINER_PATH not in names:
            raise InvalidEpubError("EPUB archive is missing META-INF/container.xml.")
        for info in archive.infolist():
            validate_archive_entry_name(info.filename)


def extract_epub(input_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(input_path) as archive:
        for info in archive.infolist():
            relative = validate_archive_entry_name(info.filename)
            if not str(relative) or info.is_dir():
                continue

            target = destination / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def find_package_document(root: Path) -> str:
    container = root / CONTAINER_PATH
    try:
        tree = ElementTree.parse(container)
    except ElementTree.ParseError as exc:
        raise InvalidEpubError("Could not parse META-INF/container.xml.") from exc

    namespace = {"container": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfile = tree.find(".//container:rootfile", namespace)
    if rootfile is None:
        rootfile = tree.find(".//rootfile")
    if rootfile is None:
        raise InvalidEpubError("container.xml does not declare an OPF rootfile.")

    full_path = rootfile.attrib.get("full-path")
    if not full_path:
        raise InvalidEpubError("OPF rootfile path is empty.")

    validate_archive_entry_name(full_path)
    if not (root / Path(*PurePosixPath(full_path).parts)).is_file():
        raise InvalidEpubError("Declared OPF package document does not exist.")

    return full_path


def make_relative_href(from_file: str, to_file: str) -> str:
    from_dir = posixpath.dirname(from_file)
    rel = posixpath.relpath(to_file, from_dir or ".")
    return rel.replace("\\", "/")


def write_epub(source_dir: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mimetype_path = source_dir / "mimetype"
    if not mimetype_path.is_file():
        raise InvalidEpubError("Cannot write EPUB without a mimetype file.")

    with zipfile.ZipFile(output_path, "w") as archive:
        archive.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file() or path == mimetype_path:
                continue
            arcname = path.relative_to(source_dir).as_posix()
            validate_archive_entry_name(arcname)
            archive.write(path, arcname, compress_type=zipfile.ZIP_DEFLATED)
