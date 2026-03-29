"""Tests for cogames/cvc/programs.py — seed program table."""

from __future__ import annotations

from cvc.programs import StepContext, seed_programs
from coglet.proglet import Program


def test_seed_programs_has_all_expected_names():
    programs = seed_programs()
    expected = {
        "step", "heal", "retreat", "mine", "align",
        "scramble", "explore", "macro", "summarize", "analyze",
    }
    assert set(programs.keys()) == expected


def test_code_programs_are_callable():
    programs = seed_programs()
    code_names = ["step", "heal", "retreat", "mine", "align",
                  "scramble", "explore", "macro", "summarize"]
    for name in code_names:
        prog = programs[name]
        assert isinstance(prog, Program)
        assert prog.executor == "code"
        assert callable(prog.fn), f"{name}.fn should be callable"


def test_analyze_is_llm_program_with_parser():
    programs = seed_programs()
    analyze = programs["analyze"]
    assert isinstance(analyze, Program)
    assert analyze.executor == "llm"
    assert analyze.parser is not None
    assert callable(analyze.parser)
    assert analyze.fn is None


def test_analyze_parser_valid_json():
    programs = seed_programs()
    parser = programs["analyze"].parser
    result = parser('{"resource_bias": "carbon", "analysis": "Low carbon supply"}')
    assert result["resource_bias"] == "carbon"
    assert "Low carbon" in result["analysis"]


def test_analyze_parser_invalid_json():
    programs = seed_programs()
    parser = programs["analyze"]._parser_fn if hasattr(programs["analyze"], "_parser_fn") else programs["analyze"].parser
    result = parser("not json at all")
    assert "analysis" in result
    assert "resource_bias" not in result


def test_analyze_parser_invalid_resource():
    programs = seed_programs()
    parser = programs["analyze"].parser
    result = parser('{"resource_bias": "unobtanium", "analysis": "test"}')
    assert "resource_bias" not in result


def test_step_context_dataclass():
    ctx = StepContext(engine=None, state=None, role="miner", invoke=lambda n, c: None)
    assert ctx.role == "miner"
    assert ctx.engine is None
    assert ctx.state is None
    assert callable(ctx.invoke)


def test_analyze_config():
    programs = seed_programs()
    analyze = programs["analyze"]
    assert "model" in analyze.config
    assert "max_tokens" in analyze.config
    assert analyze.config["temperature"] == 0.2


def test_analyze_has_system_prompt_builder():
    programs = seed_programs()
    analyze = programs["analyze"]
    assert analyze.system is not None
    assert callable(analyze.system)
