# EPUB Optimizer

A local, Dockerized web app for normalizing EPUB files into a consistent house
style.

EPUB Optimizer accepts one or more `.epub` files, processes them locally, and
returns separate `-optimized.epub` downloads. It is built for predictable,
conservative cleanup rather than aggressive rewriting.

![EPUB Optimizer UI showcase](assets/ui-showcase-1.1.0.png)

## What It Does

- supports EPUB 2 and EPUB 3
- replaces publisher-specific CSS with one canonical stylesheet
- removes embedded font and old stylesheet package entries
- normalizes body text, headings, title pages, metadata pages, tables of
  contents, images, extracts, quotes, and front matter
- preserves readable text, spine order, metadata, navigation, links, anchors,
  inline emphasis, and image resources
- keeps image bytes unchanged
- writes a valid EPUB with the required uncompressed `mimetype` entry first

It does not remove DRM, rewrite book text, strip metadata, recompress images,
fetch remote resources, upload books anywhere, or overwrite the original EPUB.

## Run

```bash
docker compose pull
docker compose up -d
```

Open:

```text
http://localhost:4200
```

The default Compose file mounts:

- `/data` for app state and temporary manual downloads
- `/watch` for optional watched-folder automation input
- `/output` for optimized files produced by automation
- `/unprocessed` for successfully processed source EPUBs, cleaned after 30 days
- `/failed` for failed automation inputs and error reports

Replace the `/output` mount with your library manager bookdrop folder when using
automation. Manual downloads and ZIP archives are removed from `/data` after
they are served.

## Local Docker Build

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up --build
```

## Published Images

GitHub Actions validates Docker builds on pull requests and pushes to `main`.
Pushing a matching version tag publishes the image:

```text
pyproject.toml version = 1.2.0
git tag v1.2.0
git push origin v1.2.0
```

## EPUBCheck assurance

When available, the optimizer runs official EPUBCheck 5.3.0 before and after
optimization. It first performs bounded deterministic repairs for supported
local-reference, manifest, and OPF metadata errors. The final result is marked
`clean` when no errors remain, or `legacy_issues` when only errors already
present in the input persist. Optimization fails if it introduces a new
EPUBCheck error. Repair actions and the validation outcome are recorded in the
result and META-INF report. Warnings and clearly reported legacy errors remain
non-blocking.
If EPUBCheck is unavailable, the result explicitly reports `unavailable` and
the existing structural validation still runs.

Set `EPUBCHECK_EXECUTABLE` to a CLI executable, or `EPUBCHECK_JAR` and `JAVA`
to use the official JAR. `EPUBCHECK_TIMEOUT` may be used by integrations to
bound subprocess execution. The Docker image bundles EPUBCheck 5.3.0 and a
Debian default headless OpenJDK runtime; see `THIRD_PARTY_NOTICES.md` for provenance and
licenses.

Published tags:

```text
ghcr.io/henrybaby/epub-optimizer:X.Y.Z
ghcr.io/henrybaby/epub-optimizer:latest
```

## Development

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m ruff check .
python -m pytest
uvicorn epub_optimizer.web:app --reload --port 4200
```
