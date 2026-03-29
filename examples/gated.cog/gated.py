"""SuppressLet example — COG gates a chatty sensor's output.

Demonstrates:
  - SuppressLet: suppress/unsuppress channels at runtime
  - COG controls when a LET's output is visible
  - TickLet: sensor emits data every second
  - LifeLet: lifecycle hooks
  - Subsumption-style architecture: higher layer gates lower
"""

import asyncio

from coglet import (
    Coglet, LifeLet, TickLet, CogletConfig, Command, every,
)
from coglet.suppresslet import SuppressLet


class NoisySensor(SuppressLet, Coglet, LifeLet, TickLet):
    """A sensor that transmits readings every second.

    SuppressLet goes first in MRO so it can gate transmit().
    The sensor keeps running internally even when suppressed.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tick_count = 0

    async def on_start(self):
        print("  [sensor] started (output ON)")

    @every(1, "s")
    async def emit(self):
        self.tick_count += 1
        await self.transmit("readings", {"tick": self.tick_count, "value": self.tick_count * 7})
        # This print always fires — suppression only affects transmit
        print(f"  [sensor] internal tick {self.tick_count}")

    async def on_stop(self):
        print(f"  [sensor] stopped after {self.tick_count} ticks")


class ControllerCoglet(Coglet, LifeLet):
    """Supervisor that toggles sensor output on and off.

    Timeline:
      0s: sensor starts, output ON
      2s: suppress "readings" channel (output gated)
      4s: unsuppress (output resumes)
    """

    async def on_start(self):
        print("[controller] spawning noisy sensor")
        self.sensor = await self.create(CogletConfig(cls=NoisySensor))

        # Watch the readings channel
        asyncio.create_task(self._watch())

        # Toggle suppression
        asyncio.create_task(self._toggle())

    async def _watch(self):
        async for data in self.observe(self.sensor, "readings"):
            print(f"[controller] received: {data}")

    async def _toggle(self):
        await asyncio.sleep(2)
        print("[controller] SUPPRESSING sensor output")
        await self.guide(
            self.sensor,
            Command("suppress", {"channels": ["readings"]}),
        )

        await asyncio.sleep(2)
        print("[controller] UNSUPPRESSING sensor output")
        await self.guide(
            self.sensor,
            Command("unsuppress", {"channels": ["readings"]}),
        )

    async def on_stop(self):
        print("[controller] stopped")
