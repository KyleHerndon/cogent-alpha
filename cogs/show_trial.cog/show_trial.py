"""ShowTrial — generator feeds questions to a trial, reporter records verdicts.

Wiring:
  generator:output   → trial:input     (questions)
  trial:output       → reporter:input  (verdicts to reporter)
  trial:output       → generator:input (verdicts back for timing)
  reporter:output    → show:verdicts   (formatted records)
  generator:log      → show:log        (timing logs)
"""

import sys
from pathlib import Path

from coglet import Coglet, LifeLet, CogBase, listen

_jury_trial_dir = str(Path(__file__).parent.parent / "jury_trial.cog")
_generator_dir = str(Path(__file__).parent.parent / "generator.cog")
for d in [_jury_trial_dir, _generator_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)

from trial import TrialCoglet
from generator import GeneratorCoglet


class ReporterCoglet(Coglet, LifeLet):
    """Receives verdicts and records formatted reports.

    Channels: input (in) → output (out)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.records = []

    async def on_start(self):
        print("[reporter] ready")

    @listen("input")
    async def on_input(self, verdict):
        if not isinstance(verdict, dict):
            return
        record = {
            "question": verdict.get("question", "?"),
            "result": verdict.get("result", "?"),
            "yes": verdict.get("yes", 0),
            "no": verdict.get("no", 0),
            "jurors": len(verdict.get("verdicts", [])),
            "votes": [
                {"id": v.get("juror_id"), "vote": v.get("vote"), "persona": v.get("persona")}
                for v in verdict.get("verdicts", [])
            ],
            "trial_number": len(self.records) + 1,
        }
        self.records.append(record)
        print(f"[reporter] Trial #{record['trial_number']}: {record['result']} ({record['yes']}-{record['no']}) — {record['question']}")
        await self.transmit("output", record)

    async def on_stop(self):
        print(f"[reporter] recorded {len(self.records)} trials")


class ShowTrialCoglet(Coglet, LifeLet):
    """Orchestrates generator + trial + reporter.

    Args:
        prompt: what to generate (default: "interesting questions about AI")
        num_jurors: jury size
        executor: "code" or "llm" — propagated to all children
        interval_s: seconds between questions

    Channels:
        log (out)      — timing logs from generator
        verdicts (out) — detailed records from reporter
    """

    def __init__(self, prompt: str = "interesting questions about AI",
                 num_jurors: int = 5, executor: str = "code",
                 interval_s: int = 30, **kwargs):
        super().__init__(**kwargs)
        self.prompt = prompt
        self.num_jurors = num_jurors
        self.executor_type = executor
        self.interval_s = interval_s

    async def on_start(self):
        generator = await self.create(CogBase(
            cls=GeneratorCoglet, label="Generator",
            kwargs={"prompt": self.prompt, "interval_s": self.interval_s,
                    "executor": self.executor_type}))
        trial = await self.create(CogBase(
            cls=TrialCoglet, label="Trial",
            kwargs={"num_jurors": self.num_jurors, "executor": self.executor_type}))
        reporter = await self.create(CogBase(
            cls=ReporterCoglet, label="Reporter"))

        # generator → trial (questions)
        self.link(generator, "output", trial, "input")
        # trial → reporter (verdicts)
        self.link(trial, "output", reporter, "input")
        # reporter → show (formatted records)
        self.link(reporter, "output", self.handle, "verdicts")

        print(f"[show_trial] running — '{self.prompt}' [{self.executor_type}]")

        # Trigger first item now that links are set up
        await generator.coglet.generate()

    @listen("verdicts")
    async def on_verdicts(self, record):
        pass

    async def on_stop(self):
        print("[show_trial] done")
