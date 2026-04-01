# cvc/agent — CvC Heuristic Policy

Per-agent heuristic decision engine for the CogsGuard (CvC) tournament. Each agent runs its own independent engine instance — no shared state between agents.

## Architecture

```
CogletPolicy (MultiAgentPolicy)            # cvc/cvc_policy.py
  └── StatefulAgentPolicy[CogletAgentState]
       └── CogletPolicyImpl
            └── CogletAgentPolicy           # coglet_policy.py (heuristic overrides)
                 └── CvcEngine              # main.py (core decision tree)
                      ├── RolesMixin        # roles.py
                      ├── NavigationMixin   # navigation.py
                      ├── TargetingMixin    # targeting.py
                      ├── PressureMixin     # pressure.py
                      └── JunctionMixin     # junctions.py
```

## Files

| File | Purpose |
|---|---|
| `main.py` | CvcEngine: init, step, evaluate_state, reset, decision tree |
| `roles.py` | Role actions: miner, aligner, scrambler, gear acquisition |
| `navigation.py` | A* pathfinding, movement, stall/oscillation detection |
| `targeting.py` | Target selection, claims, sticky targets, directive routing |
| `pressure.py` | Role budgets, retreat logic, pressure metrics, deposit |
| `junctions.py` | Junction memory, hub/depot lookups |
| `world_model.py` | Per-agent entity memory (tracks known entities from observations) |
| `coglet_policy.py` | CogletAgentPolicy: optimized heuristic overrides for CvcEngine |
| `cogames_policy.py` | CvcBasePolicy: MultiAgentPolicy wrapper, creates one engine per agent |
| [`helpers/`](helpers/) | Pure functions: geometry, resources, targeting, types |

## Rules

- Each agent is fully independent. No shared dicts, objects, or communication.
- Each agent may run in a separate process.
- Shared team state comes only from `state.team_summary` (read-only, provided by the game).
