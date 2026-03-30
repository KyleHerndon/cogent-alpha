"""Tests for cogweb.ui server — REST API and WebSocket graph endpoint."""
from __future__ import annotations

import json

import pytest

from coglet import Coglet, CogBase, CogletRuntime, LifeLet
from coglet.weblet import CogWebRegistry, WebLet
from cogweb.ui.server import CogWebUI, _STATIC_DIR


class WebNode(Coglet, WebLet, LifeLet):
    pass


# --- Static file ---


def test_static_index_exists():
    index = _STATIC_DIR / "index.html"
    assert index.exists()
    content = index.read_text()
    assert "CogWeb" in content


# --- REST API via test client ---


@pytest.fixture
def registry_with_node():
    """Create a registry with one manually registered coglet."""
    reg = CogWebRegistry()
    cog = WebNode(cogweb=reg)
    cog._runtime = None
    reg.register(cog)
    return reg


@pytest.fixture
def app(registry_with_node):
    ui = CogWebUI(registry_with_node)
    return ui._build_app()


def test_api_graph_returns_snapshot(app, registry_with_node):
    from starlette.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/api/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 1
    node = list(data["nodes"].values())[0]
    assert node["class_name"] == "WebNode"


def test_index_serves_html(app):
    from starlette.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "CogWeb" in resp.text


def test_ws_receives_initial_snapshot(app, registry_with_node):
    from starlette.testclient import TestClient
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert len(msg["data"]["nodes"]) == 1


def test_ws_refresh_command(app, registry_with_node):
    from starlette.testclient import TestClient
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        # Consume initial snapshot
        ws.receive_json()
        # Send refresh
        ws.send_text(json.dumps({"type": "refresh"}))
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"


def test_ws_ping_pong(app):
    from starlette.testclient import TestClient
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # initial snapshot
        ws.send_text(json.dumps({"type": "ping"}))
        msg = ws.receive_json()
        assert msg["type"] == "pong"


def test_ws_invalid_json(app):
    from starlette.testclient import TestClient
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # initial snapshot
        ws.send_text("not json")
        msg = ws.receive_json()
        assert msg["type"] == "error"


# --- Integration with runtime ---


@pytest.mark.asyncio
async def test_runtime_integration():
    """Full pipeline: runtime → WebLet → registry → UI snapshot."""
    reg = CogWebRegistry()
    rt = CogletRuntime()
    handle = await rt.spawn(CogBase(cls=WebNode, kwargs={"cogweb": reg}))

    ui = CogWebUI(reg)
    app = ui._build_app()

    from starlette.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/api/graph")
    data = resp.json()
    assert len(data["nodes"]) == 1
    node = list(data["nodes"].values())[0]
    assert node["class_name"] == "WebNode"
    assert node["status"] == "running"

    await rt.shutdown()

    # After shutdown, node is deregistered
    resp = client.get("/api/graph")
    data = resp.json()
    assert len(data["nodes"]) == 0
