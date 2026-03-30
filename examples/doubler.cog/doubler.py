"""Doubler — listens on 'count', doubles the value, transmits on 'doubled'."""

from coglet import Coglet, LifeLet, listen


class DoublerCoglet(Coglet, LifeLet):
    async def on_start(self):
        print("[doubler] started")

    @listen("count")
    async def on_count(self, n):
        result = n * 2
        await self.transmit("doubled", result)

    async def on_stop(self):
        print("[doubler] stopped")
