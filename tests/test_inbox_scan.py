import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_mesh_core import AgentMeshCoordinator
from agent_mesh_core.inbox import (
    MAX_CLAIM_BATCH_SIZE,
    acknowledge_claims,
    claim_inbox_messages,
    scan_and_clear_inbox,
)


def _send(sender, target, n=1):
    return [sender.send_message(target, "task.assigned", {"i": i}) for i in range(n)]


def test_claim_inbox_messages_empty(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")

    result = claim_inbox_messages(mesh_root, "agent_a")

    assert result.claimed == []


def test_claim_inbox_messages_claims_without_deleting(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    _send(sender, "agent_a")

    result = claim_inbox_messages(mesh_root, "agent_a")

    assert len(result.claimed) == 1
    claimed = result.claimed[0]
    claim_dir = mesh_root / "agents" / "agent_a" / "inbox" / ".processing" / claimed.claim_id
    assert (claim_dir / claimed.filename).exists()
    sidecar = json.loads((claim_dir / f"{claimed.filename}.claim.json").read_text())
    assert sidecar["claim_token"] == claimed.claim_token
    assert sidecar["claimant_agent_id"] == "agent_a"


def test_claim_inbox_messages_retries_claim_id_collision(monkeypatch, mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    _send(sender, "agent_a")
    first = "0" * 32
    second = "1" * 32
    processing = mesh_root / "agents" / "agent_a" / "inbox" / ".processing"
    (processing / first).mkdir(parents=True)
    generated = iter([first, second])
    monkeypatch.setattr("agent_mesh_core.inbox._new_claim_id", lambda: next(generated))

    result = claim_inbox_messages(mesh_root, "agent_a")

    assert result.claimed[0].claim_id == second


def test_concurrent_claims_of_one_message_have_exactly_one_winner(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    _send(sender, "agent_a")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim_inbox_messages(mesh_root, "agent_a"), range(2)))

    assert sum(len(result.claimed) for result in results) == 1
    assert len(list((mesh_root / "agents" / "agent_a" / "inbox").glob("*.json"))) == 0


@pytest.mark.parametrize("max_messages", [0, -1, 51, "1", True])
def test_claim_inbox_messages_validates_max_before_touch(mesh_root, max_messages):
    AgentMeshCoordinator(mesh_root, "agent_a")
    with pytest.raises(ValueError):
        claim_inbox_messages(mesh_root, "agent_a", max_messages=max_messages)


def test_claim_inbox_messages_bounds_attempts(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    _send(sender, "agent_a", n=MAX_CLAIM_BATCH_SIZE + 1)

    result = claim_inbox_messages(mesh_root, "agent_a", max_messages=3)

    assert len(result.claimed) == 3
    assert len(list((mesh_root / "agents" / "agent_a" / "inbox").glob("*.json"))) == (
        MAX_CLAIM_BATCH_SIZE + 1 - 3
    )


def test_sidecar_write_failure_orphans_and_counts_attempts(monkeypatch, mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    claimant = AgentMeshCoordinator(mesh_root, "agent_a")
    _send(sender, "agent_a", n=5)

    def boom(_path, _data):
        raise OSError("disk")

    monkeypatch.setattr(claimant, "atomic_write_json", boom)

    result = claim_inbox_messages(mesh_root, "agent_a", max_messages=3, coordinator=claimant)

    assert result.claimed == []
    assert len(result.orphaned) == 3
    assert len(list((mesh_root / "agents" / "agent_a" / "inbox").glob("*.json"))) == 2


def test_malformed_message_is_quarantined_and_hidden_files_reported(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    inbox = mesh_root / "agents" / "agent_a" / "inbox"
    (inbox / "bad.json").write_text("{")
    (inbox / ".tmp_x").write_text("{}")

    result = claim_inbox_messages(mesh_root, "agent_a")

    assert result.skipped == [{"filename": "bad.json", "reason": "malformed"}]
    assert result.ignored == [".tmp_x"]
    assert (inbox / ".invalid" / "bad.json").exists()


def test_acknowledge_claims_deletes_only_matching_token(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    _send(sender, "agent_a", n=2)
    result = claim_inbox_messages(mesh_root, "agent_a")

    acked = acknowledge_claims(
        mesh_root,
        "agent_a",
        [{"claim_id": result.claimed[0].claim_id, "claim_token": result.claimed[0].claim_token}],
    )

    assert acked == [{"claim_id": result.claimed[0].claim_id, "status": "acknowledged"}]
    assert not (
        mesh_root / "agents" / "agent_a" / "inbox" / ".processing" / result.claimed[0].claim_id
    ).exists()
    remaining_claim_dir = (
        mesh_root / "agents" / "agent_a" / "inbox" / ".processing" / result.claimed[1].claim_id
    )
    assert remaining_claim_dir.exists()


def test_acknowledge_claims_reports_not_found_on_second_ack(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    _send(sender, "agent_a")
    result = claim_inbox_messages(mesh_root, "agent_a")
    item = result.claimed[0]
    claim = {"claim_id": item.claim_id, "claim_token": item.claim_token}
    acknowledge_claims(mesh_root, "agent_a", [claim])

    assert acknowledge_claims(mesh_root, "agent_a", [claim]) == [
        {"claim_id": item.claim_id, "status": "not-found"}
    ]


@pytest.mark.parametrize("token", ["", None, 123])
def test_acknowledge_claims_validates_token_before_touch(mesh_root, token):
    AgentMeshCoordinator(mesh_root, "agent_a")
    with pytest.raises(ValueError):
        acknowledge_claims(mesh_root, "agent_a", [{"claim_id": "0" * 32, "claim_token": token}])


def test_acknowledge_claims_validates_claim_item_shape(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    with pytest.raises(ValueError):
        acknowledge_claims(mesh_root, "agent_a", ["not-a-dict"])


def test_acknowledge_claims_token_mismatch_leaves_complete_claim(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    _send(sender, "agent_a")
    result = claim_inbox_messages(mesh_root, "agent_a")
    item = result.claimed[0]

    acked = acknowledge_claims(
        mesh_root, "agent_a", [{"claim_id": item.claim_id, "claim_token": "wrong"}]
    )

    assert acked == [{"claim_id": item.claim_id, "status": "token-mismatch"}]
    assert (mesh_root / "agents" / "agent_a" / "inbox" / ".processing" / item.claim_id).exists()


def test_acknowledge_claims_partial_cleanup_does_not_abort_batch(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    _send(sender, "agent_a", n=2)
    result = claim_inbox_messages(mesh_root, "agent_a")
    first, second = result.claimed
    first_dir = mesh_root / "agents" / "agent_a" / "inbox" / ".processing" / first.claim_id
    (first_dir / "extra").write_text("x")

    acked = acknowledge_claims(
        mesh_root,
        "agent_a",
        [
            {"claim_id": first.claim_id, "claim_token": first.claim_token},
            {"claim_id": second.claim_id, "claim_token": second.claim_token},
        ],
    )

    assert acked[0]["claim_id"] == first.claim_id
    assert acked[0]["status"] == "partial"
    assert acked[0]["cleanup_errors"]
    assert acked[1] == {"claim_id": second.claim_id, "status": "acknowledged"}
    assert (first_dir / "extra").exists()
    second_dir = mesh_root / "agents" / "agent_a" / "inbox" / ".processing" / second.claim_id
    assert not second_dir.exists()


def test_acknowledge_claims_unacknowledgeable_orphan_shapes(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    processing = mesh_root / "agents" / "agent_a" / "inbox" / ".processing"
    empty = processing / ("0" * 32)
    no_sidecar = processing / ("1" * 32)
    malformed = processing / ("2" * 32)
    empty.mkdir(parents=True)
    no_sidecar.mkdir()
    (no_sidecar / "msg.json").write_text("{}")
    malformed.mkdir()
    (malformed / "msg.json").write_text("{}")
    (malformed / "msg.json.claim.json").write_text("{")

    results = acknowledge_claims(
        mesh_root,
        "agent_a",
        [
            {"claim_id": empty.name, "claim_token": "x"},
            {"claim_id": no_sidecar.name, "claim_token": "x"},
            {"claim_id": malformed.name, "claim_token": "x"},
        ],
    )

    assert [row["status"] for row in results] == ["unacknowledgeable"] * 3
    assert [row["shape"] for row in results] == ["empty", "no-sidecar", "malformed-sidecar"]


def test_scan_and_clear_inbox_composes_claim_and_ack(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_b")
    AgentMeshCoordinator(mesh_root, "agent_a")
    _send(sender, "agent_a")

    result = scan_and_clear_inbox(mesh_root, "agent_a")

    assert len(result.claimed) == 1
    assert result.ack_results == [
        {"claim_id": result.claimed[0].claim_id, "status": "acknowledged"}
    ]
