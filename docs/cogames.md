# CoGames CLI

## Setup

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e . && uv pip install cogames
```

Verify: `source .venv/bin/activate && cogames --version`

## Running Locally

Play a game and check the "per cog" score:

```bash
source .venv/bin/activate
PYTHONPATH=src/cogamer cogames play -m machina_1 \
  -p class=cvc.cogamer_policy.CvCPolicy \
  -c 8 -r none --seed 42
```

**Test across 5+ seeds** (42–46) and average. Single-seed results are noise.

Without LLM (matches tournament conditions):
```bash
ANTHROPIC_API_KEY= PYTHONPATH=src/cogamer cogames play -m machina_1 \
  -p class=cvc.cogamer_policy.CvCPolicy \
  -c 8 -r none --seed 42
```

## Deploying

### Prerequisites

```bash
uv sync                          # install project + dependencies
cogames auth status              # verify auth (should show email)
# If not authenticated:
cogames auth set-token <token>   # set token from secrets
```

### Upload to Season

Upload a policy to a season. Use the cogent name from `cogent/IDENTITY.md` as the policy name (`-n`). Must run from `src/cogamer/`:

```bash
cd src/cogamer && PYTHONPATH=. cogames upload \
  -p class=cvc.cogamer_policy.CvCPolicy \
  -n <cogent-name> \
  -f cvc -f mettagrid_sdk -f setup_policy.py \
  --setup-script setup_policy.py \
  --season <season> \
  --skip-validation
```

`setup_policy.py` runs on the remote server to install `anthropic[bedrock]` for LLM calls.

### Validate Before Upload

Always test locally across 5+ seeds before uploading:

```bash
for seed in 42 43 44 45 46; do
  ANTHROPIC_API_KEY= PYTHONPATH=src/cogamer cogames play -m machina_1 \
    -p class=cvc.cogamer_policy.CvCPolicy \
    -c 8 -r none --seed $seed
done
```

If average score drops vs baseline, do NOT upload — revert the change first.

## Monitoring

```bash
cogames leaderboard <season> --mine       # standings
cogames matches --season <season>         # recent matches
cogames match-artifacts <match-id>        # logs from a match
cogames season progress <season>          # stage progression
```

## Seasons

| Season | Purpose | Format |
|--------|---------|--------|
| `beta-cvc` | **Freeplay** — test against real opponents, low stakes | Self-play qualifier → 20 matches vs random partners |
| `beta-teams-tiny-fixed` | **Tournament** — ranked competition | Multi-stage elimination, team-based scoring |

Freeplay policies qualify via self-play, then play 20 matches against random partners. Use this to validate changes against diverse opponents before committing to tournament.

Tournament format: multi-stage elimination. Policies qualify via self-play, get seeded into teams, teams compete across progressive stages with culling. Final score based on team rank.

## Learnings & Experience

Games write experience to `/tmp/coglet_learnings/{game_id}.json` containing snapshots, LLM logs, and per-agent state. Use these for PCO epochs.
