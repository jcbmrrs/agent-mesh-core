from __future__ import annotations

import pytest

from agent_mesh_core import AgentMeshCoordinator


class FakeClock:
    def __init__(self, start: float = 1_000.0):
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def mesh_root(tmp_path):
    return tmp_path / "mesh"


@pytest.fixture
def coordinator_factory(mesh_root):
    def make(agent_id: str = "agent_a", **kwargs):
        return AgentMeshCoordinator(mesh_root, agent_id, **kwargs)

    return make
