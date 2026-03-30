"""Unit tests for coglet.weblet: WebLet mixin and CogWebRegistry."""
from __future__ import annotations

import pytest

from coglet import Coglet, CogBase, CogletHandle, CogletRuntime, Command, LifeLet
from coglet.weblet import CogWebNode, CogWebRegistry, WebLet, _node_id


class WebNode(Coglet, WebLet, LifeLet):
    pass


class PlainChild(Coglet, LifeLet):
    pass


class WebChild(Coglet, WebLet, LifeLet):
    pass


class ParentNode(Coglet, WebLet, LifeLet):
    """Spawns a child on start."""
    def __init__(self, child_cls=PlainChild, **kwargs):
        super().__init__(**kwargs)
        self._child_cls = child_cls
        self._child_handle: CogletHandle | None = None

    async def on_start(self):
        await super().on_start()
        self._child_handle = await self.create(CogBase(
            cls=self._child_cls,
            kwargs={"cogweb": self._cogweb} if issubclass(self._child_cls, WebLet) else {},
        ))


# --- CogWebRegistry ---


def test_registry_register_and_snapshot():
    reg = CogWebRegistry()
    cog = WebNode()
    reg.register(cog)
    snap = reg.snapshot()
    nid = _node_id(cog)
    assert nid in snap.nodes
    assert snap.nodes[nid].class_name == "WebNode"


def test_registry_deregister():
    reg = CogWebRegistry()
    cog = WebNode()
    nid = reg.register(cog)
    reg.add_edge(nid, "other", "data")
    reg.deregister(nid)
    assert nid not in reg.snapshot().nodes
    assert len(reg.snapshot().edges) == 0


def test_registry_add_edge():
    reg = CogWebRegistry()
    reg.add_edge("a", "b", "results", kind="data")
    reg.add_edge("a", "b", "results", kind="data")  # duplicate
    assert len(reg.snapshot().edges) == 1


def test_registry_set_status():
    reg = CogWebRegistry()
    cog = WebNode()
    nid = reg.register(cog)
    reg.set_status(nid, "error")
    assert reg.snapshot().nodes[nid].status == "error"


def test_registry_set_status_nonexistent_noop():
    reg = CogWebRegistry()
    reg.set_status("missing", "error")  # no crash


def test_snapshot_to_dict():
    reg = CogWebRegistry()
    cog = WebNode()
    nid = reg.register(cog)
    reg.add_edge(nid, "y", "ch")
    d = reg.snapshot().to_dict()
    assert nid in d["nodes"]
    assert d["nodes"][nid]["class_name"] == "WebNode"
    assert len(d["edges"]) == 1


def test_snapshot_reflects_live_state():
    """Snapshot reads live state, so adding a subscriber shows up."""
    reg = CogWebRegistry()
    cog = WebNode()
    reg.register(cog)
    nid = _node_id(cog)
    # Initially no channels
    assert reg.snapshot().nodes[nid].channels == {}
    # Add a subscriber
    cog._bus.subscribe("test_ch")
    # Snapshot should reflect the change
    assert "test_ch" in reg.snapshot().nodes[nid].channels


# --- WebLet mixin ---


@pytest.mark.asyncio
async def test_weblet_registers_on_start():
    reg = CogWebRegistry()
    rt = CogletRuntime()
    handle = await rt.spawn(CogBase(cls=WebNode, kwargs={"cogweb": reg}))
    assert len(reg.node_ids) == 1
    node = reg.snapshot().nodes[reg.node_ids[0]]
    assert node.class_name == "WebNode"
    assert "WebLet" in node.mixins
    assert "LifeLet" in node.mixins
    assert node.status == "running"
    await rt.shutdown()


@pytest.mark.asyncio
async def test_weblet_deregisters_on_stop():
    reg = CogWebRegistry()
    rt = CogletRuntime()
    await rt.spawn(CogBase(cls=WebNode, kwargs={"cogweb": reg}))
    assert len(reg.node_ids) == 1
    await rt.shutdown()
    assert len(reg.node_ids) == 0


@pytest.mark.asyncio
async def test_weblet_without_registry_is_noop():
    """WebLet without cogweb kwarg should work fine (inert)."""
    rt = CogletRuntime()
    handle = await rt.spawn(CogBase(cls=WebNode))
    assert handle.coglet._cogweb is None
    await rt.shutdown()


@pytest.mark.asyncio
async def test_weblet_tracks_children():
    reg = CogWebRegistry()
    rt = CogletRuntime()
    handle = await rt.spawn(CogBase(
        cls=ParentNode,
        kwargs={"cogweb": reg},
    ))
    parent = handle.coglet
    # Snapshot reads live children from coglet
    snap = reg.snapshot()
    parent_node = snap.nodes[parent._cogweb_node_id]
    assert len(parent_node.children) == 1
    await rt.shutdown()


@pytest.mark.asyncio
async def test_weblet_parent_child_edges():
    """When both parent and child are WebLet, both register and edge exists."""
    reg = CogWebRegistry()
    rt = CogletRuntime()
    handle = await rt.spawn(CogBase(
        cls=ParentNode,
        kwargs={"cogweb": reg, "child_cls": WebChild},
    ))
    snap = reg.snapshot()
    assert len(snap.nodes) == 2
    # Should have control edges from parent to child
    control_edges = [e for e in snap.edges if e["kind"] == "control"]
    assert len(control_edges) >= 1
    await rt.shutdown()


@pytest.mark.asyncio
async def test_weblet_includes_listen_and_enact():
    from coglet.coglet import listen, enact as enact_deco

    class InstrumentedNode(Coglet, WebLet, LifeLet):
        @listen("obs")
        async def handle_obs(self, data):
            pass

        @enact_deco("configure")
        async def handle_configure(self, data):
            pass

    reg = CogWebRegistry()
    rt = CogletRuntime()
    await rt.spawn(CogBase(cls=InstrumentedNode, kwargs={"cogweb": reg}))
    snap = reg.snapshot()
    node = list(snap.nodes.values())[0]
    assert "obs" in node.listen_channels
    assert "configure" in node.enact_commands
    assert "cogweb_status" in node.enact_commands  # from WebLet
    await rt.shutdown()


@pytest.mark.asyncio
async def test_weblet_config_from_runtime():
    reg = CogWebRegistry()
    rt = CogletRuntime()
    await rt.spawn(CogBase(
        cls=WebNode,
        kwargs={"cogweb": reg},
        restart="on_error",
        max_restarts=5,
        backoff_s=2.0,
    ))
    snap = reg.snapshot()
    node = list(snap.nodes.values())[0]
    assert node.config["restart"] == "on_error"
    assert node.config["max_restarts"] == 5
    assert node.config["backoff_s"] == 2.0
    await rt.shutdown()


@pytest.mark.asyncio
async def test_weblet_status_enact():
    reg = CogWebRegistry()
    rt = CogletRuntime()
    handle = await rt.spawn(CogBase(cls=WebNode, kwargs={"cogweb": reg}))
    await handle.coglet._dispatch_enact(Command("cogweb_status", "error"))
    snap = reg.snapshot()
    node = list(snap.nodes.values())[0]
    assert node.status == "error"
    await rt.shutdown()


def test_node_id_stable():
    """_node_id should produce consistent ids for the same instance."""
    cog = WebNode()
    assert _node_id(cog) == _node_id(cog)
    assert _node_id(cog).startswith("WebNode_")
