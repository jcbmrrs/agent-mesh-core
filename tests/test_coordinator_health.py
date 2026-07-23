from agent_mesh_core import AgentMeshCoordinator
from agent_mesh_core.inbox import claim_inbox_messages


def test_health_check_reports_agents_processing_claims_and_locks(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a")
    sender.send_message("agent_a", "task.assigned", {"x": 1})
    claim = claim_inbox_messages(mesh_root, "agent_a").claimed[0]
    lock = coordinator.acquire_lock("shared")
    tokenless = mesh_root / "locks" / "tokenless"
    tokenless.mkdir()

    health = coordinator.health_check()

    assert health["status"] == "ok"
    assert health["mesh_root"] == str(mesh_root)
    agent_a = next(agent for agent in health["agents"] if agent["agent_id"] == "agent_a")
    assert agent_a["processing_claims"][0]["claim_id"] == claim.claim_id
    assert agent_a["processing_claims"][0]["shape"] == "complete"
    locks = {item["lock_name"]: item["shape"] for item in health["locks"]}
    assert locks == {"shared": "token-present", "tokenless": "token-missing"}

    coordinator.release_lock(lock)
