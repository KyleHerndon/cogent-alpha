"""Pressure budgets, retreat logic, and role selection mixin."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mettagrid_sdk.sdk import MettagridState

from cvc.agent import helpers as _h
from cvc.agent.helpers import KnownEntity

if TYPE_CHECKING:
    from cvc.agent.world_model import WorldModel

_RETREAT_MARGIN = 15
_ECONOMY_BOOTSTRAP_ALIGNER_BUDGET = 2
# Extended to cover all IDs for any team size. First entries preserved for 8-agent.
_ALIGNER_PRIORITY = (4, 5, 6, 7, 3, 2, 1, 0)
_SCRAMBLER_PRIORITY = (7, 6, 3, 2, 1, 0)


@dataclass(slots=True)
class PressureMetrics:
    frontier_neutral_junctions: int
    best_frontier_coverage: int
    best_enemy_scramble_block: int


class PressureMixin:
    _world_model: WorldModel
    _agent_id: int
    _role_id: int
    _step_index: int

    def _desired_role(self, state: MettagridState, *, objective: str | None = None) -> str:
        aligner_budget, scrambler_budget = self._pressure_budgets(state, objective=objective)
        scrambler_ids = set(_SCRAMBLER_PRIORITY[:scrambler_budget])
        aligner_ids = []
        for agent_id in _ALIGNER_PRIORITY:
            if agent_id in scrambler_ids:
                continue
            if len(aligner_ids) == aligner_budget:
                break
            aligner_ids.append(agent_id)
        if self._role_id in scrambler_ids:
            return "scrambler"
        if self._role_id in aligner_ids:
            return "aligner"
        return "miner"

    def _macro_snapshot(self, state: MettagridState, role: str) -> dict[str, int | str | bool]:
        safe_target = self._nearest_friendly_depot(state)  # type: ignore[attr-defined]
        safe_distance = 0 if safe_target is None else _h.manhattan(_h.absolute_position(state), safe_target.position)
        hp = int(state.self_state.inventory.get("hp", 0))
        team = _h.team_id(state)
        in_enemy_aoe = self._in_enemy_aoe(state, _h.absolute_position(state), team_id=team)
        low_hp_risk = self._should_retreat(state, role, safe_target)
        payload_at_risk = low_hp_risk and (
            int(state.self_state.inventory.get("heart", 0)) > 0 or _h.resource_total(state) > 0
        )
        pressure_metrics = self._pressure_metrics(state)
        aligner_budget, scrambler_budget = self._pressure_budgets(state)
        heart_supply = _h.heart_supply_capacity(state)

        macro_note = (
            f"frontier={pressure_metrics.frontier_neutral_junctions} "
            f"best_cover={pressure_metrics.best_frontier_coverage} "
            f"best_scramble={pressure_metrics.best_enemy_scramble_block} "
            f"pressure={aligner_budget + scrambler_budget} "
            f"safe_distance={safe_distance}"
        )
        return {
            "hp": hp,
            "safe_distance": safe_distance,
            "low_hp_risk": low_hp_risk,
            "payload_at_risk": payload_at_risk,
            "team_can_afford_role_gear": _h.team_can_afford_gear(state, role),
            "in_enemy_aoe": in_enemy_aoe,
            "frontier_neutral_junctions": pressure_metrics.frontier_neutral_junctions,
            "best_frontier_coverage": pressure_metrics.best_frontier_coverage,
            "best_enemy_scramble_block": pressure_metrics.best_enemy_scramble_block,
            "heart_supply": heart_supply,
            "pressure_budget": aligner_budget + scrambler_budget,
            "aligner_budget": aligner_budget,
            "scrambler_budget": scrambler_budget,
            "macro_note": macro_note,
        }

    def _pressure_metrics(self, state: MettagridState) -> PressureMetrics:
        team = _h.team_id(state)
        hub = self._nearest_hub(state)  # type: ignore[attr-defined]
        friendly_sources = []
        if hub is not None:
            friendly_sources.append(hub)
        friendly_sources.extend(self._known_junctions(state, predicate=lambda entity: entity.owner == team))  # type: ignore[attr-defined]
        neutral_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner in {None, "neutral"})  # type: ignore[attr-defined]
        frontier_junctions = [
            entity for entity in neutral_junctions if _h.within_alignment_network(entity.position, friendly_sources)
        ]
        unreachable_junctions = [entity for entity in neutral_junctions if entity not in frontier_junctions]
        best_frontier_coverage = max(
            (
                sum(
                    1
                    for neutral in unreachable_junctions
                    if _h.manhattan(candidate.position, neutral.position) <= _h._JUNCTION_ALIGN_DISTANCE
                )
                for candidate in frontier_junctions
            ),
            default=0,
        )
        enemy_junctions = self._known_junctions(  # type: ignore[attr-defined]
            state,
            predicate=lambda entity: entity.owner not in {None, "neutral", team},
        )
        best_enemy_scramble_block = max(
            (
                sum(
                    1
                    for neutral in neutral_junctions
                    if _h.manhattan(enemy.position, neutral.position) <= _h._JUNCTION_AOE_RANGE
                )
                for enemy in enemy_junctions
            ),
            default=0,
        )
        return PressureMetrics(
            frontier_neutral_junctions=len(frontier_junctions),
            best_frontier_coverage=best_frontier_coverage,
            best_enemy_scramble_block=best_enemy_scramble_block,
        )

    def _pressure_budgets(self, state: MettagridState, *, objective: str | None = None) -> tuple[int, int]:
        step = state.step or self._step_index

        min_res = _h.team_min_resource(state)
        can_hearts = _h.team_can_refill_hearts(state)
        if step < 30:
            pressure_budget = 2
        elif step < 3000:
            pressure_budget = 5
            if min_res < 1 and not can_hearts:
                pressure_budget = 2
            elif min_res < 3:
                pressure_budget = 4
        else:
            pressure_budget = 6
            if min_res < 1 and not can_hearts:
                pressure_budget = 3

        scrambler_budget = 0
        if step >= 100:
            scrambler_budget = 1
        aligner_budget = max(pressure_budget - scrambler_budget, 0)
        if objective == "resource_coverage":
            return 0, 0
        if objective == "economy_bootstrap":
            return min(aligner_budget, _ECONOMY_BOOTSTRAP_ALIGNER_BUDGET), 0
        return aligner_budget, scrambler_budget

    def _in_enemy_aoe(self, state: MettagridState, position: tuple[int, int], *, team_id: str) -> bool:
        enemies = self._known_junctions(  # type: ignore[attr-defined]
            state,
            predicate=lambda entity: entity.owner not in {None, "neutral", team_id},
        )
        for enemy in enemies:
            if _h.manhattan(position, enemy.position) <= _h._JUNCTION_AOE_RANGE:
                return True
        return False

    def _near_enemy_territory(self, state: MettagridState, position: tuple[int, int], *, team_id: str) -> bool:
        """Wider enemy detection (radius 20) for retreat decisions, matching alpha.0."""
        enemies = self._known_junctions(  # type: ignore[attr-defined]
            state,
            predicate=lambda entity: entity.owner not in {None, "neutral", team_id},
        )
        for enemy in enemies:
            if _h.manhattan(position, enemy.position) <= 20:
                return True
        return False

    def _should_retreat(self, state: MettagridState, role: str, safe_target: KnownEntity | None) -> bool:
        hp = int(state.self_state.inventory.get("hp", 0))
        if safe_target is None:
            return hp <= _h.retreat_threshold(state, role)

        safe_steps = max(0, _h.manhattan(_h.absolute_position(state), safe_target.position) - _h._JUNCTION_AOE_RANGE)
        margin = _RETREAT_MARGIN
        current_pos = _h.absolute_position(state)
        team = _h.team_id(state)
        if self._in_enemy_aoe(state, current_pos, team_id=team):
            margin += 10
        margin += int(state.self_state.inventory.get("heart", 0)) * 5
        margin += min(_h.resource_total(state), 12) // 2
        if not _h.has_role_gear(state, role):
            margin += 10
        if (state.step or 0) >= 2_500:
            margin += 10 if role in {"aligner", "scrambler"} else 5
        return hp <= safe_steps + margin

    def _should_deposit_resources(self, state: MettagridState) -> bool:
        cargo = _h.resource_total(state)
        if cargo <= 0:
            return False
        if cargo >= _h.deposit_threshold(state):
            return True

        safe_target = self._nearest_friendly_depot(state)  # type: ignore[attr-defined]
        if safe_target is None:
            return cargo >= 4

        safe_distance = _h.manhattan(_h.absolute_position(state), safe_target.position)
        if cargo >= 16 and safe_distance > 18:
            return True
        if cargo >= 8 and self._should_retreat(state, "miner", safe_target):
            return True
        if cargo >= 12 and self._in_enemy_aoe(state, _h.absolute_position(state), team_id=_h.team_id(state)):
            return True
        return False
