"""LogLet example — supervisor monitors child log streams.

Demonstrates:
  - LogLet: structured log channel with level filtering
  - guide() to change log level at runtime
  - observe() to subscribe to a child's log channel
  - TickLet: child emits logs periodically
  - LifeLet: lifecycle hooks
"""

import asyncio

from coglet import (
    Coglet, LifeLet, TickLet, LogLet, CogletConfig, Command, every,
)


class SensorCoglet(Coglet, LifeLet, TickLet, LogLet):
    """A sensor that logs at various levels each tick."""

    def __init__(self, name: str = "sensor", **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.reading = 0

    async def on_start(self):
        await self.log("info", f"{self.name} started")

    @every(1, "s")
    async def sample(self):
        self.reading += 10
        await self.log("debug", f"{self.name} raw={self.reading}")
        await self.log("info", f"{self.name} reading={self.reading}")
        if self.reading >= 50:
            await self.log("warn", f"{self.name} high reading: {self.reading}")
        await self.transmit("data", {"sensor": self.name, "value": self.reading})

    async def on_stop(self):
        await self.log("info", f"{self.name} stopped")


class SupervisorCoglet(Coglet, LifeLet):
    """Spawns a sensor, watches its logs, and adjusts verbosity."""

    async def on_start(self):
        print("[supervisor] spawning sensor")
        config = CogletConfig(cls=SensorCoglet, kwargs={"name": "temp-1"})
        self.sensor = await self.create(config)

        # Watch logs in a background task
        asyncio.create_task(self._watch_logs())

        # After 3s, switch sensor to debug level for more detail
        asyncio.create_task(self._adjust_level())

    async def _watch_logs(self):
        async for entry in self.observe(self.sensor, "log"):
            level = entry["level"].upper()
            data = entry["data"]
            print(f"[supervisor] LOG [{level}] {data}")

    async def _adjust_level(self):
        await asyncio.sleep(3)
        print("[supervisor] switching sensor to DEBUG level")
        await self.guide(self.sensor, Command("log_level", "debug"))

    async def on_stop(self):
        print("[supervisor] stopped")
