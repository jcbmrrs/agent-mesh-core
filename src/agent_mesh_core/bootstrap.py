from __future__ import annotations

import argparse
from pathlib import Path

from agent_mesh_core.coordinator import AgentMeshCoordinator
from agent_mesh_core.names import validate_name
from agent_mesh_core.rules_template import write_local_rules_template

DEFAULT_AGENT_IDS = ["agent_mac_mini", "agent_mbp", "agent_ollama_local"]


def bootstrap_mesh(
    mesh_root: str | Path,
    agent_ids: list[str] | None = None,
    rules_overrides: dict | None = None,
    force_rules: bool = False,
) -> None:
    mesh_root = Path(mesh_root)
    agent_ids = agent_ids or DEFAULT_AGENT_IDS
    validated = [validate_name(agent_id) for agent_id in agent_ids]
    if len(set(agent_id.casefold() for agent_id in validated)) != len(validated):
        raise ValueError("duplicate agent IDs after lowercase normalization")
    coordinators = [AgentMeshCoordinator(mesh_root, agent_id) for agent_id in validated]
    writer = coordinators[0] if coordinators else AgentMeshCoordinator(mesh_root, "agent_mac_mini")
    write_local_rules_template(
        mesh_root, overrides=rules_overrides, force=force_rules, coordinator=writer
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-mesh-bootstrap")
    parser.add_argument("--mesh-root", required=True)
    parser.add_argument("--agent-ids", default=",".join(DEFAULT_AGENT_IDS))
    parser.add_argument("--force-rules", action="store_true")
    args = parser.parse_args(argv)
    agent_ids = [item.strip() for item in args.agent_ids.split(",") if item.strip()]
    bootstrap_mesh(args.mesh_root, agent_ids=agent_ids, force_rules=args.force_rules)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
