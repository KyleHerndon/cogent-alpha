"""Seed program table: decomposes CvcEngine heuristics into named programs.

Each code program takes a StepContext and returns (Action, summary) or None.
The ``seed_programs()`` function returns a dict[str, Program] ready to be
registered into a ProgLet.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from coglet.proglet import Program

_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")


@dataclass
class StepContext:
    """Holds everything a program needs for one tick."""
    engine: Any  # CvcEngine / CogletAgentPolicy instance
    state: Any  # MettagridState
    role: str
    invoke: Callable[[str, "StepContext"], Any]


# ---------------------------------------------------------------------------
# Code programs
# ---------------------------------------------------------------------------

def _step(ctx: StepContext) -> tuple[Any, str]:
    """Main dispatch — mirrors CvcEngine._choose_action priority chain."""
    engine = ctx.engine
    state = ctx.state
    role = ctx.role

    from cvc.agent import helpers as _h
    from cvc.agent.helpers.types import KnownEntity

    safe_target = engine._nearest_hub(state)
    safe_distance = (
        0 if safe_target is None
        else _h.manhattan(_h.absolute_position(state), safe_target.position)
    )
    hp = int(state.self_state.inventory.get("hp", 0))
    step = state.step or engine._step_index

    # Heal at hub
    if hp < 100 and hp > 0 and safe_target is not None and safe_distance <= 3 and step <= 20:
        return ctx.invoke("heal", ctx)

    # Early retreat
    if step < 150 and safe_target is not None and safe_distance > 8:
        if hp < 40 or (hp < 50 and safe_distance > 15):
            return ctx.invoke("retreat", ctx)

    # Wipeout recovery
    if hp == 0 and safe_target is not None:
        if safe_distance > 5:
            return ctx.invoke("retreat", ctx)
        return ctx.invoke("mine", ctx)

    # Standard retreat
    if engine._should_retreat(state, role, safe_target):
        engine._clear_target_claim()
        engine._clear_sticky_target()
        if safe_target is not None and safe_distance > 2:
            return ctx.invoke("retreat", ctx)
        if _h.has_role_gear(state, role):
            return engine._hold(summary="retreat_hold", vibe="change_vibe_default")

    # Unstick on oscillation
    if engine._oscillation_steps >= 4:
        return engine._unstick_action(state, role)

    # Unstick on stall
    if engine._stalled_steps >= 12:
        return engine._unstick_action(state, role)

    # Emergency mining
    if role != "miner" and _h.needs_emergency_mining(state):
        return ctx.invoke("mine", ctx)

    # Aligner gear delay
    if role == "aligner" and not _h.has_role_gear(state, role):
        if (state.step or engine._step_index) < 0:
            engine._clear_target_claim()
            engine._clear_sticky_target()
            return ctx.invoke("mine", ctx)

    # Gear acquisition
    if not _h.has_role_gear(state, role):
        engine._clear_target_claim()
        engine._clear_sticky_target()
        if not _h.team_can_afford_gear(state, role):
            return ctx.invoke("mine", ctx)
        return engine._acquire_role_gear(state, role)

    # Role action
    if role == "miner":
        return ctx.invoke("mine", ctx)
    if role == "aligner":
        return ctx.invoke("align", ctx)
    if role == "scrambler":
        return ctx.invoke("scramble", ctx)
    return ctx.invoke("explore", ctx)


def _heal(ctx: StepContext) -> tuple[Any, str]:
    """Stay near hub to regenerate HP."""
    return ctx.engine._hold(summary="hub_camp_heal", vibe="change_vibe_default")


def _retreat(ctx: StepContext) -> tuple[Any, str]:
    """Move back towards the nearest hub for safety."""
    engine = ctx.engine
    state = ctx.state
    safe_target = engine._nearest_hub(state)
    if safe_target is not None:
        return engine._move_to_known(state, safe_target, summary="retreat_to_hub")
    return engine._hold(summary="retreat_hold", vibe="change_vibe_default")


def _mine(ctx: StepContext) -> tuple[Any, str]:
    """Execute mining action."""
    return ctx.engine._miner_action(ctx.state)


def _align(ctx: StepContext) -> tuple[Any, str]:
    """Execute aligner action."""
    return ctx.engine._aligner_action(ctx.state)


def _scramble(ctx: StepContext) -> tuple[Any, str]:
    """Execute scrambler action."""
    return ctx.engine._scrambler_action(ctx.state)


def _explore(ctx: StepContext) -> tuple[Any, str]:
    """Explore the map."""
    return ctx.engine._explore_action(ctx.state, role=ctx.role, summary="explore")


def _macro(ctx: StepContext) -> tuple[Any, str] | None:
    """Compute macro directive (resource bias, role override)."""
    directive = ctx.engine._macro_directive(ctx.state)
    return directive  # type: ignore[return-value]


def _summarize(ctx: StepContext) -> dict[str, Any]:
    """Build a snapshot summary of the current game state."""
    from cvc.cvc_policy import _build_context
    context = _build_context(ctx.engine, ctx.engine._agent_id)
    return context or {}


# ---------------------------------------------------------------------------
# LLM program: analyze
# ---------------------------------------------------------------------------

def _build_analysis_prompt(context: dict) -> str:
    """Build the LLM analysis prompt from extracted game context."""
    lines = [
        f"CvC game step {context['step']}/10000. 88x88 map, 8 agents per team.",
        f"Agent {context['agent_id']}: HP={context['hp']}, Hearts={context['hearts']}",
        f"Gear: aligner={context['aligner']} scrambler={context['scrambler']} miner={context['miner']}",
        f"Hub resources: {context['resources']}",
    ]
    if context["roles"]:
        lines.append(f"Team roles: {context['roles']}")

    j = context["junctions"]
    lines.append(
        f"Visible junctions: friendly={j['friendly']} enemy={j['enemy']} neutral={j['neutral']}"
    )

    lines.append(
        "\nRespond with ONLY a JSON object (no other text):"
        '\n{"resource_bias": "carbon"|"oxygen"|"germanium"|"silicon",'
        ' "analysis": "1-2 sentence analysis"}'
        "\nChoose resource_bias = the element with lowest supply."
    )
    return "\n".join(lines)


def _parse_analysis(text: str) -> dict:
    """Parse the LLM response text into a directive dict."""
    result: dict[str, Any] = {"analysis": text[:100]}
    try:
        directive = json.loads(text)
        if isinstance(directive, dict):
            if directive.get("resource_bias") in _ELEMENTS:
                result["resource_bias"] = directive["resource_bias"]
            result["analysis"] = directive.get("analysis", text[:100])
    except (json.JSONDecodeError, ValueError):
        pass
    return result


# ---------------------------------------------------------------------------
# seed_programs
# ---------------------------------------------------------------------------

def seed_programs() -> dict[str, Program]:
    """Return the seed program table decomposing CvcEngine heuristics."""
    return {
        "step": Program(executor="code", fn=_step),
        "heal": Program(executor="code", fn=_heal),
        "retreat": Program(executor="code", fn=_retreat),
        "mine": Program(executor="code", fn=_mine),
        "align": Program(executor="code", fn=_align),
        "scramble": Program(executor="code", fn=_scramble),
        "explore": Program(executor="code", fn=_explore),
        "macro": Program(executor="code", fn=_macro),
        "summarize": Program(executor="code", fn=_summarize),
        "analyze": Program(
            executor="llm",
            system=_build_analysis_prompt,
            parser=_parse_analysis,
            config={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 150,
                "temperature": 0.2,
                "max_turns": 1,
            },
        ),
    }
