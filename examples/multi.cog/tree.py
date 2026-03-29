"""A 3-level coglet tree: Root -> 2 Workers -> 2 Leaves each."""

from coglet import Coglet, LifeLet, TickLet, CogletConfig, every, listen


class LeafCoglet(Coglet, LifeLet, TickLet):
    """Leaf node that ticks and transmits results upward."""

    def __init__(self, name: str = "leaf", **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.tick_count = 0

    async def on_start(self):
        print(f"    [leaf] {self.name} started")

    @every(1, "s")
    async def heartbeat(self):
        self.tick_count += 1
        await self.transmit("pulse", {"leaf": self.name, "tick": self.tick_count})
        print(f"    [leaf] {self.name} tick {self.tick_count}")

    async def on_stop(self):
        print(f"    [leaf] {self.name} stopped (ticked {self.tick_count}x)")


class WorkerCoglet(Coglet, LifeLet):
    """Mid-level node that spawns leaf children."""

    def __init__(self, name: str = "worker", num_leaves: int = 2, **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.num_leaves = num_leaves

    async def on_start(self):
        print(f"  [worker] {self.name} started, spawning {self.num_leaves} leaves")
        for i in range(self.num_leaves):
            leaf_name = f"{self.name}/leaf-{i}"
            await self.create(CogletConfig(
                cls=LeafCoglet,
                kwargs={"name": leaf_name},
            ))

    async def on_child_error(self, handle, error):
        print(f"  [worker] {self.name} child error: {error}, restarting")
        return "restart"

    async def on_stop(self):
        print(f"  [worker] {self.name} stopped")


class RootCoglet(Coglet, LifeLet):
    """Root node that spawns worker children."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def on_start(self):
        print("[root] started, spawning 2 workers")
        for i in range(2):
            await self.create(CogletConfig(
                cls=WorkerCoglet,
                kwargs={"name": f"worker-{i}", "num_leaves": 2},
            ))
        print("[root] tree ready")

    async def on_child_error(self, handle, error):
        print(f"[root] child error: {error}, restarting")
        return "restart"

    async def on_stop(self):
        print("[root] stopped")
