"""CvC PolicyCoglet: StatefulPolicyImpl with per-agent LLM brain.

Each agent is fully independent — NO shared state between agents.
State is managed via CogletAgentState dataclass.

Architecture:
  CogletPolicy (MultiAgentPolicy)
    └─ StatefulAgentPolicy[CogletAgentState]  (one per agent)
         └─ CogletPolicyImpl (StatefulPolicyImpl)
              └─ CogletAgentPolicy (heuristic engine)
              └─ LLM brain (periodic Claude calls for resource_bias)
              └─ Snapshot logging (periodic game state capture)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cvc.agent.coglet_policy import CogletAgentPolicy
from cvc.agent.world_model import WorldModel
from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

from coglet.llm_executor import LLMExecutor
from coglet.proglet import Program

_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")
_LLM_INTERVAL = 500
_LOG_INTERVAL = 500
_LEARNINGS_DIR = os.environ.get("COGLET_LEARNINGS_DIR", "/tmp/coglet_learnings")


def _build_context(engine: CogletAgentPolicy, agent_id: int) -> dict[str, Any] | None:
    """Extract game state into a dict for prompt building and snapshot logging."""
    game_state = engine._previous_state
    if game_state is None:
        return None

    inv = game_state.self_state.inventory
    team = game_state.team_summary
    resources = {}
    if team:
        resources = {r: int(team.shared_inventory.get(r, 0)) for r in _ELEMENTS}

    team_id = team.team_id if team else ""
    friendly_j = sum(1 for e in game_state.visible_entities if e.entity_type == "junction" and e.attributes.get("owner") == team_id)
    enemy_j = sum(1 for e in game_state.visible_entities if e.entity_type == "junction" and e.attributes.get("owner") not in {None, "neutral", team_id})
    neutral_j = sum(1 for e in game_state.visible_entities if e.entity_type == "junction" and e.attributes.get("owner") in {None, "neutral"})

    roles: dict[str, int] = {}
    if team:
        for m in team.members:
            roles[m.role] = roles.get(m.role, 0) + 1

    return {
        "step": engine._step_index,
        "agent_id": agent_id,
        "hp": inv.get("hp", 0),
        "hearts": inv.get("heart", 0),
        "aligner": inv.get("aligner", 0),
        "scrambler": inv.get("scrambler", 0),
        "miner": inv.get("miner", 0),
        "resources": resources,
        "roles": roles,
        "junctions": {"friendly": friendly_j, "enemy": enemy_j, "neutral": neutral_j},
        "team": team,
    }


def _build_analysis_prompt(context: dict) -> str:
    """Build the LLM analysis prompt from extracted game context."""
    lines = [
        f"CvC game step {context['step']}/10000. 88x88 map, 8 agents per team.",
        f"Agent {context['agent_id']}: HP={context['hp']}, Hearts={context['hearts']}",
        f"Gear: aligner={context['aligner']} scrambler={context['scrambler']} miner={context['miner']}",
        f"Hub resources: {context['resources']}",
    ]
    if context['roles']:
        lines.append(f"Team roles: {context['roles']}")

    j = context['junctions']
    lines.append(f"Visible junctions: friendly={j['friendly']} enemy={j['enemy']} neutral={j['neutral']}")

    lines.append(
        "\nRespond with ONLY a JSON object (no other text):"
        '\n{"resource_bias": "carbon"|"oxygen"|"germanium"|"silicon",'
        ' "analysis": "1-2 sentence analysis"}'
        "\nChoose resource_bias = the element with lowest supply."
    )
    return "\n".join(lines)


def _parse_analysis(text: str) -> dict:
    """Parse the LLM response text into a directive dict.

    Returns a dict with optional keys: resource_bias, analysis.
    """
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


ANALYZE_RESOURCES = Program(
    executor="llm",
    parser=_parse_analysis,
    config={
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 150,
        "temperature": 0.2,
        "max_turns": 1,
    },
)


@dataclass
class CogletAgentState:
    """All mutable state for one agent."""
    engine: CogletAgentPolicy | None = None
    last_llm_step: int = 0
    llm_interval: int = _LLM_INTERVAL
    llm_latencies: list[float] = field(default_factory=list)
    resource_bias_from_llm: str | None = None
    llm_log: list[dict[str, Any]] = field(default_factory=list)
    snapshot_log: list[dict[str, Any]] = field(default_factory=list)
    last_snapshot_step: int = 0


class CogletPolicyImpl(StatefulPolicyImpl[CogletAgentState]):
    """Per-agent decision logic. Fully independent — no shared state."""

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        llm_executor: LLMExecutor | None = None,
        game_id: str = "",
    ) -> None:
        self._policy_env_info = policy_env_info
        self._agent_id = agent_id
        self._llm_executor = llm_executor
        self._game_id = game_id

    def initial_agent_state(self) -> CogletAgentState:
        engine = CogletAgentPolicy(
            self._policy_env_info,
            agent_id=self._agent_id,
            world_model=WorldModel(),
        )
        return CogletAgentState(engine=engine)

    def step_with_state(
        self, obs: AgentObservation, state: CogletAgentState
    ) -> tuple[Action, CogletAgentState]:
        engine = state.engine
        assert engine is not None

        engine._llm_resource_bias = state.resource_bias_from_llm
        action = engine.step(obs)
        step = engine._step_index

        if (
            self._llm_executor is not None
            and step - state.last_llm_step >= state.llm_interval
        ):
            state.last_llm_step = step
            self._llm_analyze(engine, state)
            self._adapt_interval(state)

        if step - state.last_snapshot_step >= _LOG_INTERVAL:
            state.last_snapshot_step = step
            self._log_snapshot(engine, state)

        return action, state

    def _llm_analyze(self, engine: CogletAgentPolicy, state: CogletAgentState) -> None:
        try:
            context = _build_context(engine, self._agent_id)
            if context is None:
                return

            prompt = _build_analysis_prompt(context)
            cfg = ANALYZE_RESOURCES.config

            t0 = time.perf_counter()
            response = self._llm_executor.client.messages.create(
                model=cfg.get("model", "claude-sonnet-4-20250514"),
                max_tokens=cfg.get("max_tokens", 150),
                temperature=cfg.get("temperature", 0.2),
                messages=[{"role": "user", "content": prompt}],
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            text = self._llm_executor._extract_text(response)

            parsed = _parse_analysis(text)
            if "resource_bias" in parsed:
                state.resource_bias_from_llm = parsed["resource_bias"]
            analysis = parsed["analysis"]

            state.llm_latencies.append(latency_ms)
            state.llm_log.append({
                "step": engine._step_index,
                "agent": self._agent_id,
                "latency_ms": round(latency_ms),
                "interval": state.llm_interval,
                "analysis": analysis,
                "resources": context["resources"],
                "resource_bias": state.resource_bias_from_llm,
            })
            print(
                f"[coglet] a{self._agent_id} step={engine._step_index} llm={latency_ms:.0f}ms "
                f"interval={state.llm_interval}: {analysis[:100]}",
                flush=True,
            )

        except Exception as e:
            state.llm_log.append({
                "step": engine._step_index,
                "agent": self._agent_id,
                "error": str(e),
            })

    def _adapt_interval(self, state: CogletAgentState) -> None:
        if not state.llm_latencies:
            return
        recent = state.llm_latencies[-5:]
        avg_ms = sum(recent) / len(recent)
        if avg_ms < 2000:
            state.llm_interval = max(200, state.llm_interval - 50)
        elif avg_ms > 5000:
            state.llm_interval = min(1000, state.llm_interval + 100)

    def _log_snapshot(self, engine: CogletAgentPolicy, state: CogletAgentState) -> None:
        context = _build_context(engine, self._agent_id)
        if context is None:
            return

        resources = context["resources"]
        junctions = context["junctions"]
        infos = engine._infos or {}
        snap = {
            "step": engine._step_index,
            "agent": self._agent_id,
            "role": infos.get("role", ""),
            "subtask": infos.get("subtask", ""),
            "hp": int(context["hp"]),
            "hearts": int(context["hearts"]),
            "resources": resources,
            "junctions": junctions,
            "resource_bias": state.resource_bias_from_llm or infos.get("directive_resource_bias", ""),
        }
        state.snapshot_log.append(snap)

        res_str = " ".join(f"{k[0].upper()}={v}" for k, v in sorted(resources.items()))
        j_str = f"f={junctions['friendly']} e={junctions['enemy']} n={junctions['neutral']}"
        print(
            f"[coglet:snap] a{self._agent_id} step={engine._step_index} "
            f"role={snap['role']} hp={snap['hp']} hearts={snap['hearts']} | "
            f"{res_str} | junc: {j_str} | {snap['subtask']}",
            flush=True,
        )


class CogletPolicy(MultiAgentPolicy):
    """Top-level CvC policy. Each agent is fully independent."""

    short_names = ["coglet", "coglet-policy"]
    minimum_action_timeout_ms = 30_000

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", **kwargs: Any):
        super().__init__(policy_env_info, device=device, **kwargs)
        self._agent_policies: dict[int, StatefulAgentPolicy[CogletAgentState]] = {}
        self._llm_executor: LLMExecutor | None = None
        self._episode_start = time.time()
        self._game_id = kwargs.get("game_id", f"game_{int(time.time())}")
        self._init_llm()

    def _init_llm(self) -> None:
        api_key = os.environ.get("COGORA_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return
        try:
            import anthropic
            self._llm_executor = LLMExecutor(anthropic.Anthropic(api_key=api_key))
        except ImportError:
            pass

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[CogletAgentState]:
        if agent_id not in self._agent_policies:
            impl = CogletPolicyImpl(
                self._policy_env_info,
                agent_id=agent_id,
                llm_executor=self._llm_executor,
                game_id=self._game_id,
            )
            self._agent_policies[agent_id] = StatefulAgentPolicy(
                impl, self._policy_env_info, agent_id=agent_id,
            )
        return self._agent_policies[agent_id]

    def reset(self) -> None:
        if self._agent_policies:
            self._write_learnings()
        self._episode_start = time.time()
        for policy in self._agent_policies.values():
            policy.reset()

    def _write_learnings(self) -> None:
        learnings_dir = Path(_LEARNINGS_DIR)
        learnings_dir.mkdir(parents=True, exist_ok=True)

        agents_data: dict[str, Any] = {}
        all_llm_logs: list[dict] = []
        all_snapshots: list[dict] = []

        for aid, wrapper in self._agent_policies.items():
            state: CogletAgentState | None = getattr(wrapper, "_state", None)
            if state is None:
                continue
            engine = state.engine
            agents_data[str(aid)] = {
                "steps": engine._step_index if engine else 0,
                "last_infos": dict(engine._infos) if engine and engine._infos else {},
            }
            all_llm_logs.extend(state.llm_log)
            all_snapshots.extend(state.snapshot_log)

        learnings = {
            "game_id": self._game_id,
            "duration_s": round(time.time() - self._episode_start, 1),
            "agents": agents_data,
            "llm_log": sorted(all_llm_logs, key=lambda x: (x.get("step", 0), x.get("agent", 0))),
            "snapshots": sorted(all_snapshots, key=lambda x: (x.get("step", 0), x.get("agent", 0))),
        }

        path = learnings_dir / f"{self._game_id}.json"
        path.write_text(json.dumps(learnings, indent=2, default=str))
