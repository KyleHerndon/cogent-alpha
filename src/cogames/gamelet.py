from __future__ import annotations

import asyncio
import os
import subprocess
from typing import Any

from coglet.coglet import Coglet, listen, enact
from coglet.lifelet import LifeLet
from coglet.ticklet import TickLet, every
from coglet.handle import CogletHandle, Command

from cogames.policy import PolicyCoglet


class GameLet(Coglet, LifeLet, TickLet):
    """Bridge between Coglet world and cogames.

    Two modes:
    - Play: local freeplay via cogames CLI
    - Tournament: upload, submit, and poll via cogames API

    Exposes game results as Coglet channels:
        observe(handle, "score")
        observe(handle, "replay")
        observe(handle, "leaderboard")
    """

    def __init__(
        self,
        policy_coglet: PolicyCoglet,
        mode: str = "play",
        mission: str = "machina_1",
        season: str | None = None,
        policy_name: str = "coglet-policy",
        render_mode: str = "none",
        num_cogs: int = 4,
        cogames_token: str | None = None,
        server_url: str = "https://api.observatory.softmax-research.net",
        poll_interval_s: int = 60,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._policy_coglet = policy_coglet
        self._mode = mode
        self._mission = mission
        self._season = season
        self._policy_name = policy_name
        self._render_mode = render_mode
        self._num_cogs = num_cogs
        self._cogames_token = cogames_token or os.environ.get("COGAMES_TOKEN")
        self._server_url = server_url
        self._poll_interval_s = poll_interval_s
        self._policy_version_id: str | None = None
        self._poll_task: asyncio.Task | None = None

    # --- Play mode ---

    async def play(self, mission: str | None = None, render_mode: str | None = None,
                   seed: int = 42) -> None:
        """Run a local freeplay episode via cogames CLI."""
        m = mission or self._mission
        r = render_mode or self._render_mode
        cmd = [
            "cogames", "play",
            "-m", m,
            "-p", f"class=cogames.policy.CogletPolicy",
            "-c", str(self._num_cogs),
            "-r", r,
            "--seed", str(seed),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        result = {
            "stdout": stdout.decode(),
            "stderr": stderr.decode(),
            "returncode": proc.returncode,
        }
        await self.transmit("play_result", result)

    # --- Tournament mode ---

    async def upload(self, name: str | None = None, season: str | None = None,
                     include_files: list[str] | None = None) -> str:
        """Upload policy to cogames tournament."""
        n = name or self._policy_name
        s = season or self._season
        cmd = [
            "cogames", "upload",
            "-p", f"class=cogames.policy.CogletPolicy",
            "-n", n,
        ]
        if s:
            cmd.extend(["--season", s])
        if include_files:
            for f in include_files:
                cmd.extend(["-f", f])
        cmd.append("--skip-validation")

        env = os.environ.copy()
        if self._cogames_token:
            env["COGAMES_TOKEN"] = self._cogames_token

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"cogames upload failed: {stderr.decode()}")

        output = stdout.decode()
        await self.transmit("upload_result", output)
        return output

    async def submit(self, season: str | None = None) -> None:
        """Submit uploaded policy to a tournament season."""
        s = season or self._season
        if not s:
            raise ValueError("No season specified")
        cmd = ["cogames", "submit", self._policy_name, "--season", s]

        env = os.environ.copy()
        if self._cogames_token:
            env["COGAMES_TOKEN"] = self._cogames_token

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"cogames submit failed: {stderr.decode()}")
        await self.transmit("submit_result", stdout.decode())

    async def poll_results(self) -> None:
        """Poll tournament API for match results. Transmits to score/replay channels."""
        # Uses cogames CLI to fetch results
        env = os.environ.copy()
        if self._cogames_token:
            env["COGAMES_TOKEN"] = self._cogames_token

        cmd = [
            "cogames", "season", "matches",
            self._season or "",
            "--limit", "10",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            await self.transmit("score", stdout.decode())

    async def poll_leaderboard(self) -> None:
        """Fetch and transmit current leaderboard."""
        env = os.environ.copy()
        if self._cogames_token:
            env["COGAMES_TOKEN"] = self._cogames_token

        cmd = ["cogames", "season", "leaderboard", self._season or ""]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            await self.transmit("leaderboard", stdout.decode())

    @enact("play")
    async def _enact_play(self, data: Any = None) -> None:
        mission = data.get("mission") if isinstance(data, dict) else None
        render_mode = data.get("render_mode") if isinstance(data, dict) else None
        seed = data.get("seed", 42) if isinstance(data, dict) else 42
        await self.play(mission=mission, render_mode=render_mode, seed=seed)

    @enact("upload")
    async def _enact_upload(self, data: Any = None) -> None:
        name = data.get("name") if isinstance(data, dict) else None
        season = data.get("season") if isinstance(data, dict) else None
        await self.upload(name=name, season=season)

    @enact("submit")
    async def _enact_submit(self, data: Any = None) -> None:
        season = data.get("season") if isinstance(data, dict) else None
        await self.submit(season=season)

    async def start_polling(self) -> None:
        """Start background polling for tournament results."""
        if self._poll_task is not None:
            return

        async def _poll_loop():
            while True:
                await self.poll_results()
                await self.poll_leaderboard()
                await asyncio.sleep(self._poll_interval_s)

        self._poll_task = asyncio.create_task(_poll_loop())

    async def stop_polling(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
