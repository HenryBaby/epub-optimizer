"""Manual Grimmory routes exercise an injected manager, never a live API."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from epub_optimizer.grimmory import GrimmoryValidationError
from epub_optimizer.web import app


@pytest.fixture
def grimmory():
    status = {
        "connected": False,
        "libraries": [],
        "job": None,
        "history": [],
        "snapshots": [],
    }
    manager = Mock()
    manager.status.return_value = status
    for action in ("connect", "preview", "start", "restore", "cancel", "close"):
        setattr(manager, action, AsyncMock(return_value=status))
    app.state.grimmory_manager = manager
    yield TestClient(app), manager
    del app.state.grimmory_manager


def test_home_and_status_do_not_start_library_work(grimmory):
    client, manager = grimmory
    response = client.get("/")
    assert response.status_code == 200
    assert 'data-tab="grimmory"' in response.text
    assert 'id="grimmory-password" type="password"' in response.text
    assert "excludes the Grimmory database and application state" in response.text
    manager.status.assert_not_called()
    assert client.get("/grimmory").json()["connected"] is False
    for action in ("connect", "preview", "start", "restore", "cancel"):
        getattr(manager, action).assert_not_awaited()
    assert client.get("/grimmory").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("action", ["connect", "preview", "start", "restore", "cancel"])
def test_grimmory_actions_are_post_only(grimmory, action):
    client, manager = grimmory
    assert client.get(f"/grimmory/{action}").status_code == 405
    getattr(manager, action).assert_not_awaited()


@pytest.mark.parametrize("body", ["{", "[]", "null", '"text"'])
def test_invalid_grimmory_json_is_rejected(grimmory, body):
    client, manager = grimmory
    response = client.post("/grimmory/start", content=body)
    assert response.status_code == 400
    manager.start.assert_not_awaited()


@pytest.mark.parametrize("action", ["connect", "preview", "start", "restore", "cancel"])
@pytest.mark.parametrize(
    "origin", ["https://evil.example", "null", "http://testserver.evil", "http://["]
)
def test_cross_origin_grimmory_actions_rejected(grimmory, action, origin):
    client, manager = grimmory
    response = client.post(f"/grimmory/{action}", json={}, headers={"Origin": origin})
    assert response.status_code == 403
    getattr(manager, action).assert_not_awaited()


@pytest.mark.parametrize(
    ("action", "payload"),
    [
        (
            "connect",
            {"base_url": "http://grimmory:6060", "username": "reader", "password": "secret"},
        ),
        (
            "preview",
            {"mappings": [{"library_id": 7, "remote_path": "/books", "local_path": "/library"}]},
        ),
        ("start", {"plan_id": "plan-1", "maintenance_confirmed": True}),
        ("restore", {"snapshot_id": "snapshot-1", "maintenance_confirmed": True}),
    ],
)
def test_explicit_actions_pass_payload_to_manager(grimmory, action, payload):
    client, manager = grimmory
    response = client.post(
        f"/grimmory/{action}", json=payload, headers={"Origin": "http://testserver"}
    )
    assert response.status_code == 200
    getattr(manager, action).assert_awaited_once_with(payload)
    assert "secret" not in response.text


def test_cancel_has_no_implicit_start(grimmory):
    client, manager = grimmory
    assert client.post("/grimmory/cancel", json={}).status_code == 200
    manager.cancel.assert_awaited_once_with()
    manager.start.assert_not_awaited()


@pytest.mark.parametrize("error,code", [(ValueError, 400), (RuntimeError, 409), (OSError, 502)])
def test_grimmory_errors_never_echo_credentials(grimmory, error, code):
    client, manager = grimmory
    manager.connect.side_effect = error("password=secret remote server dump")
    response = client.post("/grimmory/connect", json={"password": "secret"})
    assert response.status_code == code
    assert "secret" not in response.text
    assert "remote server dump" not in response.text


def test_oversize_grimmory_request_rejected(grimmory):
    client, manager = grimmory
    response = client.post("/grimmory/connect", json={"password": "x" * 65536})
    assert response.status_code == 413
    manager.connect.assert_not_awaited()


def test_safe_manager_validation_reason_is_visible(grimmory):
    client, manager = grimmory
    manager.start.side_effect = GrimmoryValidationError("Disable Grimmory library watching first.")
    response = client.post("/grimmory/start", json={"plan_id": "preview"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Disable Grimmory library watching first."


def test_lifespan_closes_grimmory_without_starting_work(grimmory, monkeypatch):
    _, manager = grimmory
    automation = Mock(start=AsyncMock(), stop=AsyncMock())
    monkeypatch.setattr(app.state, "automation_manager", automation, raising=False)
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
    manager.close.assert_awaited_once_with()
    manager.connect.assert_not_awaited()
    manager.preview.assert_not_awaited()
    manager.start.assert_not_awaited()
