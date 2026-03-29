"""ProgLet example — a data processing pipeline.

Demonstrates:
  - ProgLet: program table with named programs
  - CodeExecutor: sync/async callables as programs
  - invoke() chaining: one program calls another
  - LifeLet: lifecycle hooks to register and run programs
"""

from coglet import Coglet, LifeLet, ProgLet, Program


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens."""
    return text.lower().split()


def count_words(tokens: list[str]) -> dict[str, int]:
    """Count word frequencies."""
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    return counts


async def top_words(context: dict[str, int]) -> list[tuple[str, int]]:
    """Return top 5 words (async to show both sync/async work)."""
    return sorted(context.items(), key=lambda x: -x[1])[:5]


class PipelineCoglet(Coglet, LifeLet, ProgLet):
    """Registers a 3-stage text pipeline and runs it on start."""

    async def on_start(self):
        # Register programs into the program table
        self.programs["tokenize"] = Program(executor="code", fn=tokenize)
        self.programs["count"] = Program(executor="code", fn=count_words)
        self.programs["top"] = Program(executor="code", fn=top_words)

        # Run the pipeline: tokenize -> count -> top
        text = (
            "the coglet framework uses coglets to manage coglets "
            "and each coglet can spawn more coglets in a tree"
        )

        tokens = await self.invoke("tokenize", text)
        print(f"[pipeline] tokens: {tokens}")

        counts = await self.invoke("count", tokens)
        print(f"[pipeline] counts: {counts}")

        top = await self.invoke("top", counts)
        print(f"[pipeline] top words: {top}")

        await self.transmit("result", {"top_words": top})

    async def on_stop(self):
        print(f"[pipeline] stopped ({len(self.programs)} programs registered)")
