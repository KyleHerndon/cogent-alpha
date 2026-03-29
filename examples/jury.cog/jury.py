"""Jury example — N jurors deliberate and vote on a question.

Demonstrates:
  - MulLet: fan-out N identical juror children
  - ProgLet: jurors use a code program to form opinions
  - LogLet: jurors log their reasoning
  - LifeLet: lifecycle for setup/teardown
  - guide()/observe(): COG sends question, collects votes
  - transmit(): jurors publish their verdicts
"""

import asyncio
import hashlib

from coglet import (
    Coglet, LifeLet, ProgLet, LogLet, CogletConfig, Command,
    Program, enact,
)
from coglet.mullet import MulLet


class JurorCoglet(Coglet, LifeLet, ProgLet, LogLet):
    """A single juror that deliberates on a question and votes.

    Each juror has a "persona" bias derived from its id to simulate
    diverse viewpoints. In a real system, you'd swap the code executor
    for an LLM executor.
    """

    def __init__(self, juror_id: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.juror_id = juror_id
        self.vote: str | None = None
        self.reasoning: str = ""

    async def on_start(self):
        # Register a deliberation program
        self.programs["deliberate"] = Program(
            executor="code",
            fn=self._deliberate,
        )
        await self.log("info", f"juror-{self.juror_id} seated")

    def _deliberate(self, question: str) -> dict:
        """Simulate deliberation with deterministic persona-based reasoning."""
        # Use juror_id to create diverse perspectives
        perspectives = [
            ("pragmatist", "focus on practical outcomes", True),
            ("skeptic", "question assumptions", False),
            ("optimist", "see potential benefits", True),
            ("conservative", "prefer proven approaches", False),
            ("innovator", "favor new solutions", True),
        ]
        idx = self.juror_id % len(perspectives)
        persona, style, lean_yes = perspectives[idx]

        # Hash question + id for pseudo-random swing factor
        h = int(hashlib.sha256(f"{question}{self.juror_id}".encode()).hexdigest(), 16)
        swing = (h % 100) > 60  # 40% chance to flip

        vote = "yes" if (lean_yes != swing) else "no"
        reasoning = (
            f"As a {persona} (I {style}), "
            f"I {'support' if vote == 'yes' else 'oppose'} this proposal."
        )
        return {"vote": vote, "reasoning": reasoning}

    @enact("question")
    async def on_question(self, question: str):
        """Receive a question, deliberate, and transmit vote."""
        await self.log("debug", f"juror-{self.juror_id} deliberating...")

        result = await self.invoke("deliberate", question)
        self.vote = result["vote"]
        self.reasoning = result["reasoning"]

        await self.log("info", f"juror-{self.juror_id}: {self.reasoning}")
        await self.transmit("verdict", {
            "juror_id": self.juror_id,
            "vote": self.vote,
            "reasoning": self.reasoning,
        })

    async def on_stop(self):
        await self.log("info", f"juror-{self.juror_id} dismissed")


class JuryCoglet(Coglet, LifeLet, MulLet):
    """Empanels N jurors, poses a question, and tallies votes.

    The jury reaches a verdict by simple majority.
    """

    def __init__(self, num_jurors: int = 5, question: str = "", **kwargs):
        super().__init__(**kwargs)
        self.num_jurors = num_jurors
        self.question = question

    async def on_start(self):
        print(f"[jury] empaneling {self.num_jurors} jurors")
        print(f"[jury] question: {self.question}")
        print()

        # Create jurors with unique IDs
        for i in range(self.num_jurors):
            config = CogletConfig(
                cls=JurorCoglet,
                kwargs={"juror_id": i},
            )
            handle = await self.create(config)
            self._mul_children.append(handle)

        # Subscribe to all verdicts before asking the question
        subs = []
        for handle in self._mul_children:
            subs.append(handle.coglet._bus.subscribe("verdict"))

        # Pose the question to all jurors
        await self.guide_mapped(Command("question", self.question))

        # Collect all verdicts
        verdicts = []
        for sub in subs:
            verdicts.append(await sub.get())

        # Tally votes
        yes_votes = sum(1 for v in verdicts if v["vote"] == "yes")
        no_votes = len(verdicts) - yes_votes
        result = "YES" if yes_votes > no_votes else "NO"

        print()
        print("[jury] === DELIBERATION ===")
        for v in verdicts:
            symbol = "+" if v["vote"] == "yes" else "-"
            print(f"  [{symbol}] juror-{v['juror_id']}: {v['reasoning']}")

        print()
        print(f"[jury] === VERDICT: {result} ({yes_votes}-{no_votes}) ===")
        await self.transmit("verdict", {
            "result": result,
            "yes": yes_votes,
            "no": no_votes,
            "verdicts": verdicts,
        })

    async def on_stop(self):
        print("[jury] dismissed")
