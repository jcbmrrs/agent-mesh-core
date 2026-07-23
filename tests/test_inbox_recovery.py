import json
import os
import time

import pytest

from agent_mesh_core import AgentMeshCoordinator
from agent_mesh_core.inbox import claim_inbox_messages, recover_processing


def test_recover_processing_validates_claim_ids_before_touch(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    with pytest.raises(ValueError):
        recover_processing(mesh_root, "agent_a", claim_ids=["../bad"], action="requeue")


def test_recover_processing_noop_without_processing(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    assert recover_processing(mesh_root, "agent_a", older_than_seconds=0) == []


def test_recover_processing_requeues_complete_claim_and_removes_sidecar_and_dir(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    sender.send_message("agent_a", "task.assigned", {"x": 1})
    claim = claim_inbox_messages(mesh_root, "agent_a").claimed[0]

    result = recover_processing(mesh_root, "agent_a", claim_ids=[claim.claim_id], action="requeue")

    assert result[0]["status"] == "recovered"
    assert len(list((mesh_root / "agents" / "agent_a" / "inbox").glob("*.json"))) == 1
    claim_dir = mesh_root / "agents" / "agent_a" / "inbox" / ".processing" / claim.claim_id
    assert not claim_dir.exists()


def test_recover_processing_quarantines_no_sidecar_claim(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    claim_id = "1" * 32
    claim_dir = mesh_root / "agents" / "agent_a" / "inbox" / ".processing" / claim_id
    claim_dir.mkdir(parents=True)
    (claim_dir / "msg.json").write_text("{}")

    result = recover_processing(mesh_root, "agent_a", claim_ids=[claim_id], action="quarantine")

    assert result[0]["status"] == "recovered"
    assert (mesh_root / "agents" / "agent_a" / "inbox" / ".invalid" / "msg.json").exists()
    assert not claim_dir.exists()


def test_recover_processing_selected_empty_claim_is_removed(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    claim_id = "2" * 32
    claim_dir = mesh_root / "agents" / "agent_a" / "inbox" / ".processing" / claim_id
    claim_dir.mkdir(parents=True)

    result = recover_processing(mesh_root, "agent_a", claim_ids=[claim_id], action="requeue")

    assert result[0]["status"] == "recovered"
    assert not claim_dir.exists()


def test_recover_processing_age_selects_old_claims_only(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    inbox = mesh_root / "agents" / "agent_a" / "inbox"
    old_id = "3" * 32
    young_id = "4" * 32
    for claim_id in [old_id, young_id]:
        claim_dir = inbox / ".processing" / claim_id
        claim_dir.mkdir(parents=True, exist_ok=True)
        (claim_dir / "msg.json").write_text("{}")
    old_msg = inbox / ".processing" / old_id / "msg.json"
    old_time = time.time() - 100
    os.utime(old_msg, (old_time, old_time))

    result = recover_processing(mesh_root, "agent_a", older_than_seconds=10, action=None)

    selected = {row["claim_id"]: row["selected"] for row in result}
    assert selected[old_id] is True
    assert selected[young_id] is False


def test_recover_processing_raises_on_destination_collision(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    inbox = mesh_root / "agents" / "agent_a" / "inbox"
    claim_id = "5" * 32
    claim_dir = inbox / ".processing" / claim_id
    claim_dir.mkdir(parents=True)
    (claim_dir / "msg.json").write_text("{}")
    (inbox / "msg.json").write_text("{}")

    with pytest.raises(FileExistsError):
        recover_processing(mesh_root, "agent_a", claim_ids=[claim_id], action="requeue")


def test_recover_processing_reports_partial_cleanup_failure(monkeypatch, mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    inbox = mesh_root / "agents" / "agent_a" / "inbox"
    claim_id = "6" * 32
    claim_dir = inbox / ".processing" / claim_id
    claim_dir.mkdir(parents=True)
    (claim_dir / "msg.json").write_text("{}")
    (claim_dir / "extra").write_text("x")

    result = recover_processing(mesh_root, "agent_a", claim_ids=[claim_id], action="requeue")

    assert result[0]["status"] == "partial"
    assert (inbox / "msg.json").exists()
    assert (claim_dir / "extra").exists()


def test_recover_processing_malformed_sidecar_shape_reports(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    inbox = mesh_root / "agents" / "agent_a" / "inbox"
    claim_id = "7" * 32
    claim_dir = inbox / ".processing" / claim_id
    claim_dir.mkdir(parents=True)
    (claim_dir / "msg.json").write_text("{}")
    (claim_dir / "msg.json.claim.json").write_text(json.dumps({"claimed_at": "bad"}))

    result = recover_processing(mesh_root, "agent_a", claim_ids=[claim_id], action=None)

    assert result[0]["shape"] == "malformed-sidecar"
