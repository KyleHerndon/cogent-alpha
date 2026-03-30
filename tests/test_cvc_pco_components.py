"""Tests for CvC PCO components: critic, losses, constraints."""

import asyncio
from dataclasses import dataclass

import pytest
from coglet import CogBase, CogletRuntime

from cvc.critic import CvCCritic
from cvc.losses import ResourceLoss, JunctionLoss, SurvivalLoss
from cvc.constraints import SyntaxConstraint, SafetyConstraint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SNAPSHOTS = [
    {
        "step": 100, "hp": 80, "hearts": 2,
        "resources": {"carbon": 10, "oxygen": 5, "germanium": 3, "silicon": 2},
        "junctions": {"friendly": 3, "enemy": 1, "neutral": 2},
    },
    {
        "step": 200, "hp": 0, "hearts": 1,
        "resources": {"carbon": 15, "oxygen": 8, "germanium": 5, "silicon": 3},
        "junctions": {"friendly": 2, "enemy": 4, "neutral": 0},
    },
    {
        "step": 300, "hp": 50, "hearts": 1,
        "resources": {"carbon": 20, "oxygen": 10, "germanium": 7, "silicon": 5},
        "junctions": {"friendly": 4, "enemy": 2, "neutral": 1},
    },
]


@dataclass
class FakeProgram:
    """Mimics a Program with a source attribute for constraint tests."""
    source: str


# ---------------------------------------------------------------------------
# Critic tests
# ---------------------------------------------------------------------------

class TestCvCCritic:

    @pytest.mark.asyncio
    async def test_evaluate_total_resources(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=CvCCritic))
        critic = handle.coglet

        evaluations = []
        async def collect():
            async for ev in handle.observe("evaluation"):
                evaluations.append(ev)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        await critic._dispatch_listen("experience", SNAPSHOTS)
        await asyncio.wait_for(task, timeout=1.0)

        # total_resources = (10+5+3+2) + (15+8+5+3) + (20+10+7+5) = 20+31+42 = 93
        assert evaluations[0]["total_resources"] == 93
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_evaluate_junction_control(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=CvCCritic))
        critic = handle.coglet

        evaluations = []
        async def collect():
            async for ev in handle.observe("evaluation"):
                evaluations.append(ev)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        await critic._dispatch_listen("experience", SNAPSHOTS)
        await asyncio.wait_for(task, timeout=1.0)

        # junction_control = (3-1) + (2-4) + (4-2) = 2 + (-2) + 2 = 2
        assert evaluations[0]["junction_control"] == 2
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_evaluate_deaths(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=CvCCritic))
        critic = handle.coglet

        evaluations = []
        async def collect():
            async for ev in handle.observe("evaluation"):
                evaluations.append(ev)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        await critic._dispatch_listen("experience", SNAPSHOTS)
        await asyncio.wait_for(task, timeout=1.0)

        # one snapshot with hp == 0
        assert evaluations[0]["deaths"] == 1
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_evaluate_final_hp(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=CvCCritic))
        critic = handle.coglet

        evaluations = []
        async def collect():
            async for ev in handle.observe("evaluation"):
                evaluations.append(ev)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        await critic._dispatch_listen("experience", SNAPSHOTS)
        await asyncio.wait_for(task, timeout=1.0)

        assert evaluations[0]["final_hp"] == 50
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_update_is_noop(self):
        """The update channel must not raise or produce output."""
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=CvCCritic))
        critic = handle.coglet
        await critic._dispatch_listen("update", {"some": "patch"})
        await runtime.shutdown()


# ---------------------------------------------------------------------------
# Loss tests
# ---------------------------------------------------------------------------

class TestResourceLoss:

    @pytest.mark.asyncio
    async def test_high_resources_low_loss(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=ResourceLoss))
        coglet = handle.coglet

        signals = []
        async def collect():
            async for s in handle.observe("signal"):
                signals.append(s)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        await coglet._dispatch_listen("experience", SNAPSHOTS)
        await coglet._dispatch_listen("evaluation", {"total_resources": 93})
        await asyncio.wait_for(task, timeout=1.0)

        assert signals[0]["name"] == "resource"
        assert signals[0]["magnitude"] == 7  # max(0, 100-93)
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_over_100_resources_zero_loss(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=ResourceLoss))
        coglet = handle.coglet

        signals = []
        async def collect():
            async for s in handle.observe("signal"):
                signals.append(s)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        await coglet._dispatch_listen("experience", SNAPSHOTS)
        await coglet._dispatch_listen("evaluation", {"total_resources": 200})
        await asyncio.wait_for(task, timeout=1.0)

        assert signals[0]["magnitude"] == 0
        await runtime.shutdown()


class TestJunctionLoss:

    @pytest.mark.asyncio
    async def test_positive_control_zero_loss(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=JunctionLoss))
        coglet = handle.coglet

        signals = []
        async def collect():
            async for s in handle.observe("signal"):
                signals.append(s)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        await coglet._dispatch_listen("experience", SNAPSHOTS)
        await coglet._dispatch_listen("evaluation", {"junction_control": 2})
        await asyncio.wait_for(task, timeout=1.0)

        assert signals[0]["name"] == "junction"
        assert signals[0]["magnitude"] == 0
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_negative_control_positive_loss(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=JunctionLoss))
        coglet = handle.coglet

        signals = []
        async def collect():
            async for s in handle.observe("signal"):
                signals.append(s)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        await coglet._dispatch_listen("experience", SNAPSHOTS)
        await coglet._dispatch_listen("evaluation", {"junction_control": -5})
        await asyncio.wait_for(task, timeout=1.0)

        assert signals[0]["magnitude"] == 5
        await runtime.shutdown()


