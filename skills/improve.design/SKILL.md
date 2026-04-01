---
name: improve.design
description: IntelligentDesign improvement iteration. Directly analyzes code and prompts, identifies a specific improvement, implements it, tests, and submits. Use when asked to "review the code", "improve the prompts", or "intelligent design".
---

# IntelligentDesign Improvement

Directly read the code and prompts, identify a specific improvement, implement it, test, submit.

Reads architecture and alpha.0 reference from `IMPROVE.md`.

## Steps

### 1. Eval Baseline

Run eval from `IMPROVE.md` on seed 42 to establish baseline score.

### 2. Analyze

Pick ONE focus area based on `IMPROVE.md` strategies, `.cogent/todos.md`, and what hasn't been tried:

1. **Code review**: Read engine files (`agent/main.py`, `roles.py`, `targeting.py`, `pressure.py`). Look for bugs, inefficiencies, or gaps vs the alpha.0 reference in `IMPROVE.md`
2. **Prompt review**: Read `_build_analysis_prompt()` and `_parse_analysis()` in `programs.py`. Is the LLM seeing the right info? Could it return more than just `resource_bias`? Could it detect stagnation like alpha.0 does?
3. **Scoring review**: Read `helpers/targeting.py`. Are `aligner_target_score` and `scramble_target_score` well-tuned? Compare weights vs alpha.0
4. **Parameter comparison**: Compare constants in `helpers/types.py` and `pressure.py` against alpha.0 (e.g. `RETREAT_MARGIN` 15 vs 20, enemy AOE radius 4 vs 20)
5. **Architecture improvement**: Read `cvc_policy.py`. Is the LLM feedback loop working? Could the `analyze` program influence more than mining? Could it adjust role allocation or targeting?

### 3. Implement

Make a focused, isolated change. Write the code directly.

- **Prompt improvements**: modify `_build_analysis_prompt()` or `_parse_analysis()` in `programs.py`
- **Code improvements**: modify the relevant engine file in `agent/`
- **Parameter changes**: modify `helpers/types.py` or the relevant mixin
- **New programs**: add to `programs.py` and wire into `all_programs()`

### 4. Test Across Seeds

Run eval across 5+ seeds. If average score drops vs baseline, **revert**.

### 5. Submit if Improved

If scores improved, automatically submit to freeplay without asking. Read the cogent name from `COGENT.md` (the `# heading`) and use it as the policy name. Run from `src/cogamer/`:

```bash
cd src/cogamer && source ../../.venv/bin/activate && PYTHONPATH=. cogames upload \
  -p class=cvc.cvc_policy.CvCPolicy \
  -n <cogent-name> \
  -f cvc -f mettagrid_sdk -f setup_policy.py \
  --setup-script setup_policy.py \
  --season beta-cvc \
  --skip-validation
```

For example, if COGENT.md has `# corgy`, use `-n corgy`.

Do NOT ask the user for confirmation — submit automatically. Log the submission version.

## Output

Report back with:
- `improved`: whether scores improved
- `score_before`: baseline average
- `score_after`: post-change average (or null if reverted)
- `focus`: which area was analyzed (code/prompt/scoring/parameter/architecture)
- `description`: what changed and why
