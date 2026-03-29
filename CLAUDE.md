# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Related Repos

- **metta-ai/cogos** — CogOS operating system
- **metta-ai/cogora** — Cogora platform

## Project Structure

```
src/coglet/     # Framework: Coglet base class + mixins
cogames/        # CvC player: Coach, PlayerCoglet, PolicyCoglet
tests/          # 108 unit + integration tests (pytest + pytest-asyncio)
docs/           # Architecture design docs
```

See [AGENTS.md](AGENTS.md) for detailed component reference and patterns.

## Architecture

Coglet is a framework for fractal asynchronous control of distributed agent systems, built on two primitives:

- **COG** (Create, Observe, Guide) — slow, reflective supervisor that spawns and manages LETs
- **LET** (Listen, Enact, Transmit) — fast, reactive executor that handles events

A Coglet is both: every COG is itself a LET under a higher COG, forming a recursive temporal hierarchy. The COG/LET boundary is a protocol contract, not a deployment boundary.

### Communication Model

- **Data plane**: `@listen(channel)` — receive data from named channels
- **Control plane**: `@enact(command_type)` — receive commands from supervising COG
- **Output**: `transmit(channel, data)` — push results outbound
- **Supervision**: `observe(handle, channel)`, `guide(handle, command)`, `create(config)`
- All communication is async, location-agnostic, fire-and-forget

### Mixins

LifeLet (lifecycle hooks), GitLet (repo-as-policy), LogLet (log stream), TickLet (`@every` periodic), ProgLet (unified program table with pluggable executors), MulLet (fan-out N children), SuppressLet (output gating).

### Runtime Features

- `CogletRuntime.tree()` — ASCII visualization of the live supervision tree
- `CogletTrace` — jsonl event recording for post-mortem debugging
- Restart policy — `CogletConfig(restart="on_error", max_restarts=3, backoff_s=1.0)`
- `Coglet.on_child_error()` — parent decides restart/stop/escalate on child failure
- `TickLet.on_ticker_error()` — overridable hook for ticker exceptions

### CvC Player Stack

Coach (Claude Code) → PlayerCoglet (GitLet) → PolicyCoglet (ProgLet + LLM brain)

### Key Commands

```bash
# Run tests
PYTHONPATH=src python -m pytest tests/ -v

# Play locally
cogames play -m machina_1 -p class=cvc.cvc_policy.CogletPolicy -c 8 --seed 42

# Upload to tournament
cogames upload -p class=cvc.cvc_policy.CogletPolicy -n coglet-v0 \
  -f cvc -f mettagrid_sdk -f setup_policy.py \
  --setup-script setup_policy.py --season beta-cvc
```

### Docs

- [AGENTS.md](AGENTS.md) — Component reference for AI agents working with this codebase
- [README.md](README.md) — Project overview and quickstart
- [docs/coglet.md](docs/coglet.md) — Architecture design (COG/LET primitives)
- [docs/framework.md](docs/framework.md) — Framework implementation reference
- [docs/improvements.md](docs/improvements.md) — Architectural improvements and status
- [docs/tournament.md](docs/tournament.md) — Tournament system design
- [docs/cvc-player.md](docs/cvc-player.md) — CvC player system (Coach, Player, Policy)
