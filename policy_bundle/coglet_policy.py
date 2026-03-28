"""Coglet policy for cogames CvC.

All interactions via movement. Score = aligned junctions held per tick.
Key challenge: agents need all 4 resource types but extractors are in separate map regions.
Solution: use local position features to navigate between hub and extractor regions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mettagrid.policy.policy import MultiAgentPolicy, AgentPolicy  # type: ignore[import-untyped]
from mettagrid.policy.policy_env_interface import PolicyEnvInterface  # type: ignore[import-untyped]
from mettagrid.simulator import Action  # type: ignore[import-untyped]

ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")
DIRS = ("east", "south", "west", "north")

# Known map layout (from cogora/mettagrid_sdk):
# Hub at spawn (0,0). Gear stations at known offsets.
# Extractors at ~28 cells out in corners.
# Coordinates: (x, y) where x=east, y=south from spawn.
_STATION_OFFSETS = {
    "aligner": (-3, 4),
    "scrambler": (-1, 4),
    "miner": (1, 4),
    "scout": (3, 4),
}
# Extractor regions (approximate corners where resources are)
_EXTRACTOR_REGIONS = [(-20, -20), (20, -20), (-20, 20), (20, 20)]
_HUB_POS = (0, 0)


@dataclass
class S:
    """Agent state."""
    step: int = 0
    wd: int = 0  # wander direction
    wl: int = 0  # wander left
    pp: tuple[int, int] | None = None  # prev pos
    stk: int = 0  # stuck counter
    phase: str = "explore"  # explore, return_hub, get_gear, get_hearts, align
    explore_dir: int = 0  # which direction to explore (0-3)
    explore_steps: int = 0  # steps spent exploring current direction
    visit_hub_countdown: int = 0  # steps to spend at hub


class CogletAgentPolicy(AgentPolicy):
    def __init__(self, env: PolicyEnvInterface, aid: int):
        super().__init__(env)
        self._env = env
        self._id = aid
        self._cx = env.obs_height // 2
        self._cy = env.obs_width // 2
        self._c = (self._cx, self._cy)
        self._t = {n: i for i, n in enumerate(env.tags)}
        self._a = set(env.action_names)
        self._s = S(wd=aid % 4, explore_dir=aid % 4)

    def _act(self, n: str) -> Action:
        return Action(name=n if n in self._a else "noop")

    def _tag(self, n: str) -> int | None:
        return self._t.get(n)

    def _inv(self, obs: Any) -> dict[str, int]:
        it: dict[str, int] = {}
        for tk in obs.tokens:
            if tk.location != self._c:
                continue
            nm = tk.feature.name
            if not nm.startswith("inv:"):
                continue
            sf = nm[4:]
            if not sf:
                continue
            item, sep, ps = sf.rpartition(":p")
            if not sep or not item or not ps.isdigit():
                item, pw = sf, 0
            else:
                pw = int(ps)
            v = int(tk.value)
            if v <= 0:
                continue
            b = max(int(tk.feature.normalization), 1)
            it[item] = it.get(item, 0) + v * (b ** pw)
        return it

    def _find(self, obs: Any, names: list[str]) -> tuple[int, int] | None:
        ids = {self._tag(n) for n in names} - {None}
        if not ids:
            return None
        best = None
        bd = 999
        for tk in obs.tokens:
            if tk.feature.name != "tag" or tk.value not in ids:
                continue
            loc = tk.location
            if loc is None:
                continue
            d = abs(loc[0] - self._cx) + abs(loc[1] - self._cy)
            if d < bd:
                bd = d
                best = (loc[0], loc[1])
        return best

    def _go(self, t: tuple[int, int]) -> Action:
        dr = t[0] - self._cx
        dc = t[1] - self._cy
        if dr == 0 and dc == 0:
            # On target — step off in alternating direction
            return self._act(f"move_{DIRS[self._s.step % 4]}")
        s = self._s.step
        if s % 2 == 0:
            if abs(dr) >= abs(dc):
                return self._act("move_south" if dr > 0 else "move_north")
            return self._act("move_east" if dc > 0 else "move_west")
        else:
            if abs(dc) >= abs(dr):
                return self._act("move_east" if dc > 0 else "move_west")
            return self._act("move_south" if dr > 0 else "move_north")

    def _wall_at(self, obs: Any, dr: int, dc: int) -> bool:
        """Check if there's a wall at offset (dr, dc) from center."""
        wt = self._tag("type:wall")
        if wt is None:
            return False
        r, c = self._cx + dr, self._cy + dc
        for tk in obs.tokens:
            if tk.feature.name == "tag" and tk.value == wt:
                loc = tk.location
                if loc and loc[0] == r and loc[1] == c:
                    return True
        return False

    def _smart_walk(self, obs: Any, d: str) -> Action:
        """Walk in direction d, but avoid walls by trying perpendicular."""
        deltas = {"north": (-1, 0), "south": (1, 0), "east": (0, 1), "west": (0, -1)}
        perps = {"north": ["east", "west"], "south": ["west", "east"],
                 "east": ["north", "south"], "west": ["south", "north"]}
        dr, dc = deltas[d]
        if not self._wall_at(obs, dr, dc):
            return self._act(f"move_{d}")
        # Wall ahead — try perpendicular directions
        for alt in perps[d]:
            adr, adc = deltas[alt]
            if not self._wall_at(obs, adr, adc):
                return self._act(f"move_{alt}")
        # All blocked — try opposite
        opp = {"north": "south", "south": "north", "east": "west", "west": "east"}
        return self._act(f"move_{opp[d]}")

    def _wander(self, obs: Any) -> Action:
        s = self._s
        if s.wl <= 0:
            s.wd = (s.wd + 1) % 4
            s.wl = 8
        s.wl -= 1
        return self._smart_walk(obs, DIRS[s.wd])

    def _pos(self, obs: Any) -> tuple[int, int] | None:
        """Get position relative to spawn from lp features (global tokens)."""
        e = w = n = s = 0
        for tk in obs.tokens:
            f = tk.feature.name
            if f == "lp:east": e = int(tk.value)
            elif f == "lp:west": w = int(tk.value)
            elif f == "lp:north": n = int(tk.value)
            elif f == "lp:south": s = int(tk.value)
        if e == 0 and w == 0 and n == 0 and s == 0:
            return None
        # Return (x, y) where x=east-west, y=south-north (matching cogora convention)
        return (e - w, s - n)

    def _goto_abs(self, obs: Any, target: tuple[int, int]) -> Action:
        """Navigate toward absolute position (relative to spawn) using lp."""
        pos = self._pos(obs)
        if pos is None:
            return self._wander(obs)
        dx = target[0] - pos[0]
        dy = target[1] - pos[1]
        if abs(dx) <= 1 and abs(dy) <= 1:
            # Close enough — we're there
            return self._act("noop")
        # Pick primary direction
        if abs(dx) >= abs(dy):
            d = "east" if dx > 0 else "west"
        else:
            d = "south" if dy > 0 else "north"
        return self._smart_walk(obs, d)

    def _stuck(self, obs: Any) -> bool:
        p = self._pos(obs)
        s = self._s
        if p and p == s.pp:
            s.stk += 1
        else:
            s.stk = 0
        s.pp = p
        return s.stk > 3

    def _unstick(self, obs: Any) -> Action:
        s = self._s
        s.stk = 0
        s.wd = (s.wd + 1) % 4
        return self._smart_walk(obs, DIRS[s.wd])

    def _gear(self, inv: dict[str, int]) -> str | None:
        for g in ("aligner", "scrambler", "miner", "scout"):
            if inv.get(g, 0) > 0:
                return g
        return None

    def _can_buy(self, inv: dict[str, int]) -> bool:
        return (inv.get("carbon", 0) >= 3 and inv.get("oxygen", 0) >= 1 and
                inv.get("germanium", 0) >= 1 and inv.get("silicon", 0) >= 1)

    def step(self, obs: Any) -> Action:
        s = self._s
        s.step += 1
        inv = self._inv(obs)
        gear = self._gear(inv)
        hearts = inv.get("heart", 0)

        if self._stuck(obs):
            return self._unstick(obs)

        # ALIGN: have aligner + hearts → find unjunctions
        if gear == "aligner" and hearts > 0:
            our = self._tag("net:cogs")
            ours: set[tuple[int, int]] = set()
            if our is not None:
                for tk in obs.tokens:
                    if tk.feature.name == "tag" and tk.value == our and tk.location:
                        ours.add((tk.location[0], tk.location[1]))
            jt = self._tag("type:junction")
            if jt is not None:
                best = None
                bd = 999
                for tk in obs.tokens:
                    if tk.feature.name != "tag" or tk.value != jt:
                        continue
                    loc = tk.location
                    if not loc:
                        continue
                    p = (loc[0], loc[1])
                    if p in ours:
                        continue
                    d = abs(loc[0] - self._cx) + abs(loc[1] - self._cy)
                    if d < bd:
                        bd = d
                        best = p
                if best:
                    return self._go(best)
            return self._wander(obs)

        # HEARTS: have aligner but no hearts → navigate to hub
        if gear == "aligner":
            hub = self._find(obs, ["type:hub"])
            if hub:
                return self._go(hub)
            # Can't see hub — navigate toward (0,0)
            return self._goto_abs(obs, _HUB_POS)

        # GEAR: can afford aligner → navigate to aligner station
        if self._can_buy(inv):
            st = self._find(obs, ["type:c:aligner"])
            if st:
                return self._go(st)
            # Navigate to known aligner station position
            return self._goto_abs(obs, _STATION_OFFSETS["aligner"])

        # MINE: navigate to extractor regions, cycling through corners
        # If we can see a needed extractor, go to it directly
        needed = [e for e in ELEMENTS if inv.get(e, 0) < 1]
        if not needed:
            needed = [e for e in ELEMENTS if inv.get(e, 0) < 3]
        if not needed:
            needed = list(ELEMENTS)

        needed_tags = [f"type:{e}_extractor" for e in needed]
        ext = self._find(obs, needed_tags)
        if ext:
            return self._go(ext)

        # Can't see needed extractors — navigate to extractor regions
        s.explore_steps += 1
        if s.explore_steps > 80:
            s.explore_steps = 0
            s.explore_dir = (s.explore_dir + 1) % 4

        target_region = _EXTRACTOR_REGIONS[s.explore_dir % len(_EXTRACTOR_REGIONS)]
        return self._goto_abs(obs, target_region)

    def reset(self, simulation: Any = None) -> None:
        self._s = S(wd=self._id % 4, explore_dir=self._id % 4)


class CogletPolicy(MultiAgentPolicy):
    short_names = ["coglet", "coglet-policy"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", **kwargs: Any):
        super().__init__(policy_env_info, device=device, **kwargs)
        self._agents: dict[int, CogletAgentPolicy] = {}

    def agent_policy(self, agent_id: int) -> CogletAgentPolicy:
        if agent_id not in self._agents:
            self._agents[agent_id] = CogletAgentPolicy(self._policy_env_info, agent_id)
        return self._agents[agent_id]

    def reset(self) -> None:
        self._agents.clear()
