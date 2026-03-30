"""Tests for the PCO runner — ExperienceActor and run_pco_epoch."""

import asyncio

import pytest

from coglet import CogBase, CogletRuntime
from coglet.handle import Command
from coglet.proglet import Program

from cvc.pco_runner import ExperienceActor, run_pco_epoch


# ── Test 1: ExperienceActor transmits experience on "run" command ──


@pytest.mark.asyncio
async def test_experience_actor_transmits():
    """Spawn an ExperienceActor, dispatch 'run', verify experience arrives."""
    experience = [
        {"resources": {"carbon": 10}, "hp": 80},
        {"resources": {"oxygen": 5}, "hp": 60},
    ]

    runtime = CogletRuntime()
    handle = await runtime.spawn(
        CogBase(
            cls=ExperienceActor,
            kwargs=dict(experience=experience),
        )
    )

    actor = handle.coglet
    sub = actor._bus.subscribe("experience")
    await actor._dispatch_enact(Command("run"))
    result = await asyncio.wait_for(sub.get(), timeout=2.0)

    assert result == experience
    await runtime.shutdown()


# ── Test 2: Full PCO epoch without an LLM client ──


@pytest.mark.asyncio
async def test_pco_epoch_runs_without_client():
    """Run a full PCO epoch with no LLM client.

    The learner returns an empty patch when client is None, and both
    constraints accept empty patches, so the epoch should complete
    with accepted=True.
    """
    experience = [
        {"resources": {"carbon": 50, "oxygen": 30}, "hp": 100, "junctions": {"friendly": 2, "enemy": 1}},
        {"resources": {"carbon": 20}, "hp": 0, "junctions": {"friendly": 1, "enemy": 3}},
    ]
    programs = {
        "step": Program(executor="code", fn=lambda ctx: ctx),
    }

    result = await run_pco_epoch(
        experience=experience,
        programs=programs,
        client=None,
        max_retries=1,
    )

    assert isinstance(result, dict)
    assert "accepted" in result
    assert "signals" in result
    assert result["accepted"] is True
    # With no client, learner returns empty dict patch
    assert result["patch"] == {}
    # Three losses should produce three signals
    assert len(result["signals"]) == 3
