import asyncio
import pytest
from coglet import Coglet, CogletRuntime, CogletConfig, CogletHandle, listen
from coglet.pco.loss import LossCoglet


class ScoreLoss(LossCoglet):
    async def compute_loss(self, experience, evaluation):
        return {"name": "score", "magnitude": evaluation["score"]}


@pytest.mark.asyncio
async def test_loss_coglet_emits_signal():
    runtime = CogletRuntime()
    handle = await runtime.spawn(CogletConfig(cls=ScoreLoss))
    coglet = handle.coglet

    signals = []
    async def collect():
        async for s in handle.observe("signal"):
            signals.append(s)
            break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.01)

    await coglet._dispatch_listen("experience", {"replay": "data"})
    await coglet._dispatch_listen("evaluation", {"score": 42})

    await asyncio.wait_for(task, timeout=1.0)
    assert signals[0]["name"] == "score"
    assert signals[0]["magnitude"] == 42
    await runtime.shutdown()
