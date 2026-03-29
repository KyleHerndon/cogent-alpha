"""TablePolicy: program-table-driven CvC policy adapter.

Mirrors CogletPolicy but replaces hard-coded CvcEngine dispatch with
program table invocation. Each agent is fully independent.

Architecture:
  TablePolicy (MultiAgentPolicy)
    └─ StatefulAgentPolicy[TableAgentState]  (one per agent)
         └─ TablePolicyImpl (StatefulPolicyImpl)
              └─ CogletAgentPolicy (heuristic engine, for world model + state)
              └─ Program table (step/heal/retreat/mine/align/scramble/explore)
              └─ LLM brain (periodic analysis via "analyze" program)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cvc.agent import helpers as _h
from cvc.agent.coglet_policy import CogletAgentPolicy
from cvc.agent.world_model import WorldModel
from cvc.programs import StepContext, seed_programs
from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation
from mettagrid_sdk.games.cogsguard import CogsguardSemanticSurface

from coglet.llm_executor import LLMExecutor
from coglet.proglet import Program

_LLM_INTERVAL = 500
_LOG_INTERVAL = 500
_LEARNINGS_DIR = os.environ.get("COGLET_LEARNINGS_DIR", "/tmp/coglet_learnings")
_COGSGUARD_SURFACE = CogsguardSemanticSurface()


@dataclass
class TableAgentState:
    """All mutable state for one agent."""
    engine: CogletAgentPolicy | None = None
    last_llm_step: int = 0
    llm_interval: int = _LLM_INTERVAL
    llm_latencies: list[float] = field(default_factory=list)
    resource_bias_from_llm: str | None = None
    llm_log: list[dict[str, Any]] = field(default_factory=list)
    snapshot_log: list[dict[str, Any]] = field(default_factory=list)
    last_snapshot_step: int = 0
    experience: list[dict] = field(default_factory=list)


class TablePolicyImpl(StatefulPolicyImpl[TableAgentState]):
    """Per-agent decision logic using the program table."""

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        programs: dict[str, Program],
        llm_executor: LLMExecutor | None = None,
        game_id: str = "",
    ) -> None:
        self._policy_env_info = policy_env_info
        self._agent_id = agent_id
        self._programs = programs
        self._llm_executor = llm_executor
        self._game_id = game_id

    def initial_agent_state(self) -> TableAgentState:
        engine = CogletAgentPolicy(
            self._policy_env_info,
            agent_id=self._agent_id,
            world_model=WorldModel(),
        )
        return TableAgentState(engine=engine)

    def _invoke_sync(self, name: str, ctx: StepContext) -> Any:
        """Synchronous program invocation for code programs."""
        prog = self._programs[name]
        if prog.executor == "code" and prog.fn is not None:
            return prog.fn(ctx)
        raise ValueError(f"Cannot sync-invoke {name} (executor={prog.executor})")

    def step_with_state(
        self, obs: AgentObservation, state: TableAgentState
    ) -> tuple[Action, TableAgentState]:
        engine = state.engine
        assert engine is not None

        # 1. Apply LLM guidance to engine
        engine._llm_resource_bias = state.resource_bias_from_llm

        # 2. Process observation: build MettagridState via CogsguardSemanticSurface
        engine._step_index += 1
        mg_state = _COGSGUARD_SURFACE.build_state_with_events(
            obs,
            policy_env_info=engine.policy_env_info,
            step=engine._step_index,
            previous_state=engine._previous_state,
        )

        # 3. Update world model + junctions (mirrors CvcEngine.evaluate_state)
        engine._current_target_position = None
        engine._current_target_kind = None
        engine._events.extend(mg_state.recent_events)
        engine._world_model.update(mg_state)
        engine._update_junctions(mg_state)
        current_pos = _h.absolute_position(mg_state)
        engine._world_model.prune_missing_extractors(
            current_position=current_pos,
            visible_entities=mg_state.visible_entities,
            obs_width=engine.policy_env_info.obs_width,
            obs_height=engine.policy_env_info.obs_height,
        )
        engine._update_temp_blocks(current_pos)
        engine._update_stall_counter(mg_state, current_pos)

        # 4. Get role via macro directive
        directive = engine._sanitize_macro_directive(engine._macro_directive(mg_state))
        engine._current_directive = directive
        engine._resource_bias = (
            engine._default_resource_bias
            if directive.resource_bias is None
            else directive.resource_bias
        )
        role = directive.role or engine._desired_role(mg_state, objective=directive.objective)

        # 5. Build StepContext, invoke "step" program
        ctx = StepContext(
            engine=engine,
            state=mg_state,
            role=role,
            invoke=self._invoke_sync,
        )
        result = self._invoke_sync("step", ctx)

        # Unpack action from program result
        if isinstance(result, tuple):
            action, summary = result
        else:
            action, summary = result, ""

        # 6. Update engine tracking (navigation, infos, previous state)
        engine._record_navigation_observation(current_pos, summary)
        macro_snapshot = engine._macro_snapshot(mg_state, role)
        engine._infos = {
            "role": role,
            "subtask": summary,
            "summary": summary,
            "oscillation_steps": engine._oscillation_steps,
            "phase": _h.phase_name(mg_state, role),
            "heart": int(mg_state.self_state.inventory.get("heart", 0)),
            "heart_batch_target": _h.heart_batch_target(mg_state, role),
            "target_kind": engine._current_target_kind or "",
            "target_position": (
                ""
                if engine._current_target_position is None
                else _h.format_position(engine._current_target_position)
            ),
            "directive_role": directive.role or "",
            "directive_resource_bias": directive.resource_bias or "",
            "directive_objective": directive.objective or "",
            "directive_note": directive.note,
            "directive_target_entity_id": directive.target_entity_id or "",
            "directive_target_region": directive.target_region or "",
            **macro_snapshot,
        }
        engine._previous_state = mg_state
        engine._last_global_pos = current_pos
        engine._last_inventory_signature = _h.inventory_signature(mg_state)

        step = engine._step_index

        # 7. Periodic LLM analysis
        if (
            self._llm_executor is not None
            and step - state.last_llm_step >= state.llm_interval
        ):
            state.last_llm_step = step
            self._llm_analyze(engine, ctx, state)
            self._adapt_interval(state)

        # 8. Periodic snapshots (experience collection)
        if step - state.last_snapshot_step >= _LOG_INTERVAL:
            state.last_snapshot_step = step
            summary_dict = self._invoke_sync("summarize", ctx)
            if summary_dict:
                state.experience.append(summary_dict)
                state.snapshot_log.append(summary_dict)

        return action, state

    def _llm_analyze(
        self,
        engine: CogletAgentPolicy,
        ctx: StepContext,
        state: TableAgentState,
    ) -> None:
        """Run the analyze LLM program via the program table."""
        try:
            summary = self._invoke_sync("summarize", ctx)
            prog = self._programs.get("analyze")
            if prog is None or prog.executor != "llm":
                return

            prompt = prog.system(summary) if callable(prog.system) else str(prog.system)
            cfg = prog.config

            t0 = time.perf_counter()
            response = self._llm_executor.client.messages.create(
                model=cfg.get("model", "claude-sonnet-4-20250514"),
                max_tokens=cfg.get("max_tokens", 150),
                temperature=cfg.get("temperature", 0.2),
                messages=[{"role": "user", "content": prompt}],
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            text = self._llm_executor._extract_text(response)
            parsed = prog.parser(text) if prog.parser else {"analysis": text}

            if "resource_bias" in parsed:
                state.resource_bias_from_llm = parsed["resource_bias"]

            state.llm_latencies.append(latency_ms)
            state.llm_log.append({
                "step": engine._step_index,
                "agent": self._agent_id,
                "latency_ms": round(latency_ms),
                "analysis": parsed.get("analysis", ""),
                "resource_bias": state.resource_bias_from_llm,
            })
            print(
                f"[table] a{self._agent_id} step={engine._step_index} "
                f"llm={latency_ms:.0f}ms interval={state.llm_interval}: "
                f"{parsed.get('analysis', '')[:100]}",
                flush=True,
            )
        except Exception as e:
            state.llm_log.append({
                "step": engine._step_index,
                "agent": self._agent_id,
                "error": str(e),
            })

    def _adapt_interval(self, state: TableAgentState) -> None:
        """Adjust LLM call frequency based on latency."""
        if not state.llm_latencies:
            return
        recent = state.llm_latencies[-5:]
        avg_ms = sum(recent) / len(recent)
        if avg_ms < 2000:
            state.llm_interval = max(200, state.llm_interval - 50)
        elif avg_ms > 5000:
            state.llm_interval = min(1000, state.llm_interval + 100)


class TablePolicy(MultiAgentPolicy):
    """Top-level CvC policy backed by a mutable program table.

    Mirrors CogletPolicy but dispatches through the program table instead
    of hard-coded CvcEngine._choose_action.
    """

    short_names = ["coglet-table", "table-policy"]
    minimum_action_timeout_ms = 30_000

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        programs: dict[str, Program] | None = None,
        **kwargs: Any,
    ):
        super().__init__(policy_env_info, device=device, **kwargs)
        self._programs = programs or seed_programs()
        self._agent_policies: dict[int, StatefulAgentPolicy[TableAgentState]] = {}
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

    @property
    def programs(self) -> dict[str, Program]:
        return self._programs

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[TableAgentState]:
        if agent_id not in self._agent_policies:
            impl = TablePolicyImpl(
                self._policy_env_info,
                agent_id,
                programs=self._programs,
                llm_executor=self._llm_executor,
                game_id=self._game_id,
            )
            self._agent_policies[agent_id] = StatefulAgentPolicy(
                impl, self._policy_env_info, agent_id=agent_id,
            )
        return self._agent_policies[agent_id]

    def collect_experience(self) -> list[dict]:
        """Collect experience from all agents for PCO."""
        all_exp: list[dict] = []
        for aid, wrapper in self._agent_policies.items():
            st: TableAgentState | None = getattr(wrapper, "_state", None)
            if st:
                all_exp.extend(st.experience)
        return sorted(all_exp, key=lambda x: x.get("step", 0))

    def reset(self) -> None:
        if self._agent_policies:
            self._write_learnings()
        self._episode_start = time.time()
        for p in self._agent_policies.values():
            p.reset()

    def _write_learnings(self) -> None:
        learnings_dir = Path(_LEARNINGS_DIR)
        learnings_dir.mkdir(parents=True, exist_ok=True)

        agents_data: dict[str, Any] = {}
        all_llm: list[dict] = []
        all_snaps: list[dict] = []

        for aid, wrapper in self._agent_policies.items():
            st: TableAgentState | None = getattr(wrapper, "_state", None)
            if st is None:
                continue
            eng = st.engine
            agents_data[str(aid)] = {
                "steps": eng._step_index if eng else 0,
                "last_infos": dict(eng._infos) if eng and eng._infos else {},
            }
            all_llm.extend(st.llm_log)
            all_snaps.extend(st.snapshot_log)

        learnings = {
            "game_id": self._game_id,
            "duration_s": round(time.time() - self._episode_start, 1),
            "agents": agents_data,
            "llm_log": sorted(all_llm, key=lambda x: (x.get("step", 0), x.get("agent", 0))),
            "snapshots": sorted(all_snaps, key=lambda x: (x.get("step", 0), x.get("agent", 0))),
        }

        path = learnings_dir / f"{self._game_id}.json"
        path.write_text(json.dumps(learnings, indent=2, default=str))
