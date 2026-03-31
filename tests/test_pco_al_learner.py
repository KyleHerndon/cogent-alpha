"""Tests for AgentLightningLearnerCoglet — Agent Lightning APO inside PCO.

Tests the integration pattern using passthrough mode (agentlightning not
required) and verifies that Agent Lightning-backed learning works within
PCO's constraint retry loop.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coglet import Coglet, CogBase, CogletRuntime, enact, listen
from cogs.agent_lightning.learner import (
    AgentLightningLearnerCoglet,
    _default_reward,
    _default_context_formatter,
)
from coglet.pco.constraint import ConstraintCoglet
from coglet.pco.loss import LossCoglet
from coglet.pco.optimizer import ProximalCogletOptimizer


# ── Helpers ───────────────────────────────────────────────


class PromptActor(Coglet):
    """Actor whose 'policy' is a prompt string."""

    def __init__(self, *, inputs: list[str], **kwargs):
        super().__init__(**kwargs)
        self.prompt = "default prompt"
        self._inputs = inputs

    @enact("run")
    async def run_rollout(self, data):
        results = [
            {"input": inp, "output": f"[{self.prompt}] {inp}"}
            for inp in self._inputs
        ]
        await self.transmit("experience", {"results": results, "prompt": self.prompt})

    @enact("update")
    async def apply_update(self, patch):
        if "prompt" in patch:
            self.prompt = patch["prompt"]


class QualityCritic(Coglet):
    @listen("experience")
    async def evaluate(self, experience):
        prompt = experience.get("prompt", "")
        await self.transmit("evaluation", {
            "prompt_length": len(prompt),
            "num_results": len(experience["results"]),
        })

    @enact("update")
    async def apply_update(self, patch):
        pass


class PromptLengthLoss(LossCoglet):
    """Loss: penalize short prompts."""

    async def compute_loss(self, experience, evaluation):
        length = evaluation.get("prompt_length", 0)
        deficit = max(0, 50 - length)
        return {"name": "prompt_length", "magnitude": deficit}


class AlwaysAccept(ConstraintCoglet):
    async def check(self, patch):
        return {"accepted": True}


class RejectShortPrompts(ConstraintCoglet):
    """Reject prompts shorter than 20 chars."""

    async def check(self, patch):
        prompt = patch.get("prompt", "")
        if len(prompt) < 20:
            return {"accepted": False, "reason": f"prompt too short ({len(prompt)} chars)"}
        return {"accepted": True}


# ── Unit tests ────────────────────────────────────────────


def test_default_reward():
    signals = [
        {"name": "loss_a", "magnitude": 3},
        {"name": "loss_b", "magnitude": 7},
    ]
    assert _default_reward(signals) == -10.0


def test_default_reward_ignores_rejections():
    signals = [
        {"name": "loss", "magnitude": 5},
        {"rejection": "too big"},
    ]
    assert _default_reward(signals) == -5.0


def test_default_reward_empty():
    assert _default_reward([]) == 0.0


def test_default_context_formatter():
    result = _default_context_formatter(
        experience={"score": 10},
        evaluation={"grade": "B"},
        signals=[
            {"name": "accuracy", "magnitude": 3},
            {"rejection": "nope"},
        ],
    )
    assert "Experience:" in result
    assert "Evaluation:" in result
    assert "accuracy" in result
    assert "magnitude=3" in result
    assert "Rejection feedback: nope" in result


# ── Integration: AgentLightningLearnerCoglet in passthrough mode ──


@pytest.mark.asyncio
async def test_agent_lightning_learner_passthrough():
    """Without agentlightning installed, learn() returns current prompt."""
    learner = AgentLightningLearnerCoglet(
        resource_key="prompt",
        initial_prompt="be helpful",
    )
    result = await learner.learn(
        experience={"results": []},
        evaluation={"score": 5},
        signals=[{"name": "loss", "magnitude": 2}],
    )
    assert result["prompt"] == "be helpful"
    assert result["source"] == "agent_lightning_apo"
    assert result["reward"] == -2.0
    assert result["epoch"] == 1


@pytest.mark.asyncio
async def test_agent_lightning_learner_custom_reward_fn():
    """Custom reward function is used."""
    learner = AgentLightningLearnerCoglet(
        initial_prompt="test",
        reward_fn=lambda signals: 42.0,
    )
    result = await learner.learn(
        experience={}, evaluation={}, signals=[],
    )
    assert result["reward"] == 42.0


@pytest.mark.asyncio
async def test_agent_lightning_learner_tracks_epochs():
    """Epoch counter increments across learn() calls."""
    learner = AgentLightningLearnerCoglet(initial_prompt="v0")

    r1 = await learner.learn({}, {}, [])
    r2 = await learner.learn({}, {}, [])
    r3 = await learner.learn({}, {}, [])

    assert r1["epoch"] == 1
    assert r2["epoch"] == 2
    assert r3["epoch"] == 3


# ── Full PCO integration with AgentLightningLearnerCoglet ─


@pytest.mark.asyncio
async def test_agent_lightning_learner_in_pco_epoch():
    """AgentLightningLearnerCoglet works as a drop-in for PCO's learner slot."""
    learner = AgentLightningLearnerCoglet(
        resource_key="prompt",
        initial_prompt="be concise",
    )

    runtime = CogletRuntime()
    handle = await runtime.spawn(CogBase(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogBase(
                cls=PromptActor,
                kwargs=dict(inputs=["hello", "world"]),
            ),
            critic_config=CogBase(cls=QualityCritic),
            losses=[PromptLengthLoss()],
            constraints=[AlwaysAccept()],
            learner=learner,
        ),
    ))
    pco = handle.coglet

    result = await pco.run_epoch()

    assert result["accepted"] is True
    assert result["patch"]["prompt"] == "be concise"
    assert result["patch"]["source"] == "agent_lightning_apo"
    actor = pco._actor_handle.coglet
    assert actor.prompt == "be concise"
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_agent_lightning_learner_with_constraint_retry():
    """AgentLightningLearnerCoglet handles PCO constraint rejection and retry."""

    class GrowingAgentLightningLearner(AgentLightningLearnerCoglet):
        """On rejection, appends to prompt to make it longer."""

        async def learn(self, experience, evaluation, signals):
            result = await super().learn(experience, evaluation, signals)
            rejected = any(
                isinstance(s, dict) and "rejection" in s for s in signals
            )
            if rejected:
                result["prompt"] = result["prompt"] + " — improved with more detail"
            return result

    learner = GrowingAgentLightningLearner(
        resource_key="prompt",
        initial_prompt="short",  # 5 chars, will be rejected
    )

    runtime = CogletRuntime()
    handle = await runtime.spawn(CogBase(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogBase(
                cls=PromptActor,
                kwargs=dict(inputs=["test"]),
            ),
            critic_config=CogBase(cls=QualityCritic),
            losses=[PromptLengthLoss()],
            constraints=[RejectShortPrompts()],
            learner=learner,
            max_retries=3,
        ),
    ))
    pco = handle.coglet

    result = await pco.run_epoch()

    assert result["accepted"] is True
    assert "improved" in result["patch"]["prompt"]
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_agent_lightning_learner_multi_epoch_in_pco():
    """AgentLightningLearnerCoglet works across multiple PCO epochs."""
    learner = AgentLightningLearnerCoglet(
        resource_key="prompt",
        initial_prompt="v0",
    )

    runtime = CogletRuntime()
    handle = await runtime.spawn(CogBase(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogBase(
                cls=PromptActor,
                kwargs=dict(inputs=["a"]),
            ),
            critic_config=CogBase(cls=QualityCritic),
            losses=[PromptLengthLoss()],
            constraints=[AlwaysAccept()],
            learner=learner,
        ),
    ))
    pco = handle.coglet

    results = await pco.run(num_epochs=3)

    assert len(results) == 3
    assert all(r["accepted"] for r in results)
    assert results[0]["patch"]["epoch"] == 1
    assert results[1]["patch"]["epoch"] == 2
    assert results[2]["patch"]["epoch"] == 3
    await runtime.shutdown()
