# alpha — Improvement TODOs

## Candidates
- [x] Hotspot tracking: already implemented in junctions.py + aligner_target_score
- [x] (ID) Wider enemy AOE for retreat: wired _near_enemy_territory (radius 20) into _should_retreat — +458% avg score
- [x] Delay scrambler to step 300: +30% on seed 42 (20.10→26.19), 5-seed avg 22.92
- [ ] LLM stagnation detection: detect stuck agents and adjust directives
- [ ] Read teammate vibes for coordination
- [ ] Late-game pressure tuning: step 3000+ budget of 6 may be too aggressive
- [ ] Junction collapse defense: peak at step 500, collapses to 0-2 by step 5000
