"""Coglet policy for cogames CvC — wraps the cogora policy.

Uses AlphaCyborgPolicy (semantic heuristic without LLM) as baseline.
AnthropicCyborgPolicy adds LLM-based runtime improvements on top.
"""
from __future__ import annotations

from typing import Any

from cvc.cogent.player_cog.policy.anthropic_pilot import AlphaCyborgPolicy, AnthropicCyborgPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface  # type: ignore[import-untyped]


class CogletPolicy(AlphaCyborgPolicy):
    """cogames policy — semantic heuristic baseline (no LLM)."""
    short_names = ["coglet", "coglet-policy"]


class CogletLLMPolicy(AnthropicCyborgPolicy):
    """cogames policy — semantic baseline + LLM runtime improvements."""
    short_names = ["coglet-llm"]
