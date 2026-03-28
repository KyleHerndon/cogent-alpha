from __future__ import annotations

from typing import Any

from mettagrid_sdk.sdk import MacroDirective, MettagridState

from cvc.cogent.player_cog.policy import helpers as _h
from cvc.cogent.player_cog.policy.helpers.types import KnownEntity
from cvc.cogent.player_cog.policy.semantic_cog import (
    MettagridSemanticPolicy,
    SemanticCogAgentPolicy,
    SharedWorldModel,
)
from cvc.cogent.player_cog.policy.pilot_base import PilotAgentPolicy, PilotCyborgPolicy
from cvc.cogent.player_cog.runtime.anthropic_pilot import AnthropicPilotSession
from mettagrid.policy.policy import AgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action

__all__ = [
    "AnthropicCyborgPolicy",
    "AnthropicPilotAgentPolicy",
    "AnthropicPilotSession",
]

_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")
# Max distance from hub for miners (stay safe, reduce deaths)
_MINER_MAX_HUB_DISTANCE = 15


def _shared_resources(state: MettagridState) -> dict[str, int]:
    if state.team_summary is None:
        return {r: 0 for r in _ELEMENTS}
    return {r: int(state.team_summary.shared_inventory.get(r, 0)) for r in _ELEMENTS}


def _least_resource(resources: dict[str, int]) -> str:
    return min(_ELEMENTS, key=lambda r: resources[r])


class AlphaCogAgentPolicy(SemanticCogAgentPolicy):
    """Optimized agent policy: aggressive alignment with scrambler defense."""

    def _macro_directive(self, state: MettagridState) -> MacroDirective:
        resources = _shared_resources(state)
        least = _least_resource(resources)
        return MacroDirective(resource_bias=least)

    def _pressure_budgets(self, state: MettagridState, *, objective: str | None = None) -> tuple[int, int]:
        """Fixed pressure budgets — no oscillation, v118."""
        step = state.step or self._step_index

        # Phase 1: First 10 steps — all mine to build economy
        if step < 10:
            return 2, 0

        # Phase 2: Steps 10-300 — 5 aligners, 0 scramblers, 3 miners
        # No economy-based scaling to prevent gear churn
        if step < 300:
            return 5, 0

        # Phase 3: Steps 300+ — 4 aligners, 1 scrambler, 3 miners
        # Fixed budgets: aligners mine in emergency without gear switching
        if objective == "resource_coverage":
            return 0, 0
        if objective == "economy_bootstrap":
            return 2, 0
        return 4, 1

    def _should_retreat(self, state: MettagridState, role: str, safe_target: KnownEntity | None) -> bool:
        """Miners: retreat if too far from hub (prevent deaths in dangerous territory)."""
        if super()._should_retreat(state, role, safe_target):
            return True
        # Extra safety for miners: don't wander too far from hub
        if role == "miner" and safe_target is not None:
            pos = _h.absolute_position(state)
            dist = _h.manhattan(pos, safe_target.position)
            hp = int(state.self_state.inventory.get("hp", 0))
            # Retreat if far from hub with low-ish HP
            if dist > _MINER_MAX_HUB_DISTANCE and hp < dist + 10:
                return True
        return False