class TestSurvivalLoss:

    @pytest.mark.asyncio
    async def test_deaths_magnitude(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=SurvivalLoss))
        coglet = handle.coglet

        signals = []
        async def collect():
            async for s in handle.observe("signal"):
                signals.append(s)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        await coglet._dispatch_listen("experience", SNAPSHOTS)
        await coglet._dispatch_listen("evaluation", {"deaths": 3})
        await asyncio.wait_for(task, timeout=1.0)

        assert signals[0]["name"] == "survival"
        assert signals[0]["magnitude"] == 3
        await runtime.shutdown()


# ---------------------------------------------------------------------------
# Constraint tests
# ---------------------------------------------------------------------------

class TestSyntaxConstraint:

    @pytest.mark.asyncio
    async def test_accepts_valid_python(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=SyntaxConstraint))
        coglet = handle.coglet

        verdicts = []
        async def collect():
            async for v in handle.observe("verdict"):
                verdicts.append(v)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)

        patch = {"choose_action": FakeProgram(source="x = 1 + 2\nreturn x")}
        await coglet._dispatch_listen("update", patch)
        await asyncio.wait_for(task, timeout=1.0)

        assert verdicts[0]["accepted"] is True
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_rejects_invalid_python(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=SyntaxConstraint))
        coglet = handle.coglet

        verdicts = []
        async def collect():
            async for v in handle.observe("verdict"):
                verdicts.append(v)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)

        patch = {"choose_action": FakeProgram(source="def broken(:\n  pass")}
        await coglet._dispatch_listen("update", patch)
        await asyncio.wait_for(task, timeout=1.0)

        assert verdicts[0]["accepted"] is False
        assert "syntax error" in verdicts[0]["reason"]
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_ignores_non_program_values(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=SyntaxConstraint))
        coglet = handle.coglet

        verdicts = []
        async def collect():
            async for v in handle.observe("verdict"):
                verdicts.append(v)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)

        patch = {"some_key": "just a string", "number": 42}
        await coglet._dispatch_listen("update", patch)
        await asyncio.wait_for(task, timeout=1.0)

        assert verdicts[0]["accepted"] is True
        await runtime.shutdown()


class TestSafetyConstraint:

    @pytest.mark.asyncio
    async def test_accepts_safe_code(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=SafetyConstraint))
        coglet = handle.coglet

        verdicts = []
        async def collect():
            async for v in handle.observe("verdict"):
                verdicts.append(v)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)

        patch = {"act": FakeProgram(source="return obs['hp'] * 2")}
        await coglet._dispatch_listen("update", patch)
        await asyncio.wait_for(task, timeout=1.0)

        assert verdicts[0]["accepted"] is True
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_rejects_eval(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=SafetyConstraint))
        coglet = handle.coglet

        verdicts = []
        async def collect():
            async for v in handle.observe("verdict"):
                verdicts.append(v)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)

        patch = {"act": FakeProgram(source="eval('dangerous')")}
        await coglet._dispatch_listen("update", patch)
        await asyncio.wait_for(task, timeout=1.0)

        assert verdicts[0]["accepted"] is False
        assert "dangerous construct" in verdicts[0]["reason"]
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_rejects_exec(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=SafetyConstraint))
        coglet = handle.coglet

        verdicts = []
        async def collect():
            async for v in handle.observe("verdict"):
                verdicts.append(v)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)

        patch = {"act": FakeProgram(source="exec('code')")}
        await coglet._dispatch_listen("update", patch)
        await asyncio.wait_for(task, timeout=1.0)

        assert verdicts[0]["accepted"] is False
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_rejects_import_os(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=SafetyConstraint))
        coglet = handle.coglet

        verdicts = []
        async def collect():
            async for v in handle.observe("verdict"):
                verdicts.append(v)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)

        patch = {"act": FakeProgram(source="import os\nos.system('rm -rf /')")}
        await coglet._dispatch_listen("update", patch)
        await asyncio.wait_for(task, timeout=1.0)

        assert verdicts[0]["accepted"] is False
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_rejects_open(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=SafetyConstraint))
        coglet = handle.coglet

        verdicts = []
        async def collect():
            async for v in handle.observe("verdict"):
                verdicts.append(v)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)

        patch = {"act": FakeProgram(source="f = open('/etc/passwd')")}
        await coglet._dispatch_listen("update", patch)
        await asyncio.wait_for(task, timeout=1.0)

        assert verdicts[0]["accepted"] is False
        await runtime.shutdown()

    @pytest.mark.asyncio
    async def test_rejects_dunder_import(self):
        runtime = CogletRuntime()
        handle = await runtime.spawn(CogBase(cls=SafetyConstraint))
        coglet = handle.coglet

        verdicts = []
        async def collect():
            async for v in handle.observe("verdict"):
                verdicts.append(v)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)

        patch = {"act": FakeProgram(source="__import__('subprocess')")}
        await coglet._dispatch_listen("update", patch)
        await asyncio.wait_for(task, timeout=1.0)

        assert verdicts[0]["accepted"] is False
        await runtime.shutdown()
