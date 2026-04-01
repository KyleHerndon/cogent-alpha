"""Coach: orchestrates PolicyCoglet across many games.

The Coach is NOT a Coglet — it's a Claude Code session that:
1. Submits PolicyCoglet to cogames for each game
2. Reads learnings/experience after each game
3. Maintains a changelog of analyses, insights, and code changes
4. Commits improvements to the repo
5. Repeats

The changelog lives at cogames/coach_log.jsonl — one JSON object per line.
Each entry has a type (game, insight, change) and timestamp.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LEARNINGS_DIR = os.environ.get("COGLET_LEARNINGS_DIR", "/tmp/coglet_learnings")
_COACH_LOG = Path(__file__).parent / "coach_log.jsonl"


# --- Changelog ---

def log_entry(entry_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Append an entry to the coach changelog."""
    entry = {
        "type": entry_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **data,
    }
    with _COACH_LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def log_game(game_id: str, score: float, learnings: dict[str, Any] | None) -> dict[str, Any]:
    """Log a completed game."""
    return log_entry("game", {
        "game_id": game_id,
        "score": score,
        "llm_calls": len(learnings.get("llm_log", [])) if learnings else 0,
        "duration_s": learnings.get("duration_s") if learnings else None,
    })


def log_insight(insight: str, source: str = "coach") -> dict[str, Any]:
    """Log an analysis insight from reviewing games."""
    return log_entry("insight", {"insight": insight, "source": source})


def log_change(description: str, files: list[str] | None = None) -> dict[str, Any]:
    """Log a code change made to the policy."""
    return log_entry("change", {"description": description, "files": files or []})


def read_log(last_n: int | None = None) -> list[dict[str, Any]]:
    """Read the coach changelog."""
    if not _COACH_LOG.exists():
        return []
    entries = []
    for line in _COACH_LOG.read_text().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    if last_n is not None:
        entries = entries[-last_n:]
    return entries


def format_log(entries: list[dict[str, Any]]) -> str:
    """Format changelog entries for display."""
    lines = []
    for e in entries:
        ts = e.get("timestamp", "")[:19]
        t = e["type"]
        if t == "game":
            lines.append(f"[{ts}] GAME {e.get('game_id', '?')}: score={e.get('score', '?')} "
                         f"llm_calls={e.get('llm_calls', 0)} duration={e.get('duration_s', '?')}s")
        elif t == "insight":
            lines.append(f"[{ts}] INSIGHT: {e.get('insight', '')}")
        elif t == "change":
            lines.append(f"[{ts}] CHANGE: {e.get('description', '')} files={e.get('files', [])}")
        else:
            lines.append(f"[{ts}] {t}: {e}")
    return "\n".join(lines)


# --- Game execution ---

def play_game(
    mission: str = "machina_1",
    seed: int = 42,
    render_mode: str = "none",
    num_cogs: int = 8,
) -> dict[str, Any]:
    """Run a single game locally and return results + learnings."""
    cmd = [
        "cogames", "play",
        "-m", mission,
        "-p", "class=cvc.cvc_policy.CogletPolicy",
        "-c", str(num_cogs),
        "-r", render_mode,
        "--seed", str(seed),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    learnings = read_latest_learnings()
    game_id = learnings.get("game_id", f"seed_{seed}") if learnings else f"seed_{seed}"

    # Extract score from output
    score = _parse_score(result.stdout)
    log_game(game_id, score, learnings)

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "score": score,
        "learnings": learnings,
    }


def _parse_score(stdout: str) -> float:
    """Extract per-cog score from cogames play output."""
    for line in stdout.splitlines():
        if "per cog" in line:
            parts = line.split()
            for p in reversed(parts):
                try:
                    return float(p)
                except ValueError:
                    continue
    return 0.0


def upload_policy(
    name: str = "coglet-v0",
    season: str = "beta-cvc",
) -> str:
    """Upload the current policy to cogames tournament."""
    cmd = [
        "cogames", "upload",
        "-p", "class=cvc.cvc_policy.CogletPolicy",
        "-n", name,
        "-f", "cvc",
        "-f", "mettagrid_sdk",
        "-f", "setup_policy.py",
        "--setup-script", "setup_policy.py",
        "--season", season,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    log_change(f"uploaded {name} to {season}", [])
    return output


# --- Learnings ---

def read_latest_learnings() -> dict[str, Any] | None:
    """Read the most recent game's learnings."""
    learnings_dir = Path(_LEARNINGS_DIR)
    if not learnings_dir.exists():
        return None
    files = sorted(learnings_dir.glob("game_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    return json.loads(files[-1].read_text())


def read_all_learnings() -> list[dict[str, Any]]:
    """Read all accumulated game learnings."""
    learnings_dir = Path(_LEARNINGS_DIR)
    if not learnings_dir.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(learnings_dir.glob("game_*.json"))]


def summarize_experience() -> str:
    """Summarize all experience: changelog + latest learnings."""
    sections = []

    # Changelog summary
    log = read_log()
    if log:
        games = [e for e in log if e["type"] == "game"]
        insights = [e for e in log if e["type"] == "insight"]
        changes = [e for e in log if e["type"] == "change"]
        scores = [e.get("score", 0) for e in games]
        avg = sum(scores) / len(scores) if scores else 0
        sections.append(
            f"## Stats\n"
            f"Games: {len(games)}, Avg score: {avg:.2f}/cog\n"
            f"Insights: {len(insights)}, Changes: {len(changes)}"
        )
        if insights:
            sections.append("## Recent Insights")
            for i in insights[-5:]:
                sections.append(f"- {i.get('insight', '')}")
        if changes:
            sections.append("## Recent Changes")
            for c in changes[-5:]:
                sections.append(f"- {c.get('description', '')}")

    # Latest game LLM analyses
    learnings = read_all_learnings()
    if learnings:
        latest = learnings[-1]
        llm_log = latest.get("llm_log", [])
        if llm_log:
            sections.append(f"\n## Latest Game LLM Analysis ({latest.get('game_id', '?')})")
            for entry in llm_log[-3:]:
                step = entry.get("step", "?")
                analysis = entry.get("analysis", "")
                sections.append(f"Step {step}: {analysis[:200]}")

    return "\n".join(sections) if sections else "No experience yet."
