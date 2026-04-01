"""Navigation, pathfinding, and movement mixin."""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mettagrid_sdk.sdk import MettagridState

from cvc.agent import helpers as _h
from cvc.agent.helpers import KnownEntity
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from cvc.agent.world_model import WorldModel

_TEMP_BLOCK_STEPS = 10
_DEFAULT_BOUND_MARGIN = 12
_OSCILLATION_HISTORY_STEPS = 6


@dataclass(slots=True)
class MoveAttempt:
    direction: str
    stationary_use: bool


@dataclass(slots=True)
class NavigationObservation:
    position: tuple[int, int]
    subtask: str
    target_kind: str
    target_position: tuple[int, int] | None


class NavigationMixin:
    _world_model: WorldModel
    _step_index: int
    _agent_id: int
    _role_id: int
    _last_attempt: MoveAttempt | None
    _last_global_pos: tuple[int, int] | None
    _temp_blocks: dict[tuple[int, int], int]
    _stalled_steps: int
    _oscillation_steps: int
    _recent_navigation: deque[NavigationObservation]
    _current_target_position: tuple[int, int] | None
    _current_target_kind: str | None
    _explore_index: int
    _action_names: set[str]
    _vibe_actions: set[str]
    _fallback_action: str
    _resource_bias: str
    _last_inventory_signature: tuple[tuple[str, int], ...] | None

    def _action(self, name: str, *, vibe: str | None = None) -> Action:
        action_name = name if name in self._action_names else self._fallback_action
        vibe_name = vibe if vibe in self._vibe_actions else None
        return Action(name=action_name, vibe=vibe_name)

    def _move_to_known(
        self,
        state: MettagridState,
        entity: KnownEntity,
        *,
        summary: str,
        vibe: str | None = None,
    ) -> tuple[Action, str]:
        self._current_target_position = entity.position
        self._current_target_kind = entity.entity_type
        return self._move_to_position(state, entity.position, summary=summary, vibe=vibe)

    def _move_to_position(
        self,
        state: MettagridState,
        target: tuple[int, int],
        *,
        summary: str,
        vibe: str | None = None,
    ) -> tuple[Action, str]:
        self._current_target_position = target
        self._current_target_kind = self._current_target_kind or "position"
        current = _h.absolute_position(state)
        next_step = self._next_step(current, target)
        if next_step is None:
            self._last_attempt = None
            return self._hold(summary=f"{summary}_hold", vibe=vibe)

        direction = _h.direction_from_step(current, next_step)
        stationary_use = next_step == target and self._world_model.is_occupied(target)
        self._last_attempt = MoveAttempt(direction=direction, stationary_use=stationary_use)
        return self._action(f"move_{direction}", vibe=vibe), summary

    def _hold(self, *, summary: str, vibe: str | None = None) -> tuple[Action, str]:
        self._last_attempt = None
        if "retreat" in summary:
            self._current_target_kind = "retreat"
        return self._action(self._fallback_action, vibe=vibe), summary

    def _next_step(self, current: tuple[int, int], target: tuple[int, int]) -> tuple[int, int] | None:
        if current == target:
            return None

        blocked = self._world_model.occupied_cells(exclude={target})
        blocked.update(cell for cell, until_step in self._temp_blocks.items() if until_step >= self._step_index)
        if _h.manhattan(current, target) <= 1:
            return target

        min_x = min(current[0], target[0]) - _DEFAULT_BOUND_MARGIN
        max_x = max(current[0], target[0]) + _DEFAULT_BOUND_MARGIN
        min_y = min(current[1], target[1]) - _DEFAULT_BOUND_MARGIN
        max_y = max(current[1], target[1]) + _DEFAULT_BOUND_MARGIN

        frontier: list[tuple[int, int, tuple[int, int]]] = [(0, 0, current)]
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        best_cost = {current: 0}

        while frontier:
            _, cost, node = heapq.heappop(frontier)
            if node == target:
                break
            if cost > best_cost.get(node, cost):
                continue
            for dx, dy in _h._MOVE_DELTAS.values():
                nxt = (node[0] + dx, node[1] + dy)
                if nxt in blocked:
                    continue
                if nxt[0] < min_x or nxt[0] > max_x or nxt[1] < min_y or nxt[1] > max_y:
                    continue
                next_cost = cost + 1
                if next_cost >= best_cost.get(nxt, 1 << 30):
                    continue
                best_cost[nxt] = next_cost
                came_from[nxt] = node
                priority = next_cost + _h.manhattan(nxt, target)
                heapq.heappush(frontier, (priority, next_cost, nxt))

        if target not in came_from:
            return _h.greedy_step(current, target, blocked)

        step = target
        while came_from[step] != current:
            step = came_from[step]
        return step

    def _update_temp_blocks(self, current_pos: tuple[int, int]) -> None:
        self._temp_blocks = {
            cell: until_step for cell, until_step in self._temp_blocks.items() if until_step >= self._step_index
        }
        if self._last_attempt is None or self._last_global_pos is None:
            return
        if current_pos != self._last_global_pos:
            return
        if self._last_attempt.stationary_use:
            return
        dx, dy = _h._MOVE_DELTAS[self._last_attempt.direction]
        blocked_cell = (current_pos[0] + dx, current_pos[1] + dy)
        self._temp_blocks[blocked_cell] = self._step_index + _TEMP_BLOCK_STEPS

    def _explore_action(self, state: MettagridState, *, role: str, summary: str) -> tuple[Action, str]:
        current_pos = _h.absolute_position(state)
        hub = self._nearest_hub(state)  # type: ignore[attr-defined]
        center = (hub.global_x, hub.global_y) if hub is not None else current_pos
        offsets = _h.explore_offsets(role)
        offset_index = (self._explore_index + self._role_id) % len(offsets)
        target = offsets[offset_index]
        absolute_target = (center[0] + target[0], center[1] + target[1])
        if _h.manhattan(current_pos, absolute_target) <= 2:
            self._explore_index += 1
            offset_index = (self._explore_index + self._role_id) % len(offsets)
            target = offsets[offset_index]
            absolute_target = (center[0] + target[0], center[1] + target[1])
        return self._move_to_position(state, absolute_target, summary=summary, vibe=_h.role_vibe(role))

    def _unstick_action(self, state: MettagridState, role: str) -> tuple[Action, str]:
        current = _h.absolute_position(state)
        if role == "miner":
            self._world_model.forget_nearest(
                position=current,
                entity_type=f"{self._resource_bias}_extractor",
                max_distance=2,
            )
            for resource_name in _h._ELEMENTS:
                self._world_model.forget_nearest(
                    position=current,
                    entity_type=f"{resource_name}_extractor",
                    max_distance=2,
                )
        self._explore_index += 1
        blocked = self._world_model.occupied_cells()
        blocked.update(cell for cell, until_step in self._temp_blocks.items() if until_step >= self._step_index)
        for direction in _h.unstick_directions(self._agent_id, self._step_index):
            dx, dy = _h._MOVE_DELTAS[direction]
            nxt = (current[0] + dx, current[1] + dy)
            if nxt in blocked:
                continue
            self._last_attempt = MoveAttempt(direction=direction, stationary_use=False)
            return self._action(f"move_{direction}", vibe=_h.role_vibe(role)), f"unstick_{role}"
        return self._hold(summary=f"unstick_{role}_hold", vibe=_h.role_vibe(role))

    def _update_stall_counter(self, state: MettagridState, current_pos: tuple[int, int]) -> None:
        inventory_signature = _h.inventory_signature(state)
        if self._last_global_pos == current_pos and self._last_inventory_signature == inventory_signature:
            self._stalled_steps += 1
        else:
            self._stalled_steps = 0

    def _record_navigation_observation(self, current_pos: tuple[int, int], summary: str) -> None:
        self._recent_navigation.append(
            NavigationObservation(
                position=current_pos,
                subtask=summary,
                target_kind=self._current_target_kind or "",
                target_position=self._current_target_position,
            )
        )
        self._oscillation_steps = self._extractor_oscillation_length()

    def _extractor_oscillation_length(self) -> int:
        if len(self._recent_navigation) < 2:
            return 0
        observations = list(self._recent_navigation)
        max_size = min(len(observations), _OSCILLATION_HISTORY_STEPS)
        for size in range(max_size, 1, -1):
            window = observations[-size:]
            first = window[0]
            second = window[1]
            if first.position == second.position:
                continue
            if not first.subtask.startswith("mine_"):
                continue
            if not first.target_kind.endswith("_extractor"):
                continue
            if first.target_position is None:
                continue
            if any(
                item.subtask != first.subtask
                or item.target_kind != first.target_kind
                or item.target_position != first.target_position
                for item in window
            ):
                continue
            if all(
                item.position == (first.position if index % 2 == 0 else second.position)
                for index, item in enumerate(window)
            ):
                return size
        return 0
