"""WebLet mixin — registers a coglet with the CogWeb UI for graph visualization.

When mixed in, a coglet publishes itself to a shared CogWebRegistry. The
registry holds live references and builds fresh snapshots on demand, so the
graph always reflects current state (children, channels, etc.).

Usage:
    class MyNode(Coglet, WebLet, LifeLet):
        async def on_start(self):
            child = await self.create(CogBase(cls=Worker))

    registry = CogWebRegistry()
    rt = CogletRuntime()
    handle = await rt.spawn(CogBase(cls=MyNode, kwargs={"cogweb": registry}))
    print(registry.snapshot().to_dict())  # full graph for UI
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from coglet.coglet import enact
from coglet.handle import CogBase, CogletHandle, Command

if TYPE_CHECKING:
    from coglet.coglet import Coglet


@dataclass
class CogWebNode:
    """Graph node representing a single coglet in the CogWeb UI."""
    node_id: str                         # unique id (e.g. "MyClass_0x7f...")
    class_name: str                      # coglet class name
    mixins: list[str]                    # mixin names (LifeLet, TickLet, etc.)
    channels: dict[str, int]             # channel_name -> subscriber count
    listen_channels: list[str]           # @listen handlers
    enact_commands: list[str]            # @enact handlers
    children: list[str]                  # child node_ids
    parent_id: str | None                # parent node_id
    config: dict[str, Any]               # restart policy etc.
    status: str = "running"              # running | stopped | error
    updated_at: float = 0.0             # monotonic timestamp


@dataclass
class CogWebSnapshot:
    """Full graph snapshot for the UI."""
    nodes: dict[str, CogWebNode] = field(default_factory=dict)
    edges: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON transport to the UI."""
        return {
            "nodes": {k: vars(v) for k, v in self.nodes.items()},
            "edges": self.edges,
        }


def _node_id(coglet: Any) -> str:
    """Stable unique id for a coglet instance."""
    return f"{type(coglet).__name__}_{id(coglet):x}"


def _mixin_names(coglet: Any) -> list[str]:
    """Extract mixin names from the MRO."""
    return [
        cls.__name__
        for cls in type(coglet).__mro__
        if cls.__name__.endswith("Let") and cls.__name__ != "Coglet"
    ]


def _channel_stats(coglet: Any) -> dict[str, int]:
    """Get channel subscriber counts from the bus."""
    subs = getattr(getattr(coglet, "_bus", None), "_subscribers", {})
    return {name: len(sub_list) for name, sub_list in subs.items()}


def _build_node(coglet: Any, parent_id: str | None = None,
                status: str = "running") -> CogWebNode:
    """Build a CogWebNode from a live coglet instance."""
    config: dict[str, Any] = {}
    runtime = getattr(coglet, "_runtime", None)
    if runtime is not None:
        cfg = runtime._configs.get(id(coglet))
        if cfg is not None:
            config = {
                "restart": cfg.restart,
                "max_restarts": cfg.max_restarts,
                "backoff_s": cfg.backoff_s,
            }

    return CogWebNode(
        node_id=_node_id(coglet),
        class_name=type(coglet).__name__,
        mixins=_mixin_names(coglet),
        channels=_channel_stats(coglet),
        listen_channels=list(getattr(coglet, "_listen_handlers", {}).keys()),
        enact_commands=list(getattr(coglet, "_enact_handlers", {}).keys()),
        children=[_node_id(h.coglet) for h in getattr(coglet, "_children", [])],
        parent_id=parent_id,
        config=config,
        status=status,
        updated_at=time.monotonic(),
    )


class CogWebRegistry:
    """Collects live coglet references from all WebLet-enabled coglets.

    Shared across a runtime — pass as kwarg ``cogweb=registry`` to coglets.
    Snapshots are built on demand from live state, so they always reflect
    current children, channels, etc.
    """

    def __init__(self) -> None:
        self._coglets: dict[str, Any] = {}       # node_id -> coglet instance
        self._statuses: dict[str, str] = {}       # node_id -> status
        self._parent_ids: dict[str, str] = {}     # node_id -> parent node_id
        self._edges: list[dict[str, str]] = []

    def register(self, coglet: Any, parent_id: str | None = None) -> str:
        """Register a live coglet. Returns its node_id."""
        nid = _node_id(coglet)
        self._coglets[nid] = coglet
        self._statuses[nid] = "running"
        if parent_id is not None:
            self._parent_ids[nid] = parent_id
        return nid

    def deregister(self, node_id: str) -> None:
        self._coglets.pop(node_id, None)
        self._statuses.pop(node_id, None)
        self._parent_ids.pop(node_id, None)
        self._edges = [e for e in self._edges if
                       e["from"] != node_id and e["to"] != node_id]

    def set_status(self, node_id: str, status: str) -> None:
        if node_id in self._statuses:
            self._statuses[node_id] = status

    def add_edge(self, from_id: str, to_id: str, channel: str,
                 kind: str = "data") -> None:
        """Record a channel edge between two coglets.

        kind: "data" (transmit/listen), "control" (guide/enact),
              "observe" (observe subscription)
        """
        edge = {"from": from_id, "to": to_id,
                "channel": channel, "kind": kind}
        if edge not in self._edges:
            self._edges.append(edge)

    def snapshot(self) -> CogWebSnapshot:
        """Build a fresh graph snapshot from live coglet state."""
        nodes: dict[str, CogWebNode] = {}
        for nid, coglet in self._coglets.items():
            parent_id = self._parent_ids.get(nid)
            status = self._statuses.get(nid, "running")
            nodes[nid] = _build_node(coglet, parent_id=parent_id, status=status)
        return CogWebSnapshot(nodes=nodes, edges=list(self._edges))

    @property
    def node_ids(self) -> list[str]:
        return list(self._coglets.keys())


class WebLet:
    """Mixin: register coglet with CogWeb UI for graph visualization.

    Requires ``cogweb: CogWebRegistry`` passed as a kwarg. If not provided,
    the mixin is inert (no-op) — coglet runs normally without registration.

    Must be mixed with Coglet. Cooperates with LifeLet for start/stop hooks.
    """

    def __init__(self, cogweb: CogWebRegistry | None = None,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cogweb: CogWebRegistry | None = cogweb
        self._cogweb_node_id: str = _node_id(self)

    async def _cogweb_register(self) -> None:
        """Register this coglet with the CogWeb registry."""
        if self._cogweb is None:
            return
        runtime = getattr(self, "_runtime", None)
        parent_id = None
        if runtime is not None:
            parent = runtime._parents.get(id(self))
            if parent is not None:
                parent_id = _node_id(parent)
        self._cogweb.register(self, parent_id=parent_id)
        if parent_id is not None:
            self._cogweb.add_edge(parent_id, self._cogweb_node_id,
                                  "child", kind="control")

    async def _cogweb_deregister(self) -> None:
        """Deregister this coglet from the CogWeb registry."""
        if self._cogweb is None:
            return
        self._cogweb.set_status(self._cogweb_node_id, "stopped")
        self._cogweb.deregister(self._cogweb_node_id)

    # --- LifeLet integration ---

    async def on_start(self) -> None:
        await self._cogweb_register()
        await super().on_start()  # type: ignore[misc]

    async def on_stop(self) -> None:
        await super().on_stop()  # type: ignore[misc]
        await self._cogweb_deregister()

    # --- Enact: UI can request a status update ---

    @enact("cogweb_status")
    async def _weblet_set_status(self, status: str) -> None:
        """Allow COG or UI to set this node's status."""
        if self._cogweb is not None:
            self._cogweb.set_status(self._cogweb_node_id, status)
