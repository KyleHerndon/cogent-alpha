"""Junction memory and entity lookup mixin."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from mettagrid_sdk.games.cogsguard import COGSGUARD_BOOTSTRAP_HUB_OFFSETS
from mettagrid_sdk.sdk import MettagridState

from cvc.agent import helpers as _h
from cvc.agent.helpers import KnownEntity

if TYPE_CHECKING:
    from cvc.agent.world_model import WorldModel

_HUB_OFFSETS = COGSGUARD_BOOTSTRAP_HUB_OFFSETS
_JUNCTION_MEMORY_STEPS = 800


class JunctionMixin:
    _world_model: WorldModel
    _junctions: dict[tuple[int, int], tuple[str | None, int]]
    _hotspots: dict[tuple[int, int], int]
    _agent_id: int
    _step_index: int

    def _nearest_hub(self, state: MettagridState) -> KnownEntity | None:
        hub = self._world_model.nearest(
            position=_h.absolute_position(state),
            entity_type="hub",
            predicate=lambda entity: entity.team == _h.team_id(state),
        )
        if hub is not None:
            return hub

        bootstrap_offset = _HUB_OFFSETS.get(self._role_id)
        if bootstrap_offset is None:
            return None
        return KnownEntity(
            entity_type="hub",
            global_x=bootstrap_offset[0],
            global_y=bootstrap_offset[1],
            labels=(),
            team=_h.team_id(state),
            owner=_h.team_id(state),
            last_seen_step=state.step or self._step_index,
            attributes={},
        )

    def _nearest_friendly_depot(self, state: MettagridState) -> KnownEntity | None:
        team = _h.team_id(state)
        depot = self._world_model.nearest(
            position=_h.absolute_position(state),
            predicate=lambda entity: (
                (entity.entity_type == "hub" and entity.team == team)
                or (entity.entity_type == "junction" and entity.owner == team)
            ),
        )
        shared_friendly = self._junction_entities(state, predicate=lambda entity: entity.owner == team)
        if shared_friendly:
            shared_nearest = min(
                shared_friendly,
                key=lambda entity: (_h.manhattan(_h.absolute_position(state), entity.position), entity.position),
            )
            if depot is None or _h.manhattan(_h.absolute_position(state), shared_nearest.position) < _h.manhattan(
                _h.absolute_position(state), depot.position
            ):
                depot = shared_nearest
        if depot is not None:
            return depot
        return self._nearest_hub(state)

    def _update_junctions(self, state: MettagridState) -> None:
        hub = self._nearest_hub(state)
        if hub is None:
            return
        team = _h.team_id(state)
        for entity in state.visible_entities:
            if entity.entity_type != "junction":
                continue
            rel_position = (
                int(entity.attributes["global_x"]) - hub.global_x,
                int(entity.attributes["global_y"]) - hub.global_y,
            )
            owner = entity.attributes.get("owner")
            new_owner = None if owner in {None, "neutral"} else str(owner)
            # Track hotspots: junction was friendly, now scrambled (neutral or enemy)
            prev = self._junctions.get(rel_position)
            if prev is not None and prev[0] == team and new_owner != team:
                abs_pos = (hub.global_x + rel_position[0], hub.global_y + rel_position[1])
                self._hotspots[abs_pos] = self._hotspots.get(abs_pos, 0) + 1
            self._junctions[rel_position] = (new_owner, state.step or self._step_index)

    def _junction_entities(
        self,
        state: MettagridState,
        *,
        predicate: Callable[[KnownEntity], bool],
    ) -> list[KnownEntity]:
        hub = self._nearest_hub(state)
        if hub is None:
            return []
        step = state.step or self._step_index
        result = []
        for (dx, dy), (owner, last_seen_step) in self._junctions.items():
            if step - last_seen_step > _JUNCTION_MEMORY_STEPS:
                continue
            entity = KnownEntity(
                entity_type="junction",
                global_x=hub.global_x + dx,
                global_y=hub.global_y + dy,
                labels=(),
                team=owner,
                owner=owner,
                last_seen_step=last_seen_step,
                attributes={},
            )
            if predicate(entity):
                result.append(entity)
        return result

    def _known_junctions(
        self,
        state: MettagridState,
        *,
        predicate: Callable[[KnownEntity], bool],
    ) -> list[KnownEntity]:
        by_position = {
            entity.position: entity
            for entity in self._world_model.entities(entity_type="junction", predicate=predicate)
        }
        for entity in self._junction_entities(state, predicate=predicate):
            by_position.setdefault(entity.position, entity)
        return list(by_position.values())
