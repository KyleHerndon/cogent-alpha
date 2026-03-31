# Agent Lightning Cog

PCO learner backend powered by [Microsoft Agent Lightning](https://github.com/microsoft/agent-lightning)'s Automatic Prompt Optimization (APO).

## What It Does

`AgentLightningLearnerCoglet` is a drop-in `LearnerCoglet` that delegates prompt optimization to Agent Lightning's APO algorithm while preserving PCO's constraint retry loop, multi-signal loss decomposition, and fractal composition.

```
PCO Epoch Flow:
  Actor rollout → Critic evaluation → Loss signals
      ↓
  AgentLightningLearnerCoglet
      ├── Collapse signals → scalar reward (via reward_fn)
      ├── Feed context → Agent Lightning store
      ├── Run APO optimization step
      └── Return updated prompt as PCO patch
      ↓
  Constraint check → accept/reject → retry if needed
```

## Usage

```python
from cogs.agent_lightning import AgentLightningLearnerCoglet
from coglet.pco import ProximalCogletOptimizer

learner = AgentLightningLearnerCoglet(
    resource_key="system_prompt",
    initial_prompt="You are a helpful assistant.",
    reward_fn=lambda signals: -sum(s["magnitude"] for s in signals),
)

pco = ProximalCogletOptimizer(
    actor_config=actor_config,
    critic_config=critic_config,
    losses=[PolicyLoss(), ValueLoss(), EntropyLoss()],
    constraints=[ChangeMagnitude(max_lines=50)],
    learner=learner,
)
```

## Install

```bash
pip install agentlightning
```

Without `agentlightning` installed, the learner runs in **passthrough mode** — it returns the current prompt unchanged. This allows tests to run without the dependency.

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `resource_key` | `"prompt"` | Key name in the PCO patch dict and Agent Lightning store |
| `initial_prompt` | `""` | Starting prompt template |
| `reward_fn` | neg. sum of magnitudes | `Callable(signals) -> float` — collapses PCO loss signals to scalar |
| `context_formatter` | string concat | `Callable(experience, evaluation, signals) -> str` — formats rollout input |
| `algorithm_kwargs` | `{}` | Extra kwargs for the APO algorithm constructor |

## How It Bridges PCO and Agent Lightning

| PCO Concept | Agent Lightning Equivalent |
|---|---|
| Loss signals (multi-dimensional) | Scalar reward (collapsed via `reward_fn`) |
| Experience + evaluation context | Rollout input (formatted via `context_formatter`) |
| Learner update (opaque patch dict) | APO resource update (PromptTemplate) |
| Constraint rejection + retry | No equivalent in AL — handled by PCO around this learner |
| Epoch | One `learn()` call → one APO step |

## Subclassing

Override `learn()` to add rejection-aware behavior:

```python
class AdaptiveLearner(AgentLightningLearnerCoglet):
    async def learn(self, experience, evaluation, signals):
        result = await super().learn(experience, evaluation, signals)
        # On constraint rejection, modify the prompt further
        if any(isinstance(s, dict) and "rejection" in s for s in signals):
            result["prompt"] += " (revised after feedback)"
        return result
```

## Architecture

See [docs/comparison-agent-lightning.md](../../docs/comparison-agent-lightning.md) for a full comparison of Agent Lightning vs Coglet PCO.
