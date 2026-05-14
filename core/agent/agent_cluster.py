from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AgentSpec:
    id: str
    role: str = ""
    description: str = ""
    model: str = ""
    tools: tuple[str, ...] = ()


class AgentCluster:
    """Small compatibility facade over agent.yaml.

    Older audits and integrations import ``core.agent.agent_cluster`` to look up
    sub-agent model assignments. The execution pipeline now lives elsewhere, but
    keeping this read-only facade prevents stale imports from breaking.
    """

    def __init__(self, config_path: str | Path | None = None):
        root = Path(__file__).resolve().parents[2]
        self._config_path = Path(config_path) if config_path else root / "agent.yaml"
        self._agents = self._load_agents()

    def _load_agents(self) -> dict[str, AgentSpec]:
        try:
            data: dict[str, Any] = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}

        agents: dict[str, AgentSpec] = {}
        for raw in data.get("agents", []) or []:
            if not isinstance(raw, dict):
                continue
            agent_id = str(raw.get("id", "")).strip()
            if not agent_id:
                continue
            tools = raw.get("tools") or ()
            agents[agent_id] = AgentSpec(
                id=agent_id,
                role=str(raw.get("role", "")),
                description=str(raw.get("description", "")),
                model=str(raw.get("model", "")),
                tools=tuple(str(t) for t in tools),
            )
        return agents

    def get_model_for_role(self, role_id: str, default: str = "qwen2.5-coder:7b") -> str:
        spec = self._agents.get(role_id)
        return spec.model if spec and spec.model else default

    def get_agent(self, role_id: str) -> AgentSpec | None:
        return self._agents.get(role_id)

    def list_agents(self) -> list[AgentSpec]:
        return list(self._agents.values())


_cluster: AgentCluster | None = None


def get_cluster() -> AgentCluster:
    global _cluster
    if _cluster is None:
        _cluster = AgentCluster()
    return _cluster
