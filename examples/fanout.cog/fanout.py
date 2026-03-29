"""MulLet example — scatter/gather with map/reduce.

Demonstrates:
  - MulLet: fan-out N identical children
  - scatter(): distribute work via custom map()
  - gather(): collect results via custom reduce()
  - guide_mapped(): broadcast a command to all children
  - LifeLet: lifecycle hooks
  - listen/transmit: data-plane communication
"""

import asyncio

from coglet import (
    Coglet, LifeLet, CogletConfig, Command, listen, enact,
)
from coglet.mullet import MulLet


class WorkerCoglet(Coglet, LifeLet):
    """Worker that squares an incoming number and transmits the result."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @enact("compute")
    async def on_compute(self, n: int):
        result = n * n
        print(f"  [worker] {n}^2 = {result}")
        await self.transmit("result", result)

    async def on_start(self):
        pass

    async def on_stop(self):
        pass


class AggregatorCoglet(Coglet, LifeLet, MulLet):
    """Fans out work to N workers and gathers/reduces results.

    Uses guide() to send each worker a number, then gathers results.
    """

    NUM_WORKERS = 4

    def reduce(self, results):
        """Sum all squared results."""
        return sum(results)

    async def on_start(self):
        print(f"[aggregator] spawning {self.NUM_WORKERS} workers")
        await self.create_mul(
            self.NUM_WORKERS,
            CogletConfig(cls=WorkerCoglet),
        )

        numbers = list(range(1, self.NUM_WORKERS + 1))  # [1, 2, 3, 4]
        print(f"[aggregator] distributing {numbers} to workers")

        # Subscribe to results BEFORE sending work
        subs = []
        for handle in self._mul_children:
            subs.append(handle.coglet._bus.subscribe("result"))

        # Send one number to each worker via guide
        for i, handle in enumerate(self._mul_children):
            await self.guide(handle, Command("compute", numbers[i]))

        # Gather one result from each subscription
        results = []
        for sub in subs:
            results.append(await sub.get())
        total = self.reduce(results)

        print(f"[aggregator] results: {results}")
        print(f"[aggregator] sum of squares = {total}")
        # Expected: 1+4+9+16 = 30
        await self.transmit("total", total)

    async def on_stop(self):
        print("[aggregator] stopped")
