"""PolicyCoglet: ProgLet-based policy for cogames.

Bridges the Coglet framework to cogames' MultiAgentPolicy interface.
The step program lives in the ProgLet program table and can be
rewritten by the LLM at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from coglet.coglet import Coglet, listen, enact
from coglet.proglet import ProgLet, Program
from coglet.lifelet import LifeLet
from coglet.ticklet import TickLet


class PolicyCoglet(Coglet, ProgLet, LifeLet, TickLet):
    """Innermost execution layer for cogames.

    Holds a mutable program table (ProgLet) whose "step" program
    is called on each observation. The LLM can rewrite programs via
    @enact("register").
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.history: list[dict[str, Any]] = []

    @listen("obs")
    async def handle_obs(self, data: Any) -> None:
        if "step" not in self.programs:
            return
        action = await self.invoke("step", data)
        await self.transmit("action", action)
        await self.tick()

    @listen("score")
    async def handle_score(self, data: Any) -> None:
        self.history.append({"type": "score", "data": data})
        await self.transmit("score", data)

    @listen("replay")
    async def handle_replay(self, data: Any) -> None:
        self.history.append({"type": "replay", "data": data})


# ---------------------------------------------------------------------------
# cogames MultiAgentPolicy adapter
# ---------------------------------------------------------------------------
# This is what cogames actually instantiates. It delegates step() calls
# down to a step function — either from a PolicyCoglet's function table
# or a plain callable passed at init time.
# ---------------------------------------------------------------------------

# Observation helpers shared by step functions

GEAR = ("aligner", "scrambler", "miner", "scout")
ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")
WANDER_DIRECTIONS = ("east", "south", "west", "north")
WANDER_STEPS = 8


@dataclass
class CogletAgentState:
    """Per-agent state for the coglet policy."""
    wander_direction_index: int = 0
    wander_steps_remaining: int = WANDER_STEPS


