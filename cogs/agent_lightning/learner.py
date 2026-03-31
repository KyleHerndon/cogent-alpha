"""AgentLightningLearnerCoglet — LearnerCoglet backed by Agent Lightning's APO.

Bridges PCO's multi-signal loss decomposition and constraint retry loop
with Agent Lightning's Automatic Prompt Optimization algorithm.

PCO signals are collapsed into a scalar reward and fed to Agent Lightning
as a rollout. APO produces an updated prompt template, which is returned
as the PCO update dict.

Requires: pip install agentlightning

Usage:
    from cogs.agent_lightning import AgentLightningLearnerCoglet

    learner = AgentLightningLearnerCoglet(
        resource_key="system_prompt",
        initial_prompt="You are a helpful assistant.",
        reward_fn=lambda signals: -sum(s["magnitude"] for s in signals),
    )
    pco = ProximalCogletOptimizer(
        actor_config=...,
        critic_config=...,
        losses=[...],
        constraints=[...],
        learner=learner,
    )
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from coglet.pco.learner import LearnerCoglet

logger = logging.getLogger(__name__)


def _default_reward(signals: list[Any]) -> float:
    """Default reward: negative sum of loss magnitudes (lower loss = higher reward)."""
    magnitudes = [
        s.get("magnitude", 0)
        for s in signals
        if isinstance(s, dict) and "magnitude" in s
    ]
    return -sum(magnitudes) if magnitudes else 0.0


def _default_context_formatter(
    experience: Any, evaluation: Any, signals: list[Any],
) -> str:
    """Format PCO context as a string for Agent Lightning rollout input."""
    parts = [f"Experience: {experience}", f"Evaluation: {evaluation}"]
    for s in signals:
        if isinstance(s, dict) and "rejection" not in s:
            parts.append(f"Signal[{s.get('name', '?')}]: magnitude={s.get('magnitude', '?')}")
        elif isinstance(s, dict) and "rejection" in s:
            parts.append(f"Rejection feedback: {s['rejection']}")
    return "\n".join(parts)


class AgentLightningLearnerCoglet(LearnerCoglet):
    """LearnerCoglet that delegates prompt optimization to Agent Lightning's APO.

    Sits inside PCO's learn->constraint->retry loop. Each call to learn():
    1. Converts PCO signals into a scalar reward via reward_fn
    2. Feeds experience as a rollout to Agent Lightning's in-memory store
    3. Runs one APO optimization step
    4. Returns the updated prompt as a PCO patch dict

    Parameters
    ----------
    resource_key:
        Key name for the prompt resource (used in patch dict and store).
    initial_prompt:
        Starting prompt template string.
    reward_fn:
        Callable(signals) -> float. Converts PCO loss signals to a scalar reward.
        Default: negative sum of magnitudes (lower loss = higher reward).
    context_formatter:
        Callable(experience, evaluation, signals) -> str. Formats PCO context
        as rollout input for Agent Lightning. Default: simple string concatenation.
    algorithm_kwargs:
        Extra kwargs passed to the APO algorithm constructor.
    """

    def __init__(
        self,
        *,
        resource_key: str = "prompt",
        initial_prompt: str = "",
        reward_fn: Callable[[list[Any]], float] | None = None,
        context_formatter: Callable[..., str] | None = None,
        algorithm_kwargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._resource_key = resource_key
        self._current_prompt = initial_prompt
        self._reward_fn = reward_fn or _default_reward
        self._context_formatter = context_formatter or _default_context_formatter
        self._algorithm_kwargs = algorithm_kwargs or {}
        self._trainer: Any = None
        self._store: Any = None
        self._epoch = 0

    def _ensure_agent_lightning(self) -> None:
        """Lazy-init Agent Lightning components on first use."""
        if self._trainer is not None:
            return

        try:
            from agentlightning import (
                InMemoryLightningStore,
                PromptTemplate,
                Trainer,
            )
            from agentlightning.algorithm import APO
        except ImportError as e:
            raise ImportError(
                "agentlightning is required for AgentLightningLearnerCoglet. "
                "Install it with: pip install agentlightning"
            ) from e

        self._store = InMemoryLightningStore()
        algorithm = APO(**self._algorithm_kwargs)
        self._trainer = Trainer(
            algorithm=algorithm,
            store=self._store,
            initial_resources={
                self._resource_key: PromptTemplate(self._current_prompt),
            },
        )

    async def learn(
        self,
        experience: Any,
        evaluation: Any,
        signals: list[Any],
    ) -> dict[str, Any]:
        """Produce a prompt update by running one APO step.

        Falls back to passthrough if agentlightning is not installed,
        making this usable in tests without the dependency.
        """
        self._epoch += 1
        reward = self._reward_fn(signals)
        context = self._context_formatter(experience, evaluation, signals)

        try:
            self._ensure_agent_lightning()
            updated_prompt = await self._run_optimization_step(context, reward)
        except ImportError:
            logger.warning("agentlightning not installed, using passthrough mode")
            updated_prompt = self._current_prompt

        self._current_prompt = updated_prompt
        return {
            self._resource_key: updated_prompt,
            "epoch": self._epoch,
            "reward": reward,
            "source": "agent_lightning_apo",
        }

    async def _run_optimization_step(self, context: str, reward: float) -> str:
        """Execute one Agent Lightning optimization step and return the updated prompt."""
        import asyncio
        from agentlightning import PromptTemplate

        store = self._store

        # 1. Enqueue a rollout with the current context as input
        rollout_id = await store.enqueue_rollout(input_data=context)

        # 2. Record the reward as a span
        await store.record_reward(rollout_id=rollout_id, reward=reward)

        # 3. Mark the rollout as complete
        await store.complete_rollout(rollout_id=rollout_id)

        # 4. Let the algorithm process and update resources
        await asyncio.to_thread(self._trainer.step)

        # 5. Extract the updated prompt
        resources = await store.get_latest_resources()
        prompt_resource = resources.get(self._resource_key)
        if isinstance(prompt_resource, PromptTemplate):
            return prompt_resource.template
        return str(prompt_resource) if prompt_resource else self._current_prompt
