from fastapi.testclient import TestClient

from epub_optimizer.web import app


def test_homepage_renders() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "EPUB Optimizer" in response.text
    assert "v0.1.13" in response.text
