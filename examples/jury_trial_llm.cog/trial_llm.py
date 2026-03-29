"""LLM-powered Jury Trial — advocates argue before an LLM jury.

Full adversarial system where:
  - Two AdvocateCoglets use LLM to build arguments (pro and con)
  - N JurorCoglets hear both sides, then use LLM to deliberate
  - SuppressLet gates juror output during argument phase
  - TrialCoglet orchestrates the full proceeding

Falls back to mock LLM if no ANTHROPIC_API_KEY is set.

Demonstrates every mixin in combination:
  - LifeLet: lifecycle hooks
  - ProgLet: program table with LLM and code executors
  - LLMExecutor: real LLM reasoning
  - LogLet: structured logging
  - SuppressLet: output gating during argument phase
  - MulLet pattern: fan-out jurors
  - Full guide/observe/transmit/listen data+control planes
"""

import json
import os

from coglet import (
    Coglet, LifeLet, ProgLet, LogLet, CogletConfig, Command,
    Program, LLMExecutor, enact, listen,
)
from coglet.suppresslet import SuppressLet


JUROR_PERSONAS = [
    "a strict empiricist who demands reproducible evidence",
    "a philosophical skeptic who questions all assumptions",
    "a practical engineer who trusts measurement and observation",
    "a historian who values the accumulated record of human knowledge",
    "a curious child who asks simple but penetrating questions",
]


def _make_client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception:
        return None


class MockLLMExecutor:
    """Deterministic fallback when no API key is available."""

    async def run(self, program, context, invoke):
        system = program.system
        if callable(system):
            system = system(context)
        system = (system or "").lower()
        ctx = context if isinstance(context, str) else str(context)

        # Advocate responses (keyed on side)
        if "prosecution" in system and "advocate" in system:
            resp = (
                f"The proposition '{ctx}' deserves serious consideration. "
                "Proponents point to alternative models and claim mainstream science suppresses dissent. "
                "They argue that personal observation — flat horizons, still water — supports their view. "
                "We urge the jury to consider whether 'settled science' has been wrong before."
            )
        elif "defense" in system and "advocate" in system:
            resp = (
                f"The evidence against '{ctx}' is overwhelming and reproducible. "
                "Satellite imagery, circumnavigation, gravitational physics, time zones, "
                "and the behavior of ships at the horizon all converge on the same conclusion. "
                "Every space agency across rival nations confirms the same oblate spheroid."
            )
        # Juror responses — match on "Your persona:" prefix to isolate persona
        elif "strict empiricist" in system:
            resp = (
                "The prosecution offers no reproducible experiment. "
                "The defense cites countless reproducible observations. "
                "As an empiricist, the data is clear. Vote: no."
            )
        elif "philosophical skeptic" in system:
            resp = (
                "Having heard both sides, the prosecution relies on anecdote "
                "while the defense presents convergent evidence from independent sources. "
                "I must follow the stronger evidence. Vote: no."
            )
        elif "practical engineer" in system:
            resp = (
                "GPS, aviation, satellite communications — none of these work "
                "on a flat model. The engineering is built on spherical geometry. "
                "Vote: no."
            )
        elif "historian" in system:
            resp = (
                "Eratosthenes measured the earth's curvature in 240 BC. "
                "Every seafaring civilization knew the earth was round. "
                "The historical record is unambiguous. Vote: no."
            )
        elif "curious child" in system:
            resp = (
                "If the earth is flat, why do ships disappear bottom-first? "
                "And why is every other planet round but not ours? "
                "That doesn't make sense. Vote: no."
            )
        else:
            resp = (
                "Weighing the arguments carefully, the evidence presented by the defense "
                "is far more compelling than the prosecution's case. Vote: no."
            )

        return program.parser(resp) if program.parser else resp


def _parse_verdict(text: str) -> dict:
    lower = text.lower()
    if "vote: yes" in lower or "i vote yes" in lower:
        vote = "yes"
    elif "vote: no" in lower or "i vote no" in lower:
        vote = "no"
    else:
        vote = "yes" if lower.count("yes") > lower.count("no") else "no"
    return {"vote": vote, "reasoning": text.strip()}


def _parse_argument(text: str) -> dict:
    return {"argument": text.strip()}


def _get_executor():
    client = _make_client()
    if client:
        return LLMExecutor(client), "llm"
    return MockLLMExecutor(), "mock"


class AdvocateCoglet(Coglet, LifeLet, ProgLet, LogLet):
    """An advocate that uses LLM to construct arguments."""

    def __init__(self, side: str = "prosecution", **kwargs):
        super().__init__(**kwargs)
        self.side = side

    async def on_start(self):
        executor, mode = _get_executor()
        self.executors["llm"] = executor
        await self.log("info", f"{self.side} advocate ready (executor={mode})")

        self.programs["argue"] = Program(
            executor="llm",
            system=lambda _ctx: (
                f"You are the {self.side} advocate in a deliberation. "
                f"{'Build a compelling case FOR the proposition. Present evidence and reasoning that supports it.' if self.side == 'prosecution' else 'Build a compelling case AGAINST the proposition. Present evidence and reasoning that refutes it.'} "
                f"Be concise but persuasive. Limit to 3-4 sentences."
            ),
            parser=_parse_argument,
            config={"max_turns": 1, "max_tokens": 300, "temperature": 0.7},
        )

    @enact("present")
    async def on_present(self, motion: str):
        result = await self.invoke("argue", motion)
        await self.log("info", f"{self.side} presented argument")
        await self.transmit("argument", {
            "side": self.side,
            **result,
        })

    async def on_stop(self):
        await self.log("info", f"{self.side} rests")


