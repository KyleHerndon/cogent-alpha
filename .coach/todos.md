# Coach TODO

## Current Priorities
- [ ] Monitor v94 freeplay (reachable-blocked scramble targeting)
- [ ] Monitor v95 tournament entry
- [ ] Monitor v92 freeplay (scrambler explore offsets)
- [ ] Monitor v88 freeplay (expansion bonus cap 40)
- [ ] Update IMPROVE.md constants: JUNCTION_ALIGN_DISTANCE=15 (not 3), JUNCTION_AOE_RANGE=10 (not 4)

## Improvement Ideas
- [ ] Map topology analysis — understand wall patterns to improve exploration
- [ ] Dynamic role switching — let agents switch roles based on game state
- [ ] PCO evolution — run more epochs to evolve program table
- [ ] Better junction discovery — agents may miss junctions behind walls
- [ ] Adaptive role allocation based on game phase (not just step count)
- [ ] Study opponent replays via `cogames match-artifacts <id>` for new strategies
- [ ] Clean up dead code in programs.py (unused _should_retreat extra logic)
- [ ] Network-dist scoring with conservative blend (50/50 hub+network dist)
- [ ] Scrambler heart priority — ensure scrambler gets hearts before aligners

## Dead Ends (Don't Retry)
- [x] Retreat threshold tuning — always trades deaths for score regression
- [x] Heart batch target changes — 3 for aligners is the sweet spot
- [x] Outer explore ring at manhattan 35 — sends agents too far, they die
- [x] Remove alignment network filter — required by game mechanics
- [x] Expand alignment range +5 — causes targeting unreachable junctions
- [x] Remove scramblers entirely (SCRIMMAGE only) — confirmed twice in self-play, scramblers help
- [x] Resource-aware pressure budgets — too aggressive scaling
- [x] Spread miner resource bias — least-available targeting is better
- [x] Reorder aligner explore offsets — existing order works better
- [x] Increase claim penalty (12→25) — pushes aligners to suboptimal targets
- [x] More aligners (6) / fewer miners (2) — economy can't sustain
- [x] Wider A* margin (12→20) — slower computation wastes ticks
- [x] Emergency mining threshold 50 or 10 — hurts high-scoring seeds more than helps low ones
- [x] Early pressure ramp (step 200) — economy can't sustain with only 2 miners, -8.8%
- [x] Wider enemy AOE radius 15 for retreat — agents retreat too much, avg 1.83 vs 2.10
- [x] Delay scramblers to step 500 — avg 0.99 vs 2.10, opponent builds unchallenged
- [x] Hotspot recapture bonus (prioritize recently-scrambled junctions) — agents waste hearts fighting over contested junctions, -27% regression
- [x] Hotspot decay (every 1000 steps) — -9% regression, not enough improvement to justify
- [x] Reading teammate vibes — vibes are NOT visible in game API (not possible)
- [x] Aggressive adaptive role allocation — killed 1v1 scores (excess_aligners math counts ALL teammates)
- [x] Pure network-dist scoring — agents venture too far and die (-31% avg)
- [x] Removing teammate penalty (v60) — hurt freeplay (1.12 vs 1.81)
- [x] Aligner refill before explore — -29.2% regression, aligners waste time at hub
- [x] Scrambler heart batch 2→1 — -34.1% regression, wastes hearts
- [x] Early pressure ramp (step 200) — economy can't sustain with only 2 miners, -8.8%

## Testing Notes
- **ALWAYS test 1v1 with `cogames run -c 16 -p A -p B`** not just scrimmage
- Scrimmage (`-c 8`) is self-play where one policy controls all agents — inflated scores
- Self-play has ENORMOUS variance (0.00-12.03 on same seed across runs) — not deterministic
- Self-play improvements DON'T predict freeplay improvements — the two are weakly correlated
- Need 7+ seeds minimum for any signal in self-play

## Done
- [x] (ID) Reachable-blocked scramble targeting — self-play +49.0%, submitted v94/v95
- [x] (ID) Mid-range scrambler explore offsets (25 before 36) — self-play +24.9%, submitted v92/v93
- [x] (ID) Expansion bonus cap 30→40 — self-play +16.4%, submitted v88/v89
- [x] (ID) Faster unstick 12→8 steps — variance halved, min improved, submitted v86/v87
- [x] (ID) Scramble blocked_neutrals weight 4.0→6.0 — self-play neutral, submitted v84/v85
- [x] (ID) Extractor memory 600→800 — self-play +4.1%, cumulative +37.9% vs baseline, submitted v80/v81
- [x] (ID) Hub-proximal hotspot discount — self-play +9.6%, cumulative +32.5% vs baseline, submitted v76/v77
- [x] (ID) Junction memory 400→800 steps — self-play +8.2%, submitted v72/v73
- [x] (ID) Network proximity bonus (alpha.0 weight 0.5 for chain-building) — self-play neutral, submitted v70/v71
- [x] (ID) Hotspot tracking (deprioritize contested junctions, alpha.0-style) — self-play +49.5%, submitted v66/v67
- [x] Establish baseline: 1.31 on machina_1 (seed 42)
- [x] Remove LLM resource herding: 1.31 → 1.72
- [x] Full ProgLet policy (GameState wraps engine): 1.76
- [x] PCO pipeline validated (learner proposes patches)
- [x] Session 5: tested retreat/budget/heart tuning — no improvement found
- [x] Session 6: fixed 4-agent role allocation (0.00 → ~0.95), submitted v13
- [x] Session 7: fixed coglet imports for tournament bundle, limited emergency mining
- [x] Session 8: shared junction memory + wider exploration (0.95 → 1.65 avg, v16)
- [x] Session 9: fixed role misassignment bug (1.65 → 6.18 avg, v17)
- [x] Session 10: chain-aware junction scoring (6.18 → 8.74 avg, v18)
- [x] Session 11: exhaustive parameter search — no improvement found, v18 is well-tuned
- [x] Session 12: emergency mining threshold tests — no improvement found
- [x] Session 13: CRITICAL FIX — agent_id normalization (% 8) for tournament mode (1v1 avg 18.38, v19)
- [x] Session 36: teammate-aware aligner targeting (+30% avg self-play), submitted v26/v27
- [x] Session 37 (ID): Fix double role-adjustment + wider enemy retreat + junction memory 400→600 (+11% self-play, v30/v31)
- [x] Session 39 (ID): Reduced heart retreat margin (hearts*5→hearts*3), tested hotspot changes (reverted). Submitted v56/v57
- [x] Session 40 (ID): Removed teammate penalty from aligner scoring (10.0→0). Self-play neutral (-3.6%). Submitted v60/v61
- [x] Session 41 (ID): Reduced late-game scramblers 2→1 (extra aligner). Self-play +216% (avg 0.87→2.75). Submitted v64/v65
