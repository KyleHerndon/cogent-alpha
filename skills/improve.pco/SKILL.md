---
name: improve.pco
description: PCO improvement iteration. Plays a game, collects experience, runs CvCLearner to propose program patches, tests locally, and submits if improved. Use when asked to "run PCO" or "evolve programs".
---

# PCO Improvement

Run one PCO (Program Conditioned Optimization) cycle: play → collect experience → learner proposes patches → test → submit.

Reads eval/submit commands from `IMPROVE.md`.

## Steps

### 1. Eval Baseline

Run eval from `IMPROVE.md` on seed 42 to establish baseline score.

### 2. Play a Game & Collect Experience

```bash
rm -f /tmp/coglet_learnings/*.json
```

Run eval again (experience is written to `/tmp/coglet_learnings/` automatically).

### 3. Run PCO Epoch

```python
import asyncio, json, glob, anthropic
from cvc.pco_runner import run_pco_epoch
from cvc.programs import all_programs

f = glob.glob('/tmp/coglet_learnings/*.json')[0]
experience = json.load(open(f))['snapshots']

result = asyncio.run(run_pco_epoch(
    experience=experience,
    programs=all_programs(),
    client=anthropic.Anthropic(),
    max_retries=2,
))
```

Log signals (resource, junction, survival magnitudes) and proposed patches.

### 4. Review & Apply Patch

If `result["accepted"]` and patch looks reasonable:
- Fix any invalid API calls (the learner sometimes invents methods)
- Apply to `programs.py` — only modify the specific function
- **Valid GameState API**: see `IMPROVE.md`

If not accepted, log why and report back to `improve` (it may switch to design).

### 5. Test Across Seeds

Run eval across 5+ seeds. If average score drops vs baseline, **revert the patch**.

### 6. Submit if Improved

Use the submit command from `IMPROVE.md`. Log the submission version.

## Output

Report back with:
- `accepted`: whether PCO produced an accepted patch
- `improved`: whether scores improved after applying the patch
- `score_before`: baseline average
- `score_after`: post-change average (or null if reverted)
- `signals`: loss signal summary from PCO
- `description`: what changed