# Keep these for backwards compatibility with tournament uploads
class AnthropicPilotAgentPolicy(PilotAgentPolicy):
    _LLM_ANALYSIS_INTERVAL = 500  # Run LLM analysis every N steps

    def _macro_directive(self, state: MettagridState) -> MacroDirective:
        resources = _shared_resources(state)
        least = _least_resource(resources)
        directive = MacroDirective(resource_bias=least)

        # Periodic LLM analysis — logs opinions without overriding strategy
        step = state.step or self._step_index
        if step > 0 and step % self._LLM_ANALYSIS_INTERVAL == 0:
            self._run_llm_analysis(state, directive)

        return directive

    def _run_llm_analysis(self, state: MettagridState, current_directive: MacroDirective) -> None:
        """Direct LLM call to analyze game state and log strategic insights."""
        try:
            backend = self._pilot_session._backend
            resources = _shared_resources(state)
            team = state.team_summary

            # Build rich game context
            inv = state.self_state.inventory
            lines = [
                f"You are agent {self._agent_id} in CogsVsClips at step {state.step}/10000.",
                f"Position: ({state.self_state.position.x}, {state.self_state.position.y})",
                f"HP: {inv.get('hp', 0)}, Hearts: {inv.get('heart', 0)}",
                f"Gear: aligner={inv.get('aligner', 0)} scrambler={inv.get('scrambler', 0)} miner={inv.get('miner', 0)}",
                f"Hub resources: carbon={resources['carbon']} oxygen={resources['oxygen']} germanium={resources['germanium']} silicon={resources['silicon']}",
                f"Current heuristic: resource_bias={current_directive.resource_bias}",
            ]
            if team:
                roles = {}
                for m in team.members:
                    roles[m.role] = roles.get(m.role, 0) + 1
                lines.append(f"Team roles: {dict(roles)}")
                lines.append(f"Team inventory: {dict(team.shared_inventory)}")

            if state.recent_events:
                event_lines = [f"  - {e.summary}" for e in state.recent_events[-5:]]
                lines.append("Recent events:\n" + "\n".join(event_lines))

            lines.append(
                "\nIn 2-3 sentences, analyze: What is going well? What is the biggest risk or "
                "inefficiency? What one change would most improve score?"
            )

            prompt = "\n".join(lines)
            import time
            start = time.perf_counter()
            response = backend._client.messages.create(
                model=backend._model,
                max_tokens=200,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            latency = (time.perf_counter() - start) * 1000
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text = block.text
                    break
            print(
                f"[LLM] step={state.step} agent={self._agent_id} "
                f"latency={latency:.0f}ms analysis={text!r}",
                flush=True,
            )
        except Exception as e:
            print(f"[LLM] step={state.step} agent={self._agent_id} error={e}", flush=True)

    def _pressure_budgets(self, state: MettagridState, *, objective: str | None = None) -> tuple[int, int]:
        step = state.step or self._step_index
        min_res = _h.team_min_resource(state)

        if step < 10:
            return 2, 0
        if step < 50:
            aligner_budget = 4 if min_res >= 5 else 3
            return aligner_budget, 0
        if min_res < 1 and not _h.team_can_refill_hearts(state):
            return 3, 0

        aligner_budget = 5
        scrambler_budget = 0
        if min_res < 5:
            aligner_budget = 4
        if step >= 400 and min_res >= 5:
            scrambler_budget = 1
            aligner_budget = min(aligner_budget, 4)

        if objective == "resource_coverage":
            return 0, 0
        if objective == "economy_bootstrap":
            return min(aligner_budget, 2), 0
        return aligner_budget, scrambler_budget


class AnthropicCyborgPolicy(PilotCyborgPolicy):
    short_names: list[str] | None = None  # avoid registry collision
    _session_class = AnthropicPilotSession
    _agent_policy_class = AnthropicPilotAgentPolicy
    _background_reviews_default = True

    def _provider_session_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        return {
            "api_key": kwargs.get("api_key"),
            "api_key_file": kwargs.get("api_key_file"),
            "anthropic_api_key": kwargs.get("anthropic_api_key"),
            "anthropic_api_key_file": kwargs.get("anthropic_api_key_file"),
        }


class AlphaCyborgPolicy(MettagridSemanticPolicy):
    """Lightweight policy without LLM dependencies."""
    short_names: list[str] | None = None  # avoid registry collision

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        if agent_id not in self._agent_policies:
            self._agent_policies[agent_id] = AlphaCogAgentPolicy(
                self.policy_env_info,
                agent_id=agent_id,
                world_model=SharedWorldModel(),
                shared_claims=self._shared_claims,
                shared_junctions=self._shared_junctions,
            )
        return self._agent_policies[agent_id]
