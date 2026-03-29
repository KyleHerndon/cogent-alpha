"""Jury Trial example — advocates argue before a jury that votes.

Demonstrates a full adversarial deliberation system:
  - TrialCoglet (COG): orchestrates the trial
    - AdvocateCoglet x2: prosecution and defense make arguments
    - JurorCoglet x N: hear arguments, then vote
  - ProgLet: advocates and jurors use programs for reasoning
  - LogLet: structured logging throughout
  - SuppressLet: jurors' output suppressed during arguments, opened for voting
  - LifeLet + TickLet: lifecycle management
  - Full use of guide/observe/transmit/listen data and control planes
"""

import asyncio
import hashlib

from coglet import (
    Coglet, LifeLet, ProgLet, LogLet, CogletConfig, Command,
    Program, enact, listen,
)
from coglet.suppresslet import SuppressLet


class AdvocateCoglet(Coglet, LifeLet, ProgLet, LogLet):
    """An advocate that builds and presents arguments for one side."""

    def __init__(self, side: str = "prosecution", **kwargs):
        super().__init__(**kwargs)
        self.side = side
        self.argument: str = ""

    async def on_start(self):
        self.programs["argue"] = Program(executor="code", fn=self._build_argument)
        await self.log("info", f"{self.side} advocate ready")

    def _build_argument(self, motion: str) -> str:
        """Build an argument for or against the motion."""
        if self.side == "prosecution":
            points = [
                f"The motion '{motion}' should be ADOPTED.",
                "Evidence shows clear benefits: increased efficiency, fewer errors, and faster iteration.",
                "Studies demonstrate that automated tools catch issues humans routinely miss.",
                "The cost of NOT adopting is falling behind competitors who already have.",
            ]
        else:
            points = [
                f"The motion '{motion}' should be REJECTED.",
                "Automated tools lack the contextual understanding that human review provides.",
                "Over-reliance on automation creates a false sense of security.",
                "The nuance of architectural decisions cannot be reduced to pattern matching.",
            ]
        return " ".join(points)

    @enact("present")
    async def on_present(self, motion: str):
        self.argument = await self.invoke("argue", motion)
        await self.log("info", f"{self.side} presenting argument")
        await self.transmit("argument", {
            "side": self.side,
            "argument": self.argument,
        })

    async def on_stop(self):
        await self.log("info", f"{self.side} advocate rests")


