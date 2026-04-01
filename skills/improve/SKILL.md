---
name: improve
description: Run one improvement iteration. Chooses between PCO and IntelligentDesign based on recent effectiveness, runs the chosen approach, falls back to the other if it fails. Use when asked to "improve the agent", "run an improvement", or "improve".
---

# Improvement Iteration

Orchestrates improvement by choosing between `/improve.pco` and `/improve.design` based on effectiveness.

Reads `IMPROVE.md` for domain context and `COGENT.md` for the cogent's identity and personality.

## Step 0: Check COGENT.md

Read `COGENT.md`. If it still contains "The Unknown Cogent" or the `/cogamer.configure` placeholder, run `/cogamer.configure` first — the cogent needs an identity before it can improve.

## Step 1: Initialize Session State

Create `.cogent/state.json` and `.cogent/todos.md` if they don't exist yet.

## Step 2: Choose Approach

Read `.cogent/state.json` (check `approach_stats`) and `.cogent/todos.md`. Pick the approach most likely to succeed this session.

### Approach Stats (tracked in state.json)

```json
{
  "approach_stats": {
    "pco": {"attempts": 5, "improvements": 2, "last_used": "20260330-..."},
    "design": {"attempts": 8, "improvements": 5, "last_used": "20260331-..."}
  }
}
```

### Decision Rules

1. **If one approach has a clearly better hit rate**, prefer it (but still use the other ~30% of the time to keep exploring)
2. **If PCO hasn't been run in 3+ sessions**, run PCO (fresh experience reveals new signals)
3. **If there's a specific bug/TODO in todos.md**, prefer IntelligentDesign (targeted fixes)
4. **If the alpha.0 reference in IMPROVE.md has an unaddressed gap**, prefer IntelligentDesign
5. **If both are similar**, alternate
6. **If no stats yet**, start with IntelligentDesign (the agent can see obvious wins first)

Log the chosen approach in the session's `plan.md`.

## Step 3: Run Chosen Approach

Run `/improve.pco` or `/improve.design`.

## Step 4: Handle Failure

If the chosen approach didn't produce an improvement (no accepted patch, or scores regressed):

1. Log the failure
2. If time/context permits, try the **other** approach as a fallback
3. If both fail, log it and move on — not every session produces a win

## Step 5: Update Approach Stats

After the session, update `approach_stats` in `.cogent/state.json`:

```python
stats = state["approach_stats"][approach]
stats["attempts"] += 1
if improved:
    stats["improvements"] += 1
stats["last_used"] = session_timestamp
```

Also update `.cogent/todos.md` with the approach tag:
```
- [x] (ID) Fixed chain-aware scoring in helpers/targeting.py — +41% avg
- [x] (PCO) Learner patched should_retreat with extra HP caution
- [x] (ID) Improved LLM prompt to return role suggestions
```

## Principles

- **One change per session.** Don't stack changes from both approaches.
- **Track what works.** The stats drive future decisions.
- **Alternate when tied.** Don't get stuck in one mode.
- **Fallback on failure.** If PCO produces nothing, try design (and vice versa).