class JurorCoglet(SuppressLet, Coglet, LifeLet, ProgLet, LogLet):
    """LLM-powered juror that hears arguments and votes."""

    def __init__(self, juror_id: int = 0, persona: str = "", **kwargs):
        super().__init__(**kwargs)
        self.juror_id = juror_id
        self.persona = persona
        self.arguments_heard: list[dict] = []

    async def on_start(self):
        executor, mode = _get_executor()
        self.executors["llm"] = executor
        await self.log("info", f"juror-{self.juror_id} seated (executor={mode})")

        self.programs["weigh"] = Program(
            executor="llm",
            system=lambda _ctx: (
                f"You are a juror. Your persona: {self.persona}. "
                f"You have heard the following arguments:\n\n"
                + "\n\n".join(
                    f"[{a['side'].upper()}]: {a['argument']}"
                    for a in self.arguments_heard
                )
                + "\n\nWeigh both sides from your unique perspective. "
                "State your reasoning briefly, then end with 'Vote: yes' or 'Vote: no'."
            ),
            parser=_parse_verdict,
            config={"max_turns": 1, "max_tokens": 200, "temperature": 0.8},
        )

    @listen("evidence")
    async def on_evidence(self, argument: dict):
        self.arguments_heard.append(argument)
        await self.log("debug", f"juror-{self.juror_id} heard {argument['side']}")

    @enact("deliberate")
    async def on_deliberate(self, motion: str):
        result = await self.invoke("weigh", motion)
        await self.log("info", f"juror-{self.juror_id} votes {result['vote']}")
        await self.transmit("verdict", {
            "juror_id": self.juror_id,
            "persona": self.persona[:40],
            **result,
        })

    async def on_stop(self):
        await self.log("info", f"juror-{self.juror_id} dismissed")


class TrialCoglet(Coglet, LifeLet):
    """Orchestrates a full LLM-powered trial."""

    def __init__(self, motion: str = "", num_jurors: int = 5, **kwargs):
        super().__init__(**kwargs)
        self.motion = motion
        self.num_jurors = num_jurors

    async def on_start(self):
        print(f"{'='*60}")
        print(f"  TRIAL: {self.motion}")
        print(f"{'='*60}")
        print()

        # Phase 1: Empanel jury (suppress verdicts)
        print("[trial] empaneling jury...")
        juror_handles = []
        for i in range(self.num_jurors):
            persona = JUROR_PERSONAS[i % len(JUROR_PERSONAS)]
            h = await self.create(CogletConfig(
                cls=JurorCoglet,
                kwargs={"juror_id": i, "persona": persona},
            ))
            await self.guide(h, Command("suppress", {"channels": ["verdict"]}))
            juror_handles.append(h)

        # Phase 2: Seat advocates
        print("[trial] seating advocates...")
        prosecution = await self.create(CogletConfig(
            cls=AdvocateCoglet, kwargs={"side": "prosecution"},
        ))
        defense = await self.create(CogletConfig(
            cls=AdvocateCoglet, kwargs={"side": "defense"},
        ))

        pro_sub = prosecution.coglet._bus.subscribe("argument")
        def_sub = defense.coglet._bus.subscribe("argument")

        # Phase 3: Prosecution
        print()
        print("[trial] PROSECUTION, present your case.")
        await self.guide(prosecution, Command("present", self.motion))
        pro_arg = await pro_sub.get()
        print(f"  PRO: {pro_arg['argument']}")

        # Phase 4: Defense
        print()
        print("[trial] DEFENSE, present your case.")
        await self.guide(defense, Command("present", self.motion))
        def_arg = await def_sub.get()
        print(f"  DEF: {def_arg['argument']}")

        # Phase 5: Deliver to jury
        print()
        print("[trial] delivering arguments to jury...")
        for h in juror_handles:
            await h.coglet._dispatch_listen("evidence", pro_arg)
            await h.coglet._dispatch_listen("evidence", def_arg)

        # Phase 6: Deliberate
        print("[trial] jury may now deliberate.")
        print()

        verdict_subs = []
        for h in juror_handles:
            verdict_subs.append(h.coglet._bus.subscribe("verdict"))

        for h in juror_handles:
            await self.guide(h, Command("unsuppress", {"channels": ["verdict"]}))
            await self.guide(h, Command("deliberate", self.motion))

        # Phase 7: Collect verdicts
        verdicts = []
        for sub in verdict_subs:
            verdicts.append(await sub.get())

        # Phase 8: Announce
        yes_votes = sum(1 for v in verdicts if v["vote"] == "yes")
        no_votes = len(verdicts) - yes_votes
        result = "MOTION CARRIES" if yes_votes > no_votes else "MOTION FAILS"

        print("[trial] === JURY DELIBERATION ===")
        for v in verdicts:
            symbol = "+" if v["vote"] == "yes" else "-"
            print(f"  [{symbol}] juror-{v['juror_id']} ({v['persona']}):")
            for line in v["reasoning"].split(". "):
                if line.strip():
                    print(f"      {line.strip()}.")
            print()

        print(f"[trial] === VERDICT: {result} ({yes_votes}-{no_votes}) ===")
        await self.transmit("result", {"motion": self.motion, "result": result})

    async def on_stop(self):
        print("[trial] court adjourned")
