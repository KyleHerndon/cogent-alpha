"""Target scoring, claiming, and alignment network helpers."""

from __future__ import annotations

from cvc.agent.helpers.geometry import manhattan
from cvc.agent.helpers.types import (
    _CLAIMED_TARGET_PENALTY,
    _EXTRACTOR_MEMORY_STEPS,
    _HUB_ALIGN_DISTANCE,
    _JUNCTION_ALIGN_DISTANCE,
    _JUNCTION_AOE_RANGE,
    _STATION_TARGETS_BY_AGENT,
    _TARGET_CLAIM_STEPS,
    KnownEntity,
)


def within_alignment_network(
    candidate: tuple[int, int],
    sources: list[KnownEntity],
) -> bool:
    for source in sources:
        max_distance = _HUB_ALIGN_DISTANCE if source.entity_type == "hub" else _JUNCTION_ALIGN_DISTANCE
        if manhattan(candidate, source.position) <= max_distance:
            return True
    return False


def teammate_closer_to_target(
    *,
    current_position: tuple[int, int],
    target: tuple[int, int],
    teammate_positions: list[tuple[int, int]],
) -> bool:
    """Check if any teammate aligner is closer to the target than we are."""
    my_dist = manhattan(current_position, target)
    for pos in teammate_positions:
        if manhattan(pos, target) < my_dist:
            return True
    return False


def aligner_target_score(
    *,
    current_position: tuple[int, int],
    candidate: KnownEntity,
    unreachable: list[KnownEntity],
    enemy_junctions: list[KnownEntity],
    claimed_by_other: bool,
    hub_position: tuple[int, int] | None = None,
    friendly_sources: list[KnownEntity] | None = None,
    hotspot_count: int = 0,
    teammate_closer: bool = False,
) -> tuple[float, float]:
    distance = float(manhattan(current_position, candidate.position))
    expansion = sum(
        1 for entity in unreachable if manhattan(candidate.position, entity.position) <= _JUNCTION_ALIGN_DISTANCE
    )
    enemy_aoe = (
        1.0
        if any(manhattan(candidate.position, enemy.position) <= _JUNCTION_AOE_RANGE for enemy in enemy_junctions)
        else 0.0
    )
    # Strongly prefer hub-proximal junctions: less travel, safer, faster cycling
    hub_penalty = 0.0
    if hub_position is not None:
        hub_dist = float(manhattan(hub_position, candidate.position))
        if hub_dist > 25:
            hub_penalty = (hub_dist - 25) * 8.0 + 50.0
        elif hub_dist > 15:
            hub_penalty = (hub_dist - 15) * 3.0 + 10.0
        elif hub_dist > 10:
            hub_penalty = (hub_dist - 10) * 1.5 + 2.0
        else:
            hub_penalty = hub_dist * 0.3
    # Reduce hotspot penalty for hub-proximal junctions (worth defending)
    hotspot_weight = 8.0
    if hub_position is not None:
        hub_dist = float(manhattan(hub_position, candidate.position))
        if hub_dist <= 10:
            hotspot_weight = 2.0  # near hub: still recapture despite contest
        elif hub_dist <= 15:
            hotspot_weight = 5.0
    hotspot_penalty = min(hotspot_count, 3) * hotspot_weight
    # Bonus for junctions near existing friendly network (chain-building)
    # Denser chains are harder to disrupt and hold territory longer
    network_bonus = 0.0
    if friendly_sources:
        nearby_friendly = sum(
            1
            for source in friendly_sources
            if source.entity_type != "hub"
            and manhattan(candidate.position, source.position) <= _JUNCTION_ALIGN_DISTANCE
        )
        network_bonus = min(nearby_friendly, 4) * 2.0
    return (
        distance
        - min(expansion * 5.0, 40.0)
        + enemy_aoe * 8.0
        + (_CLAIMED_TARGET_PENALTY if claimed_by_other else 0.0)
        + hub_penalty
        + hotspot_penalty
        - network_bonus,
        -float(expansion),
    )


def is_claimed_by_other(
    *,
    claims: dict[tuple[int, int], tuple[int, int]],
    candidate: tuple[int, int],
    agent_id: int,
    step: int,
) -> bool:
    claim = claims.get(candidate)
    if claim is None:
        return False
    owner_id, owner_step = claim
    if owner_id == agent_id:
        return False
    return step - owner_step <= _TARGET_CLAIM_STEPS


def is_usable_recent_extractor(entity: KnownEntity, *, step: int) -> bool:
    return step - entity.last_seen_step <= _EXTRACTOR_MEMORY_STEPS


def scramble_target_score(
    *,
    current_position: tuple[int, int],
    hub_position: tuple[int, int],
    candidate: KnownEntity,
    neutral_junctions: list[KnownEntity],
    friendly_junctions: list[KnownEntity] | None = None,
) -> tuple[float, float]:
    distance = float(manhattan(current_position, candidate.position))
    blocked_neutrals = sum(
        1 for neutral in neutral_junctions if manhattan(candidate.position, neutral.position) <= _JUNCTION_AOE_RANGE
    )
    # Extra bonus for neutrals that are within our alignment network (actionable targets)
    reachable_blocked = 0
    for neutral in neutral_junctions:
        if manhattan(candidate.position, neutral.position) > _JUNCTION_AOE_RANGE:
            continue
        # Check if neutral is reachable from hub or friendly junctions
        if manhattan(hub_position, neutral.position) <= _HUB_ALIGN_DISTANCE:
            reachable_blocked += 1
        elif friendly_junctions and any(
            manhattan(f.position, neutral.position) <= _JUNCTION_ALIGN_DISTANCE for f in friendly_junctions
        ):
            reachable_blocked += 1
    corner_pressure = min(manhattan(hub_position, candidate.position) / 8.0, 10.0)
    # Strongly prioritize enemy junctions near our friendly network (defending our score)
    threat_bonus = 0.0
    if friendly_junctions:
        threatened = sum(
            1 for f in friendly_junctions if manhattan(candidate.position, f.position) <= _JUNCTION_ALIGN_DISTANCE
        )
        threat_bonus = threatened * 10.0
    return (
        distance - blocked_neutrals * 6.0 - reachable_blocked * 4.0 - corner_pressure - threat_bonus,
        -float(blocked_neutrals + reachable_blocked),
    )


def spawn_relative_station_target(agent_id: int, role: str) -> tuple[int, int] | None:
    station_targets = _STATION_TARGETS_BY_AGENT.get(role)
    if station_targets is None:
        return None
    return station_targets.get(agent_id)
