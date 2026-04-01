"""PlayerCoglet: GitLet COG that manages PolicyCoglets across games.

Submits a PolicyCoglet per game. After each game, reads the PolicyCoglet's
learnings/experience. Analyzes across games and commits improvements to repo.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from coglet.coglet import Coglet, listen, enact
from coglet.gitlet import GitLet
from coglet.lifelet import LifeLet
from coglet.handle import CogBase, Command


class PlayerCoglet(Coglet, GitLet, LifeLet):
    """COG over PolicyCoglets across many games.

    - Submits PolicyCoglet per game
    - Reads learnings after each game ends
    - Accumulates experience across games
    - Commits improvements to the repo (GitLet)
    """

    def __init__(
        self,
        repo_path: str | None = None,
        learnings_dir: str = "/tmp/coglet_learnings",
        **kwargs: Any,
    ) -> None:
        super().__init__(repo_path=repo_path, **kwargs)
        self.learnings_dir = Path(learnings_dir)
        self.experience: list[dict[str, Any]] = []

    async def on_start(self) -> None:
        self.learnings_dir.mkdir(parents=True, exist_ok=True)

    @listen("game_complete")
    async def handle_game_complete(self, data: Any) -> None:
        """Called when a game finishes. Read learnings from PolicyCoglet."""
        game_id = data.get("game_id") if isinstance(data, dict) else str(data)
        learnings = self._read_learnings(game_id)
        if learnings:
            self.experience.append(learnings)
            await self.transmit("learnings", learnings)

    def _read_learnings(self, game_id: str) -> dict[str, Any] | None:
        path = self.learnings_dir / f"{game_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def get_experience(self) -> list[dict[str, Any]]:
        """Get all accumulated experience for Coach to analyze."""
        return self.experience

    @enact("improve")
    async def handle_improve(self, analysis: Any = None) -> None:
        """Coach directs an improvement based on cross-game analysis."""
        if analysis:
            await self.transmit("improvement", analysis)

    async def on_stop(self) -> None:
        """Log summary of all experience on shutdown."""
        if self.experience:
            summary_path = self.learnings_dir / "experience_summary.json"
            summary_path.write_text(json.dumps({
                "total_games": len(self.experience),
                "games": [e.get("game_id", "unknown") for e in self.experience],
            }, indent=2))