def default_step_fn(
    obs: Any,
    state: CogletAgentState,
    env_info: Any,
) -> tuple[Any, CogletAgentState]:
    """Default heuristic step function.

    Modeled on the cogames starter agent:
    - No gear → go to gear station
    - Aligner/Scrambler → get hearts then go to junctions
    - Miner → go to extractors
    - Scout → wander
    """
    from mettagrid.simulator import Action  # type: ignore[import-untyped]

    action_names = env_info.action_names
    action_name_set = set(action_names)
    fallback = "noop" if "noop" in action_name_set else action_names[0]
    center = (env_info.obs_height // 2, env_info.obs_width // 2)

    tag_name_to_id: dict[str, int] = {name: idx for idx, name in enumerate(env_info.tags)}

    def resolve_tags(names: list[str]) -> set[int]:
        ids: set[int] = set()
        for n in names:
            if n in tag_name_to_id:
                ids.add(tag_name_to_id[n])
            type_n = f"type:{n}"
            if type_n in tag_name_to_id:
                ids.add(tag_name_to_id[type_n])
        return ids

    gear_station_tags = {g: resolve_tags([f"c:{g}"]) for g in GEAR}
    all_gear_tags: set[int] = set()
    for v in gear_station_tags.values():
        all_gear_tags |= v
    extractor_tags = resolve_tags([f"{e}_extractor" for e in ELEMENTS])
    junction_tags = resolve_tags(["junction"])
    heart_source_tags = resolve_tags(["hub", "chest"])

    # Parse inventory from tokens
    items: dict[str, int] = {}
    for token in obs.tokens:
        if token.location != center:
            continue
        name = token.feature.name
        if not name.startswith("inv:"):
            continue
        suffix = name[4:]
        if not suffix:
            continue
        item_name, sep, power_str = suffix.rpartition(":p")
        if not sep or not item_name or not power_str.isdigit():
            item_name = suffix
            power = 0
        else:
            power = int(power_str)
        value = int(token.value)
        if value <= 0:
            continue
        base = max(int(token.feature.normalization), 1)
        items[item_name] = items.get(item_name, 0) + value * (base ** power)

    # Determine current gear
    gear: str | None = None
    for g in GEAR:
        if items.get(g, 0) > 0:
            gear = g
            break

    has_heart = items.get("heart", 0) > 0

    # Choose target tags
    if gear is None:
        target_tags = all_gear_tags
    elif gear == "aligner":
        target_tags = junction_tags if has_heart else heart_source_tags
    elif gear == "scrambler":
        target_tags = junction_tags if has_heart else heart_source_tags
    elif gear == "miner":
        target_tags = extractor_tags
    else:
        target_tags = set()

    # Find closest target
    best_loc: tuple[int, int] | None = None
    best_dist = 999
    if target_tags:
        for token in obs.tokens:
            if token.feature.name != "tag":
                continue
            if token.value not in target_tags:
                continue
            loc = token.location
            if loc is None:
                continue
            dist = abs(loc[0] - center[0]) + abs(loc[1] - center[1])
            if dist < best_dist:
                best_dist = dist
                best_loc = (loc[0], loc[1])

    # Move toward target or wander
    def make_action(name: str) -> Any:
        if name in action_name_set:
            return Action(name=name)
        return Action(name=fallback)

    if best_loc is not None:
        dr = best_loc[0] - center[0]
        dc = best_loc[1] - center[1]
        if dr == 0 and dc == 0:
            return make_action(fallback), state
        if abs(dr) >= abs(dc):
            direction = "south" if dr > 0 else "north"
        else:
            direction = "east" if dc > 0 else "west"
        return make_action(f"move_{direction}"), state

    # Wander
    if state.wander_steps_remaining <= 0:
        state.wander_direction_index = (state.wander_direction_index + 1) % len(WANDER_DIRECTIONS)
        state.wander_steps_remaining = WANDER_STEPS
    direction = WANDER_DIRECTIONS[state.wander_direction_index]
    state.wander_steps_remaining -= 1
    return make_action(f"move_{direction}"), state


class CogletPolicy:
    """cogames MultiAgentPolicy implementation backed by a coglet step function.

    cogames instantiates this class. It delegates agent_policy(id).step(obs)
    to either a PolicyCoglet's function table or the default heuristic.
    """

    short_names = ["coglet", "coglet-policy"]

    def __init__(
        self,
        policy_env_info: Any,
        device: str = "cpu",
        step_fn: Callable[..., Any] | None = None,
        **kwargs: Any,
    ):
        self._policy_env_info = policy_env_info
        self._step_fn = step_fn or default_step_fn
        self._agents: dict[int, CogletAgentPolicy] = {}

    def agent_policy(self, agent_id: int) -> CogletAgentPolicy:
        if agent_id not in self._agents:
            self._agents[agent_id] = CogletAgentPolicy(
                policy_env_info=self._policy_env_info,
                agent_id=agent_id,
                step_fn=self._step_fn,
            )
        return self._agents[agent_id]

    def reset(self) -> None:
        self._agents.clear()


class CogletAgentPolicy:
    """Per-agent policy that calls the coglet step function."""

    def __init__(
        self,
        policy_env_info: Any,
        agent_id: int,
        step_fn: Callable[..., Any],
    ):
        self._policy_env_info = policy_env_info
        self._agent_id = agent_id
        self._step_fn = step_fn
        self._state = CogletAgentState(
            wander_direction_index=agent_id % len(WANDER_DIRECTIONS)
        )
        self._infos: dict[str, Any] = {}

    @property
    def infos(self) -> dict[str, Any]:
        return self._infos

    def step(self, obs: Any) -> Any:
        action, self._state = self._step_fn(obs, self._state, self._policy_env_info)
        return action

    def reset(self, simulation: Any = None) -> None:
        self._state = CogletAgentState(
            wander_direction_index=self._agent_id % len(WANDER_DIRECTIONS)
        )
