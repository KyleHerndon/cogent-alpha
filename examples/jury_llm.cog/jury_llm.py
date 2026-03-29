"""LLM-powered Jury — N jurors deliberate using an LLM brain.

Each juror has a unique persona and uses LLMExecutor (via ProgLet)
to reason about the question. Falls back to a mock if no API key.

Demonstrates:
  - LLMExecutor: real LLM reasoning via Anthropic API
  - ProgLet: program table with both "llm" and "code" executors
  - MulLet: fan-out N jurors
  - LogLet: structured log stream
  - LifeLet: lifecycle hooks
"""

import json
import os

from coglet import (
    Coglet, LifeLet, ProgLet, LogLet, CogletConfig, Command,
    Program, LLMExecutor, enact,
)
from coglet.mullet import MulLet

PERSONAS = [
    "a strict empiricist who demands reproducible evidence",
    "a philosophical skeptic who questions all assumptions",
    "a practical engineer who trusts measurement and observation",
    "a historian who values the accumulated record of human knowledge",
    "a curious child who asks simple but penetrating questions",
]


def _make_client():
    """Create Anthropic client, or None if unavailable."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception:
        return None


def _parse_verdict(text: str) -> dict:
    """Parse LLM verdict text into structured vote."""
    lower = text.lower()
    # Look for explicit vote markers
    if '"vote": "yes"' in lower or "vote: yes" in lower:
        vote = "yes"
    elif '"vote": "no"' in lower or "vote: no" in lower:
        vote = "no"
    elif "i vote yes" in lower or "vote is: yes" in lower:
        vote = "yes"
    elif "i vote no" in lower or "vote is: no" in lower:
        vote = "no"
    else:
        # Fallback: count yes/no occurrences
        vote = "yes" if lower.count("yes") > lower.count("no") else "no"
    return {"vote": vote, "reasoning": text.strip()}


class MockLLMExecutor:
    """Fallback executor that mimics LLM behavior without an API key."""

    async def run(self, program, context, invoke):
        system = program.system
        if callable(system):
            system = system(context)
        system = system or ""
        question = context if isinstance(context, str) else str(context)

        # Deterministic response based on persona keywords in system prompt
        if "skeptic" in system or "questions all" in system:
            response = (
                f"As a skeptic, I question whether '{question}' holds up to scrutiny. "
                f"Examining the evidence, I find the claim lacks support. "
                f"Vote: no. Extraordinary claims require extraordinary evidence."
            )
        elif "empiricist" in system or "reproducible" in system:
            response = (
                f"As an empiricist, I evaluate '{question}' against available data. "
                f"The scientific consensus is clear and reproducible. "
                f"Vote: no. Measurements and observations decisively refute this."
            )
        elif "child" in system or "curious" in system:
            response = (
                f"I wonder about '{question}'. "
                f"If I look at the horizon, ships disappear bottom-first. That's weird if it's flat! "
                f"Vote: no. Simple observations suggest otherwise."
            )
        elif "engineer" in system or "measurement" in system:
            response = (
                f"As an engineer considering '{question}': GPS, aviation, and satellite comms "
                f"all depend on spherical geometry. If it were flat, none of that would work. "
                f"Vote: no. The engineering is clear."
            )
        elif "historian" in system or "record" in system:
            response = (
                f"As a historian: Eratosthenes measured Earth's curvature in 240 BC. "
                f"Every seafaring civilization knew the earth was round. "
                f"Vote: no. The historical record is unambiguous."
            )
        else:
            response = (
                f"Considering '{question}': the weight of evidence points clearly "
                f"in one direction. Vote: no. Established knowledge is well-supported."
            )
        return program.parser(response) if program.parser else response


class JurorCoglet(Coglet, LifeLet, ProgLet, LogLet):
    """A juror that uses an LLM to reason about questions."""

    def __init__(self, juror_id: int = 0, persona: str = "", **kwargs):
        super().__init__(**kwargs)
        self.juror_id = juror_id
        self.persona = persona

    async def on_start(self):
        # Register LLM executor (or mock fallback)
        client = _make_client()
        if client:
            self.executors["llm"] = LLMExecutor(client)
            await self.log("info", f"juror-{self.juror_id} using LLM")
        else:
            self.executors["llm"] = MockLLMExecutor()
            await self.log("info", f"juror-{self.juror_id} using mock LLM (no API key)")

        # Register the deliberation program as LLM-powered
        self.programs["deliberate"] = Program(
            executor="llm",
            system=lambda _ctx: (
                f"You are a juror on a deliberation panel. Your persona: {self.persona}. "
                f"Consider the question carefully from your unique perspective. "
                f"Provide your reasoning, then state your vote clearly as 'Vote: yes' or 'Vote: no'."
            ),
            parser=_parse_verdict,
            config={"max_turns": 1, "max_tokens": 300, "temperature": 0.7},
        )
        await self.log("info", f"juror-{self.juror_id} ({self.persona[:30]}...) seated")

    @enact("question")
    async def on_question(self, question: str):
        await self.log("debug", f"juror-{self.juror_id} deliberating on: {question}")
        result = await self.invoke("deliberate", question)
        await self.log("info", f"juror-{self.juror_id} votes {result['vote']}")
        await self.transmit("verdict", {
            "juror_id": self.juror_id,
            "persona": self.persona[:40],
            **result,
        })

    async def on_stop(self):
        await self.log("info", f"juror-{self.juror_id} dismissed")


class JuryCoglet(Coglet, LifeLet, MulLet):
    """Empanels N LLM-powered jurors and collects their votes."""

    def __init__(self, num_jurors: int = 5, question: str = "", **kwargs):
        super().__init__(**kwargs)
        self.num_jurors = num_jurors
        self.question = question

    async def on_start(self):
        print(f"[jury] empaneling {self.num_jurors} jurors")
        print(f"[jury] question: {self.question}")
        print()

        for i in range(self.num_jurors):
            persona = PERSONAS[i % len(PERSONAS)]
            handle = await self.create(CogletConfig(
                cls=JurorCoglet,
                kwargs={"juror_id": i, "persona": persona},
            ))
            self._mul_children.append(handle)

        # Subscribe before sending question
        subs = []
        for h in self._mul_children:
            subs.append(h.coglet._bus.subscribe("verdict"))

        # Pose question
        await self.guide_mapped(Command("question", self.question))

        # Collect verdicts
        verdicts = []
        for sub in subs:
            verdicts.append(await sub.get())

        # Tally
        yes_votes = sum(1 for v in verdicts if v["vote"] == "yes")
        no_votes = len(verdicts) - yes_votes
        result = "YES" if yes_votes > no_votes else "NO"

        print("[jury] === DELIBERATION ===")
        for v in verdicts:
            symbol = "+" if v["vote"] == "yes" else "-"
            print(f"  [{symbol}] juror-{v['juror_id']} ({v['persona']}):")
            # Print reasoning wrapped
            for line in v["reasoning"].split(". "):
                if line.strip():
                    print(f"      {line.strip()}.")
            print()

        print(f"[jury] === VERDICT: {result} ({yes_votes}-{no_votes}) ===")
        await self.transmit("verdict", {
            "result": result, "yes": yes_votes, "no": no_votes,
        })

    async def on_stop(self):
        print("[jury] dismissed")
