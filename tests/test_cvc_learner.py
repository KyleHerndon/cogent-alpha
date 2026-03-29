"""Tests for CvCLearner — LLM-based program table optimizer."""
import pytest
from coglet.proglet import Program
from cvc.learner import CvCLearner


@pytest.fixture
def learner_no_client():
    return CvCLearner(
        client=None,
        current_programs={"step": Program(executor="code", fn=lambda ctx: ctx)},
    )


@pytest.mark.asyncio
async def test_learner_without_client_returns_empty(learner_no_client):
    result = await learner_no_client.learn(
        experience={"data": "rollout"},
        evaluation={"score": 5},
        signals=[{"name": "policy", "magnitude": 0.5}],
    )
    assert result == {}


def test_parse_patch_valid_code():
    learner = CvCLearner(
        client=None,
        current_programs={},
    )
    text = '{"heal": {"type": "code", "source": "def _heal(ctx):\\n    return (None, \'healed\')"}}'
    patches = learner._parse_patch(text)
    assert "heal" in patches
    prog = patches["heal"]
    assert prog.executor == "code"
    assert prog.fn is not None
    assert prog.fn(None) == (None, "healed")
    assert hasattr(prog.fn, "_source")


def test_parse_patch_valid_prompt():
    current = Program(
        executor="llm",
        system="old prompt",
        parser=lambda x: {"parsed": x},
        config={"model": "claude-sonnet-4-20250514", "max_tokens": 150},
    )
    learner = CvCLearner(
        client=None,
        current_programs={"analyze": current},
    )
    text = '{"analyze": {"type": "prompt", "source": "new system prompt"}}'
    patches = learner._parse_patch(text)
    assert "analyze" in patches
    prog = patches["analyze"]
    assert prog.executor == "llm"
    assert prog.system == "new system prompt"
    # Parser and config preserved from current program
    assert prog.parser is current.parser
    assert prog.config == current.config


def test_parse_patch_invalid_json():
    learner = CvCLearner(
        client=None,
        current_programs={},
    )
    result = learner._parse_patch("this is not json at all")
    assert result == {}


def test_parse_patch_json_in_code_block():
    learner = CvCLearner(
        client=None,
        current_programs={},
    )
    text = '```json\n{"heal": {"type": "code", "source": "def _heal(ctx):\\n    return (None, \'ok\')"}}\n```'
    patches = learner._parse_patch(text)
    assert "heal" in patches
    assert patches["heal"].fn(None) == (None, "ok")


def test_update_programs():
    learner = CvCLearner(
        client=None,
        current_programs={},
    )
    new_progs = {"step": Program(executor="code", fn=lambda ctx: ctx)}
    learner.update_programs(new_progs)
    assert learner.current_programs is new_progs
