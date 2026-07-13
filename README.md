# EPUB Optimizer

A local, Dockerized web app for normalizing EPUB files into a consistent house
style.

EPUB Optimizer accepts one or more `.epub` files, processes them locally, and
returns separate `-optimized.epub` downloads. It is built for predictable,
conservative cleanup rather than aggressive rewriting.

![EPUB Optimizer UI showcase](assets/ui-showcase.png)

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
pyproject.toml version = 1.0.6
git tag v1.0.6
git push origin v1.0.6
```

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
