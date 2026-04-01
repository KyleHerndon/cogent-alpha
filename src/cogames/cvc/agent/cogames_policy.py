"""CvcBasePolicy: MultiAgentPolicy wrapper that creates independent CvcEngine per agent."""

from __future__ import annotations

from cvc.agent.main import CvcEngine
from cvc.agent.world_model import WorldModel
from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface


class CvcBasePolicy(MultiAgentPolicy):
    """Creates one independent CvcEngine per agent. No shared state."""

    short_names: list[str] | None = None

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", **kwargs) -> None:
        super().__init__(policy_env_info, device=device, **kwargs)
        self._agent_policies: dict[int, CvcEngine] = {}

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        if agent_id not in self._agent_policies:
            self._agent_policies[agent_id] = CvcEngine(
                self.policy_env_info,
                agent_id=agent_id,
                world_model=WorldModel(),
            )
        return self._agent_policies[agent_id]

    def reset(self) -> None:
        for policy in self._agent_policies.values():
            policy.reset()
