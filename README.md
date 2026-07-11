# epub-optimizer

A local, Dockerized EPUB optimizer with a small browser GUI.

The app accepts one EPUB at a time, applies a conservative house-style
normalization, and returns a separate `-optimized.epub` download.

## Run

```bash
docker compose up --build
```

Then open:

```text
http://localhost:8000
```

## Development

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
uvicorn epub_optimizer.web:app --reload
```