class JurorCoglet(SuppressLet, Coglet, LifeLet, ProgLet, LogLet):
    """A juror who hears arguments and votes.

    SuppressLet is first in MRO so the trial can gate verdict output
    until deliberation phase.
    """

    def __init__(self, juror_id: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.juror_id = juror_id
        self.arguments_heard: list[dict] = []
        self.vote: str | None = None

    async def on_start(self):
        self.programs["weigh"] = Program(executor="code", fn=self._weigh_arguments)
        await self.log("info", f"juror-{self.juror_id} seated")

    @listen("evidence")
    async def on_evidence(self, argument: dict):
        """Hear an argument from an advocate."""
        self.arguments_heard.append(argument)
        await self.log("debug",
            f"juror-{self.juror_id} heard {argument['side']}")

    def _weigh_arguments(self, context) -> dict:
        """Weigh arguments and decide. Persona-based for diversity."""
        personas = [
            ("analytical", 0.6),   # slight prosecution lean
            ("empathetic", 0.4),   # slight defense lean
            ("pragmatic", 0.55),
            ("principled", 0.45),
            ("experiential", 0.5),  # true neutral
            ("systematic", 0.6),
            ("creative", 0.35),
        ]
        idx = self.juror_id % len(personas)
        persona, base_lean = personas[idx]

        # Hash for pseudo-random variation
        h = int(hashlib.sha256(
            f"{self.juror_id}{''.join(a['argument'] for a in self.arguments_heard)}".encode()
        ).hexdigest(), 16)
        noise = ((h % 100) - 50) / 200  # +/- 0.25

        score = base_lean + noise
        vote = "yes" if score > 0.5 else "no"

        pro_arg = next(
            (a["argument"][:80] for a in self.arguments_heard
             if a["side"] == "prosecution"), "none heard")
        def_arg = next(
            (a["argument"][:80] for a in self.arguments_heard
             if a["side"] == "defense"), "none heard")

        reasoning = (
            f"As a {persona} thinker, weighing "
            f"prosecution ({pro_arg}...) vs "
            f"defense ({def_arg}...), "
            f"I vote {vote.upper()}."
        )
        return {"vote": vote, "reasoning": reasoning, "persona": persona}

    @enact("deliberate")
    async def on_deliberate(self, _data):
        """Called when it's time to vote."""
        result = await self.invoke("weigh", None)
        self.vote = result["vote"]
        await self.log("info",
            f"juror-{self.juror_id} ({result['persona']}): {result['vote']}")
        await self.transmit("verdict", {
            "juror_id": self.juror_id,
            "vote": result["vote"],
            "reasoning": result["reasoning"],
            "persona": result["persona"],
        })

    async def on_stop(self):
        await self.log("info", f"juror-{self.juror_id} dismissed")


class TrialCoglet(Coglet, LifeLet):
    """Orchestrates a full trial: advocates argue, jury deliberates.

    Timeline:
      1. Empanel jury (verdicts suppressed during arguments)
      2. Prosecution presents
      3. Defense presents
      4. Arguments delivered to jury
      5. Unsuppress jury, ask for deliberation
      6. Collect and tally votes
    """

    def __init__(self, motion: str = "", num_jurors: int = 5, **kwargs):
        super().__init__(**kwargs)
        self.motion = motion
        self.num_jurors = num_jurors

    async def on_start(self):
        print(f"{'='*60}")
        print(f"  TRIAL: {self.motion}")
        print(f"{'='*60}")
        print()

        # --- Phase 1: Empanel jury (suppress verdicts during arguments) ---
        print("[trial] empaneling jury...")
        juror_handles = []
        for i in range(self.num_jurors):
            h = await self.create(CogletConfig(
                cls=JurorCoglet,
                kwargs={"juror_id": i},
            ))
            # Suppress verdict channel during argument phase
            await self.guide(h, Command("suppress", {"channels": ["verdict"]}))
            juror_handles.append(h)

        # --- Phase 2: Seat advocates ---
        print("[trial] seating advocates...")
        prosecution = await self.create(CogletConfig(
            cls=AdvocateCoglet,
            kwargs={"side": "prosecution"},
        ))
        defense = await self.create(CogletConfig(
            cls=AdvocateCoglet,
            kwargs={"side": "defense"},
        ))

        # Subscribe to arguments before they're presented
        pro_sub = prosecution.coglet._bus.subscribe("argument")
        def_sub = defense.coglet._bus.subscribe("argument")

        # --- Phase 3: Prosecution presents ---
        print()
        print("[trial] PROSECUTION, present your case.")
        await self.guide(prosecution, Command("present", self.motion))
        pro_arg = await pro_sub.get()
        print(f"  PRO: {pro_arg['argument']}")

        # --- Phase 4: Defense presents ---
        print()
        print("[trial] DEFENSE, present your case.")
        await self.guide(defense, Command("present", self.motion))
        def_arg = await def_sub.get()
        print(f"  DEF: {def_arg['argument']}")

        # --- Phase 5: Deliver arguments to jury ---
        print()
        print("[trial] delivering arguments to jury...")
        for h in juror_handles:
            await h.coglet._dispatch_listen("evidence", pro_arg)
            await h.coglet._dispatch_listen("evidence", def_arg)

        # --- Phase 6: Unsuppress and deliberate ---
        print("[trial] jury may now deliberate.")
        print()

        # Subscribe to verdicts BEFORE unsuppressing
        verdict_subs = []
        for h in juror_handles:
            verdict_subs.append(h.coglet._bus.subscribe("verdict"))

        # Unsuppress and ask for deliberation
        for h in juror_handles:
            await self.guide(h, Command("unsuppress", {"channels": ["verdict"]}))
            await self.guide(h, Command("deliberate", None))

        # --- Phase 7: Collect verdicts ---
        verdicts = []
        for sub in verdict_subs:
            verdicts.append(await sub.get())

        # --- Phase 8: Announce result ---
        yes_votes = sum(1 for v in verdicts if v["vote"] == "yes")
        no_votes = len(verdicts) - yes_votes
        result = "MOTION CARRIES" if yes_votes > no_votes else "MOTION FAILS"

        print("[trial] === JURY DELIBERATION ===")
        for v in verdicts:
            symbol = "+" if v["vote"] == "yes" else "-"
            print(f"  [{symbol}] juror-{v['juror_id']} ({v['persona']}): {v['vote']}")
        print()
        print(f"[trial] === VERDICT: {result} ({yes_votes}-{no_votes}) ===")
        print()

        await self.transmit("result", {
            "motion": self.motion,
            "result": result,
            "yes": yes_votes,
            "no": no_votes,
            "verdicts": verdicts,
        })

    async def on_stop(self):
        print("[trial] court adjourned")
