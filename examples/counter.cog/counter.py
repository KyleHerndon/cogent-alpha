"""Counter — transmits incrementing numbers on the 'count' channel."""

from coglet import Coglet, LifeLet, TickLet, every


class CounterCoglet(Coglet, LifeLet, TickLet):
    def __init__(self, interval: int = 1, **kwargs):
        super().__init__(**kwargs)
        self.n = 0

    async def on_start(self):
        print("[counter] started")

    @every(1, "s")
    async def tick(self):
        self.n += 1
        await self.transmit("count", self.n)

    async def on_stop(self):
        print(f"[counter] stopped at {self.n}")
